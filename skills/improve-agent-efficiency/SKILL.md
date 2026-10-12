---
name: improve-agent-efficiency
description: Probes host development tools, mines causal command failure chains across past agent sessions, measures token burn and efficiency gains, and executes verified remediation across host binaries, global rules, and workspace AGENTS.md files.
---

# Improve Agent Efficiency

This skill audits agent conversation histories in Antigravity, detects execution friction and multi-turn retry loops, probes the live host environment for tool discrepancies, evaluates comparative efficiency gains and token burn over time, and executes verified systemic remediations.

---

## Direct Chat Prompts

The workflow supports two distinct operational modes depending on user intent:

### Mode A: Status, Efficiency Gains & Token Burn Check (Read-Only)
When the user wants to inspect recent performance or verify if previous remediations worked:
- *"Check our efficiency status and token burn over the last 24 hours."*
- *"Analyze our efficiency gains since yesterday."*
- *"Did our recent rule updates reduce command failures and token burn?"*
- *"Show me token expenditure and command failure metrics since last week."*

**Fast Execution Path:** Run `audit_trajectories.py (Get-Location).Path --since <YYYY-MM-DD> --compare` (or `--since 24h`), report the comparative delta table directly to the user, and complete the turn without running unnecessary host probes or modifying configurations.

**Critical Analytical Discipline (Anti-Hallucination Gate):**
- **Log File Selection (`transcript_full.jsonl` vs `transcript.jsonl`):** Trajectory auditing must prefer `transcript_full.jsonl` whenever present. Compact `transcript.jsonl` truncates tool outputs (`"truncated_fields": ["content"]`), causing tool token calculations (such as file views and command outputs) to report misleadingly tiny sizes (~20 chars/call) and producing false-positive efficiency claims.
- **Decompose Model Response:** Response output tokens must distinguish between visible assistant prose, tool call arguments (e.g. `write_to_file` payloads), and internal reasoning/thinking tokens. A high response volume typically reflects active code generation and large edit payloads, not conversational loquacity.
- **Verify Attribution & Magnitude Before Diagnosing:** Never attribute high tool token consumption to a single tool (such as `view_file`) without verifying the actual token contribution (`unbounded_view_tokens`, `bounded_view_tokens`, `run_command_tokens`, `system_tokens`) in `trajectory_audit_summary.json`. System streaming overhead (`EPHEMERAL_MESSAGE`) enters model context on every turn but must not be confused with tool execution cost.
- **Distinguish Prompt Cache Read from Fresh Input:** When native API token metrics (`input_tokens`, `cache_read_tokens`) are present, report the Prompt Cache Hit Rate (~93%+). The agent processes tens of millions of context tokens via KV cache without incurring fresh input pricing.
- **Normalize by Volume:** Compare rates (e.g. `Friction Loops / 100 Cmds`, `Inline Scripts / 100 Cmds`) rather than raw counts. An increase in raw incidents alongside an increase in total command volume is volume expansion, not quality drift.
- **Beware of the Denominator Artifact:** A reduction in tokens/turn is only an efficiency gain if median or mean tokens per conversation also decreased. If user turns doubled, tokens/turn drops purely as a mathematical artifact of task granularity.
- **Granular Inline Script Analysis:** Differentiate multi-line inline scripts (`py -c`, `node -e` with line breaks or >100 chars) from clean one-liners. Multi-line quoting collapses primarily in complex shell parsers, whereas one-liners have distinct failure patterns.
- **Distinguish Intentional Non-Zero Exits:** TDD red-phase test assertions (`pytest` failing before writing code) and polling status (`gh pr checks` exit 8 pending) are normal workflow signals, not execution failures.

### Mode B: Deep Friction Audit & Tri-Layer Remediation
When the user wants to identify recurring errors, eliminate multi-turn loops, or update configurations:
- *"Audit my past sessions and optimize agent rules."*
- *"Check my command failure rate across past trajectories and update workspace AGENTS.md."*
- *"Analyze execution friction across my projects and recommend host tooling fixes."*
- *"Probe my host environment and identify discrepancies in my agent configuration."*

