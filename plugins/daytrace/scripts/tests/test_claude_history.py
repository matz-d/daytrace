#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "claude_history.py"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


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


    def test_workspace_switch_produces_separate_logical_packets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_a = root / "workspace-a"
            workspace_b = root / "workspace-b"
            workspace_a.mkdir()
            workspace_b.mkdir()

            base = datetime.now(timezone.utc)
            claude_root = root / "claude"
            write_jsonl(
                claude_root / "repo" / "session-switch.jsonl",
                [
                    {
                        "type": "user",
                        "cwd": str(workspace_a),
                        "sessionId": "s1",
                        "isSidechain": False,
                        "timestamp": base.isoformat(),
                        "message": {"role": "user", "content": "Review app.py"},
                    },
                    {
                        "type": "assistant",
                        "cwd": str(workspace_a),
                        "sessionId": "s1",
                        "isSidechain": False,
                        "timestamp": (base + timedelta(minutes=2)).isoformat(),
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "Reviewing app.py now."}]},
                    },
                    {
                        "type": "user",
                        "cwd": str(workspace_b),
                        "sessionId": "s1",
                        "isSidechain": False,
                        "timestamp": (base + timedelta(minutes=5)).isoformat(),
                        "message": {"role": "user", "content": "Prepare notes.md"},
                    },
                    {
                        "type": "assistant",
                        "cwd": str(workspace_b),
                        "sessionId": "s1",
                        "isSidechain": False,
                        "timestamp": (base + timedelta(minutes=7)).isoformat(),
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "Preparing notes.md draft."}]},
                    },
                    {
                        "type": "user",
                        "cwd": str(workspace_a),
                        "sessionId": "s1",
                        "isSidechain": False,
                        "timestamp": (base + timedelta(minutes=10)).isoformat(),
                        "message": {"role": "user", "content": "Review api.py"},
                    },
                    {
                        "type": "assistant",
                        "cwd": str(workspace_a),
                        "sessionId": "s1",
                        "isSidechain": False,
                        "timestamp": (base + timedelta(minutes=12)).isoformat(),
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "Reviewing api.py now."}]},
                    },
                ],
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--root",
                    str(claude_root),
                    "--workspace",
                    str(workspace_a),
                ],
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
            logical_packets = event["details"]["logical_packets"]
            self.assertEqual(len(logical_packets), 2)
            self.assertEqual(logical_packets[0]["packet_index"], 0)
            self.assertEqual(logical_packets[1]["packet_index"], 1)
            for packet in logical_packets:
                self.assertEqual(packet["cwd"], str(workspace_a))


if __name__ == "__main__":
    unittest.main()
