#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Amir Farhadi
"""
Repository Safety, Secret, Path Hygiene & Integrity Scanner

Inspects tracked repository files for:
1. Hardcoded absolute user paths (Windows C:\\Users, Unix /home and /Users, local file:/// URIs).
2. Active OS username string components.
3. Secrets, API keys, private keys, JWT tokens, and plain personal email addresses.
4. Tracked binary artifacts, build outputs, and large blobs.
5. Optional manifest and package descriptor integrity.
"""

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import List, Optional, Set, Tuple

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

IGNORED_DIRS: Set[str] = {
    ".git",
    ".vs",
    ".vscode",
    "bin",
    "obj",
    "node_modules",
    ".ruff_cache",
    ".idea",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".agents",
}

IGNORED_EXTENSIONS: Set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".mp4",
    ".ico",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
}

DISALLOWED_BINARY_EXTENSIONS: Set[str] = {
    ".dll",
    ".exe",
    ".pdb",
    ".so",
    ".dylib",
    ".pyc",
    ".pyo",
    ".pyd",
    ".class",
    ".zip",
    ".tar.gz",
    ".tgz",
    ".7z",
    ".bin",
}

IGNORED_FILES: Set[str] = {
    ".test_cache.json",
}

WINDOWS_USER_PATH_RE = re.compile(
    r"[A-Za-z]:(?:\\{1,4}|/)+(?:Users|Documents and Settings)(?:\\{1,4}|/)+",
    re.IGNORECASE,
)
USER_HOME_PATH_RE = re.compile(
    r"(?:[A-Za-z]:(?:\\{1,4}|/)+|/|\\{1,4})(?:Users|home|Documents and Settings)(?:\\{1,4}|/)+[A-Za-z0-9_.-]+(?:\\{1,4}|/)+",
    re.IGNORECASE,
)
UNIX_USER_PATH_RE = re.compile(
    r"^/(?:Users|home)/[A-Za-z0-9_.-]+(?:/|$)", re.IGNORECASE
)
USER_FILE_URI_RE = re.compile(
    r"file:///(?:[A-Za-z]:/(?:Users|Documents and Settings|home)|(?:Users|home)/)",
    re.IGNORECASE,
)

try:
    CURRENT_USER = getpass.getuser()
    if (
        CURRENT_USER
        and len(CURRENT_USER) > 1
        and CURRENT_USER.lower()
        not in {
            "root",
            "runner",
            "github",
            "administrator",
            "system",
            "default",
        }
    ):
        ACTIVE_USER_PATH_RE = re.compile(
            rf"(?:\\{{1,4}}|/)+{re.escape(CURRENT_USER)}(?:\\{{1,4}}|/)+",
            re.IGNORECASE,
        )
    else:
        ACTIVE_USER_PATH_RE = None
except Exception:
    ACTIVE_USER_PATH_RE = None

SECRET_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (
        re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP)?\s?PRIVATE KEY-----"),
        "Private Key Header",
    ),
    (re.compile(r"\b(?:sk|pk)_(?:live|test)_[0-9a-zA-Z]{24,}\b"), "API Key Token"),
    (re.compile(r"\bghp_[0-9a-zA-Z]{36}\b"), "GitHub Personal Access Token"),
    (re.compile(r"\bgho_[0-9a-zA-Z]{36}\b"), "GitHub OAuth Access Token"),
    (
        re.compile(
            r"\beyJ[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{20,}\b"
        ),
        "JWT Token",
    ),
    (
        re.compile(
            r"\b[A-Za-z0-9._%+-]+@(?!(?:example\.com|users\.noreply\.github\.com|domain\.com)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
            re.IGNORECASE,
        ),
        "Plain Personal Email Address",
    ),
]


def resolve_repo_root(start_dir: Optional[str] = None) -> Path:
    cur = Path(start_dir or os.getcwd()).resolve()
    while cur != cur.parent:
        if (cur / ".git").exists():
            return cur
        cur = cur.parent
    return Path(start_dir or os.getcwd()).resolve()


