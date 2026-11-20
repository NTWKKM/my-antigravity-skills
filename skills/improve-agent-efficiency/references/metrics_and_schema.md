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
   - `unmodified_overlap_pct` tracks redundant re-reading of lines within the same file modification epoch (reset whenever `write_file`, `write_to_file`, `edit_file`, `replace_file_content`, or `multi_replace_file_content` modifies that file).
   - `gross_overlap_pct` includes legitimate post-edit inspection across modification epochs.
   - All file-read, file-write, and surgical-edit metrics treat legacy (`view_file`, `write_to_file`, `replace_file_content`, `multi_replace_file_content`) and Antigravity 2.0 (`read_file`, `write_file`, `edit_file`) tool names with 100% parity.

4. **Ephemeral Context & Prompt Caching (`api_tokens_ground_truth`)**:
   - Runtime injections (`[ACTIVE SKILLS LOADED: ...]`, `[MCP MEMORY RECALL: ...]`) are per-turn ephemeral steps (`retained_in_history: false`).
   - Use `cache_hit_rate_pct` (`cache_read_tokens / (input_tokens_fresh + cache_read_tokens) * 100`) and `fresh_input_per_conv` as primary cost truth whenever `has_ground_truth` is `true`. Optional `cache_creation_input_tokens` is folded into `input_tokens_fresh` without double-counting `input_tokens`.

5. **Full vs Compact Transcript Selection**:
   - Always inspect `transcript_full.jsonl` over `transcript.jsonl`. Compact transcripts truncate tool outputs (`"truncated_fields": ["content"]`), skewing `read_file`/`view_file` and `run_command` token counts downward.

6. **Interactive vs Subagent Cohort Separation & Hook Denial Isolation**:
   - Conversations with `user_turns >= 1` are classified as `interactive`; sessions with `user_turns == 0` (spawned subagents and headless SDK runs) are classified as `subagent_or_headless`.
   - By default (`--include-subagents` omitted), primary cohort summaries and bootstrap significance tests are scoped strictly to interactive sessions so `median_turns_per_conv` is not dragged to `0.0` and conversation-level independence is preserved. Subagent telemetry is emitted in `subagent_summary` and combined spend is always preserved in `total_api_tokens_including_subagents`.
   - `PreToolUse` denials (`"tool call denied by pre-tool hook"`, `"Blocked by PreToolUse"`) are excluded from true runtime command `failures` and reported separately in `hook_denials`.

---

## 2. Schema of `trajectory_audit_summary.json`

When `--compare` is active, the root object contains:
- `include_subagents`, `interactive_conversations`, `subagent_or_headless_conversations`, `subagent_summary`, `total_api_tokens_including_subagents`.
- `comparison.target_window`: Cohort summary for interactive conversations (or all if `--include-subagents`) with `start_dt >= since_filter`.
- `comparison.baseline_window` (and alias `comparison.baseline`): Cohort summary for conversations prior to `since_filter`.
- `comparison.target_subagent_summary` / `comparison.baseline_subagent_summary`: Subagent/headless cohort summaries for each window.
- `comparison.target_total_api_tokens_including_subagents` / `comparison.baseline_total_api_tokens_including_subagents`: Combined API token totals across interactive + subagent sessions per window.
- `comparison.bootstrap_significance_tests`:
  - `unit_of_analysis`: `"conversation"`
  - `iterations`: `1000`
  - Keys: `failure_rate`, `friction_loops`, `median_tokens`, `unmodified_overlap`, `unbounded_views`, `prompt_cache_hit`, `api_context`, `api_input_tokens` (each `{ "p_value": Float, "significant": Bool }`).

In standard mode, the root object also includes `include_subagents`, `interactive_conversations`, `subagent_or_headless_conversations`, `subagent_summary`, and `total_api_tokens_including_subagents` alongside all cohort summary fields below.

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
- **File Viewing, Editing Hygiene & Tool Telemetry (Legacy + Antigravity 2.0 Parity)**:
  - `file_views`, `unbounded_views`, `unbounded_view_pct`, `unbounded_view_tokens`, `bounded_view_tokens` (counts both `read_file` and `view_file`).
  - `file_view_overlap`: `{ "total_unmodified_lines", "unique_unmodified_lines", "unmodified_overlap_pct", "total_gross_lines", "unique_gross_lines", "gross_overlap_pct" }`.
  - `write_to_file_modes`: `{ "overwrite": N, "create": N, "append": N }` (counts both `write_file` and `write_to_file`).
  - `tool_call_counts`: Complete per-tool invocation map across all tools (`read_file`, `view_file`, `write_file`, `write_to_file`, `edit_file`, `replace_file_content`, `multi_replace_file_content`, `run_command`, `call_mcp_tool`, `invoke_subagent`, `run_workflow`, `swarm`, etc.), plus `total_tool_calls`.
  - `surgical_edits` (`edit_file` + `replace_file_content` + `multi_replace_file_content`) and `surgical_edit_ratio_pct` (`surgical_edits / (surgical_edits + write_to_file_modes.overwrite) * 100`).
