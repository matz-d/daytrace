#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from conftest import PROJECT_ROOT, PLUGIN_ROOT

from skill_miner_common import build_claude_session_ref, build_codex_session_ref


DETAIL = PLUGIN_ROOT / "scripts" / "skill_miner_detail.py"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


class SkillMinerDetailCLITests(unittest.TestCase):
    def test_cli_resolves_claude_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            claude_file = root / "claude" / "repo" / "session-a.jsonl"
            started_at = "2026-03-09T10:00:00+09:00"
            write_jsonl(
                claude_file,
                [
                    {
                        "type": "user",
                        "cwd": str(workspace),
                        "sessionId": "claude-review",
                        "isSidechain": False,
                        "timestamp": started_at,
                        "message": {"role": "user", "content": "Review this change and summarize findings."},
                    },
                    {
                        "type": "assistant",
                        "cwd": str(workspace),
                        "sessionId": "claude-review",
                        "isSidechain": False,
                        "timestamp": "2026-03-09T10:05:00+09:00",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "I will inspect the diff and report findings first."}]},
                    },
                ],
            )
            session_ref = build_claude_session_ref(str(claude_file), started_at)

            completed = subprocess.run(
                [
                    "python3",
                    str(DETAIL),
                    "--refs",
                    session_ref,
                    "--codex-history-file",
                    str(root / "missing-history.jsonl"),
                    "--codex-sessions-root",
                    str(root / "missing-sessions"),
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["errors"], [])
            self.assertEqual(len(payload["details"]), 1)
            self.assertEqual(payload["details"][0]["source"], "claude-history")
            self.assertIn("Review this change", payload["details"][0]["messages"][0]["text"])

    def test_cli_resolves_codex_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sessions_root = root / "codex" / "sessions"
            history_file = root / "codex" / "history.jsonl"
            session_id = "codex-review"
            started_at = "2026-03-09T11:00:00+09:00"

            write_jsonl(
                history_file,
                [
                    {
                        "session_id": session_id,
                        "ts": 1773021600,
                        "text": "Review this PR and keep findings first.",
                    }
                ],
            )
            write_jsonl(
                sessions_root / "2026" / "03" / "09" / "rollout-review.jsonl",
                [
                    {
                        "timestamp": started_at,
                        "type": "session_meta",
                        "payload": {"id": session_id, "timestamp": started_at, "cwd": str(root / "workspace")},
                    },
                    {
                        "timestamp": "2026-03-09T11:00:01+09:00",
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "Review the diff and summarize issues."},
                    },
                    {
                        "timestamp": "2026-03-09T11:00:02+09:00",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "I will inspect files and list findings first."}],
                        },
                    },
                    {
                        "timestamp": "2026-03-09T11:00:03+09:00",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "arguments": json.dumps({"cmd": "rg -n TODO src && git diff -- src/server.py"}),
                        },
                    },
                ],
            )
            session_ref = build_codex_session_ref(session_id, started_at)

            completed = subprocess.run(
                [
                    "python3",
                    str(DETAIL),
                    "--refs",
                    session_ref,
                    "--codex-history-file",
                    str(history_file),
                    "--codex-sessions-root",
                    str(sessions_root),
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["errors"], [])
            self.assertEqual(len(payload["details"]), 1)
            self.assertEqual(payload["details"][0]["source"], "codex-history")
            self.assertTrue(any(tool["name"] == "rg" for tool in payload["details"][0]["tool_calls"]))

    def test_cli_resolves_later_codex_logical_packet_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sessions_root = root / "codex" / "sessions"
            history_file = root / "codex" / "history.jsonl"
            workspace = root / "workspace"
            session_id = "codex-split"
            workspace.mkdir()

            write_jsonl(
                history_file,
                [
                    {
                        "session_id": session_id,
                        "ts": "2026-03-09T11:00:00+09:00",
                        "text": "Review this PR and keep findings first.",
                    }
                ],
            )
            write_jsonl(
                sessions_root / "2026" / "03" / "09" / "rollout-review.jsonl",
                [
                    {
                        "timestamp": "2026-03-09T11:00:00+09:00",
                        "type": "session_meta",
                        "payload": {"id": session_id, "timestamp": "2026-03-09T11:00:00+09:00", "cwd": str(workspace)},
                    },
                    {
                        "timestamp": "2026-03-09T11:00:01+09:00",
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "Review the diff and summarize issues."},
                    },
                    {
                        "timestamp": "2026-03-09T11:00:02+09:00",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "id": "call-1",
                            "name": "exec_command",
                            "arguments": json.dumps({"cmd": "rg -n TODO src && git diff -- src/server.py"}),
                        },
                    },
                    {
                        "timestamp": "2026-03-09T11:00:03+09:00",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": "call-1",
                            "status": "error",
                            "exit_code": 1,
                            "stderr": "rg failed",
                        },
                    },
                    {
                        "timestamp": "2026-03-09T11:00:04+09:00",
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "Instead, draft release notes."},
                    },
                    {
                        "timestamp": "2026-03-09T11:00:05+09:00",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Switching to release note drafting."}],
                        },
                    },
                ],
            )
            session_ref = build_codex_session_ref(session_id, "2026-03-09T11:00:04+09:00")

            completed = subprocess.run(
                [
                    "python3",
                    str(DETAIL),
                    "--refs",
                    session_ref,
                    "--codex-history-file",
                    str(history_file),
                    "--codex-sessions-root",
                    str(sessions_root),
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["details"][0]["messages"][0]["text"], "Instead, draft release notes.")


if __name__ == "__main__":
    unittest.main()
