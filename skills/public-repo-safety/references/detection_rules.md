# Detection Rules & Threat Model

The `check_repo_safety.py` scanner validates tracked files against three risk categories:

## 1. Absolute Local Path Leaks
* **Windows Drive Paths:** Matches `[A-Za-z]:\Users\` or `[A-Za-z]:/Users/`.
* **Unix Home Paths:** Matches `/home/<user>/` or `/Users/<user>/`.
* **Local File URIs:** Matches `file:///C:/Users/...` or `file:///home/...`.
* **Active User Leaks:** Matches dynamically resolved username strings (`getpass.getuser()`) within filesystem paths.

## 2. Secrets & Credentials
* **Private Keys:** `-----BEGIN [RSA|OPENSSH|EC|DSA|PGP] PRIVATE KEY-----`.
* **API Keys:** Common provider token signatures (`sk_live_...`, `pk_test_...`).
* **GitHub Tokens:** Personal access tokens (`ghp_...`) and OAuth access tokens (`gho_...`).
* **JWT Tokens:** Standard Base64 encoded JSON Web Tokens (`eyJ...`).
* **Personal Emails:** Plain email addresses matching real domains (ignores `example.com`, `domain.com`, `users.noreply.github.com`).

## 3. Disallowed Binary Blobs
* Flags tracked binary extensions: `.dll`, `.exe`, `.pdb`, `.so`, `.dylib`, `.pyc`, `.pyo`, `.pyd`, `.class`, `.zip`, `.tar.gz`, `.tgz`, `.7z`, `.bin`.

## 4. Antigravity & Plugin Manifest Integrity
* **`plugin.json`:** Verifies valid JSON object structure and non-empty `name` field when present.
* **`.agents/skills.json`:** Verifies valid JSON object structure and confirms all workspace-relative `entries[].path` targets exist on disk.
* **`skills/*/SKILL.md`:** Verifies that every skill directory contains a `SKILL.md` with valid YAML frontmatter (`---`), a `name` matching the directory name, and a non-empty `description`.
* **`manifest.json`:** Validates legacy plugin paths and `metadata.toml` alignment when present.

## Inline Exclusions
To intentionally bypass detection for test fixtures or mock payloads:
* Append `# nosec` or `# allow-path` to the target line.