- **`PreToolUse` Hook Denial Telemetry (`hook_denials`)**:
  - `total`: Total tool calls denied by `PreToolUse` hooks (excluded from true runtime command `failures`).
  - `per_100_tool_calls`: `total / total_tool_calls * 100`.
  - `by_guard`: Counts grouped by guard prefix (e.g., `Git Worktree Boundary`, `Bounded Read Guard`, `Missing Python Dependency`, `Local Module API`, `Surgical Diff Guard`, `Polling Loop Guard`).
- **Cache-Drift & Context Hygiene Diagnostics (`cache_drift_diagnostics`)**:
  - `compactions_total`: Total `# Resuming from a compaction` checkpoints.
  - `convs_with_compaction`: Conversations containing at least one compaction.
  - `long_convs_without_compaction`: Conversations with `user_turns >= 15` and `0` compactions.
  - `model_switches_total` & `convs_with_model_switch`: Mid-conversation `<USER_SETTINGS_CHANGE>` `Model Selection` switches (excludes initial `from None to <model>` selection).
  - `persistent_hook_system_messages`: `{ "count", "tokens", "per_conv", "tokens_per_conv" }` for `SYSTEM_MESSAGE` injections from `PreInvocation` hooks (`[CONTRACT DIARY:`, `[ACTIVE WORKSPACE:`, `[ZERO-SLASH MANDATE:`).
- **4-Channel Customization Usage Attribution (`customization_usage`)**:
  - Zero top-N truncation, excluding audit sessions by default. Discovers installed customizations from `~/.gemini/config/config.json`, `~/.gemini/config/mcp_config.json`, `~/.gemini/config/skills/*/SKILL.md`, and `~/.gemini/config/agents/*.md`.
  - Top-level maps: `plugins`, `skills`, `mcp_servers`, `agents`.
  - Each item reports `{ "enabled": Bool, "total": N, "skill_read": N, "cli_or_script": N, "mcp": N, "agent": N, "conversations": N }`:
    1. `skill_read`: `read_file`/`view_file` reads of `/plugins/<plugin>/.../SKILL.md` or `/skills/<skill>/SKILL.md`.
    2. `cli_or_script`: `run_command` invocations of CLI-backed plugins (`gdocs`, `gdrive`, `gsheets`, `gcalendar`, `gslides`, `coderabbit`/`cr`, `firebase`, `claude-9arm`, plus plugin-manifest CLIs) or `/skills/<skill>/` scripts.
    3. `mcp`: `call_mcp_tool` calls by `ServerName` (also attributing plugin-owned MCP servers like `firebase-mcp-server` to their parent plugin).
    4. `agent`: `invoke_subagent` calls by `TypeName` for both custom agents and plugin-bundled agents.
- **Token Decomposition**:
  - `total_tokens`, `prompt_tokens`, `response_tokens`, `tool_tokens`, `system_tokens`.
  - `response_breakdown`: `{ "visible_prose_tokens", "tool_call_args_tokens", "tool_call_args_by_tool", "thinking_tokens" }`.
  - `tool_breakdown`: `{ "unbounded_view_tokens", "bounded_view_tokens", "run_command_tokens", "other_tool_tokens" }`.
  - `system_breakdown`: `{ "skills_notice_tokens", "memory_recall_tokens", "system_message_tokens", "other_ephemeral_tokens" }`.
  - `skills_notice_stats`: `{ "total_injections", "injections_per_conv", "injections_per_turn", "total_tokens", "persistence_model", "retained_in_history" }`.
  - `tokens_per_conv`, `median_tokens_per_conv`, `p75_tokens_per_conv`, `p90_tokens_per_conv`, `min_tokens_per_conv`, `max_tokens_per_conv`, `tokens_per_turn`.
- **Ground-Truth API Telemetry (`api_tokens_ground_truth`)**:
  - `has_ground_truth`: Boolean indicating availability of API usage metadata.
  - `input_tokens_fresh`: Cumulative fresh input tokens written to cache (`input_tokens + cache_creation_input_tokens`, without double-counting).
  - `cache_creation_input_tokens`: Optional cumulative cache-creation input tokens when emitted by the provider (`0` when API ground truth is available but no cache-creation tokens were reported; `null` when ground truth is unavailable — this field may be `null`, not always numeric).
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