def get_git_tracked_files(repo_root: Path) -> List[str]:
    try:
        res = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        out = []
        for entry in res.stdout.split("\0"):
            if entry and (repo_root / entry).is_file():
                out.append(entry)
        return sorted(set(out))
    except Exception:
        files = []
        for root, dirs, filenames in os.walk(str(repo_root)):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for fn in filenames:
                p = Path(root) / fn
                rel = p.relative_to(repo_root).as_posix()
                files.append(rel)
        return files


def check_file_hygiene(repo_root: Path, rel_path: str) -> List[str]:
    violations: List[str] = []
    file_path = repo_root / rel_path

    if Path(rel_path).name == "check_repo_safety.py":
        return violations

    ext = file_path.suffix.lower()
    if ext in DISALLOWED_BINARY_EXTENSIONS:
        violations.append(
            f"{rel_path}: Tracked binary or build artifact extension ({ext})"
        )
        return violations

    if ext in IGNORED_EXTENSIONS or file_path.name in IGNORED_FILES:
        return violations

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()

        # Ignore documentation placeholder examples like C:\\Users\\... or /home/<user>
        doc_placeholder_re = re.compile(
            r"(?:Users|home|Documents and Settings)(?:\\{1,4}|/)+(?:\.\.\.|<[^>]+>|\[[^\]]+\]|\$[A-Za-z_]+|%[A-Za-z_]+%|your_username|your-username|username)",
            re.IGNORECASE,
        )

        for line_no, line in enumerate(lines, start=1):
            if "# nosec" in line or "# allow-path" in line or "allow-path" in line:
                continue

            is_placeholder = bool(doc_placeholder_re.search(line))

            if WINDOWS_USER_PATH_RE.search(line) and not is_placeholder:
                violations.append(
                    f"{rel_path}:{line_no}: Hardcoded Windows user directory path leak: {line.strip()[:100]}"
                )
            if USER_HOME_PATH_RE.search(line) and not is_placeholder:
                violations.append(
                    f"{rel_path}:{line_no}: Hardcoded user profile directory path: {line.strip()[:100]}"
                )
            if UNIX_USER_PATH_RE.search(line) and not is_placeholder:
                violations.append(
                    f"{rel_path}:{line_no}: Hardcoded Unix user home directory path: {line.strip()[:100]}"
                )
            if (
                ACTIVE_USER_PATH_RE
                and ACTIVE_USER_PATH_RE.search(line)
                and not is_placeholder
            ):
                violations.append(
                    f"{rel_path}:{line_no}: Active OS user path component leak: {line.strip()[:100]}"
                )
            if USER_FILE_URI_RE.search(line) and not is_placeholder:
                violations.append(
                    f"{rel_path}:{line_no}: Local user file URI (file:///): {line.strip()[:100]}"
                )

            for pattern, desc in SECRET_PATTERNS:
                if pattern.search(line):
                    violations.append(
                        f"{rel_path}:{line_no}: Potential secret/credential ({desc}): {line.strip()[:60]}..."
                    )

    except Exception as ex:
        violations.append(f"{rel_path}: Failed to read file ({ex})")

    return violations


_VALID_YAML_SINGLE_ESCAPES = {
    "0": "\0",
    "a": "\a",
    "b": "\b",
    "t": "\t",
    "\t": "\t",
    "n": "\n",
    "v": "\v",
    "f": "\f",
    "r": "\r",
    "e": "\x1b",
    " ": " ",
    '"': '"',
    "/": "/",
    "\\": "\\",
    "N": "\x85",
    "_": "\xa0",
    "L": "\u2028",
    "P": "\u2029",
}


