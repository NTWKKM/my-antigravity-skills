# Remediation Patterns & Invariant Archetypes

This reference guide details how to translate trajectory failure patterns into actionable, high-density Antigravity configurations.

---

## 1. The Quad-Layer Remediation Model

When auditing agent failures in Antigravity, prioritize zero-token deterministic layers before spending always-on rule context budget:

```
Layer 1: Native Host Tools & Antigravity 2.0 Settings (Zero Token Cost)
   ├── Install missing host binaries (rg, gh, fd, jq, uv, node, pnpm, go, cargo, dotnet) globally rather than adding prompt workarounds.
   └── Configure Antigravity 2.0 Settings (Command Allowlist/Denylist, Sandbox Mode, Non-Workspace File Access, Permission Grants).

Layer 2: Deterministic Lifecycle Hooks (hooks.json — Zero Token Cost)
   ├── Use PreToolUse (matcher: "run_command") to hard-block ("decision": "deny") or rewrite ("overwrite": {"CommandLine": "..."}) recurring command anti-patterns (e.g., multiline python -c, wrong package manager).
   └── Use PostToolUse (matcher: "replace_file_content|write_to_file") for automatic formatting/linting instead of spending agent turns.

Layer 3: Global Rules (~/.gemini/config/GEMINI.md & AGENTS.md)
   ├── Enforce cross-project behavioral invariants (File-First Execution SOP, bounded reading).
   └── Budget Guardrail: Each rule file is hard-capped at 24,000 bytes (truncated on line boundaries above 24 KB) and all always-on rules share a 20,000-token defaultRulesBudget. Always prune or disclose domain rules before adding new lines.

Layer 4: Workspace Customizations (<repo_root>/AGENTS.md & .agents/)
   └── Deploy project-specific invariants (PYTHONPATH, package manager, solution file, port hygiene, test targets, .agents/skills.json, .agents/hooks.json) locally.
```

---

## 2. Common Failure Archetypes & Prescriptions

### Archetype 1: Inline Script Quoting Collapse
- **Symptoms:** `SyntaxError: unterminated string literal`, `SyntaxError: '(' was never closed`, `ParserError: Unexpected token`.
- **Root Cause:** Shell parsing in bash, zsh, or PowerShell strips nested quotes and breaks multi-line logic passed via inline flags (`python -c`, `node -e`, `bash -c`).
- **Remediation:**
  - **Global Rule:** Enforce a strict **File-First Execution SOP**: multi-line logic must be written to `<appDataDir>/brain/<id>/scratch/` as a standalone script file and executed directly.
  - **Deterministic Hook (`hooks.json`):** Add a `PreToolUse` handler matching `"run_command"` that returns `{"decision": "deny", "reason": "Multi-line python -c / node -e is prohibited; write a script file to scratch/ instead."}` when `CommandLine` contains `python -c` / `node -e` with newline characters.

### Archetype 2: Console Output Encoding & Stream Traps
- **Symptoms:** `UnicodeEncodeError: 'charmap' codec can't encode character...`, garbled terminal control sequences.
- **Root Cause:** Operating system terminal standard output defaults to legacy non-UTF-8 code pages.
- **Remediation:**
  - Set persistent environment variable `PYTHONIOENCODING=utf-8`.
  - On Windows, install a `sitecustomize.py` in Python `site-packages` that reconfigures `sys.stdout` to UTF-8.

### Archetype 3: Missing Host Binary
- **Symptoms:** `The term '<binary>' is not recognized`, `command not found: <binary>`.
- **Root Cause:** Agent prompts or model training bias reach for standard CLI tools not installed in the host system PATH.
- **Auditor Guidance:**
  - Dynamically extract whatever binary name triggered `not recognized` or `command not found` from the standard error stream.
  - Typical examples include repository search utilities (`rg`, `fd`), platform clients (`gh`, `agy`), language runtimes (`uv`, `node`, `pnpm`, `go`, `cargo`, `dotnet`), and data formatters (`jq`).
- **Remediation:**
  - Windows: `winget install --id <PackageId> --exact`
  - macOS: `brew install <package>`
  - Linux: `apt install -y <package>` or `pacman -S <package>`

### Archetype 4: Dependency & Module Resolution Failures
- **Symptoms:** `ModuleNotFoundError: No module named '<pkg>'`, `ERR_MODULE_NOT_FOUND`, `ERESOLVE unable to resolve dependency tree`.
- **Root Cause:** Scripts executed without exporting local project paths, virtual environment binaries, or running wrong package manager variants (`npm` instead of `pnpm`).
- **Remediation:**
  - Python: Deploy `<repo_root>/AGENTS.md` containing explicit environment exports (e.g. `PYTHONPATH = "."`) or pinning runners (`uv run pytest`).
  - JavaScript / TypeScript: Specify exact package manager (`pnpm`, `npm`, `yarn`, `bun`) and enforce strict lockfile adherence (`pnpm install --frozen-lockfile`).

### Archetype 5: Concurrency, Port Collisions, & Process File Locks
- **Symptoms:** `CSC : error CS2012: Cannot open '...dll' for writing`, `EADDRINUSE: address already in use :::3000`, `text file busy`.
- **Root Cause:** A running daemon, background test runner, or dev server holds an open handle or socket on the build target.
- **Remediation:**
  - Deploy `<repo_root>/AGENTS.md` prescribing pre-build process termination or port reclamation before recompiling or launching servers.

