#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from codex_history import load_history_indexes
from common import parse_datetime

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "codex_history.py"


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


class CodexHistoryTests(unittest.TestCase):
    def test_cli_emits_workspace_scoped_session_commentary_and_tool_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            other_workspace = root / "other-workspace"
            workspace.mkdir()
            other_workspace.mkdir()
            history_file = root / "history.jsonl"
            sessions_root = root / "sessions"

            write_jsonl(
                history_file,
                [
                    {
                        "session_id": "inside-session",
                        "ts": "2026-03-12T09:00:00+09:00",
                        "text": "Review server.py and keep findings first.",
                    },
                    {
                        "session_id": "outside-session",
                        "ts": "2026-03-12T08:00:00+09:00",
                        "text": "Work somewhere else.",
                    },
                ],
            )
            write_jsonl(
                sessions_root / "2026" / "03" / "12" / "rollout-inside.jsonl",
                [
                    {
                        "timestamp": "2026-03-12T09:00:00+09:00",
                        "type": "session_meta",
                        "payload": {"id": "inside-session", "timestamp": "2026-03-12T09:00:00+09:00", "cwd": str(workspace)},
                    },
                    {
                        "timestamp": "2026-03-12T09:00:01+09:00",
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "Review the diff and summarize findings."},
                    },
                    {
                        "timestamp": "2026-03-12T09:00:02+09:00",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "I will inspect files and report findings first."}],
                        },
                    },
                    {
                        "timestamp": "2026-03-12T09:00:03+09:00",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "arguments": json.dumps({"cmd": "pytest plugins/daytrace/scripts/tests -q"}),
                        },
                    },
                ],
            )
            write_jsonl(
                sessions_root / "2026" / "03" / "12" / "rollout-outside.jsonl",
                [
                    {
                        "timestamp": "2026-03-12T08:00:00+09:00",
                        "type": "session_meta",
                        "payload": {"id": "outside-session", "timestamp": "2026-03-12T08:00:00+09:00", "cwd": str(other_workspace)},
                    },
                    {
                        "timestamp": "2026-03-12T08:00:01+09:00",
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "Do something in the other workspace."},
                    },
                ],
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--history-file",
                    str(history_file),
                    "--sessions-root",
                    str(sessions_root),
                    "--workspace",
                    str(workspace),
                    "--since",
                    "2026-03-12T00:00:00+09:00",
                    "--until",
                    "2026-03-12T23:59:59+09:00",
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["scanned_rollouts"], 2)
            self.assertEqual({event["type"] for event in payload["events"]}, {"session_meta", "commentary", "tool_call"})
            self.assertTrue(all(event["details"]["session_id"] == "inside-session" for event in payload["events"]))

            tool_event = next(event for event in payload["events"] if event["type"] == "tool_call")
            self.assertEqual(tool_event["details"]["total_calls"], 1)
            self.assertEqual(tool_event["confidence"], "high")
            self.assertEqual(tool_event["details"]["cwd"], str(workspace))

    def test_load_history_indexes_returns_full_and_filtered_views(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            history_file = Path(temp_dir) / "history.jsonl"
            history_file.write_text(
                "\n".join(
                    [
                        '{"session_id":"inside","ts":"2026-03-09T10:00:00+09:00","text":"review this PR"}',
                        '{"session_id":"outside","ts":"2026-03-07T10:00:00+09:00","text":"old session"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            full_index, filtered_index = load_history_indexes(
                history_file,
                parse_datetime("2026-03-09", bound="start"),
                parse_datetime("2026-03-09", bound="end"),
            )

            self.assertEqual(set(full_index.keys()), {"inside", "outside"})
            self.assertEqual(set(filtered_index.keys()), {"inside"})
            self.assertEqual(filtered_index["inside"]["user_excerpts"], ["review this PR"])

    def test_load_history_indexes_uses_head_tail_excerpts_for_long_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            history_file = Path(temp_dir) / "history.jsonl"
            rows = [
                json.dumps(
                    {
                        "session_id": "inside",
                        "ts": f"2026-03-09T10:{index:02d}:00+09:00",
                        "text": f"message-{index}",
                    }
                )
                for index in range(10)
            ]
            history_file.write_text("\n".join(rows) + "\n", encoding="utf-8")

            _full_index, filtered_index = load_history_indexes(
                history_file,
                parse_datetime("2026-03-09", bound="start"),
                parse_datetime("2026-03-09", bound="end"),
            )

            excerpts = filtered_index["inside"]["user_excerpts"]
            self.assertEqual(len(excerpts), 8)
            self.assertIn("message-0", excerpts[0])
            self.assertTrue(any("message-9" in excerpt for excerpt in excerpts))


if __name__ == "__main__":
    unittest.main()
