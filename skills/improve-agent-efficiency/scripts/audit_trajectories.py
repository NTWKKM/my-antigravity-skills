#!/usr/bin/env python3
"""
Trajectory Efficiency Auditor for Antigravity.
Cross-platform, zero-dependency auditor for analyzing Antigravity agent transcripts,
correlating unlabeled conversations to repositories, detecting command execution failures,
mining causal retry chains (initial failure -> retries -> eventual resolution),
measuring token burn and context consumption, evaluating efficiency gains over time,
and synthesizing systemic remediation recommendations.
"""

import os
import sys
import json
import re
import platform
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import random

# Ensure UTF-8 output across all environments
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def clean_str(val):
    if not val or not isinstance(val, str):
        return ""
    v = val.strip(" \t\r\n\"'")
    if v.startswith("file:///"):
        v = v.replace("file:///", "").replace("%3A", ":")
        if platform.system() == "Windows":
            v = v.replace("/", "\\")
    return v


def norm_path(p_str):
    if not p_str:
        return ""
    cp = clean_str(p_str)
    try:
        res = os.path.abspath(cp)
        return os.path.normcase(res) if platform.system() == "Windows" else res
    except Exception:
        return cp


def find_git_root(path_str):
    """Ascends directory tree to identify enclosing git repository root."""
    if not path_str:
        return None
    try:
        p = Path(clean_str(path_str))
        if not p.is_dir() and p.parent.exists():
            p = p.parent
        for candidate in [p] + list(p.parents):
            if (candidate / ".git").exists():
                return str(candidate.resolve())
    except Exception:
        pass
    return None


def locate_antigravity_dir():
    custom = os.environ.get("ANTIGRAVITY_DATA_DIR")
    if custom and Path(custom).exists():
        return Path(custom)
    default_dir = Path.home() / ".gemini" / "antigravity"
    if default_dir.exists():
        return default_dir
    default_ide = Path.home() / ".gemini" / "antigravity-ide"
    if default_ide.exists():
        return default_ide
    return Path.home() / ".gemini"


def locate_brain_directories(base_dir=None):
    brain_dirs = []
    custom = os.environ.get("ANTIGRAVITY_DATA_DIR")
    if custom:
        p = Path(custom)
        if (p / "brain").exists() and (p / "brain") not in brain_dirs:
            brain_dirs.append(p / "brain")
        elif p.exists() and p not in brain_dirs:
            brain_dirs.append(p)

    gemini_dir = Path.home() / ".gemini"
    for sub in ["antigravity-ide", "antigravity", "antigravity-cli"]:
        b = gemini_dir / sub / "brain"
        if b.exists() and b not in brain_dirs:
            brain_dirs.append(b)

    b_direct = gemini_dir / "brain"
    if b_direct.exists() and b_direct not in brain_dirs:
        brain_dirs.append(b_direct)

    if (
        base_dir
        and (base_dir / "brain").exists()
        and (base_dir / "brain") not in brain_dirs
    ):
        brain_dirs.append(base_dir / "brain")

    return brain_dirs


def locate_ide_workspace_storage():
    system = platform.system()
    home = Path.home()
    candidates = []

    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(
                Path(appdata) / "Antigravity IDE" / "User" / "workspaceStorage"
            )
            candidates.append(
                Path(appdata) / "Antigravity" / "User" / "workspaceStorage"
            )
    elif system == "Darwin":
        candidates.append(
            home
            / "Library"
            / "Application Support"
            / "Antigravity IDE"
            / "User"
            / "workspaceStorage"
        )
        candidates.append(
            home
            / "Library"
            / "Application Support"
            / "Antigravity"
            / "User"
            / "workspaceStorage"
        )
    else:  # Linux
        config_dir = os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))
        candidates.append(
            Path(config_dir) / "Antigravity IDE" / "User" / "workspaceStorage"
        )
        candidates.append(
            Path(config_dir) / "Antigravity" / "User" / "workspaceStorage"
        )

    for c in candidates:
        if c.exists():
            return c
    return None


def discover_ide_workspaces(ws_storage_dir):
    workspaces = []
    if not ws_storage_dir or not ws_storage_dir.exists():
        return workspaces

    for item in ws_storage_dir.iterdir():
        ws_json = item / "workspace.json"
        if ws_json.exists():
            try:
                mtime = os.path.getmtime(ws_json)
                with open(ws_json, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                    uri = data.get("folder") or data.get("workspace")
                    if uri:
                        cp = clean_str(uri)
                        workspaces.append(
                            {
                                "storage_id": item.name,
                                "mtime": mtime,
                                "date": datetime.fromtimestamp(mtime).strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                ),
                                "raw_uri": uri,
                                "norm_path": norm_path(cp),
                                "display_path": cp,
                            }
                        )
            except Exception:
                pass

    workspaces.sort(key=lambda x: x["mtime"], reverse=True)
    return workspaces


def discover_git_repositories(ide_workspaces, base_dir):
    repos = {}
    search_dirs = [
        Path.home() / "Documents" / "repos",
        Path.home() / "Documents" / "Projects",
        Path.home() / "Projects",
        Path.home() / "src",
        Path.home() / "repos",
        Path.home() / "dev",
        Path.home() / "code",
        Path.home() / "workspace",
        Path.home() / "workspaces",
        Path.home() / "Documents",
        base_dir / "scratch",
    ]

    for sd in search_dirs:
        if sd.exists():
            if (sd / ".git").exists():
                np = norm_path(str(sd))
                repos[np] = str(sd.resolve())
            else:
                try:
                    for child in sd.iterdir():
                        if child.is_dir() and (child / ".git").exists():
                            np = norm_path(str(child))
                            repos[np] = str(child.resolve())
                except Exception:
                    pass

    for ws in ide_workspaces:
        p_str = ws["display_path"]
        p = Path(p_str)
        if p.exists() and (p / ".git").exists():
            repos[norm_path(p_str)] = str(p.resolve())

    return repos


def is_benign_command_outcome(cmd, exit_code, resp_content):
    """
    Identifies commands where non-zero exit code denotes a normal/expected status
    rather than an execution error or crash.
    """
    cmd_lower = (cmd or "").strip().lower()
    resp_lower = (resp_content or "").lower()

    # 1. Search tools (rg, ripgrep, grep, findstr, diff) returning 1 for zero matches
    if exit_code == 1:
        is_search = bool(
            re.search(r"(^|[|;&\s])(rg|ripgrep|grep|findstr|diff)\b", cmd_lower)
        )
        if is_search:
            error_signals = [
                "error:",
                "fatal:",
                "invalid option",
                "unrecognized option",
                "commandnotfound",
                "the term '",
                "syntaxerror",
                "permission denied",
            ]
            if not any(sig in resp_lower for sig in error_signals):
                return True

    # 2. gh pr checks returning 8 when checks are pending (e.g. CodeRabbit review in progress)
    if exit_code == 8 and "gh pr checks" in cmd_lower:
        if any(
            sig in resp_lower
            for sig in [
                "some checks are still pending",
                "review in progress",
                "pending checks",
            ]
        ):
            return True

    return False


INLINE_PREFIXES = (
    "py -c",
    "python -c",
    "python3 -c",
    "node -e",
    "bash -c",
    "powershell -c",
)


def determine_inline_failure_class(cmd_str, resp_content):
    resp_tail = (
        resp_content[-2000:] if len(resp_content) > 2000 else (resp_content or "")
    )
    resp_lines = [
        line.strip() for line in (resp_content or "").split("\n") if line.strip()
    ]
    last_line = resp_lines[-1] if resp_lines else ""

    if any(
        k in resp_tail
        for k in [
            "ModuleNotFoundError:",
            "No module named",
            "Cannot find module",
            "MODULE_NOT_FOUND",
            "ImportError:",
        ]
    ) or "which uv" in (cmd_str or ""):
        return "missing_dependency"
    elif any(
        k in resp_tail
        for k in [
            "SyntaxError:",
            "parse error",
            "unterminated string",
            "unmatched",
            "bad math expression",
            "bad pattern",
            "closing parenthesis",
            "unexpected character after line continuation",
            "EOF while scanning",
        ]
    ) or any(k in last_line for k in ["zsh:", "bash:"]):
        return "syntax_shell_parse"
    elif "AssertionError:" in resp_tail:
        return "assertion_or_logic"
    elif (
        any(
            k in resp_tail
            for k in [
                "KeyError:",
                "AttributeError:",
                "IndexError:",
                "FileNotFoundError:",
                "ValueError:",
                "TypeError:",
                "NameError:",
                "ZeroDivisionError:",
                "CalledProcessError",
                "PatsyError",
                "Exception:",
            ]
        )
        or "CalledProcessError" in last_line
    ):
        return "runtime_exception"
    else:
        return "other_failure"


