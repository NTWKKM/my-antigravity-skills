# Trajectory Audit Schema & Statistical Methodology

This reference documents the JSON schema produced by [`scripts/audit_trajectories.py`](../scripts/audit_trajectories.py) and the statistical guardrails used when interpreting comparative efficiency deltas (`--compare`).

---

## 1. Statistical & Analytical Methodology

1. **Conversation-Level Non-Parametric Bootstrap (`bootstrap_significance_tests`)**:
   - All rate metrics (`failure_rate`, `friction_loops`, `unmodified_overlap`, `unbounded_views`, `prompt_cache_hit`) and continuous token metrics (`median_tokens`, `api_context`, `api_input_tokens`) are evaluated at the **conversation level** using 1,000-resample non-parametric cluster bootstrapping (`seed=42`).
   - Pooled $z$-tests on raw event counts are prohibited because tool calls cluster within conversations (intra-cluster correlation / pseudoreplication).
   - Directional labels (`IMPROVED` / `DRIFT`) are assigned strictly when both cohorts have $N \ge 15$ conversations and $0$ lies outside the 95% bootstrap confidence interval; otherwise the delta is labeled `NEUTRAL`.

2. **High-Percentile Tail Variance (`P90`)**:
   - High percentiles (`p90_tokens_per_conv`) reflect a handful of outlier sessions and are always tagged `NOISE` rather than `IMPROVED` or `DRIFT`. Always cross-check token deltas against `turns_per_conv`.

3. **Unmodified Re-Reading vs Post-Edit Verification (`file_view_overlap`)**:
   - `unmodified_overlap_pct` tracks redundant re-reading of lines within the same file modification epoch (reset whenever `write_to_file` or `replace_file_content` modifies that file).
   - `gross_overlap_pct` includes legitimate post-edit inspection across modification epochs.

4. **Ephemeral Context & Prompt Caching (`api_tokens_ground_truth`)**:
   - Runtime injections (`[ACTIVE SKILLS LOADED: ...]`, `[MCP MEMORY RECALL: ...]`) are per-turn ephemeral steps (`retained_in_history: false`).
   - Use `cache_hit_rate_pct` (`cache_read_tokens / (input_tokens_fresh + cache_read_tokens) * 100`) and `fresh_input_per_conv` as primary cost truth whenever `has_ground_truth` is `true`.

5. **Full vs Compact Transcript Selection**:
   - Always inspect `transcript_full.jsonl` over `transcript.jsonl`. Compact transcripts truncate tool outputs (`"truncated_fields": ["content"]`), skewing `view_file` and `run_command` token counts downward.

---

## 2. Schema of `trajectory_audit_summary.json`

When `--compare` is active, the root object contains:
- `comparison.target_window`: Cohort summary for conversations with `start_dt >= since_filter`.
- `comparison.baseline_window` (and alias `comparison.baseline`): Cohort summary for conversations prior to `since_filter`.
- `comparison.bootstrap_significance_tests`:
  - `unit_of_analysis`: `"conversation"`
  - `iterations`: `1000`
  - Keys: `failure_rate`, `friction_loops`, `median_tokens`, `unmodified_overlap`, `unbounded_views`, `prompt_cache_hit`, `api_context`, `api_input_tokens` (each `{ "p_value": Float, "significant": Bool }`).

### Cohort Summary Fields

- **Volume & Turn Granularity**:
  - `conversations`, `user_turns`, `turns_per_conv`, `median_turns_per_conv`, `commands`, `cmds_per_conv`, `cmds_per_turn`.
- **Command Failure & Friction Metrics**:
  - `failures`: Non-benign command failure count (excludes zero-match `rg`/`grep`/`findstr`/`diff` exit 1 and pending `gh pr checks` exit 8).
  - `failure_rate_pct`: True failure rate percentage.
  - `total_incidents`, `high_friction_count`, `friction_per_100_cmds`.
  - `failures_by_category`, `failures_by_repo`, `high_friction_incidents`.
- **Inline Script & Dependency Forensics**:
  - `py_c_inline`, `inline_per_100_cmds`.
  - `py_c_multiline`: `{ "total": N, "failed": N, "fail_pct": Float }`.
  - `py_c_oneline`: `{ "total": N, "failed": N, "fail_pct": Float }`.
  - `inline_failures_by_class`: `{ "missing_dependency": N, "syntax_shell_parse": N, "runtime_exception": N, "assertion_or_logic": N, "other_failure": N }`.
  - `missing_dependency_details`: `{ "by_repo": { "<repo>": N }, "by_conv": { "<conv_id>": N } }`.