**Full Remediation Path:** Follow the sequential phases below (Inventory -> Probe -> Deep Audit -> Sampling -> Remediation -> Verification). Before proposing any new rule in `GEMINI.md` or `AGENTS.md`, prove with actual transcript sampling that the friction is systematic, recurring, and causes material token/time waste. Avoid speculative rule additions (adhere strictly to YAGNI).

---

## Architecture: Fast Probing, Causal Mining, and Verified Remediation

The workflow operates across six distinct phases:

1. **Scoping & Discovery Gate (Interactive Selection):**
   When invoked without arguments, a fast inventory scan enumerates repositories and date boundaries. The agent uses `ask_question` to let the user select the target project scope and time window before deep parsing begins.

2. **Host Environment Probe (Local Script):**
   `scripts/probe_environment.py` inspects the live host runtime, verifies installed CLI binaries (`git`, `gh`, `rg`, `python`, `dotnet`, `node`, `cargo`), tests standard output stream encoding, and cross-references active rules in `GEMINI.md` to identify false negative claims.

3. **Causal Trajectory Mining & Gains Auditor (Local Script):**
   `scripts/audit_trajectories.py` parses conversation logs, matches sessions to repositories via dynamic git discovery, disambiguates benign zero-match searches (`rg`, `findstr`, `grep`), reconstructs multi-turn incident chains (`initial failed command -> intermediate retries / file writes -> eventual working resolution`), and measures token burn and context metrics.

4. **Targeted Forensic Sampling (Agent Reasoning):**
   For the highest-friction incident chains, the agent uses bounded `view_file` calls directly on `transcript.jsonl` to inspect the original prompt intent, raw error tracebacks, and tool execution context.

5. **Tri-Layer Remediation Synthesis (Agent Execution):**
   Interventions are partitioned into Host Tooling (package manager installs), Global Rules (`~/.gemini/config/GEMINI.md`), and Workspace Rules (`<repo_root>/AGENTS.md`).

6. **Verification Gate (Live Execution):**
   All applied environment configurations, shell rules, or workspace settings are tested using verification commands before completing the turn.

---

## Operational Procedure

### Phase 0: Scoping & Discovery Gate

1. **Explicit Prompt Intent Check:**
   - If the user asks for a **status check, efficiency gains, or token burn**, immediately execute the **Mode A** fast path:
     ```pwsh
     py -3.10 "$SkillScripts\audit_trajectories.py" (Get-Location).Path --since <YYYY-MM-DD> --compare
     ```
     Present findings and finish without running Phase 1-5.
   - If the user designates a target repository (e.g. *"Audit Caster"*) or specific time window (e.g. *"since last week"*), bypass the interactive prompt and execute Phase 1 directly with `--repo <name>` or `--since <date>`.

2. **Rapid Inventory Discovery (< 2 seconds):**
   If invoked bare (e.g. `/improve-agent-efficiency`), execute the rapid inventory discovery mode:

   ```pwsh
   # Windows (PowerShell)
   $SkillScripts = "$HOME\.gemini\config\skills\improve-agent-efficiency\scripts"
   py -3.10 "$SkillScripts\audit_trajectories.py" (Get-Location).Path --inventory-only
   ```

   ```bash
   # macOS / Linux (POSIX)
   SkillScripts="$HOME/.gemini/config/skills/improve-agent-efficiency/scripts"
   python3 "$SkillScripts/audit_trajectories.py" "$(pwd)" --inventory-only
   ```

3. **Interactive Scoping Modal (`ask_question`):**
   Read `trajectory_inventory.json` and call `ask_question` with discovered options pre-populated:
   - **Repository Scope:**
     - `(Recommended) Current workspace only (<current_repo>)`
     - `Top active repositories (<top_3_repos>)`
     - `Full system sweep (all repositories)`
   - **Time Window:**
     - `(Recommended) Recent history (last 14 days)`
     - `Medium history (last 30 days)`
     - `Full lifetime history`

