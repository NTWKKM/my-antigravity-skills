# My Antigravity Skills

A repository of custom skills, diagnostic utilities, and execution runbooks for Google Antigravity (**Antigravity 2.0**, **Antigravity IDE**, and **Antigravity CLI (`agy`)**).

This repository ships as a native Antigravity plugin ([`plugin.json`](./plugin.json)) with workspace auto-discovery ([`.agents/skills.json`](./.agents/skills.json)), and can also be mounted globally into `~/.gemini/config/skills/` or `~/.gemini/config/plugins/`.

---

## Skills Catalog

| Skill | Category | Platforms | Supported Stacks | Key Capability |
| :--- | :--- | :--- | :--- | :--- |
| [`improve-agent-efficiency`](./skills/improve-agent-efficiency/) | Diagnostics & Auditing | Linux, macOS, Windows | TypeScript/Node, Python, Go, Rust, .NET | Probes live host tooling & rule context budgets (`24 KB` per file / `20,000` tokens), mines multi-turn causal incident chains across Antigravity 2.0/IDE/CLI transcripts, evaluates comparative gains via conversation-level bootstrap testing, and deploys verified quad-layer remediations (host binaries, `hooks.json`, global rules, and workspace `AGENTS.md`). |
| [`public-repo-safety`](./skills/public-repo-safety/) | Security & Hygiene | Linux, macOS, Windows | Any (Language-agnostic Git & Python scanner) | Audits, scaffolds, and enforces pre-commit hooks, CI safety gates, and Antigravity manifest integrity (`plugin.json`, `.agents/skills.json`, `SKILL.md` frontmatter) to prevent hardcoded local user paths, secrets, API keys, and binary blobs from being committed. |

---

## Included Skills

### `improve-agent-efficiency`

An automated diagnostic runbook and toolset that inspects past agent conversation transcripts across Antigravity 2.0, Antigravity IDE, and Antigravity CLI, evaluates token burn and efficiency gains, detects execution friction and multi-turn retry loops, probes the live host environment and rule context budgets, and executes verified systemic remediations.

#### Core Diagnostic Utilities

The skill bundles two standalone, zero-dependency Python scripts in `scripts/` and disclosed reference manuals in `references/`:

1. **Host Environment & Rule Budget Probe ([`scripts/probe_environment.py`](./skills/improve-agent-efficiency/scripts/probe_environment.py)):**
   - Tests UTF-8 codec resilience in-memory without polluting `stdout`.
   - Inspects host availability and version strings for standard engineering & Antigravity CLI binaries (`git`, `gh`, `rg`, `fd`, `jq`, `curl`, `python`, `python3`, `uv`, `node`, `pnpm`, `npm`, `cargo`, `go`, `dotnet`, `agy`, plus platform package managers `brew`, `winget`, `pwsh`, `apt`).
   - Audits `~/.gemini/GEMINI.md`, `~/.gemini/AGENTS.md`, `~/.gemini/config/GEMINI.md`, `~/.gemini/config/AGENTS.md`, and `~/.gemini/config/rules/*.md` against Antigravity's **`24,000`-byte per-file truncation cap** and **`20,000`-token `defaultRulesBudget`**, as well as binary discrepancies and `hooks.json` presence.
   - Writes diagnostic output to `host_environment_probe.json`.