- **File Viewing & Editing Hygiene**:
  - `file_views`, `unbounded_views`, `unbounded_view_pct`, `unbounded_view_tokens`, `bounded_view_tokens`.
  - `file_view_overlap`: `{ "total_unmodified_lines", "unique_unmodified_lines", "unmodified_overlap_pct", "total_gross_lines", "unique_gross_lines", "gross_overlap_pct" }`.
  - `write_to_file_modes`: `{ "overwrite": N, "create": N, "append": N }`.
- **Token Decomposition**:
  - `total_tokens`, `prompt_tokens`, `response_tokens`, `tool_tokens`, `system_tokens`.
  - `response_breakdown`: `{ "visible_prose_tokens", "tool_call_args_tokens", "tool_call_args_by_tool", "thinking_tokens" }`.
  - `tool_breakdown`: `{ "unbounded_view_tokens", "bounded_view_tokens", "run_command_tokens", "other_tool_tokens" }`.
  - `system_breakdown`: `{ "skills_notice_tokens", "memory_recall_tokens", "system_message_tokens", "other_ephemeral_tokens" }`.
  - `skills_notice_stats`: `{ "total_injections", "injections_per_conv", "injections_per_turn", "total_tokens", "persistence_model", "retained_in_history" }`.
  - `tokens_per_conv`, `median_tokens_per_conv`, `p75_tokens_per_conv`, `p90_tokens_per_conv`, `min_tokens_per_conv`, `max_tokens_per_conv`, `tokens_per_turn`.
- **Ground-Truth API Telemetry (`api_tokens_ground_truth`)**:
  - `has_ground_truth`: Boolean indicating availability of API usage metadata.
  - `input_tokens_fresh`: Cumulative fresh input tokens written to cache.
  - `cache_read_tokens`: Cumulative input tokens served from prompt cache.
  - `output_tokens_model`: Cumulative completion tokens generated by the model.
  - `total_api_context_processed`: Cumulative prompt input context (`input_tokens_fresh + cache_read_tokens`). Context accounts for **99.43% of processed tokens** and **~92.8% – 94.5% of financial cost**.
  - `total_api_tokens_all`: Total tokens across all API calls (`total_api_context_processed + output_tokens_model`).
  - `fresh_input_per_conv`: Fresh input tokens per conversation.
  - `cache_read_per_conv`: Cached tokens read per conversation.
  - `output_per_conv`: Model completion tokens per conversation.
  - `context_per_conv`: Prompt context tokens processed per conversation.
  - `total_api_per_conv`: Combined total API tokens per conversation.
  - `cache_hit_rate_pct`: `cache_read_tokens / (input_tokens_fresh + cache_read_tokens) * 100`.
  - `calibration`:
    - `output_token_ratio_api_vs_est`: Ratio of API-reported output tokens to estimated content output tokens strictly on the cohort with telemetry ($1.58\times – 1.9\times$).
    - `context_magnification_factor`: Cumulative API input context divided by unrepeated content tokens ($\approx 90\times – 97\times$). This reflects multi-turn trajectory accumulation where context is re-evaluated across median ~84 API calls per session ($\approx \frac{N}{2} \times \text{final context}$).
    - `spread_by_conversation`: Distribution summary (`mean`, `median`, `p25`, `p75`, `min`, `max`) of per-session calibration ratios.

---

## 3. Empirical Output Decomposition & Financial Cost Weights

Analysis across 68 development sessions ($N = 9,768$ steps, OLS $R^2 = 0.964$) establishes the structural decomposition of model output and true dollar cost:

1. **Output Token Distribution**:
   - **Tool Call Arguments**: **~48.3%** ($b_1 \approx 0.316 \text{ tok/char} \implies 3.16 \text{ chars/token}$).
   - **Thinking Trace**: **~34.9%** ($b_2 \approx 0.824 \text{ tok/char} \implies 1.21 \text{ chars/token}$). Controlled tests prove this ~1.2 chars/token density is NOT a tool framing artifact, but reflects API-counted internal chain-of-thought tokens that are omitted from plain transcript text.
   - **Per-Step Framing Overhead**: **~11.0%** ($\approx 74 \text{ tok/step}$).
   - **Visible Chat Prose**: **~5.8%** ($b_3 \approx 0.340 \text{ tok/char} \implies 2.94 \text{ chars/token}$).

2. **Token Volume vs Dollar Cost Disparity**:
   - **Context Input**: 99.43% of tokens $\implies$ **~92.8% – 94.5% of total bill**.
   - **Model Output**: 0.57% of tokens $\implies$ **~5.5% – 7.2% of total bill** (due to 5x–12x pricing premium over cache reads).
   - **Visible Prose**: < 0.04% of tokens $\implies$ **< 0.4% of total bill**. Prompting agents to "be concise" in chat prose has negligible financial impact; actual cost optimization requires bounding file views, surgical diffs, and context compaction.