def _parse_double_quoted_yaml(val: str, raw_val: str) -> str:
    """Validates and unescapes a YAML 1.2 double-quoted scalar."""
    if len(val) < 2 or not val.startswith('"') or not val.endswith('"'):
        raise ValueError(f"Unclosed double-quoted string: {raw_val}")
    inner = val[1:-1]
    out: List[str] = []
    idx = 0
    length = len(inner)
    while idx < length:
        ch = inner[idx]
        if ch == '"':
            raise ValueError(f"Unescaped double quote in scalar: {raw_val}")
        if ch != "\\":
            out.append(ch)
            idx += 1
            continue
        idx += 1
        if idx >= length:
            raise ValueError(f"Trailing backslash in double-quoted string: {raw_val}")
        esc = inner[idx]
        if esc in _VALID_YAML_SINGLE_ESCAPES:
            out.append(_VALID_YAML_SINGLE_ESCAPES[esc])
            idx += 1
        elif esc in ("x", "u", "U"):
            hex_len = 2 if esc == "x" else (4 if esc == "u" else 8)
            hex_part = inner[idx + 1 : idx + 1 + hex_len]
            if len(hex_part) != hex_len or not re.fullmatch(r"[0-9A-Fa-f]+", hex_part):
                raise ValueError(
                    f"Invalid YAML hex escape '\\{esc}{hex_part}' in: {raw_val}"
                )
            out.append(chr(int(hex_part, 16)))
            idx += 1 + hex_len
        else:
            raise ValueError(f"Invalid YAML escape sequence '\\{esc}' in: {raw_val}")
    return "".join(out)


def _parse_single_quoted_yaml(val: str, raw_val: str) -> str:
    """Validates and unescapes a YAML 1.2 single-quoted scalar."""
    if len(val) < 2 or not val.startswith("'") or not val.endswith("'"):
        raise ValueError(f"Unclosed single-quoted string: {raw_val}")
    inner = val[1:-1]
    out: List[str] = []
    idx = 0
    length = len(inner)
    while idx < length:
        ch = inner[idx]
        if ch == "'":
            if idx + 1 < length and inner[idx + 1] == "'":
                out.append("'")
                idx += 2
            else:
                raise ValueError(f"Unescaped single quote in scalar: {raw_val}")
        else:
            out.append(ch)
            idx += 1
    return "".join(out)


def _parse_yaml_scalar(raw_val: str) -> object:
    """Parses a single-line YAML scalar value and validates syntax."""
    val = raw_val.strip()
    if not val:
        return None
    if val[0] == '"':
        return _parse_double_quoted_yaml(val, raw_val)
    if val[0] == "'":
        return _parse_single_quoted_yaml(val, raw_val)
    if val.startswith("[") or val.startswith("{"):
        if (val.startswith("[") and not val.endswith("]")) or (
            val.startswith("{") and not val.endswith("}")
        ):
            raise ValueError(f"Unclosed flow collection: {raw_val}")
        return [] if val.startswith("[") else {}
    low = val.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", val):
        return int(val)
    if re.fullmatch(r"-?\d+\.\d+", val):
        return float(val)
    if ": " in val or val.endswith(":"):
        raise ValueError(f"Unquoted colon in scalar value: {raw_val}")
    return val


