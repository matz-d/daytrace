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
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "git_history.py"
SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

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
                ["python3", str(SCRIPT), "--workspace", str(workspace)],
                cwd=str(REPO_ROOT),
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


if __name__ == "__main__":
    unittest.main()
