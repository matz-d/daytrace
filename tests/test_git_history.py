#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


from conftest import PROJECT_ROOT, PLUGIN_ROOT

SCRIPT = PLUGIN_ROOT / "scripts" / "git_history.py"

import git_history


def run_checked(command: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)


class GitHistoryTests(unittest.TestCase):
    def test_not_git_repo_returns_skipped_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--workspace", str(workspace)],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "skipped")
            self.assertEqual(payload["reason"], "not_git_repo")
            self.assertEqual(payload["workspace"], str(workspace.resolve()))

    def test_timeout_returns_error_payload(self) -> None:
        stdout = io.StringIO()
        workspace = Path("/tmp/daytrace-timeout-workspace")
        timeout = subprocess.TimeoutExpired(cmd=["git", "log"], timeout=git_history.GIT_TIMEOUT_SEC)

        with patch("git_history.run_command", side_effect=timeout):
            with patch.object(sys, "argv", ["git_history.py", "--workspace", str(workspace)]):
                with contextlib.redirect_stdout(stdout):
                    git_history.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "error")
        self.assertIn("timed out after", payload["message"])
        self.assertEqual(payload["workspace"], str(workspace.resolve()))

    def test_workspace_commit_is_emitted_with_numstat_details(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            workspace = repo_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)

            run_checked(["git", "init"], cwd=repo_root)
            run_checked(["git", "config", "user.name", "DayTrace Tests"], cwd=repo_root)
            run_checked(["git", "config", "user.email", "daytrace@example.com"], cwd=repo_root)

            tracked_file = workspace / "notes.txt"
            tracked_file.write_text("first line\nsecond line\n", encoding="utf-8")
            run_checked(["git", "add", "workspace/notes.txt"], cwd=repo_root)
            run_checked(["git", "commit", "-m", "Add workspace notes"], cwd=repo_root)

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--workspace", str(workspace)],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(len(payload["events"]), 1)
            event = payload["events"][0]
            self.assertEqual(event["type"], "commit")
            self.assertEqual(event["summary"], "Add workspace notes")
            self.assertEqual(event["details"]["stats"]["files_changed"], 1)
            self.assertEqual(event["details"]["stats"]["insertions"], 2)
            self.assertEqual(event["details"]["changed_files"][0]["path"], "workspace/notes.txt")

    def test_worktree_status_is_emitted_for_today_window_with_path_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            workspace = repo_root / "workspace"
            tests_dir = workspace / "tests"
            tests_dir.mkdir(parents=True, exist_ok=True)

            run_checked(["git", "init"], cwd=repo_root)
            run_checked(["git", "config", "user.name", "DayTrace Tests"], cwd=repo_root)
            run_checked(["git", "config", "user.email", "daytrace@example.com"], cwd=repo_root)

            tracked_files = {
                workspace / "README.md": "# Notes\n",
                tests_dir / "test_alpha.py": "def test_alpha():\n    assert True\n",
                tests_dir / "test_beta.py": "def test_beta():\n    assert True\n",
            }
            for path, content in tracked_files.items():
                path.write_text(content, encoding="utf-8")
            run_checked(["git", "add", "workspace"], cwd=repo_root)
            run_checked(["git", "commit", "-m", "Add tracked files"], cwd=repo_root)

            (tests_dir / "test_alpha.py").write_text("def test_alpha():\n    assert False\n", encoding="utf-8")
            run_checked(["git", "add", "workspace/tests/test_alpha.py"], cwd=repo_root)
            (tests_dir / "test_beta.py").write_text("def test_beta():\n    assert False\n", encoding="utf-8")
            (workspace / "README.md").write_text("# Notes\n\nUpdated today.\n", encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--workspace", str(workspace)],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            worktree_event = next(event for event in payload["events"] if event["type"] == "worktree_status")
            self.assertTrue(worktree_event["details"]["dirty"])
            self.assertEqual(worktree_event["details"]["staged_count"], 1)
            self.assertEqual(worktree_event["details"]["unstaged_count"], 2)
            self.assertTrue(worktree_event["details"]["branch"])
            self.assertEqual(worktree_event["details"]["dominant_kind"], "tests")
            self.assertEqual(worktree_event["details"]["path_kinds"]["tests"], 2)
            self.assertEqual(worktree_event["details"]["path_kinds"]["docs"], 1)
            self.assertEqual(worktree_event["details"]["languages"]["python"], 2)
            self.assertEqual(worktree_event["details"]["languages"]["markdown"], 1)
            self.assertEqual(worktree_event["details"]["top_dirs"][0], {"path": "workspace/tests", "count": 2})
            self.assertIn("workspace/tests/test_alpha.py", worktree_event["details"]["staged_files"])
            self.assertIn("workspace/tests/test_beta.py", worktree_event["details"]["unstaged_files"])
            self.assertIn("workspace/README.md", worktree_event["details"]["unstaged_files"])

    def test_clean_worktree_for_today_window_emits_only_commit_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            workspace = repo_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)

            run_checked(["git", "init"], cwd=repo_root)
            run_checked(["git", "config", "user.name", "DayTrace Tests"], cwd=repo_root)
            run_checked(["git", "config", "user.email", "daytrace@example.com"], cwd=repo_root)

            tracked_file = workspace / "notes.txt"
            tracked_file.write_text("hello\n", encoding="utf-8")
            run_checked(["git", "add", "workspace/notes.txt"], cwd=repo_root)
            run_checked(["git", "commit", "-m", "Add notes"], cwd=repo_root)

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--workspace", str(workspace)],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual([event["type"] for event in payload["events"]], ["commit"])

    def test_worktree_status_is_not_emitted_for_past_only_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            workspace = repo_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)

            run_checked(["git", "init"], cwd=repo_root)
            run_checked(["git", "config", "user.name", "DayTrace Tests"], cwd=repo_root)
            run_checked(["git", "config", "user.email", "daytrace@example.com"], cwd=repo_root)

            tracked_file = workspace / "notes.txt"
            tracked_file.write_text("base\n", encoding="utf-8")
            run_checked(["git", "add", "workspace/notes.txt"], cwd=repo_root)
            run_checked(["git", "commit", "-m", "Add notes"], cwd=repo_root)

            tracked_file.write_text("base\nupdated\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--workspace",
                    str(workspace),
                    "--since",
                    "2000-01-01",
                    "--until",
                    "2000-01-01",
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["events"], [])

    def test_build_worktree_status_event_returns_none_when_diff_fails(self) -> None:
        repo_root = Path("/tmp/repo-root")
        workspace = repo_root / "workspace"

        responses = [
            SimpleNamespace(returncode=1, stdout="", stderr="diff failed"),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
        ]

        with patch("git_history.run_command", side_effect=responses):
            event = git_history.build_worktree_status_event(repo_root, workspace, "workspace")

        self.assertIsNone(event)

    def test_current_branch_falls_back_to_short_sha_for_detached_head(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            workspace = repo_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)

            run_checked(["git", "init"], cwd=repo_root)
            run_checked(["git", "config", "user.name", "DayTrace Tests"], cwd=repo_root)
            run_checked(["git", "config", "user.email", "daytrace@example.com"], cwd=repo_root)

            tracked_file = workspace / "notes.txt"
            tracked_file.write_text("hello\n", encoding="utf-8")
            run_checked(["git", "add", "workspace/notes.txt"], cwd=repo_root)
            run_checked(["git", "commit", "-m", "Add notes"], cwd=repo_root)
            run_checked(["git", "checkout", "--detach"], cwd=repo_root)

            branch = git_history.current_branch(repo_root)

            self.assertIsNotNone(branch)
            self.assertRegex(str(branch), r"^[0-9a-f]{7,}$")


if __name__ == "__main__":
    unittest.main()