### Phase 1: Execute Host Probe and Trajectory Mining

Execute both diagnostic tools using the scoped arguments:

```pwsh
# Windows (PowerShell)
$SkillScripts = "$HOME\.gemini\config\skills\improve-agent-efficiency\scripts"
py -3.10 "$SkillScripts\probe_environment.py" (Get-Location).Path
py -3.10 "$SkillScripts\audit_trajectories.py" (Get-Location).Path --since <YYYY-MM-DD> --repo <target_repo>
```

```bash
# macOS / Linux (POSIX)
SkillScripts="$HOME/.gemini/config/skills/improve-agent-efficiency/scripts"
python3 "$SkillScripts/probe_environment.py" "$(pwd)"
python3 "$SkillScripts/audit_trajectories.py" "$(pwd)" --since <YYYY-MM-DD> --repo <target_repo>
```

#### Supported Mining Flags
- `--since YYYY-MM-DD`: Restrict audit to sessions on or after a specific date. Useful for measuring the impact of recent rule updates.
- `--compare`: Compare the target time window against baseline history, outputting side-by-side deltas for failure rate, friction loops, token burn per turn/session, and unbounded file view ratios.
- `--repo <keyword>`: Restrict audit to sessions associated with a specific repository name.
- `--exclude <name1,name2>`: Exclude specific repositories from the audit.
- `--all`: Parse all discovered sessions without conversation count limits.
- `--limit <N>`: Maximum recent conversations to evaluate (default: 100).
- `--inventory-only`: Rapid repository inventory scan without parsing transcripts (<2 seconds).
- `--print-summary`: Print structured JSON summary payload directly to stdout after audit completion for programmatic piping without intermediate disk inspection.

The diagnostic run produces two artifacts in the working directory:
- `host_environment_probe.json`: Live binary inventory, stdout encoding status, and rule discrepancies.
- `trajectory_audit_summary.json`: Command failure counts, token burn estimations, repository distribution, and extracted incident chains.

#### Structure & Schema of `trajectory_audit_summary.json`

When `--compare` is active, the JSON root provides:
- `comparison.target_window`: Cohort metrics post `--since` date.
- `comparison.baseline_window` (and alias `comparison.baseline`): Cohort metrics prior to `--since` date.

Each cohort summary object provides:
- `conversations`: Total active conversations in the window.
- `user_turns`: Total user prompts.
- `turns_per_conv`: Mean turns per conversation.
- `commands`: Total CLI commands executed.
- `cmds_per_turn`: Commands normalized per turn.
- `failures`: Non-benign command failure count.
- `failure_rate_pct`: True command failure percentage.
- `friction_per_100_cmds`: High-friction incident rate per 100 commands.
- `inline_per_100_cmds`: Inline `py -c` / `node -e` rate per 100 commands.
- `py_c_multiline`: `{ "total": N, "failed": N, "fail_pct": Float }` (multi-line scripts with `\n` or >100 chars).
- `py_c_oneline`: `{ "total": N, "failed": N, "fail_pct": Float }` (clean one-line scripts).
- `unbounded_views`: Total unbounded `view_file` calls.
- `unbounded_view_pct`: Percentage of file views that were unbounded.
- `total_tokens`: Total tokens across all categories.
- `prompt_tokens`: Tokens from user prompts.
- `response_tokens`: Total response tokens generated by the model (`visible_prose_tokens` + `tool_call_args_tokens`).
- `response_breakdown`:
  - `visible_prose_tokens`: Assistant markdown prose.
  - `tool_call_args_tokens`: Tool call arguments (file write payloads, edits, commands).
  - `thinking_tokens`: Model chain-of-thought tokens.
