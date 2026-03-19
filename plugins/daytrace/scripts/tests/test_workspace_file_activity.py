#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "workspace_file_activity.py"


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


class WorkspaceFileActivityTests(unittest.TestCase):
    def test_no_untracked_files_is_success_with_empty_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            workspace = repo_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)

            run_checked(["git", "init"], cwd=repo_root)
            run_checked(["git", "config", "user.name", "DayTrace Tests"], cwd=repo_root)
            run_checked(["git", "config", "user.email", "daytrace@example.com"], cwd=repo_root)

            tracked_file = workspace / "tracked.txt"
            tracked_file.write_text("tracked\n", encoding="utf-8")
            run_checked(["git", "add", "workspace/tracked.txt"], cwd=repo_root)
            run_checked(["git", "commit", "-m", "Add tracked file"], cwd=repo_root)

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--workspace", str(workspace)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["events"], [])

    def test_untracked_file_is_emitted_with_workspace_details(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            workspace = repo_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)

            run_checked(["git", "init"], cwd=repo_root)
            run_checked(["git", "config", "user.name", "DayTrace Tests"], cwd=repo_root)
            run_checked(["git", "config", "user.email", "daytrace@example.com"], cwd=repo_root)

            untracked_file = workspace / "draft.txt"
            untracked_file.write_text("draft\n", encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--workspace", str(workspace)],
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
            self.assertEqual(event["type"], "untracked_file")
            self.assertEqual(event["details"]["path"], "workspace/draft.txt")
            self.assertEqual(event["details"]["workspace"], str(workspace.resolve()))

    def test_not_git_repo_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--workspace", str(workspace)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "skipped")
            self.assertEqual(payload["reason"], "not_git_repo")
            self.assertEqual(payload["events"], [])


if __name__ == "__main__":
    unittest.main()