def classify_failure(cmd, response_snippet, exit_code, inline_failure_class=None):
    snip = (response_snippet or "").lower()
    cmd_lower = (cmd or "").lower()

    if any(k in cmd_lower for k in ["pytest", "vitest", "playwright"]) and any(
        k in snip for k in ["failed:", "assertionerror", "test session starts", "fail"]
    ):
        return "Test Assertion / TDD Failure"
    if any(p in cmd_lower for p in INLINE_PREFIXES):
        if inline_failure_class is None:
            inline_failure_class = determine_inline_failure_class(
                cmd, response_snippet or ""
            )
        if inline_failure_class == "missing_dependency":
            return "Missing Python Dependency / Path"
        elif inline_failure_class == "syntax_shell_parse":
            return "Inline Script Quoting Collapse"
        elif inline_failure_class == "assertion_or_logic":
            return "Test Assertion / TDD Failure"
        elif inline_failure_class == "runtime_exception":
            return f"Runtime Execution Failure (Exit Code {exit_code})"
        else:
            return "Inline Script Quoting Collapse"
    if "charmap" in snip or "unicodeencodeerror" in snip:
        return "Console Encoding Trap (Non-UTF8 Stream)"
    if any(
        k in snip
        for k in [
            "parsererror",
            "syntaxerror near unexpected token",
            "unterminated quoted string",
            "syntaxerror: unterminated",
            "syntaxerror: '(' was never closed",
        ]
    ):
        return "Shell Parser / Quoting Error"
    if any(
        k in snip
        for k in [
            "command not found",
            "is not recognized as",
            "commandnotfoundexception",
            "the term",
        ]
    ):
        return "Missing Host Binary / Tool"
    if any(
        k in snip
        for k in [
            "err_module_not_found",
            "cannot find module",
            "eresolve unable to resolve dependency tree",
            "err_pnpm_outdated_lockfile",
            "npm err!",
        ]
    ):
        return "JavaScript / Node Module or Lockfile Error"
    if any(
        k in snip for k in ["error ts", "tsc : error", "ts2304", "ts2307", "ts2322"]
    ):
        return "TypeScript Compilation / Type Check Failure"
    if (
        ("cannot open" in snip and "for writing" in snip)
        or "being used by another process" in snip
        or "text file busy" in snip
        or "error cs2012" in snip
    ):
        return "Process File Lock Collision"
    if "eaddrinuse" in snip or "address already in use" in snip:
        return "Port / Network Socket Collision"
    if "permission denied" in snip or "eacces" in snip:
        return "Filesystem / Permission Denied"
    if "no module named" in snip or "importerror" in snip:
        return "Missing Python Dependency / Path"
    if any(k in snip for k in ["cargo build", "cargo check"]) and (
        "error[e" in snip or "failed to compile" in snip
    ):
        return "Rust Cargo Compilation Failure"
    if ("go build" in cmd_lower or "go test" in cmd_lower) and (
        "no required module provides package" in snip or "undefined:" in snip
    ):
        return "Go Module / Build Failure"
    if "fatal: " in snip or "pathspec" in snip or "forbidden_do_not_push" in snip:
        return "Git Remote / Branch Safety Error"
    return f"Runtime Execution Failure (Exit Code {exit_code})"


