---
name: improve-agent-efficiency
description: Audits Antigravity agent conversation transcripts, probes host CLI tooling and rule budgets, measures token burn and comparative efficiency gains via conversation-level bootstrap testing, and deploys verified remediations across host binaries, hooks.json, global rules, and workspace AGENTS.md files. Use when the user asks to check token burn, evaluate efficiency gains since a date, audit command failure rates or retry loops across past sessions, or optimize GEMINI.md, AGENTS.md, and hooks.json.
---

# Improve Agent Efficiency

This skill audits agent conversation histories in Antigravity (Antigravity 2.0, IDE, and CLI), detects execution friction and multi-turn retry loops, probes the live host environment and rule context budgets, evaluates comparative efficiency gains and token burn over time, and executes verified systemic remediations.

---

## Operational Modes

### Mode A: Status, Efficiency Gains & Token Burn Check (Read-Only)
Trigger when the user wants to inspect recent performance or verify whether previous rule/hook updates worked:
- *"Check our efficiency status and token burn over the last 24 hours."*
- *"Analyze our efficiency gains since yesterday."*
- *"Did our recent rule updates reduce command failures and token burn?"*

**Fast Execution Path:**
Run [`scripts/audit_trajectories.py`](scripts/audit_trajectories.py) with `--since <YYYY-MM-DD> --compare` targeting the session scratch directory (`<appDataDir>/brain/<conversation-id>/scratch`), report the comparative delta table directly to the user, and complete the turn without running host probes or modifying configurations.

**Analytical Guardrails (Anti-Hallucination Gate):**
1. **Bootstrap Significance Guard:** All rate metrics (`failure_rate`, `friction_loops`, `unmodified_overlap`, `unbounded_views`, `prompt_cache_hit`) and continuous token metrics (`median_tokens`, `api_context`, `api_input_tokens`) are tested at the **conversation level** using 1,000-resample non-parametric bootstrapping. Assign `IMPROVED` or `DRIFT` strictly when $N \ge 15$ per cohort and $0$ is outside the 95% CI; otherwise report `NEUTRAL`.
2. **Tail Variance & Turn Volume:** Treat `p90_tokens_per_conv` shifts as `NOISE` and always evaluate per-session token shifts alongside `turns_per_conv`.
3. **Unmodified Re-Reading vs Post-Edit Verification:** Use `unmodified_overlap_pct` (lines re-read within the same file modification epoch) rather than `gross_overlap_pct` (which includes legitimate post-edit inspection).
4. **Prompt Cache & API Ground Truth:** Elevate `api_tokens_ground_truth` (`cache_hit_rate_pct`, `fresh_input_per_conv`, `total_api_per_conv`) and its per-conversation calibration spread as primary cost truth.
5. **Prefer Full Transcripts:** Always inspect `transcript_full.jsonl` over `transcript.jsonl` to avoid truncated tool outputs (`"truncated_fields": ["content"]`).
6. **Benign Non-Zero Exits:** Zero-match searches (`rg`, `grep`, `findstr`, `diff` exit 1), TDD red-phase test runs, and pending `gh pr checks` (exit 8) are normal workflow signals, not command failures.

For the complete JSON output schema and statistical formulas, read [`references/metrics_and_schema.md`](references/metrics_and_schema.md).

---

### Mode B: Deep Friction Audit & Quad-Layer Remediation
Trigger when the user wants to identify recurring errors, eliminate multi-turn loops, or harden configurations:
- *"Audit my past sessions and optimize agent rules."*
- *"Check my command failure rate across past trajectories and update workspace AGENTS.md."*
- *"Probe my host environment and identify discrepancies in my agent configuration."*

**Full Remediation Path:** Execute Phases 0 through 5 below in order. Before adding any new rule to `GEMINI.md` or `AGENTS.md`, prove with transcript sampling that the friction is recurring and causes material waste (YAGNI), and prefer zero-token layers (host binaries, `hooks.json`) first.

---

## Operational Procedure

Resolve `<SkillDir>` to the directory containing this `SKILL.md` file, and set `<ScratchDir>` to `<appDataDir>/brain/<conversation-id>/scratch` so generated JSON reports never pollute the user's git working tree.

### Phase 0: Scoping & Discovery Gate

1. **Explicit Prompt Intent Check:**
   - If the user asks for a **status check, efficiency gains, or token burn**, run the **Mode A** fast path and stop after reporting:
     ```bash
     # macOS / Linux (POSIX)
     python3 "<SkillDir>/scripts/audit_trajectories.py" "<ScratchDir>" --since <YYYY-MM-DD> --compare
     ```
     ```pwsh
     # Windows (PowerShell)
     py -3.10 "<SkillDir>\scripts\audit_trajectories.py" "<ScratchDir>" --since <YYYY-MM-DD> --compare
     ```
   - If the user already specified a repository (`--repo <name>`) or date window (`--since <date>`), proceed directly to Phase 1.

2. **Rapid Inventory Discovery (< 2 seconds):**
   When invoked without scope arguments, run `--inventory-only`:
   ```bash
   python3 "<SkillDir>/scripts/audit_trajectories.py" "<ScratchDir>" --inventory-only
   ```
   Read `<ScratchDir>/trajectory_inventory.json` and call `ask_question` with discovered options:
   - **Repository Scope:**
     - `(Recommended) Current workspace only (<active_workspace>)`
     - `Top active repositories (<top_3_repos>)`
     - `Full system sweep (all repositories)`
   - **Time Window:**
     - `(Recommended) Recent history (last 14 days)`
     - `Medium history (last 30 days)`
     - `Full lifetime history`

### Phase 1: Execute Host Probe and Trajectory Mining