def parse_yaml_frontmatter(fm_text: str) -> dict:
    """Parses YAML frontmatter into a dictionary, rejecting invalid YAML syntax."""
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None

    if yaml is not None:

        class _UniqueKeySafeLoader(yaml.SafeLoader):
            pass

        def _construct_mapping(loader, node, deep=False):
            seen_keys = set()
            for key_node, _ in node.value:
                key = loader.construct_object(key_node, deep=deep)
                if key in seen_keys:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        f"found duplicate YAML key ({key})",
                        key_node.start_mark,
                    )
                seen_keys.add(key)
            return yaml.SafeLoader.construct_mapping(loader, node, deep)

        _UniqueKeySafeLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            _construct_mapping,
        )
        try:
            loaded = yaml.load(fm_text, Loader=_UniqueKeySafeLoader)  # nosec B506
        except yaml.YAMLError as yex:
            raise ValueError(f"YAML parse error: {yex}") from yex
        if not isinstance(loaded, dict):
            raise ValueError("YAML frontmatter must parse to a mapping object")
        return loaded

    lines = fm_text.splitlines()
    result: dict = {}
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        if "\t" in line:
            raise ValueError("Tabs are not permitted in YAML frontmatter")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if line[0].isspace():
            raise ValueError(f"Unexpected indentation at line: {line}")
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if not m:
            raise ValueError(f"Invalid YAML mapping line: {line}")
        key = m.group(1)
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        rest = m.group(2).strip()

        # Handle block scalars (|, |-, |+, >, >-, >+)
        if rest in ("|", "|-", "|+", ">", ">-", ">+"):
            block_lines = []
            i += 1
            while i < n:
                bline = lines[i]
                if not bline.strip():
                    block_lines.append("")
                    i += 1
                    continue
                if bline[0].isspace():
                    block_lines.append(bline.strip())
                    i += 1
                else:
                    break
            if not any(bl for bl in block_lines):
                raise ValueError(f"Empty block scalar for key '{key}'")
            joiner = " " if rest.startswith(">") else "\n"
            result[key] = joiner.join(block_lines).strip()
            continue

        # Handle empty value followed by indented block (list/mapping or multiline string)
        if not rest:
            sub_lines = []
            i += 1
            while i < n:
                bline = lines[i]
                if not bline.strip():
                    i += 1
                    continue
                if bline[0].isspace():
                    sub_lines.append(bline.strip())
                    i += 1
                else:
                    break
            if not sub_lines:
                result[key] = None
            elif all(sl.startswith("- ") or sl == "-" for sl in sub_lines):
                result[key] = [sl[1:].strip() for sl in sub_lines]
            elif any(":" in sl for sl in sub_lines):
                result[key] = {}
            else:
                result[key] = " ".join(sub_lines)
            continue

        result[key] = _parse_yaml_scalar(rest)
        i += 1

    return result


