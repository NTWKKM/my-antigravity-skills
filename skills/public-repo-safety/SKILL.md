---
name: public-repo-safety
description: Audits, scaffolds, and enforces pre-commit hooks, CI safety gates, and Antigravity manifest integrity checks to prevent hardcoded local user paths (Windows C:\Users, Unix /home or /Users), secrets, API keys, binary blobs, and malformed SKILL.md or plugin.json files from being committed. Use when open-sourcing a repository, auditing for path or secret leaks, setting up pre-commit or GitHub Actions safety checks, or validating Antigravity skill/plugin repositories.
---

# Public Repository Safety & Hygiene

Use this skill when onboarding, auditing, or configuring a public repository (including Antigravity skill and plugin repositories) to intercept personal path leaks, credentials, binary artifacts, and manifest errors before commits reach GitHub.

## When to Run This Skill
- Creating or open-sourcing a new public repository.
- Auditing an existing repository prior to release or contribution.
- Validating Antigravity customization manifests (`plugin.json`, `.agents/skills.json`, and `skills/*/SKILL.md` frontmatter).
- Scaffolding local developer hooks (`.git/hooks/pre-commit`, `.pre-commit-config.yaml`) and GitHub Actions CI gates (`.github/workflows/ci.yml`).

See [`references/detection_rules.md`](references/detection_rules.md) for the full threat model, regex signatures, and inline suppression markers (`# nosec`, `# allow-path`).

---

## Workflow Sequence

### Phase 1: Pre-Audit Existing Workspace
1. Verify repository root via `git rev-parse --show-toplevel`.
2. Execute [`scripts/check_repo_safety.py`](scripts/check_repo_safety.py) across all tracked files and manifests:
   ```bash
   python3 "<SkillDir>/scripts/check_repo_safety.py" --repo-root "$(git rev-parse --show-toplevel)"
   ```
3. If violations are flagged, redact leaked paths/secrets or fix malformed `SKILL.md` / `plugin.json` / `.agents/skills.json` files before committing.

### Phase 2: Scaffold Safety Components
Deploy the three-tier safety infrastructure into `<target_repo>`:

1. **Scanner Script:**
   Copy [`scripts/check_repo_safety.py`](scripts/check_repo_safety.py) to `<target_repo>/scripts/check_repo_safety.py`.
2. **Pre-Commit Framework Configuration:**
   Copy [`templates/.pre-commit-config.yaml`](templates/.pre-commit-config.yaml) to `<target_repo>/.pre-commit-config.yaml`.
3. **Native Git Hook Wrapper:**
   Copy [`templates/pre-commit-hook.sh`](templates/pre-commit-hook.sh) to `<target_repo>/.git/hooks/pre-commit` and make it executable:
   ```bash
   chmod +x .git/hooks/pre-commit
   ```
4. **CI Workflow Gate:**
   Copy [`templates/ci-safety.yml`](templates/ci-safety.yml) to `<target_repo>/.github/workflows/ci.yml`.

### Phase 3: Verification & Interception Gate
1. Run `python3 scripts/check_repo_safety.py` in `<target_repo>` and confirm `[PASSED]` (exit code `0`) with zero violations.
2. Verify that `.git/hooks/pre-commit` is executable (`test -x .git/hooks/pre-commit`).
3. Confirm `.gitignore` does not block required Antigravity manifests (`!plugin.json`, `!.agents/*.json`) if wildcard `*.json` rules are present.

---

## Platform Portability
- **Windows:** Supported via Python 3.10+ and Git for Windows (`.git/hooks/pre-commit` runs under Git Bash).
- **macOS & Linux:** Native execution using `python3` and POSIX `sh`.