2. **Causal Trajectory Auditor ([`scripts/audit_trajectories.py`](./skills/improve-agent-efficiency/scripts/audit_trajectories.py)):**
   - Parses local conversation transcripts across all discovered brain storage locations (`antigravity`, `antigravity-ide`, `antigravity-cli`), automatically preferring uncompressed `transcript_full.jsonl` whenever available to prevent tool truncation skew.
   - **Antigravity 2.0 & IDE Workspace Resolution:** Dynamically maps conversations to git repositories via Antigravity 2.0 multi-root `Active Workspaces:` blocks, `Command Working Directory:` headers, legacy `active workspace is` lines, and file paths touched during tool calls.
   - **Post-Filter Cohort Limiting:** Applies `--repo` and `--exclude` filters before slicing to `--limit <N>` (and caps cohorts independently in `--compare` mode) so targeted repository audits are never starved by newer sessions in other projects.
   - **Zero-Match & Pending-Check Disambiguation:** Distinguishes benign pattern searches (`rg`, `grep`, `findstr`, `diff` exiting with code 1) and pending PR checks (`gh pr checks` exit 8) from actual runtime crashes.
   - **Conversation-Level Bootstrap Significance (`--compare`):** Evaluates comparative efficiency gains and token burn using 1,000-resample non-parametric cluster bootstrapping (`seed=42`) with pooled-ratio statistics for rate metrics and location statistics for continuous metrics. Directional outcomes (`IMPROVED` / `DRIFT`) require $N \ge 15$ per cohort and $0$ outside the 95% CI; otherwise variations are labeled `NEUTRAL`.
   - **Ground-Truth API Token Telemetry:** Extracts native API token counts (`input_tokens_fresh`, `cache_read_tokens`, `output_tokens_model`), calculates prompt KV cache hit rates, evaluates context magnification factors, and calibrates estimation ratios against transcript character counts.
   - **Granular Token & Action Decomposition:** Decomposes response tokens into visible assistant prose, tool call arguments (`overwrite`, `append`, and `create` modes), and internal thinking tokens; distinguishes redundant unmodified file re-reading from legitimate post-edit verifications via modification epoch tracking.
   - **Rapid Inventory Mode (`--inventory-only`):** Enumerates repositories, conversation counts, and true `created_at` temporal boundaries in seconds.
   - Writes structured reports to `trajectory_audit_summary.json` or `trajectory_inventory.json` (see [`references/metrics_and_schema.md`](./skills/improve-agent-efficiency/references/metrics_and_schema.md)).

#### Two Operational Modes

##### Mode A: Read-Only Efficiency Gains & Token Burn Check
Use when evaluating whether recent rule adjustments, hooks, or environment updates worked:
- *"Check our efficiency status and token burn over the last 24 hours."*
- *"Analyze our efficiency gains since yesterday."*
- *"Did our recent rule updates reduce command failures and token burn?"*

The agent runs a single read-only command targeting the session scratch directory (`audit_trajectories.py <scratch_dir> --since <date> --compare`), reports the comparison table, and exits without modifying files.

##### Mode B: Deep Friction Audit & Quad-Layer Remediation
Use when discovering new friction, repairing broken tool paths, or writing new hooks/rules:
- *"Audit my past sessions and optimize agent rules."*
- *"Check my command failure rate across past trajectories and update workspace AGENTS.md."*

Executes across six sequential phases:
1. **Scoping & Discovery Gate:** Run rapid inventory scan (`--inventory-only`) into `<scratch_dir>` and select scope.
2. **Host Probe and Trajectory Mining:** Run `probe_environment.py` and `audit_trajectories.py`.
3. **Diagnostic Output Review:** Inspect `host_environment_probe.json` (including rule byte/token caps) and high-friction incidents.
4. **Targeted Forensic Sampling:** Inspect bounded lines in `transcript_full.jsonl` around failure steps.
5. **Quad-Layer Remediation Deployment** (see [`references/remediation_patterns.md`](./skills/improve-agent-efficiency/references/remediation_patterns.md)):
   - **Layer 1 — Host Tooling & Antigravity 2.0 Settings (Zero Token Cost):** Install missing platform binaries (`brew`, `winget`, `apt`), configure `PYTHONIOENCODING=utf-8`, and align Antigravity 2.0 Command Allowlist/Denylist & Sandbox settings.
   - **Layer 2 — Deterministic Lifecycle Hooks (`hooks.json` — Zero Token Cost):** Use `PreToolUse` (`"decision": "deny"` or `"overwrite"`) and `PostToolUse` to intercept recurring command anti-patterns or auto-format files without spending prompt tokens.
   - **Layer 3 — Global Rules (`~/.gemini/config/GEMINI.md` & `AGENTS.md`):** Correct platform binary declarations and enforce the File-First Execution SOP while keeping each rule file strictly `< 24,000` bytes and aggregate rules `< 20,000` tokens.
   - **Layer 4 — Workspace Customizations (`<repo_root>/AGENTS.md` & `.agents/`):** Enforce runtime pinning, lockfile policies, build/test commands, pre-build process termination, and `.agents/skills.json`.