### Archetype 6: POSIX Permissions & Shell Execution Traps
- **Symptoms:** `permission denied: ./script.sh`, `EACCES: permission denied`.
- **Root Cause:** Scripts generated without executable bits (`+x`) or invoked without explicit shell interpreter prefix.
- **Remediation:**
  - Codify interpreter prefixes in rules (e.g. `bash ./script.sh` or explicit `chmod +x` prior to invocation).

### Archetype 8: Context Magnification & Token Cost Inefficiency
- **Symptoms:** High token burn across long conversations, slow response latency, context reaching P90 (>240k tokens).
- **Root Cause:** In multi-turn agent loops (median ~84 API calls), prompt context is re-processed on every turn, causing a ~90x cumulative context magnification factor. Context input represents **~92.8% – 94.5% of total dollar cost**, while tool call arguments represent **~48.3% of model output tokens**. Visible chat prose is <0.4% of cost.
- **Remediation:**
  - **Surgical Diff Tooling (Layer 2/3):** Enforce `replace_file_content` over whole-file `write_to_file`. Replacing a 10-line block consumes ~50 tokens in tool arguments, whereas rewriting an 800-line file consumes ~4,000 output tokens.
  - **Bounded File Views (Layer 3):** Always use `view_file` with explicit `StartLine` and `EndLine` parameters (or grep/find first) to prevent injecting megabytes of source files into conversation context history.
  - **Proactive Compaction Gate (Layer 3):** Trigger `/compact` or summarize history when conversation reaches ~20 turns or context approaches P90 (~240k tokens), before the 90x magnification factor multiplies the accumulated context across remaining turns.
  - **Prefix Cache Stability (Layer 3/4):** Keep invariant rules, skills, and system instructions in stable prefixes so the prompt cache achieves $\ge 93\%$ cache hit rates ($0.25\times$ pricing discount).

---

## 3. Workspace Rule Templates (`AGENTS.md`)

### Template A: TypeScript / Full-Stack Project (Node.js, Vite, Next.js)
```markdown
# <ProjectName> Workspace Rules

## 1. Runtime & Package Management
- Package Manager: Pin to `pnpm`. Do not use `npm` or `yarn`.
- Install Command: Use `pnpm install --frozen-lockfile`.
- Module Resolution: Project uses native ECMAScript Modules (`"type": "module"`). Use fully qualified import specifiers with extensions if required by bundler.

## 2. Quality Checks & Builds
- Type Checking: Run `pnpm exec tsc --noEmit` before proposing completed refactors.
- Linter: Run `pnpm lint`.
- Dev Server Hygiene: Before starting dev servers (`pnpm dev`), ensure target ports (e.g. 3000, 5173) are vacant.

## 3. Test Execution
- Runner: Run tests via `pnpm test` or `pnpm exec vitest run <file>`.
```

### Template B: Python Project (Modern `uv` / Virtualenv)
```markdown
# <ProjectName> Workspace Rules

## 1. Runtime & Environment Stack
- Package & Environment Manager: Target `uv` or pinned virtualenv at `.venv/`.
- Execution Prefix: Run scripts and tools via `uv run python <script>` or `uv run pytest`.
- Environment Paths: Set `PYTHONPATH = "."` when executing uninstalled package modules.
- Encoding: Enforce UTF-8 standard output on all data parsers and file handlers.

## 2. Test Execution
- Run tests via pinned environment: `uv run pytest tests/ -v`
- Avoid wildcard path arguments in shell runners.
```

### Template C: Go Module Project
```markdown
# <ProjectName> Workspace Rules

## 1. Toolchain & Dependencies
- Go Version: Target Go 1.22+.
- Dependency Sync: Run `go mod tidy` after modifying imports. Do not manually edit `go.sum`.

## 2. Testing & Quality Checks
- Test Execution: Run `go test -race -timeout 30s ./...`
- Targeted Test: Run `go test -v -run <TestName> ./<package>`
- Vet: Run `go vet ./...` before finalizing code edits.
```

### Template D: Rust / Cargo Workspace
```markdown
# <ProjectName> Workspace Rules

## 1. Toolchain & Workspace Targets
- Compiler: Stable Rust toolchain.
- Target Selection: Target specific crates via `-p <crate_name>` in workspace roots.
- Fast Checks: Run `cargo check --workspace` before initiating full compilation.

## 2. Testing & Linting
- Linting: Run `cargo clippy --all-targets -- -D warnings`
- Tests: Run `cargo test -p <crate_name> -- --nocapture`
```

### Template E: .NET / C# Solution
```markdown
# <ProjectName> Workspace Rules

## 1. Runtime & Build Target
- Framework: .NET 10 (`net10.0-windows` or `net10.0`).
- Solution File: Target `<Project>.slnx` directly. Do not target legacy `.sln` files.
- Process Hygiene: Before running `dotnet build`, terminate running instances locking output binaries:
  PowerShell: `Get-Process -Name "*<ProcessName>*" -ErrorAction SilentlyContinue | Stop-Process -Force`
  POSIX: `pkill -f "<ProcessName>" || true`
```
