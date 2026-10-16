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
            with mock.patch.object(Path, "home", return_value=tmp_home):
                repos = audit_trajectories.discover_git_repositories([], tmp_home)
                repo_names = [Path(p).name for p in repos.values()]
                self.assertIn("my-home-repo", repo_names)


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
        """check_manifest_integrity should detect missing frontmatter in SKILL.md."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_repo = Path(tmp)
            bad_skill = tmp_repo / "skills" / "bad-skill"
            bad_skill.mkdir(parents=True)
            (bad_skill / "SKILL.md").write_text("# No Frontmatter\n", encoding="utf-8")

            violations = check_repo_safety.check_manifest_integrity(tmp_repo)
            self.assertTrue(any("SKILL.md" in v for v in violations))


if __name__ == "__main__":
    unittest.main()