def parse_conversations(
    brain_dirs,
    candidate_repos,
    max_conversations=50,
    since_dt=None,
    until_dt=None,
    target_repo=None,
    exclude_repo=None,
    exclude_convs=None,
    auto_exclude_audit=True,
    compare_mode=False,
):
    sorted_repo_norms = sorted(
        list(candidate_repos.keys()), key=lambda x: len(x), reverse=True
    )
    conversations = []
    seen_conv_ids = set()
    conv_candidates = []

    if isinstance(brain_dirs, Path):
        brain_dirs = [brain_dirs]

    exclude_conv_set = set(exclude_convs) if exclude_convs else set()

    for brain_dir in brain_dirs:
        if not brain_dir or not brain_dir.exists():
            continue

        for item in brain_dir.iterdir():
            if (
                not item.is_dir()
                or item.name == "tempmediaStorage"
                or item.name in seen_conv_ids
                or item.name in exclude_conv_set
            ):
                continue

            tpath_full = item / ".system_generated" / "logs" / "transcript_full.jsonl"
            tpath_compact = item / ".system_generated" / "logs" / "transcript.jsonl"
            tpath = tpath_full if tpath_full.exists() else tpath_compact
            if not tpath.exists():
                continue

            seen_conv_ids.add(item.name)

            # Determine true conversation start time and prompt preview from user prompt
            start_dt = None
            first_step_text = ""
            try:
                with open(tpath, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line_str = line.strip()
                        if not line_str:
                            continue
                        d0 = json.loads(line_str)
                        if not start_dt:
                            c_str = d0.get("created_at")
                            if c_str:
                                start_dt = (
                                    datetime.fromisoformat(c_str.replace("Z", "+00:00"))
                                    .astimezone()
                                    .replace(tzinfo=None)
                                )
                        st = d0.get("type", "")
                        source = d0.get("source", "")
                        if st == "USER_INPUT" or source == "USER_EXPLICIT":
                            first_step_text = d0.get("content", "") or ""
                            break
            except Exception:
                pass

            if not start_dt:
                try:
                    start_dt = datetime.fromtimestamp(os.path.getmtime(tpath))
                except Exception:
                    continue

            # Auto-exclude audit sessions (current active session or sessions executing trajectory audit)
            if auto_exclude_audit:
                if item.name == "9594bcbb-d8fb-4482-bb7d-3e80af28a13e":
                    continue
                if any(
                    k in first_step_text
                    for k in [
                        "audit_trajectories.py",
                        "/improve-agent-efficiency",
                        "improve-agent-efficiency",
                        "efficiency status และ token burn",
                    ]
                ):
                    continue

            if until_dt and start_dt > until_dt:
                continue

            # When comparing, we keep both cohorts (target >= since_dt and baseline < since_dt)
            if since_dt and not compare_mode and start_dt < since_dt:
                continue

            conv_candidates.append((start_dt.timestamp(), item, tpath, start_dt))

    conv_candidates.sort(key=lambda x: x[0], reverse=True)
    total_candidates = len(conv_candidates)
    if max_conversations and max_conversations > 0:
        conv_candidates = conv_candidates[:max_conversations]

    for mtime, item, tpath, conv_dt in conv_candidates:
        first_prompt = ""
        user_prompts = []
        active_ws = ""
        touched_paths = set()
        action_trace = []
        user_turn_indices = []

        total_prompt_chars = 0
        total_resp_chars = 0
        total_thinking_chars = 0
        total_tool_output_chars = 0
        total_system_chars = 0
        planner_prose_chars = 0
        planner_tool_args_chars = 0
        tool_args_chars_by_tool = Counter()
        run_cmd_output_chars = 0
        file_views_count = 0
        file_views_unbounded = 0
        file_views_bounded = 0
        file_views_unbounded_chars = 0
        file_views_bounded_chars = 0
        file_lines_read_gross = defaultdict(list)
        file_lines_read_epoch = defaultdict(list)
        epoch_total_lines = 0
        epoch_unique_lines = 0
        write_to_file_modes = Counter()
        skills_notice_count = 0
        skills_notice_chars = 0
        user_turns_count = 0
        api_input_tokens = 0
        api_cache_read_tokens = 0
        api_output_tokens = 0
        has_api_tokens = False
        ephemeral_by_cat = Counter()

        try:
            with open(tpath, "r", encoding="utf-8", errors="ignore") as f:
                steps = [json.loads(line) for line in f if line.strip()]
        except Exception:
            continue

        for i, step in enumerate(steps):
            st = step.get("type", "")
            source = step.get("source", "")
            content = step.get("content", "") or ""
            thinking = step.get("thinking", "") or ""

            if "input_tokens" in step:
                has_api_tokens = True
                api_input_tokens += step.get("input_tokens") or 0
                api_cache_read_tokens += step.get("cache_read_tokens") or 0
                api_output_tokens += step.get("output_tokens") or 0

            if st == "USER_INPUT" or source == "USER_EXPLICIT":
                user_turns_count += 1
                user_turn_indices.append(i)
                total_prompt_chars += len(content)
                p_clean = content.strip().replace("\r", " ").replace("\n", " ")
                if "<USER_REQUEST>" in p_clean:
                    start = p_clean.find("<USER_REQUEST>") + len("<USER_REQUEST>")
                    end = p_clean.find("</USER_REQUEST>")
                    p_clean = (
                        p_clean[start:end].strip()
                        if end != -1
                        else p_clean[start:].strip()
                    )
                if not first_prompt:
                    first_prompt = p_clean[:200]
                user_prompts.append(p_clean[:120])
            elif st == "PLANNER_RESPONSE":
                planner_prose_chars += len(content)
                total_resp_chars += len(content)
                total_thinking_chars += len(thinking)
                tcs_step = step.get("tool_calls", [])
                for tc_item in tcs_step:
                    tname_item = tc_item.get("name") or "other"
                    targs = tc_item.get("args") or {}
                    targs_str = (
                        json.dumps(targs) if isinstance(targs, dict) else str(targs)
                    )
                    planner_tool_args_chars += len(targs_str)
                    tool_args_chars_by_tool[tname_item] += len(targs_str)
            elif st in [
                "EPHEMERAL_MESSAGE",
                "SYSTEM_MESSAGE",
                "CHECKPOINT",
                "CONVERSATION_HISTORY",
            ] or source in ["SYSTEM_SDK", "SYSTEM"]:
                total_system_chars += len(content)
                if "ACTIVE SKILLS LOADED" in content or "ZERO-SLASH MANDATE" in content:
                    ephemeral_by_cat["skills_notice"] += len(content)
                    skills_notice_count += 1
                    skills_notice_chars += len(content)
                elif "MCP MEMORY RECALL" in content or "MEMORY:" in content:
                    ephemeral_by_cat["memory_recall"] += len(content)
                elif "SYSTEM_MESSAGE" in content:
                    ephemeral_by_cat["system_message"] += len(content)
                else:
                    ephemeral_by_cat["other_ephemeral"] += len(content)
            else:
                total_tool_output_chars += len(content)

            if "<user_information>" in content:
                for line in content.split("\n"):
                    if "active workspace is" in line.lower():
                        cand = line.split("active workspace is")[-1].strip().rstrip(".")
                        if cand:
                            active_ws = norm_path(cand)

            tc_list = step.get("tool_calls", [])
            for tc_idx, tc in enumerate(tc_list):
                tname = tc.get("name")
                args = tc.get("args") or tc.get("arguments") or {}
                if not isinstance(args, dict):
                    continue

                for k in ["Cwd", "TargetFile", "AbsolutePath"]:
                    v = args.get(k)
                    if v and isinstance(v, str):
                        np = norm_path(v)
                        if np:
                            touched_paths.add(np)
                            git_root = find_git_root(v)
                            if git_root:
                                gn = norm_path(git_root)
                                if gn not in candidate_repos:
                                    candidate_repos[gn] = git_root
                                    sorted_repo_norms = sorted(
                                        list(candidate_repos.keys()),
                                        key=lambda x: len(x),
                                        reverse=True,
                                    )

                if tname in ["write_to_file", "replace_file_content"]:
                    target_f = clean_str(args.get("TargetFile"))
                    if tname == "write_to_file":
                        if args.get("Overwrite") is True:
                            write_to_file_modes["overwrite"] += 1
                        elif args.get("Append") is True:
                            write_to_file_modes["append"] += 1
                        else:
                            write_to_file_modes["create"] += 1

                    # Flush and reset unmodified epoch for this file
                    if target_f and target_f in file_lines_read_epoch:
                        for s_int, e_int in file_lines_read_epoch[target_f]:
                            epoch_total_lines += max(0, e_int - s_int + 1)
                        ep_uniq = set()
                        for s_int, e_int in file_lines_read_epoch[target_f]:
                            for ln in range(s_int, e_int + 1):
                                ep_uniq.add(ln)
                        epoch_unique_lines += len(ep_uniq)
                        file_lines_read_epoch[target_f] = []

                    action_trace.append(
                        {
                            "step_index": i,
                            "tool": tname,
                            "target_file": target_f,
                            "is_command": False,
                        }
                    )

                elif tname == "view_file":
                    file_views_count += 1
                    s_line = args.get("StartLine")
                    e_line = args.get("EndLine")
                    is_bounded = s_line is not None and e_line is not None
                    v_len = 0
                    t_idx = i + tc_idx + 1
                    if t_idx < len(steps):
                        v_len = len(steps[t_idx].get("content", "") or "")
                    if is_bounded:
                        file_views_bounded += 1
                        file_views_bounded_chars += v_len
                        t_file = clean_str(args.get("AbsolutePath"))
                        try:
                            s_int = int(s_line)
                            e_int = int(e_line)
                            file_lines_read_gross[t_file].append((s_int, e_int))
                            file_lines_read_epoch[t_file].append((s_int, e_int))
                        except Exception:
                            pass
                    else:
                        file_views_unbounded += 1
                        file_views_unbounded_chars += v_len

                elif tname == "run_command":
                    exit_code = None
                    resp_content = ""
                    for j in range(i + tc_idx + 1, min(i + tc_idx + 4, len(steps))):
                        m_content = steps[j].get("content", "")
                        if (
                            "exited with code" in m_content
                            or "finished with result:" in m_content
                        ):
                            resp_content = m_content
                            m = re.search(r"exited with code (-?\d+)", m_content)
                            if m:
                                exit_code = int(m.group(1))
                            break

                    is_failed = False
                    cmd_str = clean_str(args.get("CommandLine"))
                    if exit_code is not None:
                        if exit_code != 0:
                            if is_benign_command_outcome(
                                cmd_str, exit_code, resp_content
                            ):
                                is_failed = False
                            else:
                                is_failed = True
                    elif any(
                        err in resp_content
                        for err in [
                            "ParserError:",
                            "SyntaxError:",
                            "CommandNotFoundException",
                            "The term",
                            "Traceback (most recent call last):",
                        ]
                    ):
                        is_failed = True

                    is_inline = any(p in cmd_str.lower() for p in INLINE_PREFIXES)
                    # Genuinely multi-line scripts contain real line breaks
                    is_multiline_inline = is_inline and (
                        "\n" in cmd_str or "\r" in cmd_str
                    )
                    is_oneline_inline = is_inline and not is_multiline_inline
                    run_cmd_output_chars += len(resp_content)

                    inline_failure_class = None
                    if is_inline and is_failed:
                        inline_failure_class = determine_inline_failure_class(
                            cmd_str, resp_content
                        )

                    action_trace.append(
                        {
                            "step_index": i,
                            "turn_index": len(user_turn_indices),
                            "tool": "run_command",
                            "command": cmd_str,
                            "cwd": clean_str(args.get("Cwd")),
                            "summary": clean_str(args.get("toolSummary")),
                            "action": clean_str(args.get("toolAction")),
                            "exit_code": exit_code,
                            "is_failed": is_failed,
                            "is_multiline_inline": is_multiline_inline,
                            "is_oneline_inline": is_oneline_inline,
                            "inline_failure_class": inline_failure_class,
                            "response_snippet": resp_content[:500],
                            "is_command": True,
                        }
                    )

        # Infer associated repository
        matched_repo_norm = None
        if active_ws:
            for rn in sorted_repo_norms:
                if (
                    active_ws == rn
                    or active_ws.startswith(rn + os.sep)
                    or active_ws.startswith(rn + "\\")
                ):
                    matched_repo_norm = rn
                    break

        if not matched_repo_norm:
            for tp in touched_paths:
                for rn in sorted_repo_norms:
                    if (
                        tp == rn
                        or tp.startswith(rn + os.sep)
                        or tp.startswith(rn + "\\")
                    ):
                        matched_repo_norm = rn
                        break
                if matched_repo_norm:
                    break

        if not matched_repo_norm:
            low_prompts = " ".join(user_prompts).lower()
            for rn in sorted_repo_norms:
                rname = Path(candidate_repos[rn]).name.lower()
                if len(rname) >= 4 and rname in low_prompts:
                    matched_repo_norm = rn
                    break

        repo_display = (
            candidate_repos[matched_repo_norm]
            if matched_repo_norm
            else "General Environment"
        )

        if target_repo and target_repo.lower() not in repo_display.lower():
            continue

        if exclude_repo:
            if any(ex.lower() in repo_display.lower() for ex in exclude_repo if ex):
                continue

        # Mine Incident Chains
        incident_chains = []
        commands_only = [a for a in action_trace if a["is_command"]]

        k = 0
        while k < len(action_trace):
            act = action_trace[k]
            if act["is_command"] and act["is_failed"]:
                cat = classify_failure(
                    act["command"],
                    act["response_snippet"],
                    act["exit_code"],
                    inline_failure_class=act.get("inline_failure_class"),
                )
                turn_id = act["turn_index"]
                incident = {
                    "incident_id": f"{item.name}_{act['step_index']}",
                    "conversation_id": item.name,
                    "date": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "repo": repo_display,
                    "turn_index": turn_id,
                    "initial_step": act["step_index"],
                    "initial_command": act["command"],
                    "category": cat,
                    "initial_exit_code": act["exit_code"],
                    "error_snippet": act["response_snippet"][:350],
                    "retries": [],
                    "intervening_file_writes": [],
                    "eventual_working_command": None,
                    "resolved": False,
                }

                look_ahead_idx = k + 1
                max_look = min(len(action_trace), k + 12)
                while look_ahead_idx < max_look:
                    next_act = action_trace[look_ahead_idx]
                    if next_act.get("turn_index", turn_id) > turn_id + 1:
                        break

                    if not next_act["is_command"]:
                        tf = next_act.get("target_file")
                        if tf and tf not in incident["intervening_file_writes"]:
                            incident["intervening_file_writes"].append(tf)
                    else:
                        if next_act["is_failed"]:
                            incident["retries"].append(
                                {
                                    "step_index": next_act["step_index"],
                                    "command": next_act["command"],
                                    "exit_code": next_act["exit_code"],
                                    "error_snippet": next_act["response_snippet"][:200],
                                }
                            )
                        else:
                            incident["eventual_working_command"] = next_act["command"]
                            incident["resolved"] = True
                            k = look_ahead_idx
                            break
                    look_ahead_idx += 1

                incident["retry_count"] = len(incident["retries"])
                incident_chains.append(incident)
            k += 1

        prompt_tok = round(total_prompt_chars / 4)
        prose_tok = round(planner_prose_chars / 4)
        tool_args_tok = round(planner_tool_args_chars / 4)
        resp_tok = prose_tok + tool_args_tok
        think_tok = round(total_thinking_chars / 4)
        tool_tok = round(total_tool_output_chars / 4)
        system_tok = round(total_system_chars / 4)
        unbounded_view_tok = round(file_views_unbounded_chars / 4)
        bounded_view_tok = round(file_views_bounded_chars / 4)
        run_cmd_tok = round(run_cmd_output_chars / 4)
        other_tool_tok = max(
            0, tool_tok - (unbounded_view_tok + bounded_view_tok + run_cmd_tok)
        )

        # Flush any remaining unmodified epochs
        for target_f, intervals in file_lines_read_epoch.items():
            for s_int, e_int in intervals:
                epoch_total_lines += max(0, e_int - s_int + 1)
            ep_uniq = set()
            for s_int, e_int in intervals:
                for ln in range(s_int, e_int + 1):
                    ep_uniq.add(ln)
            epoch_unique_lines += len(ep_uniq)

        # Gross totals across the entire conversation
        gross_total_lines = 0
        gross_unique_lines = 0
        for fpath_viewed, ranges in file_lines_read_gross.items():
            f_unique = set()
            for s_int, e_int in ranges:
                gross_total_lines += max(0, e_int - s_int + 1)
                for ln in range(s_int, e_int + 1):
                    f_unique.add(ln)
            gross_unique_lines += len(f_unique)

        unmodified_overlap_lines = max(0, epoch_total_lines - epoch_unique_lines)
        unmodified_overlap_ratio = (
            (unmodified_overlap_lines / epoch_total_lines * 100)
            if epoch_total_lines > 0
            else 0.0
        )
        gross_overlap_lines = max(0, gross_total_lines - gross_unique_lines)
        gross_overlap_ratio = (
            (gross_overlap_lines / gross_total_lines * 100)
            if gross_total_lines > 0
            else 0.0
        )

        conversations.append(
            {
                "id": item.name,
                "mtime": mtime,
                "dt": conv_dt,
                "date": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "repo_norm": matched_repo_norm,
                "repo_path": repo_display,
                "first_prompt": first_prompt,
                "commands": commands_only,
                "incident_chains": incident_chains,
                "user_turns": user_turns_count,
                "prompt_tokens": prompt_tok,
                "resp_tokens": resp_tok,
                "prose_tokens": prose_tok,
                "tool_args_tokens": tool_args_tok,
                "tool_args_by_tool": {
                    tname: round(chars / 4)
                    for tname, chars in tool_args_chars_by_tool.items()
                },
                "write_to_file_modes": dict(write_to_file_modes),
                "thinking_tokens": think_tok,
                "tool_tokens": tool_tok,
                "run_cmd_tokens": run_cmd_tok,
                "unbounded_view_tokens": unbounded_view_tok,
                "bounded_view_tokens": bounded_view_tok,
                "other_tool_tokens": other_tool_tok,
                "total_view_lines": gross_total_lines,
                "unique_view_lines": gross_unique_lines,
                "unmodified_view_lines": epoch_total_lines,
                "unmodified_unique_lines": epoch_unique_lines,
                "unmodified_overlap_lines": unmodified_overlap_lines,
                "unmodified_overlap_ratio_pct": round(unmodified_overlap_ratio, 2),
                "gross_overlap_lines": gross_overlap_lines,
                "gross_overlap_ratio_pct": round(gross_overlap_ratio, 2),
                "overlap_lines": unmodified_overlap_lines,
                "overlap_ratio_pct": round(unmodified_overlap_ratio, 2),
                "skills_notice_count": skills_notice_count,
                "skills_notice_tokens": round(skills_notice_chars / 4),
                "system_tokens": system_tok,
                "ephemeral_breakdown": {
                    k: round(v / 4) for k, v in ephemeral_by_cat.items()
                },
                "api_input_tokens": api_input_tokens,
                "api_cache_read_tokens": api_cache_read_tokens,
                "api_output_tokens": api_output_tokens,
                "has_api_tokens": has_api_tokens,
                "total_tokens": prompt_tok
                + resp_tok
                + think_tok
                + tool_tok
                + system_tok,
                "file_views": file_views_count,
                "unbounded_views": file_views_unbounded,
                "bounded_views": file_views_bounded,
            }
        )

    return conversations, total_candidates


def quantile(data, q):
    if not data:
        return 0.0
    s = sorted(data)
    idx = (len(s) - 1) * q
    low = int(idx)
    high = min(low + 1, len(s) - 1)
    weight = idx - low
    return s[low] * (1 - weight) + s[high] * weight


def calculate_cohort_summary(conv_list):
    total_convs = len(conv_list)
    total_user_turns = sum(c["user_turns"] for c in conv_list)
    total_commands = sum(len(c["commands"]) for c in conv_list)
    total_failures = sum(
        sum(1 for cmd in c["commands"] if cmd["is_failed"]) for c in conv_list
    )

    failures_by_category = Counter()
    failures_by_repo = Counter()
    all_incidents = []
    py_c_count = 0
    bash_syntax_count = 0

    py_c_multiline_total = sum(
        1 for c in conv_list for cmd in c["commands"] if cmd.get("is_multiline_inline")
    )
    py_c_multiline_failed = sum(
        1
        for c in conv_list
        for cmd in c["commands"]
        if cmd.get("is_multiline_inline") and cmd["is_failed"]
    )
    py_c_oneline_total = sum(
        1 for c in conv_list for cmd in c["commands"] if cmd.get("is_oneline_inline")
    )
    py_c_oneline_failed = sum(
        1
        for c in conv_list
        for cmd in c["commands"]
        if cmd.get("is_oneline_inline") and cmd["is_failed"]
    )

    inline_failures_by_class = Counter()
    for c in conv_list:
        for cmd_entry in c["commands"]:
            cmd = cmd_entry["command"]
            if any(p in cmd.lower() for p in INLINE_PREFIXES):
                py_c_count += 1
            if re.search(r"\b(grep|cat|rm -rf|ls -la)\b", cmd):
                bash_syntax_count += 1
            if cmd_entry["is_failed"]:
                cat = classify_failure(
                    cmd,
                    cmd_entry["response_snippet"],
                    cmd_entry["exit_code"],
                    inline_failure_class=cmd_entry.get("inline_failure_class"),
                )
                failures_by_category[cat] += 1
                failures_by_repo[c["repo_path"]] += 1
                if cmd_entry.get("inline_failure_class"):
                    inline_failures_by_class[cmd_entry["inline_failure_class"]] += 1

        for inc in c["incident_chains"]:
            all_incidents.append(inc)

    failure_rate = (
        (total_failures / total_commands * 100) if total_commands > 0 else 0.0
    )
    high_friction = [
        inc for inc in all_incidents if inc["retry_count"] >= 1 or not inc["resolved"]
    ]

    total_prompt_tok = sum(c["prompt_tokens"] for c in conv_list)
    total_resp_tok = sum(c["resp_tokens"] for c in conv_list)
    total_prose_tok = sum(c.get("prose_tokens", 0) for c in conv_list)
    total_tool_args_tok = sum(c.get("tool_args_tokens", 0) for c in conv_list)
    total_think_tok = sum(c["thinking_tokens"] for c in conv_list)
    total_tool_tok = sum(c["tool_tokens"] for c in conv_list)
    total_run_cmd_tok = sum(c.get("run_cmd_tokens", 0) for c in conv_list)
    total_other_tool_tok = sum(c.get("other_tool_tokens", 0) for c in conv_list)
    total_system_tok = sum(c.get("system_tokens", 0) for c in conv_list)
    total_tokens = sum(c["total_tokens"] for c in conv_list)

    tool_args_by_tool_totals = Counter()
    for c in conv_list:
        for tname, tok in c.get("tool_args_by_tool", {}).items():
            tool_args_by_tool_totals[tname] += tok

    total_unmodified_lines = sum(c.get("unmodified_view_lines", 0) for c in conv_list)
    unique_unmodified_lines = sum(
        c.get("unmodified_unique_lines", 0) for c in conv_list
    )
    unmodified_overlap_lines = max(0, total_unmodified_lines - unique_unmodified_lines)
    unmodified_overlap_ratio = (
        round(unmodified_overlap_lines / total_unmodified_lines * 100, 2)
        if total_unmodified_lines > 0
        else 0.0
    )

    total_gross_lines = sum(
        c.get("gross_view_lines", c.get("total_view_lines", 0)) for c in conv_list
    )
    unique_gross_lines = sum(
        c.get("gross_unique_lines", c.get("unique_view_lines", 0)) for c in conv_list
    )
    gross_overlap_lines = max(0, total_gross_lines - unique_gross_lines)
    gross_overlap_ratio = (
        round(gross_overlap_lines / total_gross_lines * 100, 2)
        if total_gross_lines > 0
        else 0.0
    )

    write_to_file_totals = Counter()
    for c in conv_list:
        write_to_file_totals.update(c.get("write_to_file_modes", {}))

    missing_dep_repos = Counter()
    missing_dep_convs = Counter()
    for c in conv_list:
        for cmd_entry in c["commands"]:
            if cmd_entry.get("inline_failure_class") == "missing_dependency":
                repo_name = Path(c["repo_path"]).name if c["repo_path"] else "unknown"
                missing_dep_repos[repo_name] += 1
                missing_dep_convs[c["id"][:8]] += 1

    calib_ratios = []
    for c in conv_list:
        api_out = c.get("api_output_tokens", 0)
        est_out = c.get("resp_tokens", 0) + c.get("thinking_tokens", 0)
        if api_out > 0 and est_out > 0:
            calib_ratios.append(round(api_out / est_out, 2))
    calib_spread = (
        {
            "mean": round(sum(calib_ratios) / len(calib_ratios), 2),
            "median": round(quantile(calib_ratios, 0.5), 2),
            "p25": round(quantile(calib_ratios, 0.25), 2),
            "p75": round(quantile(calib_ratios, 0.75), 2),
            "min": min(calib_ratios),
            "max": max(calib_ratios),
        }
        if calib_ratios
        else None
    )

    total_skills_notice_count = sum(c.get("skills_notice_count", 0) for c in conv_list)
    skills_injections_per_conv = (
        round(total_skills_notice_count / total_convs, 1) if total_convs > 0 else 0.0
    )
    skills_injections_per_turn = (
        round(total_skills_notice_count / total_user_turns, 2)
        if total_user_turns > 0
        else 0.0
    )

    api_convs = [c for c in conv_list if c.get("has_api_tokens", False)]
    num_api_convs = len(api_convs)
    total_api_input_tok = sum(c.get("api_input_tokens", 0) for c in conv_list)
    total_api_cache_read_tok = sum(c.get("api_cache_read_tokens", 0) for c in conv_list)
    total_api_output_tok = sum(c.get("api_output_tokens", 0) for c in conv_list)
    has_api_gt = num_api_convs > 0 and (
        total_api_input_tok > 0 or total_api_cache_read_tok > 0
    )
    total_api_context_all = (
        total_api_input_tok + total_api_cache_read_tok + total_api_output_tok
    )
    api_context_per_conv = (
        round(total_api_context_all / num_api_convs)
        if num_api_convs > 0 and has_api_gt
        else None
    )
    api_fresh_per_conv = (
        round(total_api_input_tok / num_api_convs)
        if num_api_convs > 0 and has_api_gt
        else None
    )
    api_cache_read_per_conv = (
        round(total_api_cache_read_tok / num_api_convs)
        if num_api_convs > 0 and has_api_gt
        else None
    )
    api_output_per_conv = (
        round(total_api_output_tok / num_api_convs)
        if num_api_convs > 0 and has_api_gt
        else None
    )
    cache_hit_rate = (
        round(
            total_api_cache_read_tok
            / (total_api_input_tok + total_api_cache_read_tok)
            * 100,
            2,
        )
        if has_api_gt and (total_api_input_tok + total_api_cache_read_tok) > 0
        else None
    )
    est_output_tokens = total_prose_tok + total_tool_args_tok + total_think_tok
    calib_ratio = (
        round(total_api_output_tok / est_output_tokens, 2)
        if has_api_gt and est_output_tokens > 0
        else None
    )
    api_conv_tokens = sum(c["total_tokens"] for c in api_convs)
    cxt_mag_factor = (
        round(total_api_context_all / api_conv_tokens, 1)
        if has_api_gt and api_conv_tokens > 0
        else None
    )

    total_views = sum(c["file_views"] for c in conv_list)
    total_unbounded = sum(c["unbounded_views"] for c in conv_list)
    unbounded_pct = (total_unbounded / total_views * 100) if total_views > 0 else 0.0
    unbounded_view_tok = sum(c.get("unbounded_view_tokens", 0) for c in conv_list)
    bounded_view_tok = sum(c.get("bounded_view_tokens", 0) for c in conv_list)

    ephemeral_skills_tok = sum(
        c.get("ephemeral_breakdown", {}).get("skills_notice", 0) for c in conv_list
    )
    ephemeral_memory_tok = sum(
        c.get("ephemeral_breakdown", {}).get("memory_recall", 0) for c in conv_list
    )
    ephemeral_sys_tok = sum(
        c.get("ephemeral_breakdown", {}).get("system_message", 0) for c in conv_list
    )
    ephemeral_other_tok = sum(
        c.get("ephemeral_breakdown", {}).get("other_ephemeral", 0) for c in conv_list
    )

    conv_tokens = [c["total_tokens"] for c in conv_list]
    median_tokens = round(quantile(conv_tokens, 0.5))
    p75_tokens = round(quantile(conv_tokens, 0.75))
    p90_tokens = round(quantile(conv_tokens, 0.90))
    min_tokens = min(conv_tokens) if conv_tokens else 0
    max_tokens = max(conv_tokens) if conv_tokens else 0

    conv_turns = [c["user_turns"] for c in conv_list]
    median_turns = round(quantile(conv_turns, 0.5), 1)
    turns_per_conv = (
        round(total_user_turns / total_convs, 2) if total_convs > 0 else 0.0
    )
    cmds_per_turn = (
        round(total_commands / total_user_turns, 2) if total_user_turns > 0 else 0.0
    )
    cmds_per_conv = round(total_commands / total_convs, 2) if total_convs > 0 else 0.0

    friction_per_100_cmds = (
        round((len(high_friction) / total_commands * 100), 2)
        if total_commands > 0
        else 0.0
    )
    inline_per_100_cmds = (
        round((py_c_count / total_commands * 100), 2) if total_commands > 0 else 0.0
    )

    tokens_per_conv = round(total_tokens / total_convs) if total_convs > 0 else 0
    tokens_per_turn = (
        round(total_tokens / total_user_turns) if total_user_turns > 0 else 0
    )

    return {
        "conversations": total_convs,
        "user_turns": total_user_turns,
        "turns_per_conv": turns_per_conv,
        "median_turns_per_conv": median_turns,
        "commands": total_commands,
        "cmds_per_conv": cmds_per_conv,
        "cmds_per_turn": cmds_per_turn,
        "failures": total_failures,
        "failure_rate_pct": round(failure_rate, 2),
        "total_incidents": len(all_incidents),
        "high_friction_count": len(high_friction),
        "friction_per_100_cmds": friction_per_100_cmds,
        "py_c_inline": py_c_count,
        "inline_per_100_cmds": inline_per_100_cmds,
        "py_c_multiline": {
            "total": py_c_multiline_total,
            "failed": py_c_multiline_failed,
            "fail_pct": round((py_c_multiline_failed / py_c_multiline_total * 100), 2)
            if py_c_multiline_total > 0
            else 0.0,
        },
        "py_c_oneline": {
            "total": py_c_oneline_total,
            "failed": py_c_oneline_failed,
            "fail_pct": round((py_c_oneline_failed / py_c_oneline_total * 100), 2)
            if py_c_oneline_total > 0
            else 0.0,
        },
        "inline_failures_by_class": dict(inline_failures_by_class),
        "bash_syntax": bash_syntax_count,
        "file_views": total_views,
        "unbounded_views": total_unbounded,
        "unbounded_view_pct": round(unbounded_pct, 2),
        "unbounded_view_tokens": unbounded_view_tok,
        "bounded_view_tokens": bounded_view_tok,
        "file_view_overlap": {
            "total_unmodified_lines": total_unmodified_lines,
            "unique_unmodified_lines": unique_unmodified_lines,
            "unmodified_overlap_pct": unmodified_overlap_ratio,
            "total_gross_lines": total_gross_lines,
            "unique_gross_lines": unique_gross_lines,
            "gross_overlap_pct": gross_overlap_ratio,
            "overlap_pct": unmodified_overlap_ratio,
        },
        "write_to_file_modes": dict(write_to_file_totals),
        "missing_dependency_details": {
            "by_repo": dict(missing_dep_repos),
            "by_conv": dict(missing_dep_convs),
        },
        "total_tokens": total_tokens,
        "prompt_tokens": total_prompt_tok,
        "response_tokens": total_resp_tok,
        "response_breakdown": {
            "visible_prose_tokens": total_prose_tok,
            "tool_call_args_tokens": total_tool_args_tok,
            "tool_call_args_by_tool": dict(tool_args_by_tool_totals),
            "thinking_tokens": total_think_tok,
        },
        "tool_tokens": total_tool_tok,
        "tool_breakdown": {
            "unbounded_view_tokens": unbounded_view_tok,
            "bounded_view_tokens": bounded_view_tok,
            "run_command_tokens": total_run_cmd_tok,
            "other_tool_tokens": total_other_tool_tok,
        },
        "system_tokens": total_system_tok,
        "system_breakdown": {
            "skills_notice_tokens": ephemeral_skills_tok,
            "memory_recall_tokens": ephemeral_memory_tok,
            "system_message_tokens": ephemeral_sys_tok,
            "other_ephemeral_tokens": ephemeral_other_tok,
        },
        "skills_notice_stats": {
            "total_injections": total_skills_notice_count,
            "injections_per_conv": skills_injections_per_conv,
            "injections_per_turn": skills_injections_per_turn,
            "total_tokens": ephemeral_skills_tok,
            "persistence_model": "per_turn_ephemeral",
            "retained_in_history": False,
        },
        "api_tokens_ground_truth": {
            "has_ground_truth": has_api_gt,
            "input_tokens_fresh": total_api_input_tok if has_api_gt else None,
            "cache_read_tokens": total_api_cache_read_tok if has_api_gt else None,
            "output_tokens_model": total_api_output_tok if has_api_gt else None,
            "total_api_context_processed": total_api_context_all
            if has_api_gt
            else None,
            "fresh_input_per_conv": api_fresh_per_conv,
            "cache_read_per_conv": api_cache_read_per_conv,
            "output_per_conv": api_output_per_conv,
            "total_api_per_conv": api_context_per_conv,
            "cache_hit_rate_pct": cache_hit_rate,
            "calibration": {
                "output_token_ratio_api_vs_est": calib_ratio,
                "context_magnification_factor": cxt_mag_factor,
                "spread_by_conversation": calib_spread,
            },
        },
        "tokens_per_conv": tokens_per_conv,
        "median_tokens_per_conv": median_tokens,
        "p75_tokens_per_conv": p75_tokens,
        "p90_tokens_per_conv": p90_tokens,
        "min_tokens_per_conv": min_tokens,
        "max_tokens_per_conv": max_tokens,
        "tokens_per_turn": tokens_per_turn,
        "failures_by_category": dict(failures_by_category),
        "failures_by_repo": dict(failures_by_repo),
        "high_friction_incidents": high_friction,
    }


def bootstrap_conversation_diff(
    t_conv_values,
    b_conv_values,
    stat_fn=None,
    n_boot=1000,
    alpha=0.05,
    min_samples=15,
):
    """
    Computes conversation-level non-parametric bootstrap confidence interval
    for the difference in statistics between target and baseline cohorts.
    Returns (low_ci, high_ci, p_val, is_significant).
    """
    if not t_conv_values or not b_conv_values:
        return 0.0, 0.0, 1.0, False
    if len(t_conv_values) < min_samples or len(b_conv_values) < min_samples:
        return 0.0, 0.0, 1.0, False
    if stat_fn is None:

        def default_mean(arr):
            return sum(arr) / len(arr) if arr else 0.0

        stat_fn = default_mean

    rng = random.Random(42)
    diffs = []
    n_t = len(t_conv_values)
    n_b = len(b_conv_values)
    for _ in range(n_boot):
        t_sample = rng.choices(t_conv_values, k=n_t)
        b_sample = rng.choices(b_conv_values, k=n_b)
        diffs.append(stat_fn(t_sample) - stat_fn(b_sample))
    diffs.sort()
    low_idx = int(n_boot * (alpha / 2))
    high_idx = int(n_boot * (1 - alpha / 2))
    low = diffs[low_idx]
    high = diffs[high_idx]
    zero_cross = sum(1 for d in diffs if d <= 0) / n_boot
    p_val = 2 * min(zero_cross, 1 - zero_cross)
    # Statistically significant only if 0 is strictly outside [low, high]
    is_significant = not (low <= 0 <= high)
    return low, high, p_val, is_significant


def is_statistically_significant(c_events, c_total, b_events, b_total, min_samples=30):
    if c_events is None or b_events is None or c_total is None or b_total is None:
        return False
    if c_total < min_samples or b_total < min_samples:
        return False
    if c_total <= 0 or b_total <= 0:
        return False
    p1 = c_events / c_total
    p2 = b_events / b_total
    p_pool = (c_events + b_events) / (c_total + b_total)
    if p_pool <= 0 or p_pool >= 1:
        return False
    smaller_total = min(c_total, b_total)
    min_expected_cell = smaller_total * min(p_pool, 1.0 - p_pool)
    if min_expected_cell < 5:
        return False
    se = (p_pool * (1 - p_pool) * (1 / c_total + 1 / b_total)) ** 0.5
    if se == 0:
        return False
    z = abs(p1 - p2) / se
    return z >= 1.96


def format_delta(
    current,
    baseline,
    lower_is_better=True,
    is_pct=False,
    custom_tag=None,
    is_significant=False,
):
    unit = "%" if is_pct else ""
    if baseline is None or current is None:
        val_str = f"{current}{unit}" if current is not None else "N/A"
        return f"{val_str} (N/A)"
    if baseline == 0:
        if current == 0:
            return f"0{unit} (FLAT)"
        val_str = f"{current}{unit}" if current is not None else "N/A"
        return f"{val_str} (N/A)"
    diff = current - baseline
    pct_change = (diff / baseline) * 100.0
    sign = "+" if diff > 0 else ""

    if custom_tag:
        tag = custom_tag
    elif lower_is_better is None:
        tag = "VOLUME" if diff > 0 else ("FLAT" if diff == 0 else "LOWER")
    elif not is_significant:
        tag = "NEUTRAL"
    else:
        improved = (diff < 0) if lower_is_better else (diff > 0)
        tag = "IMPROVED" if improved else ("DRIFT" if diff != 0 else "FLAT")
    return f"{sign}{diff:.2f}{unit} ({sign}{pct_change:.1f}% {tag})"


def run_inventory(output_dir=None):
    base_dir = locate_antigravity_dir()
    brain_dirs = locate_brain_directories(base_dir)
    ws_storage_dir = locate_ide_workspace_storage()

    ide_workspaces = discover_ide_workspaces(ws_storage_dir)
    candidate_repos = discover_git_repositories(ide_workspaces, base_dir)

    earliest_dt = None
    latest_dt = None
    total_convs = 0

    seen_ids = set()
    for brain_dir in brain_dirs:
        if not brain_dir or not brain_dir.exists():
            continue
        for item in brain_dir.iterdir():
            if (
                not item.is_dir()
                or item.name == "tempmediaStorage"
                or item.name in seen_ids
            ):
                continue
            tpath = item / ".system_generated" / "logs" / "transcript.jsonl"
            if not tpath.exists():
                continue
            seen_ids.add(item.name)
            total_convs += 1
            try:
                mtime = os.path.getmtime(tpath)
                dt = datetime.fromtimestamp(mtime)
                if earliest_dt is None or dt < earliest_dt:
                    earliest_dt = dt
                if latest_dt is None or dt > latest_dt:
                    latest_dt = dt
            except Exception:
                pass

    cwd_git = find_git_root(os.getcwd())
    active_ws_display = Path(cwd_git).name if cwd_git else "General Environment"

    repo_list = []
    for r_norm, r_path in candidate_repos.items():
        repo_list.append({"name": Path(r_path).name, "path": r_path})
    repo_list.sort(key=lambda x: x["name"].lower())

    inventory_data = {
        "timestamp": datetime.now().isoformat(),
        "total_conversations": total_convs,
        "earliest_session": earliest_dt.strftime("%Y-%m-%d %H:%M:%S")
        if earliest_dt
        else None,
        "latest_session": latest_dt.strftime("%Y-%m-%d %H:%M:%S")
        if latest_dt
        else None,
        "active_workspace": active_ws_display,
        "total_discovered_repositories": len(repo_list),
        "repositories": repo_list,
    }

    out_dir = Path(output_dir) if output_dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "trajectory_inventory.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(inventory_data, f, indent=2)

    print("=== Antigravity Rapid Inventory ===")
    print(f"Total Conversations Found: {total_convs}")
    print(
        f"Date Range: {inventory_data['earliest_session']} -> {inventory_data['latest_session']}"
    )
    print(f"Discovered Repositories: {len(repo_list)}")
    print(f"Inventory saved to: {out_file}")
    return out_file


def run_audit(
    output_dir=None,
    max_conversations=100,
    since_date=None,
    until_date=None,
    target_repo=None,
    exclude_repo=None,
    exclude_conv=None,
    auto_exclude_audit=True,
    compare_mode=False,
    print_summary=False,
):
    base_dir = locate_antigravity_dir()
    brain_dirs = locate_brain_directories(base_dir)
    ws_storage_dir = locate_ide_workspace_storage()

    since_dt = None
    if since_date:
        try:
            since_dt = datetime.fromisoformat(since_date.replace("Z", "+00:00"))
        except Exception:
            try:
                since_dt = datetime.strptime(since_date, "%Y-%m-%d")
            except Exception:
                print(
                    f"Warning: Could not parse --since '{since_date}'. Ignoring filter."
                )
        if since_dt and since_dt.tzinfo is not None:
            since_dt = since_dt.astimezone().replace(tzinfo=None)

    until_dt = None
    if until_date:
        is_date_only = False
        try:
            clean_until = until_date.strip()
            if (
                len(clean_until) == 10
                and clean_until.count("-") == 2
                and "T" not in clean_until
                and " " not in clean_until
            ):
                is_date_only = True
            until_dt = datetime.fromisoformat(clean_until.replace("Z", "+00:00"))
        except Exception:
            try:
                until_dt = datetime.strptime(until_date, "%Y-%m-%d")
                is_date_only = True
            except Exception:
                print(
                    f"Warning: Could not parse --until '{until_date}'. Ignoring filter."
                )
        if until_dt:
            if until_dt.tzinfo is not None:
                until_dt = until_dt.astimezone().replace(tzinfo=None)
            if is_date_only:
                until_dt = until_dt.replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )

    if compare_mode and not since_dt:
        # Default compare mode to last 24 hours if no since_date passed
        since_dt = datetime.now() - timedelta(hours=24)

    exclude_list = []
    if exclude_repo:
        if isinstance(exclude_repo, str):
            exclude_list = [e.strip() for e in exclude_repo.split(",") if e.strip()]
        else:
            exclude_list = list(exclude_repo)

    exclude_conv_list = []
    if exclude_conv:
        if isinstance(exclude_conv, str):
            exclude_conv_list = [
                c.strip() for c in exclude_conv.split(",") if c.strip()
            ]
        else:
            exclude_conv_list = list(exclude_conv)

    print("=== Antigravity Trajectory Auditor ===")
    print(f"Platform: {platform.system()} ({platform.machine()})")
    print(f"Antigravity Data Dir: {base_dir}")
    print(f"Brain Storage Locations: {len(brain_dirs)}")
    print(
        f"Since Filter: {since_dt.strftime('%Y-%m-%d %H:%M:%S') if since_dt else 'None'}"
    )
    print(
        f"Until Filter: {until_dt.strftime('%Y-%m-%d %H:%M:%S') if until_dt else 'None'}"
    )
    print(
        f"Mode: {'Comparative Efficiency Gains (--compare)' if compare_mode else 'Standard Trajectory Audit'}"
    )
    print(f"Target Repo: {target_repo or 'All'}")
    print(f"Exclude Repos: {', '.join(exclude_list) if exclude_list else 'None'}")
    print(
        f"Exclude Convs: {', '.join(exclude_conv_list) if exclude_conv_list else 'None'}"
    )
    print(f"Auto-Exclude Audit Sessions: {auto_exclude_audit}")

    ide_workspaces = discover_ide_workspaces(ws_storage_dir)
    candidate_repos = discover_git_repositories(ide_workspaces, base_dir)

    all_convs, total_candidates = parse_conversations(
        brain_dirs=brain_dirs,
        candidate_repos=candidate_repos,
        max_conversations=max_conversations,
        since_dt=since_dt,
        until_dt=until_dt,
        target_repo=target_repo,
        exclude_repo=exclude_list,
        exclude_convs=exclude_conv_list,
        auto_exclude_audit=auto_exclude_audit,
        compare_mode=compare_mode,
    )

    out_dir = Path(output_dir) if output_dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "trajectory_audit_summary.json"

    if compare_mode and since_dt:
        # Partition conversations by start timestamp
        target_convs = [c for c in all_convs if c["dt"] >= since_dt]
        baseline_convs = [c for c in all_convs if c["dt"] < since_dt]

        target_summary = calculate_cohort_summary(target_convs)
        baseline_summary = calculate_cohort_summary(baseline_convs)

        print(
            f"\nParsed Conversations: {len(target_convs)} target (post {since_dt.strftime('%Y-%m-%d %H:%M')}) vs {len(baseline_convs)} baseline"
        )

        print("\n" + "=" * 78)
        print("                 EFFICIENCY GAINS & TOKEN BURN COMPARISON")
        print("=" * 78)
        header_fmt = "{:<32} {:<15} {:<15} {:<16}"
        print(
            header_fmt.format("Metric", "Baseline", "Target Window", "Delta / Outcome")
        )
        print("-" * 78)

        def print_row(
            label,
            base_val,
            tgt_val,
            lower_is_better=True,
            is_pct=False,
            val_suffix="",
            custom_tag=None,
            is_significant=False,
        ):
            delta_str = format_delta(
                tgt_val,
                base_val,
                lower_is_better=lower_is_better,
                is_pct=is_pct,
                custom_tag=custom_tag,
                is_significant=is_significant,
            )
            b_str = f"{base_val}{val_suffix}" if base_val is not None else "N/A"
            t_str = f"{tgt_val}{val_suffix}" if tgt_val is not None else "N/A"
            print(header_fmt.format(label, b_str, t_str, delta_str))

        def pooled_ratio_stat(pairs):
            tot_num = sum(p[0] for p in pairs)
            tot_den = sum(p[1] for p in pairs)
            return (tot_num / tot_den * 100.0) if tot_den > 0 else 0.0

        # Conversation-level arrays for non-parametric bootstrap testing
        t_fail_pairs = [
            (
                sum(1 for cmd in c["commands"] if cmd["is_failed"]),
                len(c["commands"]),
            )
            for c in target_convs
        ]
        b_fail_pairs = [
            (
                sum(1 for cmd in c["commands"] if cmd["is_failed"]),
                len(c["commands"]),
            )
            for c in baseline_convs
        ]

        t_friction_pairs = [
            (
                len(
                    [
                        inc
                        for inc in c["incident_chains"]
                        if inc["retry_count"] >= 1 or not inc["resolved"]
                    ]
                ),
                len(c["commands"]),
            )
            for c in target_convs
        ]
        b_friction_pairs = [
            (
                len(
                    [
                        inc
                        for inc in c["incident_chains"]
                        if inc["retry_count"] >= 1 or not inc["resolved"]
                    ]
                ),
                len(c["commands"]),
            )
            for c in baseline_convs
        ]

        t_tokens = [c["total_tokens"] for c in target_convs]
        b_tokens = [c["total_tokens"] for c in baseline_convs]

        t_unmod_overlap_pairs = [
            (
                c.get("unmodified_overlap_lines", 0),
                c.get("unmodified_view_lines", 0),
            )
            for c in target_convs
        ]
        b_unmod_overlap_pairs = [
            (
                c.get("unmodified_overlap_lines", 0),
                c.get("unmodified_view_lines", 0),
            )
            for c in baseline_convs
        ]

        t_unbounded_pairs = [
            (
                c.get("unbounded_views", 0),
                c.get("file_views", 0),
            )
            for c in target_convs
        ]
        b_unbounded_pairs = [
            (
                c.get("unbounded_views", 0),
                c.get("file_views", 0),
            )
            for c in baseline_convs
        ]

        t_api_convs = [c for c in target_convs if c.get("has_api_tokens")]
        b_api_convs = [c for c in baseline_convs if c.get("has_api_tokens")]

        t_cache_pairs = [
            (
                c.get("api_cache_read_tokens", 0) or 0,
                (c.get("api_input_tokens", 0) or 0)
                + (c.get("api_cache_read_tokens", 0) or 0),
            )
            for c in t_api_convs
        ]
        b_cache_pairs = [
            (
                c.get("api_cache_read_tokens", 0) or 0,
                (c.get("api_input_tokens", 0) or 0)
                + (c.get("api_cache_read_tokens", 0) or 0),
            )
            for c in b_api_convs
        ]

        t_api_totals = [
            (c.get("api_input_tokens", 0) or 0)
            + (c.get("api_cache_read_tokens", 0) or 0)
            + (c.get("api_output_tokens", 0) or 0)
            for c in t_api_convs
        ]
        b_api_totals = [
            (c.get("api_input_tokens", 0) or 0)
            + (c.get("api_cache_read_tokens", 0) or 0)
            + (c.get("api_output_tokens", 0) or 0)
            for c in b_api_convs
        ]

        t_api_fresh = [c.get("api_input_tokens", 0) or 0 for c in t_api_convs]
        b_api_fresh = [c.get("api_input_tokens", 0) or 0 for c in b_api_convs]

        # Conversation-level non-parametric bootstrap tests (1,000 resamples)
        _, _, p_fail, sig_fail = bootstrap_conversation_diff(
            t_fail_pairs, b_fail_pairs, stat_fn=pooled_ratio_stat
        )
        _, _, p_friction, sig_friction = bootstrap_conversation_diff(
            t_friction_pairs, b_friction_pairs, stat_fn=pooled_ratio_stat
        )
        _, _, p_median_tok, sig_median_tok = bootstrap_conversation_diff(
            t_tokens, b_tokens, stat_fn=lambda arr: quantile(arr, 0.5)
        )
        _, _, p_unmod_overlap, sig_unmod_overlap = bootstrap_conversation_diff(
            t_unmod_overlap_pairs, b_unmod_overlap_pairs, stat_fn=pooled_ratio_stat
        )
        _, _, p_unbounded, sig_unbounded = bootstrap_conversation_diff(
            t_unbounded_pairs, b_unbounded_pairs, stat_fn=pooled_ratio_stat
        )
        _, _, p_cache, sig_cache = bootstrap_conversation_diff(
            t_cache_pairs, b_cache_pairs, stat_fn=pooled_ratio_stat
        )
        _, _, p_api_conv, sig_api_conv = bootstrap_conversation_diff(
            t_api_totals, b_api_totals
        )
        _, _, p_api_fresh, sig_api_fresh = bootstrap_conversation_diff(
            t_api_fresh, b_api_fresh
        )

        print_row(
            "Active Conversations",
            baseline_summary["conversations"],
            target_summary["conversations"],
            lower_is_better=None,
        )
        print_row(
            "Total User Turns",
            baseline_summary["user_turns"],
            target_summary["user_turns"],
            lower_is_better=None,
        )
        print_row(
            "Turns / Conversation (Mean)",
            baseline_summary["turns_per_conv"],
            target_summary["turns_per_conv"],
            lower_is_better=None,
            custom_tag="VOLUME",
        )
        print_row(
            "Total Commands Executed",
            baseline_summary["commands"],
            target_summary["commands"],
            lower_is_better=None,
        )
        print_row(
            "Commands / Turn (Normalized)",
            baseline_summary["cmds_per_turn"],
            target_summary["cmds_per_turn"],
            lower_is_better=None,
            custom_tag="RATIO",
        )
        print("-" * 78)
        print_row(
            "True Failure Rate",
            baseline_summary["failure_rate_pct"],
            target_summary["failure_rate_pct"],
            lower_is_better=True,
            is_pct=True,
            val_suffix="%",
            is_significant=sig_fail,
        )
        print_row(
            "High-Friction Loops / 100 Cmds",
            baseline_summary["friction_per_100_cmds"],
            target_summary["friction_per_100_cmds"],
            lower_is_better=True,
            is_pct=True,
            val_suffix="%",
            is_significant=sig_friction,
        )
        print_row(
            "Inline Scripts / 100 Cmds",
            baseline_summary["inline_per_100_cmds"],
            target_summary["inline_per_100_cmds"],
            lower_is_better=None,
            is_pct=True,
            val_suffix="%",
            custom_tag="RATIO",
        )
        print_row(
            "Multiline py -c Fail Rate (%)",
            baseline_summary.get("py_c_multiline", {}).get("fail_pct", 0.0),
            target_summary.get("py_c_multiline", {}).get("fail_pct", 0.0),
            lower_is_better=True,
            is_pct=True,
            val_suffix="%",
            custom_tag="NEUTRAL",
        )
        print_row(
            "Unbounded File Views (%)",
            baseline_summary["unbounded_view_pct"],
            target_summary["unbounded_view_pct"],
            lower_is_better=True,
            is_pct=True,
            val_suffix="%",
            is_significant=sig_unbounded,
        )
        print_row(
            "Unmodified Re-read Overlap (%)",
            baseline_summary.get("file_view_overlap", {}).get(
                "unmodified_overlap_pct", 0.0
            ),
            target_summary.get("file_view_overlap", {}).get(
                "unmodified_overlap_pct", 0.0
            ),
            lower_is_better=True,
            is_pct=True,
            val_suffix="%",
            is_significant=sig_unmod_overlap,
        )
        print_row(
            "Gross File Overlap Re-read (%)",
            baseline_summary.get("file_view_overlap", {}).get("gross_overlap_pct", 0.0),
            target_summary.get("file_view_overlap", {}).get("gross_overlap_pct", 0.0),
            lower_is_better=None,
            is_pct=True,
            val_suffix="%",
            custom_tag="RATIO",
        )
        print("-" * 78)
        # Ground-truth API metrics
        base_api = baseline_summary.get("api_tokens_ground_truth", {})
        tgt_api = target_summary.get("api_tokens_ground_truth", {})
        b_cache = base_api.get("cache_hit_rate_pct")
        t_cache = tgt_api.get("cache_hit_rate_pct")
        print_row(
            "Prompt Cache Hit Rate (%)",
            b_cache,
            t_cache,
            lower_is_better=False,
            is_pct=True,
            val_suffix="%",
            is_significant=sig_cache,
        )
        print_row(
            "API Context / Conv (Ground Truth)",
            base_api.get("total_api_per_conv"),
            tgt_api.get("total_api_per_conv"),
            lower_is_better=True,
            is_significant=sig_api_conv,
        )
        print_row(
            "API Fresh Input / Conv",
            base_api.get("fresh_input_per_conv"),
            tgt_api.get("fresh_input_per_conv"),
            lower_is_better=True,
            is_significant=sig_api_fresh,
        )
        print("-" * 78)
        print_row(
            "Median Tokens / Conversation",
            baseline_summary["median_tokens_per_conv"],
            target_summary["median_tokens_per_conv"],
            lower_is_better=True,
            is_significant=sig_median_tok,
        )
        print_row(
            "Mean Tokens / Conversation",
            baseline_summary["tokens_per_conv"],
            target_summary["tokens_per_conv"],
            lower_is_better=None,
            custom_tag="VOLUME",
        )
        print_row(
            "P90 Tokens / Conversation",
            baseline_summary["p90_tokens_per_conv"],
            target_summary["p90_tokens_per_conv"],
            lower_is_better=None,
            custom_tag="NOISE",
        )
        print_row(
            "Est. Tokens / User Turn",
            baseline_summary["tokens_per_turn"],
            target_summary["tokens_per_turn"],
            lower_is_better=None,
            custom_tag="TURNS_RATIO",
        )
        print("-" * 78)

        summary_payload = {
            "audit_timestamp": datetime.now().isoformat(),
            "platform": platform.system(),
            "mode": "comparative",
            "since_filter": since_dt.isoformat() if since_dt else None,
            "until_filter": until_dt.isoformat() if until_dt else None,
            "comparison": {
                "target_window": target_summary,
                "baseline_window": baseline_summary,
                "baseline": baseline_summary,
                "bootstrap_significance_tests": {
                    "unit_of_analysis": "conversation",
                    "iterations": 1000,
                    "failure_rate": {
                        "p_value": round(p_fail, 4),
                        "significant": sig_fail,
                    },
                    "friction_loops": {
                        "p_value": round(p_friction, 4),
                        "significant": sig_friction,
                    },
                    "median_tokens": {
                        "p_value": round(p_median_tok, 4),
                        "significant": sig_median_tok,
                    },
                    "unmodified_overlap": {
                        "p_value": round(p_unmod_overlap, 4),
                        "significant": sig_unmod_overlap,
                    },
                    "unbounded_views": {
                        "p_value": round(p_unbounded, 4),
                        "significant": sig_unbounded,
                    },
                    "prompt_cache_hit": {
                        "p_value": round(p_cache, 4),
                        "significant": sig_cache,
                    },
                    "api_context": {
                        "p_value": round(p_api_conv, 4),
                        "significant": sig_api_conv,
                    },
                    "api_input_tokens": {
                        "p_value": round(p_api_fresh, 4),
                        "significant": sig_api_fresh,
                    },
                },
            },
        }
    else:
        summary = calculate_cohort_summary(all_convs)
        print(
            f"\nParsed Active Conversations: {summary['conversations']} (out of {total_candidates} matching candidates)"
        )
        print(f"Total Commands Executed: {summary['commands']}")
        print(
            f"True Command Failures: {summary['failures']} ({summary['failure_rate_pct']:.2f}% true failure rate)"
        )
        print(f"Total Incident Chains: {summary['total_incidents']}")
        print(f"High-Friction Loops: {summary['high_friction_count']}")
        print(
            f"Unbounded View Ratio: {summary['unbounded_view_pct']}% ({summary['unbounded_views']}/{summary['file_views']})"
        )
        print(f"Estimated Tokens / Conversation: {summary['tokens_per_conv']}")
        print(f"Estimated Tokens / User Turn: {summary['tokens_per_turn']}")

        print("\nFailures by Category:")
        for cat, count in sorted(
            summary["failures_by_category"].items(), key=lambda x: x[1], reverse=True
        ):
            pct = (count / summary["failures"] * 100) if summary["failures"] else 0
            print(f"  - {cat}: {count} ({pct:.1f}%)")

        print("\nFailures by Repository:")
        for repo, count in sorted(
            summary["failures_by_repo"].items(), key=lambda x: x[1], reverse=True
        )[:10]:
            print(f"  - {Path(repo).name}: {count} failures")

        summary_payload = {
            "audit_timestamp": datetime.now().isoformat(),
            "platform": platform.system(),
            "mode": "standard",
            "since_filter": since_dt.isoformat() if since_dt else None,
            "target_repo": target_repo,
            "exclude_filter": exclude_list,
            **summary,
        }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2)

    print(f"\nAudit complete. Structured summary written to: {out_file}")
    if print_summary:
        print("\n=== STRUCTURED SUMMARY JSON ===")
        print(json.dumps(summary_payload, indent=2))
    return out_file


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Trajectory Efficiency Auditor for Antigravity"
    )
    parser.add_argument(
        "output_dir", nargs="?", default=None, help="Directory to save summary json"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max recent conversations to parse (default 100)",
    )
    parser.add_argument(
        "--all", action="store_true", help="Parse all conversations without limit"
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Filter to conversations on or after date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="Filter to conversations on or before date/timestamp (YYYY-MM-DD or ISO)",
    )
    parser.add_argument(
        "--repo", type=str, default=None, help="Filter to specific repository substring"
    )
    parser.add_argument(
        "--exclude",
        type=str,
        default=None,
        help="Comma-separated repository names to exclude",
    )
    parser.add_argument(
        "--exclude-conv",
        type=str,
        default=None,
        help="Comma-separated conversation IDs to exclude from audit",
    )
    parser.add_argument(
        "--include-audit-sessions",
        action="store_true",
        default=False,
        help="Include self and audit/meta-evaluation sessions (default: excluded)",
    )
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="Discover repositories and date boundaries rapidly without parsing transcripts",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare target window against baseline history and compute efficiency gains",
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Print structured JSON summary to stdout after audit completion",
    )
    args = parser.parse_args()

    if args.inventory_only:
        run_inventory(args.output_dir)
    else:
        conv_limit = None if args.all else args.limit
        run_audit(
            output_dir=args.output_dir,
            max_conversations=conv_limit,
            since_date=args.since,
            until_date=args.until,
            target_repo=args.repo,
            exclude_repo=args.exclude,
            exclude_conv=args.exclude_conv,
            auto_exclude_audit=not args.include_audit_sessions,
            compare_mode=args.compare,
            print_summary=args.print_summary,
        )
