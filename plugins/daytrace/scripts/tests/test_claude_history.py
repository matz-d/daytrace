#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "claude_history.py"


class ClaudeHistoryTests(unittest.TestCase):
    def test_permission_denied_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            blocked = root / "blocked.jsonl"
            blocked.write_text(
                '{"type":"user","timestamp":"2026-03-09T00:00:00Z","cwd":"/tmp","message":{"content":"secret https://example.com/x?token=123"}}\n',
                encoding="utf-8",
            )
            os.chmod(blocked, 0)
            try:
                completed = subprocess.run(
                    ["python3", str(SCRIPT), "--root", str(root)],
                    cwd=str(REPO_ROOT),
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                os.chmod(blocked, stat.S_IRUSR | stat.S_IWUSR)

            self.assertEqual(completed.returncode, 0)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "skipped")
            self.assertEqual(payload["reason"], "permission_denied")


if __name__ == "__main__":
    unittest.main()