Run both [`scripts/probe_environment.py`](scripts/probe_environment.py) and [`scripts/audit_trajectories.py`](scripts/audit_trajectories.py) targeting `<ScratchDir>`:

```bash
# macOS / Linux (POSIX)
python3 "<SkillDir>/scripts/probe_environment.py" "<ScratchDir>"
python3 "<SkillDir>/scripts/audit_trajectories.py" "<ScratchDir>" --since <YYYY-MM-DD> --repo <target_repo>
```

```pwsh
# Windows (PowerShell)
py -3.10 "<SkillDir>\scripts\probe_environment.py" "<ScratchDir>"
py -3.10 "<SkillDir>\scripts\audit_trajectories.py" "<ScratchDir>" --since <YYYY-MM-DD> --repo <target_repo>
```

#### Supported Mining Flags (`audit_trajectories.py`)
- `--since YYYY-MM-DD` / `--until YYYY-MM-DD`: Bound the evaluation time window.
- `--compare`: Compare target window (`>= --since`) against baseline (`< --since`) with 1,000-iteration conversation-level bootstrap tests.
- `--repo <keyword>` / `--exclude <name1,name2>` / `--exclude-conv <id1,id2>`: Filter by repository or conversation ID (applied before `--limit`).
- `--limit <N>` (default `100`) / `--all`: Cap evaluated conversations after repo filtering, or parse all sessions.
- `--include-audit-sessions`: Include meta/audit sessions (excluded by default).
- `--inventory-only`: Fast repository and date boundary discovery without parsing full transcripts.
- `--print-summary`: Stream structured JSON summary to stdout.

### Phase 2: Review Diagnostic Outputs

Inspect `<ScratchDir>/host_environment_probe.json` and `<ScratchDir>/trajectory_audit_summary.json` (see [`references/metrics_and_schema.md`](references/metrics_and_schema.md) for field definitions):

1. **Host & Rule Budget Findings (`host_environment_probe.json`):**
   - Check missing CLI tools (`rg`, `fd`, `jq`, `gh`, `uv`, `pnpm`, `agy`, runtimes) and stream encoding status.
   - Check `configuration_audit.discrepancies` for false negatives (tools declared missing in `GEMINI.md` that are installed on `PATH`) and rule budget violations (`rule_file_over_24kb_cap` exceeding Antigravity's `24,000`-byte per-file truncation limit or `aggregate_rules_over_token_budget` exceeding the `20,000`-token `defaultRulesBudget`).
2. **High-Friction Incident Chains (`trajectory_audit_summary.json`):**
   - Inspect `high_friction_incidents` where `retry_count >= 1`, `resolved: false`, or `intervening_file_writes` is non-empty.
   - Check `missing_dependency_details.by_repo` and `inline_failures_by_class` to distinguish workspace-local environment gaps from global shell syntax issues.

### Phase 3: Targeted Forensic Sampling

For recurring incident categories, sample the raw conversation log:
1. Take `conversation_id` and `initial_step` from the incident entry.
2. Locate `<appDataDir>/brain/<conversation_id>/.system_generated/logs/transcript_full.jsonl` (fallback to `transcript.jsonl` only if `transcript_full.jsonl` is absent).
3. Use bounded `view_file` (`StartLine` / `EndLine` around `initial_step`) to verify the exact command, stderr traceback, and recovery action.

### Phase 4: Quad-Layer Remediation Deployment

Consult [`references/remediation_patterns.md`](references/remediation_patterns.md) and apply fixes starting from the lowest-token layer:

1. **Layer 1 — Host Tooling & Antigravity 2.0 Settings (Zero Token Cost):**
   - Install missing CLI binaries requested by agents (`brew install <pkg>`, `winget install --id <Id>`).
   - Set persistent UTF-8 stream variables (`PYTHONIOENCODING=utf-8`).
   - Recommend Antigravity 2.0 Settings (Command Allowlist/Denylist, Sandbox Mode, Permission Grants) where appropriate.
2. **Layer 2 — Deterministic Lifecycle Hooks (`hooks.json` — Zero Token Cost):**
   - Use `PreToolUse` (`matcher: "run_command"`) to deterministically deny (`"decision": "deny"`) or rewrite (`"overwrite": {...}`) recurring command mistakes (such as multi-line `python -c` or wrong package managers).
   - Use `PostToolUse` (`matcher: "replace_file_content|write_to_file"`) for automatic formatting/linting.
3. **Layer 3 — Global Rules (`~/.gemini/config/GEMINI.md` & `AGENTS.md`):**
   - Fix false binary claims, enforce the File-First Execution SOP, and verify that every rule file stays strictly under **`24,000` bytes** and total always-on rules remain under **`20,000` tokens**.
4. **Layer 4 — Workspace Customizations (`<repo_root>/AGENTS.md` & `.agents/`):**
   - Codify repo-specific runtime pinning (`uv run`, `pnpm`), `PYTHONPATH`, build/test commands, pre-build process cleanup, and `.agents/skills.json` or `.agents/hooks.json` using the templates in [`references/remediation_patterns.md`](references/remediation_patterns.md).

### Phase 5: Verification Gate

Verify every applied change before finishing the turn:
1. **Host Binaries:** Run `<binary> --version` and confirm exit code `0`.
2. **Rule Budgets & Hooks:** Re-run `probe_environment.py "<ScratchDir>"` to confirm `discrepancies` is empty and all rule files are `< 24,000` bytes.
3. **Workspace Commands:** Execute the target repository's test/lint commands to confirm zero regression.
4. **Report:** Present the comparative metrics, root-cause incident trace, and verified remediations to the user.
