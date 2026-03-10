#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "workspace_file_activity.py"


class WorkspaceFileActivityTests(unittest.TestCase):
    def test_no_untracked_files_is_success_with_empty_events(self) -> None:
        workspace = REPO_ROOT / "plugins" / "daytrace" / "skills" / "daily-report"
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
        self.assertEqual(payload["events"], [])


if __name__ == "__main__":
    unittest.main()