6. **Verification Gate:** Test all applied changes (`<binary> --version`, rule budget probe, builds, and tests) before concluding.

---

### `public-repo-safety`

An automated security, hygiene, and manifest integrity runbook for public and open-source repositories. Scaffolds pre-commit interception hooks, portable scanners, and GitHub Actions CI gates to prevent data leakage, user path disclosure, accidental credential commits, and broken Antigravity skill/plugin manifests.

#### Core Capabilities
- **Local Path Hygiene:** Detects Windows user paths (`C:\Users\...`), Unix user home paths (`/home/...`, `/Users/...`), active username fragments, and local `file:///` URIs.
- **Credential & Secret Interception:** Flags private key headers, provider API tokens, GitHub personal access tokens, JWT tokens, and unredacted personal email addresses.
- **Binary Artifact Gate:** Blocks tracking of compiled binaries, objects, and unmanaged archives (`.dll`, `.exe`, `.so`, `.dylib`, `.zip`, `.pyc`).
- **Antigravity & Plugin Manifest Integrity:** Validates `plugin.json`, `.agents/skills.json` entry paths, and `skills/*/SKILL.md` YAML frontmatter (`name` matching directory and non-empty `description`).
- **Three-Tier Enforcement:** Deploys a standalone scanner ([`scripts/check_repo_safety.py`](./skills/public-repo-safety/scripts/check_repo_safety.py)), local Git hook interception (`.git/hooks/pre-commit`, `.pre-commit-config.yaml`), and GitHub Actions CI verification (`.github/workflows/ci.yml`).

#### Known Limitations & Caveats
- Requires Python 3.10+ and Git CLI on the host machine.
- For intentional test fixtures or mock payloads, bypass inspection on specific lines by appending `# nosec` or `# allow-path`.

---

## Usage

### Direct Chat Invocation

Trigger the audit workflow directly from chat:

```
# Mode A: Status & Gains
/improve-agent-efficiency check efficiency gains and token burn for the last 24 hours

# Mode B: Full Audit & Remediation
/improve-agent-efficiency audit my past sessions and optimize agent rules
```

### Manual CLI Execution & Unit Tests

Run the diagnostic scripts or unit test suite directly from the repository root:

```bash
# macOS / Linux (POSIX)
# 1. Comparative efficiency gains & token burn audit
python3 ./skills/improve-agent-efficiency/scripts/audit_trajectories.py ./scratch --since 2026-10-07 --compare

# 2. Rapid repository inventory (<2 seconds)
python3 ./skills/improve-agent-efficiency/scripts/audit_trajectories.py ./scratch --inventory-only

# 3. Deep diagnostic probe & trajectory audit
python3 ./skills/improve-agent-efficiency/scripts/probe_environment.py ./scratch
python3 ./skills/improve-agent-efficiency/scripts/audit_trajectories.py ./scratch --limit 50 --exclude temp-repo

# 4. Repository safety check & unit test suite
python3 ./scripts/check_repo_safety.py
python3 -m unittest discover -s tests -v
```

```pwsh
# Windows (PowerShell)
# 1. Comparative efficiency gains & token burn audit
python .\skills\improve-agent-efficiency\scripts\audit_trajectories.py .\scratch --since 2026-10-07 --compare

# 2. Rapid repository inventory (<2 seconds)
python .\skills\improve-agent-efficiency\scripts\audit_trajectories.py .\scratch --inventory-only

# 3. Deep diagnostic probe & trajectory audit
python .\skills\improve-agent-efficiency\scripts\probe_environment.py .\scratch
python .\skills\improve-agent-efficiency\scripts\audit_trajectories.py .\scratch --limit 50 --exclude temp-repo

# 4. Repository safety check & unit test suite
python .\scripts\check_repo_safety.py
python -m unittest discover -s tests -v
```