- `tool_tokens`: Total tool output tokens returned to the model.
- `tool_breakdown`:
  - `unbounded_view_tokens`: File view outputs without start/end lines.
  - `bounded_view_tokens`: File view outputs with line slicing.
  - `run_command_tokens`: Command stdout/stderr outputs.
  - `other_tool_tokens`: Outputs from specialized tools (MCP, subagents, etc.).
- `system_tokens`: Total system / ephemeral injected tokens.
- `system_breakdown`:
  - `skills_notice_tokens`: `[ACTIVE SKILLS LOADED: ...]` injections.
  - `memory_recall_tokens`: `[MCP MEMORY RECALL: ...]` injections.
  - `system_message_tokens`: `<SYSTEM_MESSAGE>` injections.
  - `other_ephemeral_tokens`: Other runtime notifications.
- `api_tokens_ground_truth`:
  - `input_tokens_fresh`: Uncached input tokens.
  - `cache_read_tokens`: Prompt cache read tokens.
  - `output_tokens_model`: Model output tokens.
  - `cache_hit_rate_pct`: Context cache hit ratio (`cache_read / (input + cache_read) * 100`).
- `tokens_per_conv`, `median_tokens_per_conv`, `p90_tokens_per_conv`: Per-session token distribution.
- `tokens_per_turn`: Ratio of total tokens to user turns (task granularity indicator).
- `high_friction_incidents`: Detailed list of multi-step retry chains.

### Phase 2: Review Diagnostic Outputs

Read both generated JSON artifacts using bounded file reading:

1. **Inspect Host Findings:**
   Check `host_environment_probe.json` for missing standard tools (`rg`, `gh`, `dotnet`, runtimes) and encoding errors. Flag any tools that are installed on the system but prohibited or declared absent in `GEMINI.md`.

2. **Inspect High-Friction Incident Chains:**
   Review `high_friction_incidents` in `trajectory_audit_summary.json`. Focus on incidents exhibiting:
   - `retry_count >= 1`: Multi-step trial-and-error attempts before finding a working command.
   - `resolved: false`: Unhandled command failures that blocked completion.
   - `intervening_file_writes`: Cases where the agent had to write a disk script to bypass shell quoting issues.

### Phase 3: Targeted Forensic Sampling

When an incident category shows recurring friction (such as process file locks, module import errors, or encoding crashes), sample the raw conversation log to understand the full context:

1. Identify the `conversation_id` and `initial_step` from the incident record.
2. Locate the transcript file at:
   `<appDataDir>/brain/<conversation_id>/.system_generated/logs/transcript.jsonl`
3. Execute bounded file inspection around the failure step index to review the exact error stack and model reasoning.

### Phase 4: Tri-Layer Remediation Deployment

Apply corrective measures categorized across three distinct layers:

1. **Host Tooling Layer (Zero Token Overhead):**
   - Install missing CLI utilities requested by agents using native package managers (`winget install --id <Id>`, `brew install <pkg>`).
   - Set persistent environment variables for terminal streams (e.g., `[Environment]::SetEnvironmentVariable("PYTHONIOENCODING", "utf-8", "User")`).

2. **Global Rules Layer (`~/.gemini/config/GEMINI.md`):**
   - Correct false statements regarding installed platform binaries.
   - Enforce the File-First Execution SOP for multi-line logic (`py -c`, `node -e`).
   - Enforce bounded reading and bounded command output limits.

3. **Workspace Rules Layer (`<repo_root>/AGENTS.md`):**
   - Reference [references/remediation_patterns.md](references/remediation_patterns.md) for language-specific templates.
   - Codify runtime pinning (`python`), explicit `PYTHONPATH` exports, solution file targets (`.slnx`), pre-build process termination, and test invocation commands.

### Phase 5: Verification Gate

Validate all applied changes before concluding the task:

1. For host tool installations: Run `<binary> --version` to verify exit code 0.
2. For environment variables: Run a test command verifying the variable is active in child processes.
3. For workspace rules: Verify test runner commands and build commands execute cleanly against the target repository.
4. Format findings, incident comparisons, and verified actions into a final Markdown artifact for user review.
