#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


from conftest import PROJECT_ROOT, PLUGIN_ROOT
from helpers import write_jsonl

SCRIPT = PLUGIN_ROOT / "scripts" / "claude_history.py"


class ClaudeHistoryTests(unittest.TestCase):
    @unittest.skipIf(os.getuid() == 0, "root bypasses file permissions")
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
                    [sys.executable, str(SCRIPT), "--root", str(root)],
                    cwd=str(PROJECT_ROOT),
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
                    sys.executable,
                    str(SCRIPT),
                    "--root",
                    str(claude_root),
                    "--workspace",
                    str(workspace_a),
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(len(payload["events"]), 2)

            event = next(item for item in payload["events"] if item["type"] == "session_summary")
            logical_packets = event["details"]["logical_packets"]
            self.assertEqual(len(logical_packets), 2)
            self.assertEqual(logical_packets[0]["packet_index"], 0)
            self.assertEqual(logical_packets[1]["packet_index"], 1)
            for packet in logical_packets:
                self.assertEqual(packet["cwd"], str(workspace_a))
                self.assertIn("referenced_files", packet)
            self.assertIn("referenced_files", event["details"])
            # v0.2.0 stopped writing the pattern-proposal packets.
            for item in payload["events"]:
                self.assertNotIn("ai_observation", item["details"])
                self.assertNotIn("ai_observation_packets", item["details"])

    def test_pivot_message_produces_separate_logical_packets_without_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()

            base = datetime.now(timezone.utc)
            claude_root = root / "claude"
            write_jsonl(
                claude_root / "repo" / "session-pivot.jsonl",
                [
                    {
                        "type": "user",
                        "cwd": str(workspace),
                        "sessionId": "s2",
                        "isSidechain": False,
                        "timestamp": base.isoformat(),
                        "message": {"role": "user", "content": "Review app.py and summarize findings."},
                    },
                    {
                        "type": "assistant",
                        "cwd": str(workspace),
                        "sessionId": "s2",
                        "isSidechain": False,
                        "timestamp": (base + timedelta(minutes=1)).isoformat(),
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "I will inspect app.py and report findings first."}]},
                    },
                    {
                        "type": "user",
                        "cwd": str(workspace),
                        "sessionId": "s2",
                        "isSidechain": False,
                        "timestamp": (base + timedelta(minutes=2)).isoformat(),
                        "message": {"role": "user", "content": "Instead, switch to drafting release notes."},
                    },
                    {
                        "type": "assistant",
                        "cwd": str(workspace),
                        "sessionId": "s2",
                        "isSidechain": False,
                        "timestamp": (base + timedelta(minutes=3)).isoformat(),
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "Switching to release note drafting."}]},
                    },
                ],
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--root",
                    str(claude_root),
                    "--workspace",
                    str(workspace),
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")

            event = next(item for item in payload["events"] if item["type"] == "session_summary")
            logical_packets = event["details"]["logical_packets"]
            self.assertEqual(len(logical_packets), 2)
            self.assertIn("Review app.py", logical_packets[0]["user_highlights"][0])
            self.assertIn("Instead, switch to drafting release notes.", logical_packets[1]["user_highlights"][0])

    def test_user_requests_skip_compact_summaries_and_injected_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            base = datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc)

            def row(minutes: int, content: object, **extra: object) -> dict:
                return {
                    "type": extra.pop("type", "user"),
                    "cwd": str(workspace),
                    "sessionId": "s1",
                    "isSidechain": extra.pop("isSidechain", False),
                    "timestamp": (base + timedelta(minutes=minutes)).isoformat(),
                    "message": {"role": "user", "content": content},
                    **extra,
                }

            claude_root = root / "claude"
            write_jsonl(
                claude_root / "repo" / "session.jsonl",
                [
                    row(0, "This session is being continued from a previous conversation that ran out of context. Summary...", isCompactSummary=True),
                    row(1, "<system-reminder>\nThe user forked this session.\n</system-reminder>"),
                    row(2, "<command-name>/insights</command-name>\n<command-message>insights</command-message>\n<command-args></command-args>"),
                    row(3, "撮影の本数は？<system-reminder>context</system-reminder>"),
                    row(4, "<local-command-stdout>ok</local-command-stdout>"),
                    row(5, "サブエージェントへの指示", isSidechain=True),
                    row(6, [{"type": "tool_result", "tool_use_id": "x", "content": "done"}]),
                    {
                        "type": "assistant",
                        "cwd": str(workspace),
                        "sessionId": "s1",
                        "isSidechain": False,
                        "timestamp": (base + timedelta(minutes=7)).isoformat(),
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "8本です。"}]},
                    },
                ],
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--root",
                    str(claude_root),
                    "--all-sessions",
                    "--since",
                    "2026-11-12T00:00:00+09:00",
                    "--until",
                    "2026-11-12T23:59:59+09:00",
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            session_event = next(event for event in payload["events"] if event["type"] == "session_summary")
            self.assertEqual(
                [request["text"] for request in session_event["details"]["user_requests"]],
                ["/insights", "撮影の本数は？"],
            )
            self.assertNotIn("continued from a previous conversation", session_event["summary"])
            self.assertNotIn("system-reminder", session_event["summary"])

    def test_user_requests_keep_only_user_text_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            base = datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc)
            claude_root = root / "claude"
            write_jsonl(
                claude_root / "repo" / "session.jsonl",
                [
                    {
                        "type": "user",
                        "cwd": str(workspace),
                        "sessionId": "s1",
                        "timestamp": base.isoformat(),
                        "message": {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "この画像の"},
                                {"type": "image", "source": {"type": "base64", "data": "AAAA"}},
                                {"type": "text", "text": "表を直して"},
                            ],
                        },
                    },
                    {
                        "type": "assistant",
                        "cwd": str(workspace),
                        "sessionId": "s1",
                        "timestamp": (base + timedelta(minutes=1)).isoformat(),
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "thinking", "thinking": "内部の推論"},
                                {"type": "text", "text": "直しました"},
                                {"type": "tool_use", "name": "Edit", "input": {"file_path": "a.md"}},
                            ],
                        },
                    },
                ],
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--root",
                    str(claude_root),
                    "--all-sessions",
                    "--since",
                    "2026-11-12T00:00:00+09:00",
                    "--until",
                    "2026-11-12T23:59:59+09:00",
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            session_event = next(event for event in payload["events"] if event["type"] == "session_summary")
            self.assertEqual([request["text"] for request in session_event["details"]["user_requests"]], ["この画像の 表を直して"])


if __name__ == "__main__":
    unittest.main()
