#!/usr/bin/env python3
"""
Host Environment & Tooling Probe.
Cross-platform, zero-dependency diagnostics utility that inspects the live host
environment, verifies binary presence, tests console encoding streams, and detects
discrepancies between global agent rules and actual system capabilities.
"""

import os
import sys
import json
import shutil
import platform
import subprocess
from pathlib import Path
from datetime import datetime

# Enforce UTF-8 for console output
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def probe_python_environment():
    """Evaluates Python interpreter, standard stream encoding, and environment flags."""
    stdout_enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    default_enc = sys.getdefaultencoding()
    fs_enc = sys.getfilesystemencoding()
    py_io_encoding = os.environ.get("PYTHONIOENCODING", "")

    # Test encoding resilience in-memory without polluting stdout
    test_str = "Test: ä, ö, å, €, ✓, →"
    encoding_error = None
    try:
        encoded = test_str.encode(stdout_enc)
        decoded = encoded.decode(stdout_enc)
        if decoded != test_str:
            encoding_error = f"Roundtrip mismatch under {stdout_enc}"
    except Exception as exc:
        encoding_error = str(exc)

    return {
        "version": platform.python_version(),
        "executable": sys.executable,
        "stdout_encoding": stdout_enc,
        "default_encoding": default_enc,
        "filesystem_encoding": fs_enc,
        "env_pythonioencoding": py_io_encoding,
        "stdout_test_passed": encoding_error is None,
        "encoding_error": encoding_error,
    }


def probe_binary(name, args=("--version",), timeout=3):
    """Probes executable availability, resolves absolute path, and retrieves version."""
    path_str = shutil.which(name)
    if not path_str:
        return {"name": name, "installed": False, "path": None, "version": None}

    version_str = None
    try:
        cmd = [path_str] + list(args)
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        output = (res.stdout or res.stderr or "").strip().splitlines()
        if output:
            version_str = output[0].strip()
    except Exception:
        pass

    return {"name": name, "installed": True, "path": path_str, "version": version_str}


def probe_host_binaries():
    """Probes core engineering CLI tools and runtimes across platforms."""
    tools_to_check = [
        ("git", ["--version"]),
        ("gh", ["--version"]),
        ("rg", ["--version"]),
        ("fd", ["--version"]),
        ("jq", ["--version"]),
        ("curl", ["--version"]),
        ("python", ["--version"]),
        ("python3", ["--version"]),
        ("uv", ["--version"]),
        ("node", ["--version"]),
        ("pnpm", ["--version"]),
        ("npm", ["--version"]),
        ("cargo", ["--version"]),
        ("go", ["version"]),
        ("dotnet", ["--version"]),
        ("agy", ["--version"]),
    ]

    sys_name = platform.system()
    if sys_name == "Windows":
        tools_to_check.extend(
            [
                ("py", ["--version"]),
                ("pwsh", ["--version"]),
                ("winget", ["--version"]),
            ]
        )
    elif sys_name == "Darwin":
        tools_to_check.append(("brew", ["--version"]))
    else:
        tools_to_check.append(("apt", ["--version"]))

    results = {}
    for name, args in tools_to_check:
        results[name] = probe_binary(name, args)

    return results


RULE_FILE_BYTE_CAP = 24000
AGGREGATE_RULES_TOKEN_BUDGET = 20000