### Command-Line Arguments

The `audit_trajectories.py` script supports the following filtering parameters:

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `output_dir` | Positional | Current Directory | Target directory for generated JSON reports (use a scratch directory to keep git clean) |
| `--compare` | Flag | `False` | Compare target window against baseline history and compute efficiency gains / token burn deltas |
| `--since` | String (`YYYY-MM-DD` / timestamp) | `None` | Restrict parsing to sessions recorded on or after this date/time (or start of target window) |
| `--until` | String (`YYYY-MM-DD` / timestamp) | `None` | Restrict parsing to sessions recorded on or before this date/time (inclusive) |
| `--limit` | Integer | `100` | Maximum number of recent matching conversations to parse (applied after `--repo` / `--exclude`) |
| `--repo` | String | `None` | Filter parsing to sessions matching a repository substring |
| `--exclude` | String | `None` | Comma-separated list of repository names to exclude from parsing |
| `--exclude-conv` | String | `None` | Comma-separated list of conversation IDs to exclude from parsing |
| `--include-audit-sessions` | Flag | `False` | Include self and audit/meta-evaluation sessions (default: excluded) |
| `--all` | Flag | `False` | Parse all discovered conversations across all storage locations |
| `--inventory-only` | Flag | `False` | Discover repositories and `created_at` date boundaries rapidly without parsing full transcripts |
| `--print-summary` | Flag | `False` | Print structured JSON summary payload directly to stdout for headless piping |

### Diagnostic Artifacts

The scripts generate structured JSON artifacts in the specified output directory:

| Artifact | Generated By | Primary Contents |
| :--- | :--- | :--- |
| `trajectory_inventory.json` | `audit_trajectories.py --inventory-only` | Total conversation count, earliest/latest `created_at` session dates, active workspace info, and list of discovered git repositories |
| `host_environment_probe.json` | `probe_environment.py` | Platform details, Python stream encoding status, installed binary inventory, `hooks.json` status, rule byte/token counts, and configuration discrepancies against `GEMINI.md` / `AGENTS.md` |
| `trajectory_audit_summary.json` | `audit_trajectories.py` | Aggregate command failure metrics, native API tokens, token burn metrics, category breakdowns, comparative gains (`--compare`), extracted incident chains, and `comparison.bootstrap_significance_tests` |

---

## Installation

### Option 1: Zero-Copy Plugin or `skills.json` Registration (Recommended)

Because this repository includes a root [`plugin.json`](./plugin.json) and [`.agents/skills.json`](./.agents/skills.json), you can link or register it directly so `git pull` updates stay live automatically:

```bash
# Symlink as a global Antigravity plugin (macOS / Linux)
mkdir -p ~/.gemini/config/plugins
ln -s "$(pwd)" ~/.gemini/config/plugins/my-antigravity-skills
```

Or register the repository's `skills/` directory in `~/.gemini/config/skills.json` (or `<project_root>/.agents/skills.json`):

```json
{
  "entries": [
    {
      "path": "/path/to/my-antigravity-skills/skills"
    }
  ]
}
```

### Option 2: Standalone Global Copy (Machine Scope)

```bash
# macOS & Linux
mkdir -p ~/.gemini/config/skills
cp -r ./skills/improve-agent-efficiency ~/.gemini/config/skills/
cp -r ./skills/public-repo-safety ~/.gemini/config/skills/
```

```pwsh
# Windows PowerShell
$dest = "$env:USERPROFILE\.gemini\config\skills"
Copy-Item -Path ".\skills\improve-agent-efficiency" -Destination "$dest\improve-agent-efficiency" -Recurse -Force
Copy-Item -Path ".\skills\public-repo-safety" -Destination "$dest\public-repo-safety" -Recurse -Force
```

### Option 3: Workspace Copy (Project Scope)

```bash
# macOS & Linux
mkdir -p <project_root>/.agents/skills
cp -r ./skills/improve-agent-efficiency <project_root>/.agents/skills/
cp -r ./skills/public-repo-safety <project_root>/.agents/skills/
```