def check_manifest_integrity(repo_root: Path) -> List[str]:
    violations: List[str] = []

    # 1. Validate legacy manifest.json if present
    manifest_path = repo_root / "manifest.json"
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            plugins = data.get("plugins", {})
            if not isinstance(plugins, dict):
                violations.append(
                    "manifest.json: 'plugins' key must be an object dictionary"
                )
            else:
                for plugin_name, meta in plugins.items():
                    rel_dir = meta.get("path", f"plugins/{plugin_name}")
                    plugin_dir = repo_root / rel_dir

                    if not plugin_dir.exists():
                        violations.append(
                            f"manifest.json: Plugin '{plugin_name}' path does not exist on disk: {rel_dir}"
                        )
                        continue

                    metadata_toml = plugin_dir / "metadata.toml"
                    if not metadata_toml.exists():
                        violations.append(
                            f"manifest.json: Plugin '{plugin_name}' missing metadata.toml at {metadata_toml}"
                        )
                        continue

                    if tomllib:
                        try:
                            with open(metadata_toml, "rb") as mf:
                                mdata = tomllib.load(mf)
                            if mdata.get("name") != plugin_name:
                                violations.append(
                                    f"{rel_dir}/metadata.toml: Name mismatch (declared '{mdata.get('name')}', expected '{plugin_name}')"
                                )
                        except Exception as mex:
                            violations.append(
                                f"{rel_dir}/metadata.toml: Parse error ({mex})"
                            )
        except Exception as ex:
            violations.append(f"manifest.json: Parse failed ({ex})")

    # 2. Validate Antigravity plugin.json if present
    plugin_json_path = repo_root / "plugin.json"
    if plugin_json_path.exists():
        try:
            pdata = json.loads(plugin_json_path.read_text(encoding="utf-8"))
            if not isinstance(pdata, dict):
                violations.append("plugin.json: Root payload must be a JSON object")
            else:
                pname = pdata.get("name")
                if (
                    not isinstance(pname, str)
                    or not pname
                    or not re.fullmatch(r"[A-Za-z0-9_-]+", pname)
                ):
                    violations.append(
                        "plugin.json: 'name' field is required and must contain only letters, digits, hyphens, or underscores"
                    )
        except Exception as ex:
            violations.append(f"plugin.json: Parse failed ({ex})")

    # 3. Validate Antigravity .agents/skills.json if present
    skills_json_path = repo_root / ".agents" / "skills.json"
    if skills_json_path.exists():
        try:
            sdata = json.loads(skills_json_path.read_text(encoding="utf-8"))
            if not isinstance(sdata, dict):
                violations.append(
                    ".agents/skills.json: Root payload must be a JSON object"
                )
            else:
                entries = sdata.get("entries", [])
                if not isinstance(entries, list):
                    violations.append(".agents/skills.json: 'entries' must be a list")
                else:
                    for entry in entries:
                        epath = entry.get("path") if isinstance(entry, dict) else None
                        if not epath or not isinstance(epath, str):
                            violations.append(
                                ".agents/skills.json: Each entry must specify a string 'path'"
                            )
                        elif not epath.startswith("/") and not epath.startswith("~/"):
                            resolved = repo_root / epath
                            if not resolved.exists():
                                violations.append(
                                    f".agents/skills.json: Entry path does not exist: {epath}"
                                )
        except Exception as ex:
            violations.append(f".agents/skills.json: Parse failed ({ex})")

    # 4. Validate skills/*/SKILL.md YAML frontmatter
    skills_dir = repo_root / "skills"
    if skills_dir.exists() and skills_dir.is_dir():
        for skill_item in sorted(skills_dir.iterdir()):
            if not skill_item.is_dir() or skill_item.name.startswith("."):
                continue
            skill_md = skill_item / "SKILL.md"
            rel_md = f"skills/{skill_item.name}/SKILL.md"
            if not skill_md.exists():
                violations.append(f"{rel_md}: Missing required SKILL.md file")
                continue
            try:
                text = skill_md.read_text(encoding="utf-8")
                if not text.startswith("---\n") and not text.startswith("---\r\n"):
                    violations.append(
                        f"{rel_md}: Missing YAML frontmatter opening '---'"
                    )
                    continue
                parts = re.split(r"^---\s*$", text, maxsplit=2, flags=re.MULTILINE)
                if len(parts) < 3:
                    violations.append(f"{rel_md}: Unclosed YAML frontmatter block")
                    continue
                fm = parts[1]
                try:
                    fm_data = parse_yaml_frontmatter(fm)
                except ValueError as vex:
                    violations.append(f"{rel_md}: Invalid YAML frontmatter ({vex})")
                    continue

                skill_name = fm_data.get("name")
                skill_desc = fm_data.get("description")
                if not isinstance(skill_name, str) or not skill_name.strip():
                    violations.append(
                        f"{rel_md}: Frontmatter 'name' must be a non-empty string"
                    )
                elif skill_name.strip() != skill_item.name:
                    violations.append(
                        f"{rel_md}: Frontmatter name '{skill_name.strip()}' does not match directory '{skill_item.name}'"
                    )
                if not isinstance(skill_desc, str) or not skill_desc.strip():
                    violations.append(
                        f"{rel_md}: Frontmatter 'description' must be a non-empty string"
                    )
            except Exception as ex:
                violations.append(f"{rel_md}: Failed to validate SKILL.md ({ex})")

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repository Safety, Secret & Path Hygiene Scanner"
    )
    parser.add_argument(
        "--repo-root", default=None, help="Root directory of the repository to scan"
    )
    parser.add_argument(
        "--skip-manifest", action="store_true", help="Skip manifest integrity checks"
    )
    args = parser.parse_args()

    repo_root = resolve_repo_root(args.repo_root)
    print(f"Scanning repository for safety, secrets, and path hygiene: {repo_root}")

    all_violations: List[str] = []

    if not args.skip_manifest:
        all_violations.extend(check_manifest_integrity(repo_root))

    tracked_files = get_git_tracked_files(repo_root)
    for rel_path in tracked_files:
        all_violations.extend(check_file_hygiene(repo_root, rel_path))

    if all_violations:
        print("\n[FAILED] Safety violations and path hygiene errors detected:")
        for v in all_violations:
            print(f"  - {v}")
        print(f"\nTotal violations: {len(all_violations)}")
        return 1

    print(
        "\n[PASSED] Zero path leaks, secrets, binary artifacts, or manifest inconsistencies detected."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