def probe_global_configuration_discrepancies(binaries):
    """Cross-references active GEMINI.md / AGENTS.md rules against detected binaries and Antigravity size budgets."""
    discrepancies = []
    gemini_home = Path.home() / ".gemini"
    config_root = gemini_home / "config"
    root_gemini_path = gemini_home / "GEMINI.md"
    root_agents_path = gemini_home / "AGENTS.md"
    gemini_config_path = config_root / "GEMINI.md"
    agents_config_path = config_root / "AGENTS.md"
    hooks_config_path = config_root / "hooks.json"

    rule_files = []
    seen_paths = set()
    for candidate in (
        root_gemini_path,
        root_agents_path,
        gemini_config_path,
        agents_config_path,
    ):
        if candidate.exists():
            resolved = str(candidate.resolve())
            if resolved not in seen_paths:
                seen_paths.add(resolved)
                rule_files.append(candidate)
    rules_dir = config_root / "rules"
    if rules_dir.exists() and rules_dir.is_dir():
        for rf_cand in sorted(rules_dir.glob("*.md")):
            resolved = str(rf_cand.resolve())
            if resolved not in seen_paths:
                seen_paths.add(resolved)
                rule_files.append(rf_cand)

    primary_config_path = (
        gemini_config_path
        if gemini_config_path.exists()
        else (root_gemini_path if root_gemini_path.exists() else gemini_config_path)
    )

    if not rule_files:
        return {
            "config_found": False,
            "config_path": str(primary_config_path),
            "hooks_configured": hooks_config_path.exists(),
            "discrepancies": discrepancies,
        }

    combined_content = ""
    total_rule_bytes = 0
    for rf in rule_files:
        try:
            raw_bytes = rf.stat().st_size
            total_rule_bytes += raw_bytes
            if raw_bytes > RULE_FILE_BYTE_CAP:
                discrepancies.append(
                    {
                        "type": "rule_file_over_24kb_cap",
                        "file": str(rf),
                        "finding": f"{rf.name} is {raw_bytes} bytes, exceeding Antigravity's 24,000-byte per-file truncation limit.",
                        "remediation": f"Prune or split {rf.name} below 24,000 bytes so trailing instructions are not truncated.",
                    }
                )
            combined_content += "\n" + rf.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            discrepancies.append(
                {
                    "type": "rule_file_read_error",
                    "file": str(rf),
                    "finding": f"Could not read {rf.name}: {exc}",
                    "remediation": "Check file permissions and UTF-8 encoding.",
                }
            )

    est_rule_tokens = round(total_rule_bytes / 4)
    if est_rule_tokens > AGGREGATE_RULES_TOKEN_BUDGET:
        discrepancies.append(
            {
                "type": "aggregate_rules_over_token_budget",
                "finding": f"Global rules estimate ~{est_rule_tokens} tokens, exceeding Antigravity's 20,000-token defaultRulesBudget.",
                "remediation": "Disclose domain-specific rules behind conditional pointers to prevent automatic demotion.",
            }
        )

    # Check for 'gh CLI is not installed' false negative
    if "gh cli is not installed" in combined_content.lower():
        if binaries.get("gh", {}).get("installed"):
            discrepancies.append(
                {
                    "type": "false_negative",
                    "tool": "gh",
                    "finding": "Rules declare gh CLI is not installed, but gh is actively present on PATH.",
                    "remediation": "Update GEMINI.md to authorize direct gh CLI operations.",
                }
            )

    # Check for missing tools that rules require or authorize
    for tool_name in ["rg", "git", "dotnet", "curl", "python", "uv", "pnpm"]:
        if f"`{tool_name}`" in combined_content or f" {tool_name} " in combined_content:
            if tool_name in binaries and not binaries.get(tool_name, {}).get(
                "installed"
            ):
                discrepancies.append(
                    {
                        "type": "missing_required_binary",
                        "tool": tool_name,
                        "finding": f"Rules reference {tool_name}, but the executable is absent from PATH.",
                        "remediation": f"Install {tool_name} via native package manager.",
                    }
                )

    return {
        "config_found": True,
        "config_path": str(primary_config_path),
        "hooks_configured": hooks_config_path.exists(),
        "total_rule_bytes": total_rule_bytes,
        "estimated_rule_tokens": est_rule_tokens,
        "discrepancies": discrepancies,
    }


def run_probe(output_dir=None):
    """Executes the host environment probe and writes a structured summary."""
    sys_info = {
        "os": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "timestamp": datetime.now().isoformat(),
    }

    py_info = probe_python_environment()
    binaries = probe_host_binaries()
    config_audit = probe_global_configuration_discrepancies(binaries)

    summary = {
        "system": sys_info,
        "python": py_info,
        "binaries": binaries,
        "configuration_audit": config_audit,
    }

    out_path = Path(output_dir) if output_dir else Path.cwd()
    out_path.mkdir(parents=True, exist_ok=True)
    target_file = out_path / "host_environment_probe.json"
    with open(target_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Print human-readable summary
    print("=== Host Environment & Tooling Probe ===")
    print(f"OS: {sys_info['os']} {sys_info['release']} ({sys_info['machine']})")
    print(
        f"Python: {py_info['version']} (stdout: {py_info['stdout_encoding']}, env: {py_info['env_pythonioencoding'] or 'unset'})"
    )
    print(
        f"Stdout Test: {'PASSED' if py_info['stdout_test_passed'] else 'FAILED: ' + str(py_info['encoding_error'])}"
    )
    print("\nPlatform Binaries:")
    for b_name, b_data in binaries.items():
        status = "INSTALLED" if b_data.get("installed") else "MISSING"
        ver = f"({b_data.get('version')})" if b_data.get("version") else ""
        print(f"  - {b_name:<10}: {status:<10} {ver}")

    if config_audit["discrepancies"]:
        print("\nRule Discrepancies Detected:")
        for disc in config_audit["discrepancies"]:
            print(f"  - [{disc['type']}] {disc['finding']}")
    else:
        print("\nRule Discrepancies: None detected.")

    print(f"\nProbe report written to: {target_file}")
    return target_file


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Host Environment & Tooling Probe")
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=None,
        help="Directory to save host_environment_probe.json",
    )
    args = parser.parse_args()
    run_probe(args.output_dir)
