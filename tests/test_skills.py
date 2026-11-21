#!/usr/bin/env python3
"""Unit tests for improve-agent-efficiency and public-repo-safety skills."""

import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
EFFICIENCY_SCRIPTS = REPO_ROOT / "skills" / "improve-agent-efficiency" / "scripts"
SAFETY_SCRIPTS = REPO_ROOT / "skills" / "public-repo-safety" / "scripts"

sys.path.insert(0, str(EFFICIENCY_SCRIPTS))
sys.path.insert(0, str(SAFETY_SCRIPTS))

import audit_trajectories  # noqa: E402
import check_repo_safety  # noqa: E402
import probe_environment  # noqa: E402


class TestAuditTrajectories(unittest.TestCase):
    def test_parses_antigravity_2_0_active_workspaces_block(self):
        """Antigravity 2.0 multi-line Active Workspaces block should resolve repo_path."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo_dir = tmp_path / "my-cool-repo"
            (repo_dir / ".git").mkdir(parents=True)

            brain_dir = tmp_path / "brain"
            conv_dir = brain_dir / "conv-agy2" / ".system_generated" / "logs"
            conv_dir.mkdir(parents=True)
            tpath = conv_dir / "transcript_full.jsonl"

            steps = [
                {
                    "step_index": 0,
                    "type": "USER_INPUT",
                    "source": "USER_EXPLICIT",
                    "created_at": "2026-10-15T10:00:00Z",
                    "content": (
                        "<user_information>\n"
                        "The USER's OS version is mac.\n"
                        "Active Workspaces:\n"
                        f"- {repo_dir}\n"
                        f"Command Working Directory: {repo_dir}\n"
                        "</user_information>\n"
                        "<USER_REQUEST>Check status</USER_REQUEST>"
                    ),
                },
                {
                    "step_index": 1,
                    "type": "PLANNER_RESPONSE",
                    "created_at": "2026-10-15T10:00:05Z",
                    "content": "Here is the status.",
                    "thinking": "Thinking...",
                    "tool_calls": [],
                },
            ]
            tpath.write_text(
                "\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8"
            )

            candidate_repos = {
                audit_trajectories.norm_path(str(repo_dir)): str(repo_dir.resolve())
            }
            convs, _ = audit_trajectories.parse_conversations(
                brain_dirs=[brain_dir],
                candidate_repos=candidate_repos,
                max_conversations=10,
            )
            self.assertEqual(len(convs), 1)
            self.assertEqual(convs[0]["repo_path"], str(repo_dir.resolve()))

    def test_limit_applied_after_repo_filter(self):
        """--limit should not starve --repo when newer conversations belong to another repo."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo_a = tmp_path / "repo-alpha"
            repo_b = tmp_path / "repo-beta"
            (repo_a / ".git").mkdir(parents=True)
            (repo_b / ".git").mkdir(parents=True)

            brain_dir = tmp_path / "brain"
            base_time = datetime(2026, 10, 10, 12, 0, 0)

            # Create 1 older conversation for repo-alpha and 5 newer conversations for repo-beta
            for idx in range(6):
                is_alpha = idx == 0
                target_repo = repo_a if is_alpha else repo_b
                conv_id = f"conv-{idx}"
                log_dir = brain_dir / conv_id / ".system_generated" / "logs"
                log_dir.mkdir(parents=True)
                dt_str = (base_time + timedelta(hours=idx)).isoformat() + "Z"
                step = {
                    "step_index": 0,
                    "type": "USER_INPUT",
                    "source": "USER_EXPLICIT",
                    "created_at": dt_str,
                    "content": f"<user_information>\nActive Workspaces:\n- {target_repo}\n</user_information>\n<USER_REQUEST>Work on project</USER_REQUEST>",
                }
                (log_dir / "transcript_full.jsonl").write_text(
                    json.dumps(step) + "\n", encoding="utf-8"
                )

            candidate_repos = {
                audit_trajectories.norm_path(str(repo_a)): str(repo_a.resolve()),
                audit_trajectories.norm_path(str(repo_b)): str(repo_b.resolve()),
            }
            convs, _ = audit_trajectories.parse_conversations(
                brain_dirs=[brain_dir],
                candidate_repos=candidate_repos,
                max_conversations=2,
                target_repo="repo-alpha",
            )
            self.assertEqual(len(convs), 1)
            self.assertIn("repo-alpha", convs[0]["repo_path"])

    def test_parallel_run_command_steps_paired_beyond_window_of_three(self):
        """Parallel run_command calls with interleaved steps should still capture exit codes."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain_dir = tmp_path / "brain"
            log_dir = brain_dir / "conv-parallel" / ".system_generated" / "logs"
            log_dir.mkdir(parents=True)

            steps = [
                {
                    "step_index": 0,
                    "type": "USER_INPUT",
                    "source": "USER_EXPLICIT",
                    "created_at": "2026-10-15T10:00:00Z",
                    "content": "<USER_REQUEST>Run parallel checks</USER_REQUEST>",
                },
                {
                    "step_index": 1,
                    "type": "PLANNER_RESPONSE",
                    "content": "",
                    "tool_calls": [
                        {
                            "name": "view_file",
                            "args": {
                                "AbsolutePath": "/tmp/a.txt",
                                "StartLine": 1,
                                "EndLine": 5,
                            },
                        },
                        {
                            "name": "view_file",
                            "args": {
                                "AbsolutePath": "/tmp/b.txt",
                                "StartLine": 1,
                                "EndLine": 5,
                            },
                        },
                        {
                            "name": "view_file",
                            "args": {
                                "AbsolutePath": "/tmp/c.txt",
                                "StartLine": 1,
                                "EndLine": 5,
                            },
                        },
                        {
                            "name": "view_file",
                            "args": {
                                "AbsolutePath": "/tmp/d.txt",
                                "StartLine": 1,
                                "EndLine": 5,
                            },
                        },
                        {
                            "name": "run_command",
                            "args": {"CommandLine": "false_cmd", "Cwd": "/tmp"},
                        },
                    ],
                },
                {
                    "step_index": 2,
                    "type": "EPHEMERAL_MESSAGE",
                    "content": "[ACTIVE SKILLS LOADED: x]",
                },
                {"step_index": 3, "type": "TOOL_RESPONSE", "content": "file a"},
                {"step_index": 4, "type": "TOOL_RESPONSE", "content": "file b"},
                {"step_index": 5, "type": "TOOL_RESPONSE", "content": "file c"},
                {"step_index": 6, "type": "TOOL_RESPONSE", "content": "file d"},
                {
                    "step_index": 7,
                    "type": "TOOL_RESPONSE",
                    "content": "The command exited with code 127.\nOutput:\ncommand not found: false_cmd",
                },
            ]
            (log_dir / "transcript_full.jsonl").write_text(
                "\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8"
            )

            convs, _ = audit_trajectories.parse_conversations(
                brain_dirs=[brain_dir],
                candidate_repos={},
                max_conversations=10,
            )
            self.assertEqual(len(convs), 1)
            cmds = convs[0]["commands"]
            self.assertEqual(len(cmds), 1)
            self.assertEqual(cmds[0]["exit_code"], 127)
            self.assertTrue(cmds[0]["is_failed"])

    def test_inventory_discovers_transcript_full_and_created_at(self):
        """run_inventory should find sessions with only transcript_full.jsonl and use created_at."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain_dir = tmp_path / "brain"
            log_dir = brain_dir / "conv-full-only" / ".system_generated" / "logs"
            log_dir.mkdir(parents=True)
            tpath = log_dir / "transcript_full.jsonl"
            tpath.write_text(
                json.dumps(
                    {
                        "step_index": 0,
                        "created_at": "2026-01-15T08:30:00Z",
                        "type": "USER_INPUT",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            out_dir = tmp_path / "out"
            with (
                mock.patch.object(
                    audit_trajectories, "locate_antigravity_dir", return_value=tmp_path
                ),
                mock.patch.object(
                    audit_trajectories,
                    "locate_brain_directories",
                    return_value=[brain_dir],
                ),
                mock.patch.object(
                    audit_trajectories,
                    "locate_ide_workspace_storage",
                    return_value=None,
                ),
                mock.patch.object(
                    audit_trajectories, "discover_git_repositories", return_value={}
                ),
            ):
                inv_file = audit_trajectories.run_inventory(str(out_dir))
                data = json.loads(inv_file.read_text(encoding="utf-8"))
                self.assertEqual(data["total_conversations"], 1)
                self.assertTrue(data["earliest_session"].startswith("2026-01-15"))

    def test_dead_pooled_z_test_and_hardcoded_uuid_removed(self):
        """is_statistically_significant (prohibited pooled z-test) and hardcoded UUID should not exist."""
        self.assertFalse(hasattr(audit_trajectories, "is_statistically_significant"))
        src = (EFFICIENCY_SCRIPTS / "audit_trajectories.py").read_text(encoding="utf-8")
        self.assertNotIn("9594bcbb-d8fb-4482-bb7d-3e80af28a13e", src)

    def test_discover_git_repositories_scans_home_direct_children(self):
        """discover_git_repositories should find git repositories directly under Path.home()."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_home = Path(tmp)
            direct_repo = tmp_home / "my-home-repo"
            (direct_repo / ".git").mkdir(parents=True)
            with (
                mock.patch.object(Path, "home", return_value=tmp_home),
                mock.patch("os.getcwd", return_value=str(tmp_home)),
            ):
                repos = audit_trajectories.discover_git_repositories([], tmp_home)
                repo_names = [Path(p).name for p in repos.values()]
                self.assertIn("my-home-repo", repo_names)

    def test_mixed_case_active_workspace_is_extracted(self):
        """parse_conversations should extract workspace paths from mixed-case 'Active Workspace is' lines."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo_dir = tmp_path / "MixedCaseRepo"
            (repo_dir / ".git").mkdir(parents=True)

            brain_dir = tmp_path / "brain"
            c_dir = brain_dir / "conv-mixed" / ".system_generated" / "logs"
            c_dir.mkdir(parents=True)
            step = {
                "type": "USER_INPUT",
                "source": "USER_EXPLICIT",
                "created_at": "2026-04-01T10:00:00Z",
                "content": f"<user_information>\nThe USER's Active Workspace is {repo_dir}.\n</user_information>",
            }
            (c_dir / "transcript.jsonl").write_text(
                json.dumps(step) + "\n", encoding="utf-8"
            )

            norm_repo = audit_trajectories.norm_path(str(repo_dir))
            candidate_repos = {norm_repo: str(repo_dir)}

            convs, _ = audit_trajectories.parse_conversations(
                [brain_dir], candidate_repos, max_conversations=10
            )
            self.assertEqual(len(convs), 1)
            self.assertEqual(convs[0]["repo_path"], str(repo_dir))

    def test_compare_mode_caps_each_cohort_at_max_conversations(self):
        """In compare_mode, parse_conversations should cap target and baseline cohorts separately at max_conversations."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain_dir = tmp_path / "brain"

            # Create 3 target sessions (>= 2026-04-10) and 3 baseline sessions (< 2026-04-10)
            sessions = [
                ("target-1", "2026-04-12T10:00:00Z"),
                ("target-2", "2026-04-11T10:00:00Z"),
                ("target-3", "2026-04-10T12:00:00Z"),
                ("base-1", "2026-04-09T10:00:00Z"),
                ("base-2", "2026-04-08T10:00:00Z"),
                ("base-3", "2026-04-07T10:00:00Z"),
            ]
            for cid, ts in sessions:
                c_dir = brain_dir / cid / ".system_generated" / "logs"
                c_dir.mkdir(parents=True)
                step = {
                    "type": "USER_INPUT",
                    "source": "USER_EXPLICIT",
                    "created_at": ts,
                    "content": "hello",
                }
                (c_dir / "transcript.jsonl").write_text(
                    json.dumps(step) + "\n", encoding="utf-8"
                )

            since_dt = datetime(2026, 4, 10)
            convs, _ = audit_trajectories.parse_conversations(
                [brain_dir],
                {},
                max_conversations=2,
                since_dt=since_dt,
                compare_mode=True,
            )
            target_parsed = [c for c in convs if c["dt"] >= since_dt]
            base_parsed = [c for c in convs if c["dt"] < since_dt]
            self.assertEqual(len(target_parsed), 2)
            self.assertEqual(len(base_parsed), 2)

    def test_auto_exclude_audit_requires_action_evidence(self):
        """auto_exclude_audit should only exclude sessions with executed audit commands or explicit skill triggers, not mere text mentions."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain_dir = tmp_path / "brain"

            # Session A: Mentions audit_trajectories.py in prompt and tool response (e.g. code review/view_file), but does not execute audit command
            dir_a = brain_dir / "conv-mention-only" / ".system_generated" / "logs"
            dir_a.mkdir(parents=True)
            steps_a = [
                {
                    "step_index": 0,
                    "type": "USER_INPUT",
                    "source": "USER_EXPLICIT",
                    "created_at": "2026-04-12T10:00:00Z",
                    "content": "Can you review scripts/audit_trajectories.py for me?",
                },
                {
                    "step_index": 1,
                    "type": "PLANNER_RESPONSE",
                    "created_at": "2026-04-12T10:00:05Z",
                    "content": "Sure, viewing audit_trajectories.py",
                    "tool_calls": [
                        {
                            "name": "view_file",
                            "args": {"AbsolutePath": "/path/to/audit_trajectories.py"},
                        }
                    ],
                },
                {
                    "step_index": 2,
                    "type": "TOOL_RESPONSE",
                    "content": "def run_audit():\n    trajectory_audit_summary = {}",
                },
            ]
            (dir_a / "transcript.jsonl").write_text(
                "\n".join(json.dumps(s) for s in steps_a) + "\n", encoding="utf-8"
            )

            # Session B: Executes audit_trajectories.py via run_command
            dir_b = brain_dir / "conv-audit-action" / ".system_generated" / "logs"
            dir_b.mkdir(parents=True)
            steps_b = [
                {
                    "step_index": 0,
                    "type": "USER_INPUT",
                    "source": "USER_EXPLICIT",
                    "created_at": "2026-04-12T10:05:00Z",
                    "content": "Please run the audit",
                },
                {
                    "step_index": 1,
                    "type": "PLANNER_RESPONSE",
                    "created_at": "2026-04-12T10:05:05Z",
                    "content": "Running trajectory audit...",
                    "tool_calls": [
                        {
                            "name": "run_command",
                            "args": {
                                "CommandLine": "python3 skills/improve-agent-efficiency/scripts/audit_trajectories.py"
                            },
                        }
                    ],
                },
            ]
            (dir_b / "transcript.jsonl").write_text(
                "\n".join(json.dumps(s) for s in steps_b) + "\n", encoding="utf-8"
            )

            convs, _ = audit_trajectories.parse_conversations(
                [brain_dir],
                {},
                max_conversations=10,
                auto_exclude_audit=True,
            )
            # Session A is preserved (not an audit session); Session B is excluded
            parsed_ids = [c["id"] for c in convs]
            self.assertIn("conv-mention-only", parsed_ids)
            self.assertNotIn("conv-audit-action", parsed_ids)

    def test_comparative_bootstrap_api_context_excludes_model_output(self):
        """In comparative mode, the api_context bootstrap test should resample fresh input + cache read, excluding output tokens."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain_dir = tmp_path / "brain"
            out_dir = tmp_path / "out"
            out_dir.mkdir()

            # Create 15 target sessions (>= 2026-04-10) and 15 baseline sessions (< 2026-04-10)
            # to satisfy min_samples=15 and exercise full bootstrap resampling
            for k in range(15):
                dir_t = brain_dir / f"conv-target-{k}" / ".system_generated" / "logs"
                dir_t.mkdir(parents=True)
                steps_t = [
                    {
                        "step_index": 0,
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": f"2026-04-12T10:{k:02d}:00Z",
                        "content": "Hello",
                    },
                    {
                        "step_index": 1,
                        "type": "PLANNER_RESPONSE",
                        "created_at": f"2026-04-12T10:{k:02d}:05Z",
                        "content": "Done",
                        "input_tokens": 100,
                        "cache_read_tokens": 200,
                        "output_tokens": 50,
                    },
                ]
                (dir_t / "transcript.jsonl").write_text(
                    "\n".join(json.dumps(s) for s in steps_t) + "\n", encoding="utf-8"
                )

                dir_b = brain_dir / f"conv-baseline-{k}" / ".system_generated" / "logs"
                dir_b.mkdir(parents=True)
                steps_b = [
                    {
                        "step_index": 0,
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": f"2026-04-08T10:{k:02d}:00Z",
                        "content": "Hello",
                    },
                    {
                        "step_index": 1,
                        "type": "PLANNER_RESPONSE",
                        "created_at": f"2026-04-08T10:{k:02d}:05Z",
                        "content": "Done",
                        "input_tokens": 300,
                        "cache_read_tokens": 400,
                        "output_tokens": 70,
                    },
                ]
                (dir_b / "transcript.jsonl").write_text(
                    "\n".join(json.dumps(s) for s in steps_b) + "\n", encoding="utf-8"
                )

            captured_calls = []
            orig_bootstrap = audit_trajectories.bootstrap_conversation_diff

            def tracking_bootstrap(t_arr, b_arr, **kwargs):
                captured_calls.append((t_arr, b_arr, kwargs.get("stat_fn")))
                return orig_bootstrap(t_arr, b_arr, **kwargs)

            with (
                mock.patch.object(
                    audit_trajectories,
                    "locate_brain_directories",
                    return_value=[brain_dir],
                ),
                mock.patch.object(
                    audit_trajectories, "discover_git_repositories", return_value={}
                ),
                mock.patch.object(
                    audit_trajectories,
                    "bootstrap_conversation_diff",
                    side_effect=tracking_bootstrap,
                ),
                mock.patch("sys.stdout", io.StringIO()),
            ):
                out_file = audit_trajectories.run_audit(
                    output_dir=str(out_dir),
                    since_date="2026-04-10",
                    compare_mode=True,
                )
                payload = json.loads(Path(out_file).read_text(encoding="utf-8"))
                boot_tests = payload["comparison"]["bootstrap_significance_tests"]
                self.assertIn("api_context", boot_tests)

                # Check captured bootstrap call for api_context:
                # Should resample t_api_context = [100 + 200 = 300] * 15 and b_api_context = [300 + 400 = 700] * 15
                # NOT [350] or [770] which include model output
                matching_calls = [
                    (t, b)
                    for t, b, fn in captured_calls
                    if t == [300] * 15 and b == [700] * 15
                ]
                self.assertEqual(len(matching_calls), 1)

                # Resampling was performed and yielded a significant result
                self.assertTrue(boot_tests["api_context"]["significant"])
                self.assertEqual(boot_tests["api_context"]["p_value"], 0.0)

    def test_auto_exclude_audit_detects_actions_after_line_25_and_arguments_key(self):
        """auto_exclude_audit should detect audit actions after line 25 and handle tool_calls using 'arguments'."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain_dir = tmp_path / "brain"

            # Session 1: 30 normal conversation steps, then step 31 executes audit_trajectories.py
            dir_1 = brain_dir / "conv-late-audit" / ".system_generated" / "logs"
            dir_1.mkdir(parents=True)
            steps_1 = [
                {
                    "step_index": idx,
                    "type": "USER_INPUT" if idx % 2 == 0 else "PLANNER_RESPONSE",
                    "source": "USER_EXPLICIT" if idx % 2 == 0 else "MODEL",
                    "created_at": f"2026-04-12T10:{idx:02d}:00Z",
                    "content": f"Step {idx}",
                }
                for idx in range(30)
            ]
            steps_1.append(
                {
                    "step_index": 30,
                    "type": "PLANNER_RESPONSE",
                    "created_at": "2026-04-12T10:30:05Z",
                    "content": "Running audit now...",
                    "tool_calls": [
                        {
                            "name": "run_command",
                            "arguments": {
                                "CommandLine": "python3 skills/improve-agent-efficiency/scripts/audit_trajectories.py"
                            },
                        }
                    ],
                }
            )
            (dir_1 / "transcript.jsonl").write_text(
                "\n".join(json.dumps(s) for s in steps_1) + "\n", encoding="utf-8"
            )

            convs, _ = audit_trajectories.parse_conversations(
                [brain_dir],
                {},
                max_conversations=10,
                auto_exclude_audit=True,
            )
            self.assertEqual(len(convs), 0)

    def test_active_workspaces_takes_precedence_over_command_working_directory(self):
        """Workspace entries under 'Active Workspaces:' should take precedence over 'Command Working Directory:'."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ws_dir = tmp_path / "primary-workspace"
            cwd_dir = tmp_path / "scratch-cwd"
            (ws_dir / ".git").mkdir(parents=True)
            (cwd_dir / ".git").mkdir(parents=True)

            brain_dir = tmp_path / "brain"
            c_dir = brain_dir / "conv-order-test" / ".system_generated" / "logs"
            c_dir.mkdir(parents=True)
            content = (
                "<user_information>\n"
                "The USER's OS version is mac.\n"
                f"Command Working Directory: {cwd_dir}\n"
                "Active Workspaces:\n"
                f"- {ws_dir}\n"
                "</user_information>\n"
            )
            step = {
                "type": "USER_INPUT",
                "source": "USER_EXPLICIT",
                "created_at": "2026-04-01T10:00:00Z",
                "content": content,
            }
            (c_dir / "transcript.jsonl").write_text(
                json.dumps(step) + "\n", encoding="utf-8"
            )

            norm_ws = audit_trajectories.norm_path(str(ws_dir))
            norm_cwd = audit_trajectories.norm_path(str(cwd_dir))
            candidate_repos = {norm_ws: str(ws_dir), norm_cwd: str(cwd_dir)}

            convs, _ = audit_trajectories.parse_conversations(
                [brain_dir], candidate_repos, max_conversations=10
            )
            self.assertEqual(len(convs), 1)
            self.assertEqual(convs[0]["repo_path"], str(ws_dir))

    def test_command_working_directory_attributed_when_active_workspaces_empty(self):
        """When 'Active Workspaces:' is present but empty, 'Command Working Directory:' should be attributed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cwd_dir = tmp_path / "scratch-cwd"
            (cwd_dir / ".git").mkdir(parents=True)

            brain_dir = tmp_path / "brain"
            c_dir = brain_dir / "conv-empty-ws-test" / ".system_generated" / "logs"
            c_dir.mkdir(parents=True)
            content = (
                "<user_information>\n"
                "The USER's OS version is mac.\n"
                "Active Workspaces:\n"
                f"Command Working Directory: {cwd_dir}\n"
                "</user_information>\n"
            )
            step = {
                "type": "USER_INPUT",
                "source": "USER_EXPLICIT",
                "created_at": "2026-04-01T10:00:00Z",
                "content": content,
            }
            (c_dir / "transcript.jsonl").write_text(
                json.dumps(step) + "\n", encoding="utf-8"
            )

            norm_cwd = audit_trajectories.norm_path(str(cwd_dir))
            candidate_repos = {norm_cwd: str(cwd_dir)}

            convs, _ = audit_trajectories.parse_conversations(
                [brain_dir], candidate_repos, max_conversations=10
            )
            self.assertEqual(len(convs), 1)
            self.assertEqual(convs[0]["repo_path"], str(cwd_dir))


class TestProbeEnvironment(unittest.TestCase):
    def test_probe_python_environment_does_not_pollute_stdout(self):
        """probe_python_environment should test encoding without writing garbage to stdout."""
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            info = probe_environment.probe_python_environment()
        self.assertEqual(buf.getvalue(), "")
        self.assertTrue(info["stdout_test_passed"])

    def test_probe_host_binaries_includes_modern_antigravity_tools(self):
        """probe_host_binaries should probe python3, uv, fd, jq, and agy."""
        bins = probe_environment.probe_host_binaries()
        for tool in ("python3", "uv", "fd", "jq", "agy"):
            self.assertIn(tool, bins, f"Expected {tool} in probed binaries")

    def test_probe_rule_budget_discrepancies(self):
        """probe_global_configuration_discrepancies should flag rule files exceeding 24,000 bytes."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_home = Path(tmp)
            cfg_dir = tmp_home / ".gemini" / "config"
            cfg_dir.mkdir(parents=True)
            oversized_gemini = cfg_dir / "GEMINI.md"
            oversized_gemini.write_text("x" * 25000, encoding="utf-8")

            with mock.patch.object(Path, "home", return_value=tmp_home):
                res = probe_environment.probe_global_configuration_discrepancies({})
                types = [d["type"] for d in res["discrepancies"]]
                self.assertIn("rule_file_over_24kb_cap", types)

    def test_probe_discovers_root_gemini_and_rules_without_config_gemini(self):
        """probe_global_configuration_discrepancies should audit ~/.gemini/GEMINI.md and rules/*.md even if ~/.gemini/config/GEMINI.md is absent."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_home = Path(tmp)
            with mock.patch.object(Path, "home", return_value=tmp_home):
                empty_res = probe_environment.probe_global_configuration_discrepancies(
                    {}
                )
                self.assertFalse(empty_res["config_found"])
                self.assertEqual(empty_res["total_rule_bytes"], 0)
                self.assertEqual(empty_res["estimated_rule_tokens"], 0)

            gemini_dir = tmp_home / ".gemini"
            rules_dir = gemini_dir / "config" / "rules"
            rules_dir.mkdir(parents=True)
            custom_rule = rules_dir / "custom.md"
            custom_rule.write_text("b" * 400, encoding="utf-8")

            with mock.patch.object(Path, "home", return_value=tmp_home):
                res_rules_only = (
                    probe_environment.probe_global_configuration_discrepancies({})
                )
                self.assertTrue(res_rules_only["config_found"])
                self.assertEqual(res_rules_only["config_path"], str(custom_rule))

            (gemini_dir / "GEMINI.md").write_text("a" * 400, encoding="utf-8")
            with mock.patch.object(Path, "home", return_value=tmp_home):
                res = probe_environment.probe_global_configuration_discrepancies({})
                self.assertTrue(res["config_found"])
                self.assertEqual(res["total_rule_bytes"], 800)

    def test_run_probe_creates_missing_output_dir(self):
        """run_probe should create missing parent directories for output_dir."""
        with tempfile.TemporaryDirectory() as tmp:
            nested_out = Path(tmp) / "nested" / "dir" / "out"
            with mock.patch("sys.stdout", io.StringIO()):
                probe_environment.run_probe(str(nested_out))
            self.assertTrue((nested_out / "host_environment_probe.json").exists())


class TestRepoSafetyAndPackaging(unittest.TestCase):
    def test_plugin_and_skills_json_exist_and_valid(self):
        """Repository should include valid plugin.json and .agents/skills.json."""
        plugin_json = REPO_ROOT / "plugin.json"
        skills_json = REPO_ROOT / ".agents" / "skills.json"
        self.assertTrue(plugin_json.exists(), "plugin.json must exist at repo root")
        self.assertTrue(skills_json.exists(), ".agents/skills.json must exist")

        pdata = json.loads(plugin_json.read_text(encoding="utf-8"))
        self.assertIn("name", pdata)

        sdata = json.loads(skills_json.read_text(encoding="utf-8"))
        self.assertIn("entries", sdata)

    def test_check_manifest_integrity_validates_skills_frontmatter(self):
        """check_manifest_integrity should detect missing or invalid YAML frontmatter and plugin.json names."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_repo = Path(tmp)
            bad_skill = tmp_repo / "skills" / "bad-skill"
            bad_skill.mkdir(parents=True)
            (bad_skill / "SKILL.md").write_text("# No Frontmatter\n", encoding="utf-8")

            violations = check_repo_safety.check_manifest_integrity(tmp_repo)
            self.assertTrue(any("SKILL.md" in v for v in violations))

            # Invalid YAML syntax or non-string fields should be rejected
            (bad_skill / "SKILL.md").write_text(
                "---\nname: [1, 2]\ndescription: true\n---\n# Bad Types\n",
                encoding="utf-8",
            )
            violations2 = check_repo_safety.check_manifest_integrity(tmp_repo)
            self.assertTrue(any("Frontmatter 'name'" in v for v in violations2))
            self.assertTrue(any("Frontmatter 'description'" in v for v in violations2))

            # Invalid YAML escape sequences in quoted strings (e.g., "\q") should be rejected
            (bad_skill / "SKILL.md").write_text(
                '---\nname: bad-skill\ndescription: "\\q"\n---\n# Invalid Escape\n',
                encoding="utf-8",
            )
            violations_esc = check_repo_safety.check_manifest_integrity(tmp_repo)
            self.assertTrue(
                any("Invalid YAML frontmatter" in v for v in violations_esc)
            )

            # Duplicate YAML keys should be rejected
            (bad_skill / "SKILL.md").write_text(
                "---\nname: bad-skill\nname: bad-skill\ndescription: duplicate key\n---\n# Duplicate\n",
                encoding="utf-8",
            )
            violations_dup = check_repo_safety.check_manifest_integrity(tmp_repo)
            self.assertTrue(
                any("Invalid YAML frontmatter" in v for v in violations_dup)
            )

            # Unhashable YAML keys (e.g. list/mapping as key) should be rejected cleanly
            (bad_skill / "SKILL.md").write_text(
                "---\n? [unhashable, key]\n: value\nname: bad-skill\ndescription: unhashable key\n---\n# Unhashable\n",
                encoding="utf-8",
            )
            violations_unhashable = check_repo_safety.check_manifest_integrity(tmp_repo)
            self.assertTrue(
                any("Invalid YAML frontmatter" in v for v in violations_unhashable)
            )

            # Valid block scalar frontmatter should pass
            (bad_skill / "SKILL.md").write_text(
                "---\nname: bad-skill\ndescription: >-\n  Multi-line valid description.\n---\n# Valid\n",
                encoding="utf-8",
            )
            violations3 = check_repo_safety.check_manifest_integrity(tmp_repo)
            self.assertEqual(violations3, [])

            # Invalid plugin.json name characters should be rejected
            (tmp_repo / "plugin.json").write_text(
                json.dumps({"name": "invalid name with spaces!"}), encoding="utf-8"
            )
            violations4 = check_repo_safety.check_manifest_integrity(tmp_repo)
            self.assertTrue(any("plugin.json" in v for v in violations4))

    def test_check_repo_safety_copies_are_byte_identical(self):
        """Root scripts/check_repo_safety.py and packaged skills/public-repo-safety/scripts/check_repo_safety.py must be identical."""
        root_copy = (REPO_ROOT / "scripts" / "check_repo_safety.py").read_bytes()
        skill_copy = (
            REPO_ROOT
            / "skills"
            / "public-repo-safety"
            / "scripts"
            / "check_repo_safety.py"
        ).read_bytes()
        self.assertEqual(root_copy, skill_copy)


class TestAuditScopingAndAttribution(unittest.TestCase):
    """--conv / --baseline-since scoping, per-turn API normalization, heredoc and model attribution."""

    def _write_conv(self, brain, cid, ts, extra_steps=(), model_to=None, api=None):
        log_dir = brain / cid / ".system_generated" / "logs"
        log_dir.mkdir(parents=True)
        content = "<USER_REQUEST>do work</USER_REQUEST>"
        if model_to:
            content += (
                "<USER_SETTINGS_CHANGE>The user changed setting `Model Selection` "
                f"from None to {model_to}. No need to comment.</USER_SETTINGS_CHANGE>"
            )
        steps = [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "source": "USER_EXPLICIT",
                "created_at": ts,
                "content": content,
            }
        ]
        if api:
            steps.append(
                {
                    "step_index": 1,
                    "type": "PLANNER_RESPONSE",
                    "content": "ok",
                    "input_tokens": api[0],
                    "cache_read_tokens": api[1],
                    "output_tokens": api[2],
                }
            )
        steps += list(extra_steps)
        (log_dir / "transcript_full.jsonl").write_text(
            "\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8"
        )

    def _run(self, tmp_path, brain, **kwargs):
        out_dir = tmp_path / "out"
        with (
            mock.patch.object(
                audit_trajectories, "locate_antigravity_dir", return_value=tmp_path
            ),
            mock.patch.object(
                audit_trajectories, "locate_brain_directories", return_value=[brain]
            ),
            mock.patch.object(
                audit_trajectories, "locate_ide_workspace_storage", return_value=None
            ),
            mock.patch.object(
                audit_trajectories, "discover_git_repositories", return_value={}
            ),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            out = audit_trajectories.run_audit(
                output_dir=str(out_dir), max_conversations=None, **kwargs
            )
        return json.loads(Path(out).read_text(encoding="utf-8"))

    def test_heredoc_is_counted_separately_from_inline_py_c(self):
        """A python heredoc whose body mentions 'python3 -c' is a heredoc, not an inline script."""
        heredoc = (
            "python3 - <<'PY'\nlabel = 'Inline python3 -c / 100 cmds'\nprint(label)\nPY"
        )
        steps = [
            {
                "step_index": 2,
                "type": "PLANNER_RESPONSE",
                "content": "",
                "tool_calls": [
                    {
                        "name": "run_command",
                        "args": {"CommandLine": heredoc, "Cwd": "/tmp"},
                    }
                ],
            },
            {
                "step_index": 3,
                "type": "TOOL_RESPONSE",
                "content": "Command exited with code 0.\nOutput:\nInline",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            self._write_conv(brain, "conv-h", "2026-10-15T10:00:00Z", steps)
            data = self._run(tmp_path, brain)
            self.assertEqual(data["py_c_multiline"]["total"], 0)
            self.assertEqual(data["py_c_oneline"]["total"], 0)
            self.assertEqual(data["heredoc_python"]["total"], 1)

    def test_conv_filter_reports_each_requested_conversation(self):
        """include_conv keeps only the named sessions (audit sessions included) and reports each one."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            self._write_conv(brain, "conv-a", "2026-10-15T10:00:00Z", api=(10, 90, 5))
            self._write_conv(brain, "conv-b", "2026-10-16T10:00:00Z", api=(20, 80, 5))
            self._write_conv(brain, "conv-c", "2026-10-17T10:00:00Z", api=(30, 70, 5))
            data = self._run(tmp_path, brain, include_conv="conv-a,conv-c")
            self.assertEqual(data["conversations"], 2)
            self.assertEqual(
                sorted(data["per_conversation"].keys()), ["conv-a", "conv-c"]
            )
            self.assertEqual(data["per_conversation"]["conv-c"]["conversations"], 1)

    def test_api_ground_truth_is_normalized_per_user_turn(self):
        """Context, fresh input and output are also reported per user turn (pooled)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            self._write_conv(
                brain,
                "conv-a",
                "2026-10-15T10:00:00Z",
                api=(100, 900, 50),
                extra_steps=[
                    {
                        "step_index": 2,
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-10-15T10:05:00Z",
                        "content": "follow-up request",
                    },
                    {
                        "step_index": 3,
                        "type": "PLANNER_RESPONSE",
                        "content": "ok",
                        "input_tokens": 300,
                        "cache_read_tokens": 700,
                        "output_tokens": 150,
                    },
                ],
            )
            data = self._run(tmp_path, brain)
            api = data["api_tokens_ground_truth"]
            self.assertEqual(data["user_turns"], 2)
            self.assertEqual(api["context_per_turn"], 1000)
            self.assertEqual(api["fresh_input_per_turn"], 200)
            self.assertEqual(api["output_per_turn"], 100)
            self.assertNotEqual(
                api["context_per_turn"], api["total_api_context_processed"]
            )
            self.assertNotEqual(api["fresh_input_per_turn"], api["input_tokens_fresh"])
            self.assertNotEqual(api["output_per_turn"], api["output_tokens_model"])

    def test_baseline_since_bounds_the_baseline_cohort(self):
        """--baseline-since drops baseline sessions older than the given date."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            for cid, ts in [
                ("old", "2026-09-01T10:00:00Z"),
                ("recent", "2026-10-20T10:00:00Z"),
                ("target", "2026-10-26T10:00:00Z"),
            ]:
                self._write_conv(brain, cid, ts)
            data = self._run(
                tmp_path,
                brain,
                since_date="2026-10-25",
                baseline_since_date="2026-10-11",
                compare_mode=True,
            )
            self.assertEqual(data["comparison"]["baseline_window"]["conversations"], 1)
            self.assertEqual(data["comparison"]["target_window"]["conversations"], 1)
            self.assertTrue(data["baseline_since_filter"].startswith("2026-10-11"))

    def test_model_selection_is_parsed_and_carried_forward(self):
        """The model persists across sessions until the next explicit switch."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            self._write_conv(
                brain,
                "conv-1",
                "2026-10-15T10:00:00Z",
                model_to="Claude Opus 5.5 (Medium)",
            )
            self._write_conv(brain, "conv-2", "2026-10-16T10:00:00Z")
            self._write_conv(
                brain,
                "conv-3",
                "2026-10-17T10:00:00Z",
                model_to="Gemini 4 Argon (Medium)",
            )
            data = self._run(tmp_path, brain, include_conv="conv-1,conv-2,conv-3")
            per = data["per_conversation"]
            self.assertEqual(
                per["conv-2"]["model_mix"], {"Claude Opus 5.5 (Medium)": 1}
            )
            self.assertEqual(per["conv-3"]["model_mix"], {"Gemini 4 Argon (Medium)": 1})
            self.assertEqual(data["model_mix"]["Claude Opus 5.5 (Medium)"], 2)

    def test_cli_exposes_new_scoping_flags(self):
        import subprocess

        r = subprocess.run(
            [
                sys.executable,
                str(EFFICIENCY_SCRIPTS / "audit_trajectories.py"),
                "--help",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertIn("--conv", r.stdout)
        self.assertIn("--baseline-since", r.stdout)

    def test_heredoc_tab_indented_body_is_stripped(self):
        """A tab-indented <<- heredoc containing 'python3 -c' in body is counted as heredoc, not inline."""
        heredoc = "python3 - <<-PY\n\tline = 'python3 -c inline'\n\tprint(line)\n\tPY"
        extra = [
            {
                "step_index": 2,
                "type": "PLANNER_RESPONSE",
                "content": "",
                "tool_calls": [
                    {
                        "name": "run_command",
                        "args": {"CommandLine": heredoc, "Cwd": "/tmp"},
                    }
                ],
            },
            {
                "step_index": 3,
                "type": "TOOL_RESPONSE",
                "content": "Command exited with code 0.\nOutput:\nInline",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            self._write_conv(
                brain, "conv-tab-h", "2026-10-15T10:00:00Z", extra_steps=extra
            )
            data = self._run(tmp_path, brain)
            self.assertEqual(data["py_c_multiline"]["total"], 0)
            self.assertEqual(data["py_c_oneline"]["total"], 0)
            self.assertEqual(data["heredoc_python"]["total"], 1)

    def test_positional_arguments_compatibility(self):
        """Calling parse_conversations and run_audit positionally preserves existing argument mapping."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            self._write_conv(brain, "conv-pos", "2026-10-15T10:00:00Z")
            convs, total = audit_trajectories.parse_conversations(
                [brain],
                {},
                None,
                None,
                None,
                None,
                None,
                None,
                True,  # auto_exclude_audit
                False,  # compare_mode
            )
            self.assertEqual(len(convs), 1)
            self.assertEqual(total, 1)

            out_dir = tmp_path / "out"
            with (
                mock.patch.object(
                    audit_trajectories, "locate_antigravity_dir", return_value=tmp_path
                ),
                mock.patch.object(
                    audit_trajectories, "locate_brain_directories", return_value=[brain]
                ),
                mock.patch.object(
                    audit_trajectories,
                    "locate_ide_workspace_storage",
                    return_value=None,
                ),
                mock.patch.object(
                    audit_trajectories, "discover_git_repositories", return_value={}
                ),
                mock.patch("sys.stdout", new_callable=io.StringIO),
            ):
                out = audit_trajectories.run_audit(
                    str(out_dir),
                    100,
                    None,
                    None,
                    None,
                    None,
                    None,
                    True,  # auto_exclude_audit
                    False,  # compare_mode
                    False,  # print_summary
                )
                data = json.loads(Path(out).read_text(encoding="utf-8"))
                self.assertEqual(data["conversations"], 1)

    def test_conv_filter_preserves_unselected_model_history(self):
        """A conversation selected by --conv inherits model set by an unselected previous conversation."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            self._write_conv(
                brain,
                "conv-1",
                "2026-10-15T10:00:00Z",
                model_to="Claude Opus 5.5 (Medium)",
            )
            self._write_conv(brain, "conv-2", "2026-10-16T10:00:00Z")
            data = self._run(tmp_path, brain, include_conv="conv-2")
            self.assertEqual(data["conversations"], 1)
            self.assertEqual(
                data["per_conversation"]["conv-2"]["model_mix"],
                {"Claude Opus 5.5 (Medium)": 1},
            )
            self.assertEqual(data["model_mix"]["Claude Opus 5.5 (Medium)"], 1)

    def test_model_changes_applied_at_event_times(self):
        """Conversations starting before a mid-session model switch do not inherit that model."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            extra_conv1 = [
                {
                    "step_index": 1,
                    "type": "USER_INPUT",
                    "source": "USER_EXPLICIT",
                    "created_at": "2026-10-15T12:00:00Z",
                    "content": "<USER_SETTINGS_CHANGE>\nThe user changed setting `Model Selection` from None to Claude Opus 5.5 (Medium).\n</USER_SETTINGS_CHANGE>",
                },
            ]
            self._write_conv(
                brain, "conv-1", "2026-10-15T10:00:00Z", extra_steps=extra_conv1
            )
            self._write_conv(brain, "conv-2", "2026-10-15T11:00:00Z")
            self._write_conv(brain, "conv-3", "2026-10-15T13:00:00Z")

            data = self._run(tmp_path, brain, include_conv="conv-1,conv-2,conv-3")
            per = data["per_conversation"]
            self.assertEqual(
                per["conv-1"]["model_mix"], {"Claude Opus 5.5 (Medium)": 1}
            )
            self.assertEqual(per["conv-2"]["model_mix"], {"unknown": 1})
            self.assertEqual(
                per["conv-3"]["model_mix"], {"Claude Opus 5.5 (Medium)": 1}
            )

    def test_empty_conv_selection_raises_value_error(self):
        """Passing an empty string or whitespace/commas to include_conv raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            self._write_conv(brain, "conv-1", "2026-10-15T10:00:00Z")
            with self.assertRaises(ValueError):
                self._run(tmp_path, brain, include_conv="")
            with self.assertRaises(ValueError):
                self._run(tmp_path, brain, include_conv=" , ")


class TestAuditHardeningAndParity(unittest.TestCase):
    def _write_steps(self, brain_dir, conv_id, steps):
        log_dir = brain_dir / conv_id / ".system_generated" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "transcript_full.jsonl", "w", encoding="utf-8") as f:
            for step in steps:
                f.write(json.dumps(step) + "\n")

    def _run_with_brain(self, tmp_path, brain_dir, config_dir=None, **kwargs):
        out_dir = tmp_path / "out"
        with (
            mock.patch.object(
                audit_trajectories, "locate_antigravity_dir", return_value=tmp_path
            ),
            mock.patch.object(
                audit_trajectories,
                "locate_brain_directories",
                return_value=[brain_dir],
            ),
            mock.patch.object(
                audit_trajectories,
                "locate_ide_workspace_storage",
                return_value=None,
            ),
            mock.patch.object(
                audit_trajectories,
                "discover_git_repositories",
                return_value={},
            ),
        ):
            out_file = audit_trajectories.run_audit(
                output_dir=str(out_dir),
                config_dir=config_dir,
                **kwargs,
            )
        return json.loads(Path(out_file).read_text(encoding="utf-8"))

    def test_interactive_vs_subagent_separation_and_total_cost(self):
        """Interactive sessions stay cleanly separated from user_turns==0 subagents while preserving total API spend."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"

            # 1 interactive session (2 user turns, 1,000 total API tokens)
            self._write_steps(
                brain,
                "interactive-1",
                [
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-10T10:00:00Z",
                        "content": "<USER_REQUEST>Build feature</USER_REQUEST>",
                    },
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-10T10:00:05Z",
                        "content": "Done step 1",
                        "input_tokens": 200,
                        "cache_read_tokens": 700,
                        "output_tokens": 100,
                    },
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-10T10:01:00Z",
                        "content": "<USER_REQUEST>Follow up</USER_REQUEST>",
                    },
                ],
            )
            # 3 subagent/headless sessions (0 user turns, 500 total API tokens each = 1,500)
            for idx in range(1, 4):
                self._write_steps(
                    brain,
                    f"subagent-{idx}",
                    [
                        {
                            "type": "SYSTEM_MESSAGE",
                            "source": "SYSTEM_SDK",
                            "created_at": f"2026-11-10T10:0{idx}:00Z",
                            "content": "Subagent task prompt",
                        },
                        {
                            "type": "PLANNER_RESPONSE",
                            "source": "MODEL",
                            "created_at": f"2026-11-10T10:0{idx}:05Z",
                            "content": "Subagent reply",
                            "input_tokens": 100,
                            "cache_read_tokens": 350,
                            "output_tokens": 50,
                        },
                    ],
                )

            data = self._run_with_brain(tmp_path, brain, config_dir=tmp_path / "nocfg")
            self.assertEqual(data["conversations"], 1)
            self.assertEqual(data["interactive_conversations"], 1)
            self.assertEqual(data["subagent_or_headless_conversations"], 3)
            self.assertGreaterEqual(data["median_turns_per_conv"], 1.0)
            self.assertEqual(data["median_turns_per_conv"], 2.0)
            self.assertEqual(
                data["api_tokens_ground_truth"]["total_api_tokens_all"], 1000
            )
            self.assertEqual(data["subagent_summary"]["conversations"], 3)
            self.assertEqual(
                data["subagent_summary"]["api_tokens_ground_truth"][
                    "total_api_tokens_all"
                ],
                1500,
            )
            self.assertEqual(data["total_api_tokens_including_subagents"], 2500)

            # With --include-subagents, all 4 conversations are merged into primary cohort
            merged = self._run_with_brain(
                tmp_path,
                brain,
                config_dir=tmp_path / "nocfg",
                include_subagents=True,
            )
            self.assertEqual(merged["conversations"], 4)
            self.assertEqual(merged["median_turns_per_conv"], 0.0)
            self.assertEqual(
                merged["api_tokens_ground_truth"]["total_api_tokens_all"], 2500
            )

    def test_antigravity_2_0_tool_parity(self):
        """Antigravity 2.0 tools (read_file/write_file/edit_file) produce identical metrics to legacy tools."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain_legacy = tmp_path / "brain_legacy"
            brain_v2 = tmp_path / "brain_v2"
            target_path = "/workspace/demo/app.py"

            def _make_steps(read_tool, write_tool, edit_tool, path_key):
                return [
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-10T10:00:00Z",
                        "content": "<USER_REQUEST>Refactor app.py</USER_REQUEST>",
                    },
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-10T10:00:01Z",
                        "content": "Reading",
                        "tool_calls": [
                            {
                                "name": read_tool,
                                "args": {
                                    path_key: target_path,
                                    "StartLine": 1,
                                    "EndLine": 10,
                                },
                            },
                            {
                                "name": read_tool,
                                "args": {
                                    path_key: target_path,
                                    "StartLine": 6,
                                    "EndLine": 15,
                                },
                            },
                            {
                                "name": read_tool,
                                "args": {path_key: "/workspace/demo/other.py"},
                            },
                        ],
                    },
                    {"type": "GENERIC", "source": "MODEL", "content": "x" * 100},
                    {"type": "GENERIC", "source": "MODEL", "content": "y" * 100},
                    {"type": "GENERIC", "source": "MODEL", "content": "z" * 200},
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-10T10:00:05Z",
                        "content": "Editing and writing",
                        "tool_calls": [
                            {
                                "name": edit_tool,
                                "args": {path_key: target_path, "Replacement": "ok"},
                            },
                            {
                                "name": write_tool,
                                "args": {
                                    path_key: "/workspace/demo/new.py",
                                    "Content": "a",
                                },
                            },
                            {
                                "name": write_tool,
                                "args": {
                                    path_key: "/workspace/demo/over.py",
                                    "Overwrite": True,
                                    "Content": "b",
                                },
                            },
                            {
                                "name": write_tool,
                                "args": {
                                    path_key: "/workspace/demo/log.txt",
                                    "Append": True,
                                    "Content": "c",
                                },
                            },
                            {
                                "name": "call_mcp_tool",
                                "args": {
                                    "ServerName": "stitch",
                                    "ToolName": "list_projects",
                                },
                            },
                            {
                                "name": "invoke_subagent",
                                "args": {"TypeName": "research", "Prompt": "check"},
                            },
                            {"name": "run_workflow", "args": {"Description": "fanout"}},
                            {"name": "swarm", "args": {"action": "status"}},
                        ],
                    },
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-10T10:00:09Z",
                        "content": "Post-edit read",
                        "tool_calls": [
                            {
                                "name": read_tool,
                                "args": {
                                    path_key: target_path,
                                    "StartLine": 1,
                                    "EndLine": 10,
                                },
                            }
                        ],
                    },
                    {"type": "GENERIC", "source": "MODEL", "content": "x" * 100},
                ]

            self._write_steps(
                brain_legacy,
                "legacy-1",
                _make_steps(
                    "view_file", "write_to_file", "replace_file_content", "TargetFile"
                ),
            )
            self._write_steps(
                brain_v2,
                "v2-1",
                _make_steps("read_file", "write_file", "edit_file", "Path"),
            )

            d_legacy = self._run_with_brain(
                tmp_path / "l", brain_legacy, config_dir=tmp_path / "nocfg"
            )
            d_v2 = self._run_with_brain(
                tmp_path / "v", brain_v2, config_dir=tmp_path / "nocfg"
            )

            for key in (
                "file_views",
                "unbounded_views",
                "unbounded_view_pct",
                "unbounded_view_tokens",
                "bounded_view_tokens",
                "file_view_overlap",
                "write_to_file_modes",
                "surgical_edits",
                "surgical_edit_ratio_pct",
                "total_tool_calls",
            ):
                self.assertEqual(d_legacy[key], d_v2[key], f"Parity mismatch on {key}")

            self.assertEqual(d_v2["file_view_overlap"]["unmodified_overlap_pct"], 16.67)
            self.assertEqual(d_v2["file_view_overlap"]["gross_overlap_pct"], 50.0)
            self.assertEqual(
                d_v2["write_to_file_modes"],
                {"create": 1, "overwrite": 1, "append": 1},
            )
            self.assertEqual(d_v2["surgical_edits"], 1)
            self.assertEqual(d_v2["surgical_edit_ratio_pct"], 50.0)
            for t in ("call_mcp_tool", "invoke_subagent", "run_workflow", "swarm"):
                self.assertEqual(d_v2["tool_call_counts"][t], 1)

    def test_pretooluse_hook_denials_isolated_from_runtime_failures(self):
        """PreToolUse denials are counted in hook_denials.by_guard and do not inflate runtime failures."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            self._write_steps(
                brain,
                "hook-conv",
                [
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-10T10:00:00Z",
                        "content": "<USER_REQUEST>Run checks</USER_REQUEST>",
                    },
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-10T10:00:01Z",
                        "content": "Calling tools",
                        "tool_calls": [
                            {
                                "name": "run_command",
                                "args": {"CommandLine": "git status"},
                            },
                            {
                                "name": "read_file",
                                "args": {"Path": "/workspace/big.json"},
                            },
                            {
                                "name": "run_command",
                                "args": {"CommandLine": "python3 missing.py"},
                            },
                            {
                                "name": "run_command",
                                "args": {"CommandLine": "echo ok"},
                            },
                            {
                                "name": "edit_file",
                                "args": {"Path": "/workspace/a.py"},
                            },
                        ],
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "content": "Encountered error in step execution: tool call denied by pre-tool hook: Git Worktree Boundary: outside repo",
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "content": "Encountered error in step execution: tool call denied by pre-tool hook: Bounded Read Guard: file too large",
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "content": "Command exited with code 1.\nTraceback (most recent call last):\nFileNotFoundError",
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "content": "Command exited with code 0.\nok",
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "content": "Blocked by PreToolUse: Surgical Diff Guard: use edit_file",
                    },
                ],
            )
            data = self._run_with_brain(tmp_path, brain, config_dir=tmp_path / "nocfg")
            # Only 2 commands actually executed (missing.py failed, echo ok succeeded); 1 hook-denied run_command excluded
            self.assertEqual(data["commands"], 2)
            self.assertEqual(data["failures"], 1)
            self.assertEqual(data["failure_rate_pct"], 50.0)
            self.assertEqual(data["hook_denials"]["total"], 3)
            self.assertEqual(data["hook_denials"]["per_100_tool_calls"], 60.0)
            self.assertEqual(
                data["hook_denials"]["by_guard"],
                {
                    "Git Worktree Boundary": 1,
                    "Bounded Read Guard": 1,
                    "Surgical Diff Guard": 1,
                },
            )

    def test_cache_drift_diagnostics(self):
        """Compactions, mid-conversation model switches, long uncompacted sessions, and PreInvocation messages are counted."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"

            # Conv 1: initial model selection (not a switch) + 1 mid-conv switch + 2 compactions + 2 persistent PreInvocation messages
            self._write_steps(
                brain,
                "drift-1",
                [
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-10T10:00:00Z",
                        "content": "<USER_REQUEST>Start</USER_REQUEST><USER_SETTINGS_CHANGE>The user changed setting `Model Selection` from None to Gemini 4 Neon (Medium).</USER_SETTINGS_CHANGE>",
                    },
                    {
                        "type": "SYSTEM_MESSAGE",
                        "source": "SYSTEM_SDK",
                        "created_at": "2026-11-10T10:00:01Z",
                        "content": "<SYSTEM_MESSAGE>\nThe following system message was injected by a PreInvocation hook:\n[CONTRACT DIARY: read ARCHITECTURE.md]\n</SYSTEM_MESSAGE>",
                    },
                    {
                        "type": "CHECKPOINT",
                        "source": "SYSTEM",
                        "created_at": "2026-11-10T10:05:00Z",
                        "content": "# Resuming from a compaction\nSummary 1",
                    },
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-10T10:06:00Z",
                        "content": "<USER_REQUEST>Switch model</USER_REQUEST><USER_SETTINGS_CHANGE>The user changed setting `Model Selection` from Gemini 4 Neon (Medium) to Claude Opus 5.5 (High).</USER_SETTINGS_CHANGE>",
                    },
                    {
                        "type": "SYSTEM_MESSAGE",
                        "source": "SYSTEM_SDK",
                        "created_at": "2026-11-10T10:06:01Z",
                        "content": "<SYSTEM_MESSAGE>\n[ZERO-SLASH MANDATE: Active skill triggers detected]\n</SYSTEM_MESSAGE>",
                    },
                    {
                        "type": "CHECKPOINT",
                        "source": "SYSTEM",
                        "created_at": "2026-11-10T10:10:00Z",
                        "content": "# Resuming from a compaction\nSummary 2",
                    },
                ],
            )
            # Conv 2: 16 user turns with 0 compactions -> counted in long_convs_without_compaction
            long_steps = [
                {
                    "type": "USER_INPUT",
                    "source": "USER_EXPLICIT",
                    "created_at": f"2026-11-10T11:{i:02d}:00Z",
                    "content": f"<USER_REQUEST>Turn {i}</USER_REQUEST>",
                }
                for i in range(16)
            ]
            self._write_steps(brain, "drift-long", long_steps)

            data = self._run_with_brain(tmp_path, brain, config_dir=tmp_path / "nocfg")
            diag = data["cache_drift_diagnostics"]
            self.assertEqual(diag["compactions_total"], 2)
            self.assertEqual(diag["convs_with_compaction"], 1)
            self.assertEqual(diag["long_convs_without_compaction"], 1)
            self.assertEqual(diag["model_switches_total"], 1)
            self.assertEqual(diag["convs_with_model_switch"], 1)
            self.assertEqual(diag["persistent_hook_system_messages"]["count"], 2)
            self.assertGreater(diag["persistent_hook_system_messages"]["tokens"], 0)

    def test_four_channel_customization_attribution_zero_truncation_and_excludes_audit(
        self,
    ):
        """All 4 channels (skill_read, cli_or_script, mcp, agent) are attributed with zero truncation and audit sessions excluded."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            cfg = tmp_path / "config"
            cfg.mkdir()

            # Configure installed plugins, MCP servers, 30 standalone skills, and custom/plugin agents
            (cfg / "config.json").write_text(
                json.dumps(
                    {
                        "plugins": {
                            "gdocs": {"enabled": True},
                            "gsheets": {"enabled": True},
                            "gdrive": {"enabled": True},
                            "firebase": {"enabled": True},
                            "unused-plugin": {"enabled": False},
                        }
                    }
                ),
                encoding="utf-8",
            )
            (cfg / "mcp_config.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "firebase-mcp-server": {},
                            "medical-terminology": {},
                        }
                    }
                ),
                encoding="utf-8",
            )
            (cfg / "plugins" / "firebase" / "agents").mkdir(parents=True)
            (
                cfg / "plugins" / "firebase" / "agents" / "firestore-rules-author.md"
            ).write_text("# agent", encoding="utf-8")
            (cfg / "agents").mkdir(parents=True)
            (cfg / "agents" / "code-auditor.md").write_text("# agent", encoding="utf-8")
            for idx in range(1, 31):
                sdir = cfg / "skills" / f"skill-{idx:02d}"
                sdir.mkdir(parents=True)
                (sdir / "SKILL.md").write_text(f"# skill {idx}", encoding="utf-8")

            # Normal interactive session exercising all 4 channels + 30 distinct skills (beyond top-25)
            skill_read_calls = [
                {
                    "name": "read_file",
                    "args": {
                        "Path": f"/fake-home/.gemini/config/skills/skill-{idx:02d}/SKILL.md",
                        "StartLine": 1,
                        "EndLine": 10,
                    },
                }
                for idx in range(1, 31)
            ]
            self._write_steps(
                brain,
                "work-1",
                [
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-10T10:00:00Z",
                        "content": "<USER_REQUEST>Use docs, sheets, drive, firebase, skills</USER_REQUEST>",
                    },
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-10T10:00:02Z",
                        "content": "Executing",
                        "tool_calls": [
                            *skill_read_calls,
                            {
                                "name": "run_command",
                                "args": {
                                    "CommandLine": "AGY_ACCOUNT=work gdocs read 123"
                                },
                            },
                            {
                                "name": "run_command",
                                "args": {
                                    "CommandLine": "gsheets get abc && gdrive list"
                                },
                            },
                            {
                                "name": "run_command",
                                "args": {
                                    "CommandLine": "python3 /fake-home/.gemini/config/skills/skill-30/scripts/run.py"
                                },
                            },
                            {
                                "name": "call_mcp_tool",
                                "args": {
                                    "ServerName": "firebase-mcp-server",
                                    "ToolName": "firebase_list_projects",
                                },
                            },
                            {
                                "name": "call_mcp_tool",
                                "args": {
                                    "ServerName": "medical-terminology",
                                    "ToolName": "icd10_search",
                                },
                            },
                            {
                                "name": "invoke_subagent",
                                "args": {
                                    "TypeName": "firestore-rules-author",
                                    "Prompt": "write rules",
                                },
                            },
                            {
                                "name": "invoke_subagent",
                                "args": {
                                    "TypeName": "code-auditor",
                                    "Prompt": "audit",
                                },
                            },
                        ],
                    },
                ],
            )
            # Audit session that MUST be excluded from customization_usage by default
            self._write_steps(
                brain,
                "audit-meta",
                [
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-10T12:00:00Z",
                        "content": "<USER_REQUEST>/improve-agent-efficiency check</USER_REQUEST>",
                    },
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-10T12:00:02Z",
                        "content": "Running",
                        "tool_calls": [
                            {
                                "name": "run_command",
                                "args": {"CommandLine": "gdocs list"},
                            }
                        ],
                    },
                ],
            )

            data = self._run_with_brain(tmp_path, brain, config_dir=cfg)
            cu = data["customization_usage"]
            # CLI-backed plugins attributed accurately (audit session excluded -> gdocs == 1, not 2)
            self.assertEqual(cu["plugins"]["gdocs"]["cli_or_script"], 1)
            self.assertEqual(cu["plugins"]["gdocs"]["total"], 1)
            self.assertEqual(cu["plugins"]["gsheets"]["cli_or_script"], 1)
            self.assertEqual(cu["plugins"]["gdrive"]["cli_or_script"], 1)
            # Plugin-owned MCP server + plugin-bundled agent both attributed to firebase plugin
            self.assertEqual(cu["plugins"]["firebase"]["mcp"], 1)
            self.assertEqual(cu["plugins"]["firebase"]["agent"], 1)
            self.assertEqual(cu["plugins"]["firebase"]["total"], 2)
            self.assertEqual(cu["plugins"]["unused-plugin"]["total"], 0)
            self.assertFalse(cu["plugins"]["unused-plugin"]["enabled"])
            # Zero top-25 truncation: all 30 skills present, and skill-30 has both skill_read + cli_or_script
            self.assertEqual(len(cu["skills"]), 30)
            self.assertEqual(cu["skills"]["skill-30"]["skill_read"], 1)
            self.assertEqual(cu["skills"]["skill-30"]["cli_or_script"], 1)
            self.assertEqual(cu["skills"]["skill-30"]["total"], 2)
            # MCP & Agents
            self.assertEqual(cu["mcp_servers"]["firebase-mcp-server"]["mcp"], 1)
            self.assertEqual(cu["mcp_servers"]["medical-terminology"]["mcp"], 1)
            self.assertEqual(cu["agents"]["firestore-rules-author"]["agent"], 1)
            self.assertEqual(cu["agents"]["code-auditor"]["agent"], 1)

    def test_api_ground_truth_exact_aggregation_without_double_counting(self):
        """API ground-truth tokens (input, cache_creation, cache_read, output, cache_hit_rate_pct) match exact math."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"

            self._write_steps(
                brain,
                "gt-1",
                [
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-10T10:00:00Z",
                        "content": "<USER_REQUEST>Task 1</USER_REQUEST>",
                    },
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-10T10:00:05Z",
                        "content": "Answer 1",
                        "input_tokens": 1000,
                        "cache_creation_input_tokens": 500,
                        "cache_read_tokens": 8500,
                        "output_tokens": 400,
                    },
                ],
            )
            self._write_steps(
                brain,
                "gt-2",
                [
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-10T11:00:00Z",
                        "content": "<USER_REQUEST>Task 2</USER_REQUEST>",
                    },
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-10T11:00:05Z",
                        "content": "Answer 2",
                        "input_tokens": 500,
                        "cache_read_tokens": 9500,
                        "output_tokens": 600,
                    },
                ],
            )

            data = self._run_with_brain(tmp_path, brain, config_dir=tmp_path / "nocfg")
            gt = data["api_tokens_ground_truth"]
            self.assertTrue(gt["has_ground_truth"])
            # Fresh input = (1000 + 500) + 500 = 2000 (no double-counting!)
            self.assertEqual(gt["input_tokens_fresh"], 2000)
            self.assertEqual(gt["cache_creation_input_tokens"], 500)
            # Cache read = 8500 + 9500 = 18000
            self.assertEqual(gt["cache_read_tokens"], 18000)
            # Output = 400 + 600 = 1000
            self.assertEqual(gt["output_tokens_model"], 1000)
            # Context = 2000 + 18000 = 20000; Total all = 21000
            self.assertEqual(gt["total_api_context_processed"], 20000)
            self.assertEqual(gt["total_api_tokens_all"], 21000)
            self.assertEqual(gt["fresh_input_per_conv"], 1000)
            self.assertEqual(gt["cache_read_per_conv"], 9000)
            self.assertEqual(gt["output_per_conv"], 500)
            self.assertEqual(gt["context_per_conv"], 10000)
            self.assertEqual(gt["total_api_per_conv"], 10500)
            # Cache hit rate = 18000 / 20000 * 100 = 90.0%
            self.assertEqual(gt["cache_hit_rate_pct"], 90.0)

    def test_pr4_hardening_regressions(self):
        """Regression tests for PR #4 review findings (denial envelope, quoting, epoch, settings, manifests, quotas)."""
        # 1. Quote-aware command segmentation
        self.assertEqual(
            audit_trajectories.extract_command_executables(
                'rg "foo|firebase|gdocs" src/ && gdocs list | jq .'
            ),
            ["rg", "gdocs", "jq"],
        )
        self.assertEqual(
            audit_trajectories.extract_command_executables(
                "python3 -c 'import os; gdocs = 1; firebase = 2'"
            ),
            ["python3"],
        )

        # 2. Hook denial envelope ignores executed command output & DONE status
        self.assertIsNone(
            audit_trajectories.extract_hook_denial_guard(
                "Command exited with code 1.\n\nCommand output:\nBlocked by PreToolUse: Bounded Read Guard"
            )
        )
        self.assertIsNone(
            audit_trajectories.extract_hook_denial_guard(
                {
                    "status": "DONE",
                    "content": "Blocked by PreToolUse: Bounded Read Guard",
                }
            )
        )
        self.assertEqual(
            audit_trajectories.extract_hook_denial_guard(
                {
                    "status": "ERROR",
                    "content": "Encountered error in step execution: tool call denied by pre-tool hook: Bounded Read Guard: too large",
                }
            ),
            "Bounded Read Guard",
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            cfg = tmp_path / "cfg"

            # 3. Malformed non-dict plugin.json is skipped without crashing
            bad_pdir = cfg / "plugins" / "bad-plugin"
            bad_pdir.mkdir(parents=True)
            (bad_pdir / "plugin.json").write_text(
                '["not", "a", "dict"]', encoding="utf-8"
            )
            good_pdir = cfg / "plugins" / "good-plugin"
            good_pdir.mkdir(parents=True)
            (good_pdir / "plugin.json").write_text(
                '{"disabled": false}', encoding="utf-8"
            )

            # 4. Denied edit preserves file_lines_read_epoch; prose model-switch ignored;
            #    command output quoting hook denial still counted as failure.
            self._write_steps(
                brain,
                "interactive-1",
                [
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-12T10:00:00Z",
                        "content": (
                            "<USER_REQUEST>User prose: changed setting `Model Selection` from Alpha to Beta.</USER_REQUEST>"
                            "<USER_SETTINGS_CHANGE>The user changed setting `Model Selection` from None to ModelA.</USER_SETTINGS_CHANGE>"
                        ),
                    },
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-12T10:01:00Z",
                        "content": (
                            "<USER_REQUEST>Switch now</USER_REQUEST>"
                            "<USER_SETTINGS_CHANGE>The user changed setting `Model Selection` from ModelA to ModelB.</USER_SETTINGS_CHANGE>"
                        ),
                    },
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-12T10:02:00Z",
                        "content": "Read, denied edit, re-read, and failing command quoting denial",
                        "tool_calls": [
                            {
                                "name": "read_file",
                                "args": {
                                    "Path": "/ws/a.py",
                                    "StartLine": 1,
                                    "EndLine": 10,
                                },
                            },
                            {
                                "name": "edit_file",
                                "args": {"Path": "/ws/a.py", "Replacement": "x"},
                            },
                            {
                                "name": "read_file",
                                "args": {
                                    "Path": "/ws/a.py",
                                    "StartLine": 1,
                                    "EndLine": 10,
                                },
                            },
                            {
                                "name": "run_command",
                                "args": {"CommandLine": "python3 fail.py"},
                            },
                            {
                                "name": "run_command",
                                "args": {"CommandLine": '"echo" "notes; gdrive list"'},
                            },
                        ],
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "status": "DONE",
                        "content": "ok",
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "status": "ERROR",
                        "content": "Blocked by PreToolUse: Surgical Diff Guard: denied",
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "status": "DONE",
                        "content": "ok",
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "status": "DONE",
                        "content": "Command exited with code 1.\nBlocked by PreToolUse: Bounded Read Guard",
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "status": "DONE",
                        "content": "Command exited with code 0.\nnotes; gdrive list",
                    },
                ],
            )
            # Older interactive conv (exceeds limit=1) and older headless conv (must still be collected!)
            self._write_steps(
                brain,
                "interactive-2-older",
                [
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-11T10:00:00Z",
                        "content": "<USER_REQUEST>Older interactive</USER_REQUEST>",
                    },
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-11T10:00:05Z",
                        "content": "Done",
                        "input_tokens": 9999,
                    },
                ],
            )
            self._write_steps(
                brain,
                "headless-oldest",
                [
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-10T10:00:00Z",
                        "content": "Subagent run",
                        "input_tokens": 700,
                        "output_tokens": 50,
                    }
                ],
            )

            data = self._run_with_brain(
                tmp_path / "run1", brain, config_dir=cfg, max_conversations=1
            )
            # Malformed plugin skipped, valid plugin discovered
            self.assertNotIn("bad-plugin", data["customization_usage"]["plugins"])
            self.assertIn("good-plugin", data["customization_usage"]["plugins"])
            # Only 1 genuine mid-conv model switch (prose in USER_REQUEST ignored)
            self.assertEqual(data["cache_drift_diagnostics"]["model_switches_total"], 1)
            # Denied edit did NOT reset epoch: 10 lines read twice -> 50% unmodified overlap
            self.assertEqual(data["file_view_overlap"]["unmodified_overlap_pct"], 50.0)
            # Command quoting "Blocked by PreToolUse" still counted as failure, not denial;
            # '"echo" "notes; gdrive list"' succeeds without falsely crediting gdrive
            self.assertEqual(data["commands"], 2)
            self.assertEqual(data["failures"], 1)
            self.assertEqual(
                data["customization_usage"]["plugins"]
                .get("gdrive", {})
                .get("cli_or_script", 0),
                0,
            )
            self.assertEqual(data["hook_denials"]["total"], 1)
            self.assertEqual(
                data["hook_denials"]["by_guard"], {"Surgical Diff Guard": 1}
            )
            # Primary capped at 1 interactive, but older headless still collected
            self.assertEqual(data["conversations"], 1)
            self.assertEqual(data["interactive_conversations"], 1)
            self.assertEqual(data["subagent_or_headless_conversations"], 1)
            self.assertEqual(data["total_api_tokens_including_subagents"], 750)

            # 5. Explicit --conv headless IDs are subject to max_conversations
            self._write_steps(
                brain,
                "headless-second",
                [
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-10T11:00:00Z",
                        "content": "Subagent 2",
                        "input_tokens": 300,
                    }
                ],
            )
            conv_limited = self._run_with_brain(
                tmp_path / "run2",
                brain,
                config_dir=cfg,
                include_conv="headless-oldest,headless-second",
                max_conversations=1,
            )
            self.assertEqual(conv_limited["conversations"], 1)
            self.assertEqual(conv_limited["subagent_or_headless_conversations"], 1)

            # 6. --include-subagents + --limit still collects older headless sessions
            #    in both standard mode and --compare mode
            incl_std = self._run_with_brain(
                tmp_path / "run3",
                brain,
                config_dir=cfg,
                include_subagents=True,
                max_conversations=1,
            )
            # Primary sample capped at 1 (newest interactive-1), while both older headless sessions are collected
            self.assertEqual(incl_std["conversations"], 1)
            self.assertEqual(incl_std["subagent_or_headless_conversations"], 2)
            self.assertEqual(incl_std["subagent_summary"]["conversations"], 2)
            self.assertEqual(incl_std["total_api_tokens_including_subagents"], 1050)

            # Add an older target-window headless session (after 2026-11-12T00:00:00Z)
            self._write_steps(
                brain,
                "headless-target-older",
                [
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-12T08:00:00Z",
                        "content": "Target subagent",
                        "input_tokens": 200,
                    }
                ],
            )
            incl_cmp = self._run_with_brain(
                tmp_path / "run4",
                brain,
                config_dir=cfg,
                since_date="2026-11-12T00:00:00Z",
                compare_mode=True,
                include_subagents=True,
                max_conversations=1,
            )
            cmp_block = incl_cmp["comparison"]
            self.assertEqual(cmp_block["target_window"]["conversations"], 1)
            self.assertEqual(cmp_block["baseline_window"]["conversations"], 1)
            self.assertEqual(cmp_block["target_subagent_summary"]["conversations"], 1)
            self.assertEqual(cmp_block["baseline_subagent_summary"]["conversations"], 2)
            self.assertEqual(
                cmp_block["target_total_api_tokens_including_subagents"], 200
            )
            self.assertEqual(
                cmp_block["baseline_total_api_tokens_including_subagents"],
                9999 + 1050,
            )

    def test_pr4_followup_attribution_and_ratio_regressions(self):
        """Regression tests for shell comments, denied CLI/edit handling, script-position attribution, and mcp_ calls."""
        # 1. Shell comment handling in _split_shell_segments / extract_command_executables
        self.assertEqual(
            audit_trajectories.extract_command_executables(
                'echo "a # ; firebase" # ; gdrive list\ngdocs list'
            ),
            ["echo", "gdocs"],
        )
        # Escaped whitespace before '#' is NOT a word boundary (Bash runs gdrive)
        self.assertEqual(
            audit_trajectories.extract_command_executables(
                r"echo foo\ #suffix; gdrive list"
            ),
            ["echo", "gdrive"],
        )
        # Backslash-newline preserves preceding word boundary (comment vs continued word)
        self.assertEqual(
            audit_trajectories.extract_command_executables(
                "echo ok \\\n# note; gdrive list\ngdocs list"
            ),
            ["echo", "gdocs"],
        )
        self.assertEqual(
            audit_trajectories.extract_command_executables(
                "echo foo\\\n#suffix; gdrive list"
            ),
            ["echo", "gdrive"],
        )

        # 2. Script path attribution only in executable or interpreter-operand position
        self.assertEqual(
            audit_trajectories.extract_command_script_targets(
                "echo skills/shinystat/scripts/run.py"
            ),
            [],
        )
        self.assertEqual(
            audit_trajectories.extract_command_script_targets(
                "python3 -c \"print('skills/shinystat/scripts/run.py')\""
            ),
            [],
        )
        self.assertEqual(
            audit_trajectories.extract_command_script_targets(
                "python3 skills/shinystat/scripts/run.py --arg 1 && ./plugins/demo/bin/go.sh"
            ),
            [("skills", "shinystat"), ("plugins", "demo")],
        )

        # 3. End-to-end: denied gdrive not credited, blocked edit + accepted overwrite => 0% ratio,
        #    direct mcp_<serverName>_<toolName> with underscores credited to server + parent plugin
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain = tmp_path / "brain"
            cfg = tmp_path / "cfg"
            pdir = cfg / "plugins" / "custom-plug"
            pdir.mkdir(parents=True)
            (pdir / "plugin.json").write_text('{"disabled": false}', encoding="utf-8")
            (pdir / "mcp_config.json").write_text(
                json.dumps({"mcpServers": {"my_custom_srv": {"command": "node"}}}),
                encoding="utf-8",
            )

            self._write_steps(
                brain,
                "e2e-1",
                [
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-15T10:00:00Z",
                        "content": "<USER_REQUEST>Run tools</USER_REQUEST>",
                    },
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-15T10:00:01Z",
                        "content": "Execute",
                        "tool_calls": [
                            {
                                "name": "run_command",
                                "args": {"CommandLine": "gdrive list"},
                            },
                            {
                                "name": "run_command",
                                "args": {
                                    "CommandLine": "echo skills/shinystat/scripts/run.py"
                                },
                            },
                            {
                                "name": "edit_file",
                                "args": {"Path": "/ws/f.py", "Replacement": "x"},
                            },
                            {
                                "name": "write_file",
                                "args": {
                                    "Path": "/ws/f.py",
                                    "Overwrite": True,
                                    "Content": "full",
                                },
                            },
                            {
                                "name": "mcp_my_custom_srv_list_items",
                                "args": {},
                            },
                        ],
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "status": "ERROR",
                        "content": "Blocked by PreToolUse: GDrive Guard: denied",
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "status": "DONE",
                        "content": "Command exited with code 0.\nskills/shinystat/scripts/run.py",
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "status": "ERROR",
                        "content": "Blocked by PreToolUse: Surgical Diff Guard: denied",
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "status": "DONE",
                        "content": "ok",
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "status": "DONE",
                        "content": "ok",
                    },
                ],
            )
            data = self._run_with_brain(tmp_path / "out", brain, config_dir=cfg)
            # Raw attempts preserved in tool_call_counts, but surgical_edits & ratio use non-denied counts
            self.assertEqual(data["tool_call_counts"]["edit_file"], 1)
            self.assertEqual(data["tool_call_counts"]["run_command"], 2)
            self.assertEqual(data["write_to_file_modes"].get("overwrite"), 1)
            self.assertEqual(data["surgical_edits"], 0)
            self.assertEqual(data["surgical_edit_ratio_pct"], 0.0)
            self.assertEqual(data["hook_denials"]["total"], 2)
            # Denied gdrive list and echoed skill path NOT credited
            self.assertEqual(
                data["customization_usage"]["plugins"]
                .get("gdrive", {})
                .get("cli_or_script", 0),
                0,
            )
            self.assertEqual(
                data["customization_usage"]["skills"]
                .get("shinystat", {})
                .get("cli_or_script", 0),
                0,
            )
            # Direct mcp_my_custom_srv_list_items credited to both server and parent plugin
            self.assertEqual(
                data["customization_usage"]["mcp_servers"]["my_custom_srv"]["mcp"], 1
            )
            self.assertEqual(
                data["customization_usage"]["plugins"]["custom-plug"]["mcp"], 1
            )

        # 4. Continuation-split &&, heredoc trailing newline, attached -cpass, -W ignore
        self.assertEqual(
            audit_trajectories.extract_command_executables(
                "echo ok &\\\n& gdrive list"
            ),
            ["echo", "gdrive"],
        )
        heredoc_then_py = "cat <<'EOF'\nhello\nEOF\npython3 skills/demo/run.py"
        self.assertEqual(
            audit_trajectories.extract_command_executables(heredoc_then_py),
            ["cat", "python3"],
        )
        self.assertEqual(
            audit_trajectories.extract_command_script_targets(heredoc_then_py),
            [("skills", "demo")],
        )
        self.assertEqual(
            audit_trajectories.extract_command_script_targets(
                "python3 -cpass skills/demo/run.py"
            ),
            [],
        )
        self.assertEqual(
            audit_trajectories.extract_command_script_targets(
                "python3 -W ignore skills/demo/run.py"
            ),
            [("skills", "demo")],
        )

        # 5. Fallback scan must not steal another tool call's denial onto an unblocked run_command
        with tempfile.TemporaryDirectory() as tmp2:
            tmp2_path = Path(tmp2)
            brain2 = tmp2_path / "brain"
            self._write_steps(
                brain2,
                "no-steal-1",
                [
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "created_at": "2026-11-16T10:00:00Z",
                        "content": "<USER_REQUEST>Run gdrive and read</USER_REQUEST>",
                    },
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "created_at": "2026-11-16T10:00:01Z",
                        "content": "Calling both",
                        "tool_calls": [
                            {
                                "name": "run_command",
                                "args": {"CommandLine": "gdrive list"},
                            },
                            {
                                "name": "read_file",
                                "args": {"Path": "/ws/huge.bin"},
                            },
                        ],
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "status": "DONE",
                        "content": "Tool is running as a background task",
                    },
                    {
                        "type": "GENERIC",
                        "source": "MODEL",
                        "status": "ERROR",
                        "content": "Blocked by PreToolUse: Bounded Read Guard: too large",
                    },
                ],
            )
            d2 = self._run_with_brain(
                tmp2_path / "out", brain2, config_dir=tmp2_path / "nocfg"
            )
            self.assertEqual(d2["commands"], 1)
            self.assertEqual(
                d2["customization_usage"]["plugins"]["gdrive"]["cli_or_script"], 1
            )
            self.assertEqual(d2["hook_denials"]["total"], 1)
            self.assertEqual(d2["hook_denials"]["by_guard"], {"Bounded Read Guard": 1})


if __name__ == "__main__":
    unittest.main()
