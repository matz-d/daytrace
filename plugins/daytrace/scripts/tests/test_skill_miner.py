#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from skill_miner_common import compact_snippet


REPO_ROOT = Path(__file__).resolve().parents[4]
PREPARE = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "skill_miner_prepare.py"
DETAIL = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "skill_miner_detail.py"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


class SkillMinerTests(unittest.TestCase):
    def create_fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        claude_root = root / "claude"
        codex_history = root / "codex" / "history.jsonl"
        codex_sessions = root / "codex" / "sessions"

        claude_file = claude_root / "repo" / "session-a.jsonl"
        write_jsonl(
            claude_file,
            [
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-review",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T00:00:00+09:00",
                    "message": {
                        "role": "user",
                        "content": (
                            f"Please review [WORKSPACE] findings in {workspace}/src/app.py and summarize by severity. "
                            "See https://example.com/path?a=1#frag"
                        ),
                    },
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-review",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T00:05:00+09:00",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "I will review the diff and list findings by severity with file and line references."}
                        ],
                    },
                },
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-review",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T09:30:00+09:00",
                    "message": {
                        "role": "user",
                        "content": f"Review another PR under {workspace}/src/api.py and keep the same findings-first format.",
                    },
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-review",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T09:40:00+09:00",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "I will inspect the files and return findings first, severity ordered, with file-line refs."}
                        ],
                    },
                },
            ],
        )

        write_jsonl(
            codex_history,
            [
                {
                    "session_id": "codex-review",
                    "ts": 1772985600,
                    "text": f"Please review the PR in {workspace}/server.py and return findings with severity ordering.",
                },
                {
                    "session_id": "codex-build",
                    "ts": 1772992800,
                    "text": "Implement a new CLI command and update the config file.",
                },
            ],
        )

        review_rollout = codex_sessions / "2026" / "03" / "09" / "rollout-review.jsonl"
        build_rollout = codex_sessions / "2026" / "03" / "09" / "rollout-build.jsonl"

        write_jsonl(
            review_rollout,
            [
                {
                    "timestamp": "2026-03-09T01:00:00+09:00",
                    "type": "session_meta",
                    "payload": {
                        "id": "codex-review",
                        "timestamp": "2026-03-09T01:00:00+09:00",
                        "cwd": str(workspace),
                    },
                },
                {
                    "timestamp": "2026-03-09T01:00:01+09:00",
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": f"Review this PR in {workspace}/server.py and report findings first.",
                    },
                },
                {
                    "timestamp": "2026-03-09T01:00:02+09:00",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "I will inspect files and summarize findings by severity."}],
                    },
                },
                {
                    "timestamp": "2026-03-09T01:00:03+09:00",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "arguments": json.dumps({"cmd": "rg -n TODO src && sed -n '1,20p' src/server.py"}),
                    },
                },
                {
                    "timestamp": "2026-03-09T01:00:04+09:00",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "arguments": json.dumps({"cmd": "git diff -- src/server.py"}),
                    },
                },
            ],
        )

        write_jsonl(
            build_rollout,
            [
                {
                    "timestamp": "2026-03-09T03:00:00+09:00",
                    "type": "session_meta",
                    "payload": {
                        "id": "codex-build",
                        "timestamp": "2026-03-09T03:00:00+09:00",
                        "cwd": str(workspace),
                    },
                },
                {
                    "timestamp": "2026-03-09T03:00:01+09:00",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "Implement a new CLI command and edit config."},
                },
                {
                    "timestamp": "2026-03-09T03:00:02+09:00",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "I will implement the feature and update the config."}],
                    },
                },
                {
                    "timestamp": "2026-03-09T03:00:03+09:00",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "arguments": json.dumps({"cmd": "python3 scripts/build.py"}),
                    },
                },
            ],
        )

        return workspace, claude_root, codex_history, codex_sessions

    def run_prepare(self, workspace: Path, claude_root: Path, codex_history: Path, codex_sessions: Path) -> dict:
        completed = subprocess.run(
            [
                "python3",
                str(PREPARE),
                "--workspace",
                str(workspace),
                "--claude-root",
                str(claude_root),
                "--codex-history-file",
                str(codex_history),
                "--codex-sessions-root",
                str(codex_sessions),
                "--top-n",
                "5",
                "--max-unclustered",
                "5",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "success", msg=completed.stdout)
        return payload

    def test_prepare_builds_candidates_and_masks_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(Path(temp_dir))
            payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)

            self.assertEqual(payload["summary"]["total_packets"], 4)
            self.assertGreaterEqual(payload["summary"]["block_count"], 1)
            self.assertEqual(len(payload["candidates"]), 1)
            candidate = payload["candidates"][0]
            self.assertEqual(candidate["support"]["total_packets"], 3)
            self.assertEqual(candidate["support"]["claude_packets"], 2)
            self.assertEqual(candidate["support"]["codex_packets"], 1)
            self.assertIn("review_changes", candidate["common_task_shapes"])
            self.assertIn("summarize_findings", candidate["common_task_shapes"])
            self.assertIn("rg", candidate["common_tool_signatures"])
            self.assertEqual(len(candidate["session_refs"]), 3)
            self.assertGreater(candidate["score"], 0)

            snippets = "\n".join(candidate["representative_examples"] + payload["unclustered"][0]["representative_snippets"])
            self.assertNotIn(str(workspace), snippets)
            self.assertIn("[WORKSPACE]", snippets)
            self.assertNotIn("?a=1", snippets)
            masked_url = compact_snippet("See https://example.com/path?a=1#frag", str(workspace))
            self.assertEqual(masked_url, "See https://example.com")

    def test_detail_resolves_prepare_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(Path(temp_dir))
            payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)
            refs = payload["candidates"][0]["session_refs"][:2]

            completed = subprocess.run(
                [
                    "python3",
                    str(DETAIL),
                    "--refs",
                    *refs,
                    "--gap-hours",
                    "8",
                    "--codex-history-file",
                    str(codex_history),
                    "--codex-sessions-root",
                    str(codex_sessions),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            details_payload = json.loads(completed.stdout)
            self.assertEqual(details_payload["status"], "success", msg=completed.stdout)
            self.assertEqual(len(details_payload["errors"]), 0)
            self.assertEqual(len(details_payload["details"]), 2)

            codex_detail = next(item for item in details_payload["details"] if item["source"] == "codex-history")
            claude_detail = next(item for item in details_payload["details"] if item["source"] == "claude-history")

            self.assertTrue(any(message["role"] == "user" for message in codex_detail["messages"]))
            self.assertTrue(any(tool["name"] == "rg" for tool in codex_detail["tool_calls"]))
            self.assertTrue(any("findings" in message["text"].lower() for message in claude_detail["messages"]))

    def test_prepare_handles_missing_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(
                [
                    "python3",
                    str(PREPARE),
                    "--workspace",
                    str(workspace),
                    "--claude-root",
                    str(root / "missing-claude"),
                    "--codex-history-file",
                    str(root / "missing-history.jsonl"),
                    "--codex-sessions-root",
                    str(root / "missing-sessions"),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertTrue(payload["summary"]["no_sources_available"])
            self.assertEqual(payload["candidates"], [])

    def test_prepare_handles_permission_denied(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            claude_root = root / "claude"
            blocked = claude_root / "repo" / "blocked.jsonl"
            blocked.parent.mkdir(parents=True, exist_ok=True)
            blocked.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "cwd": str(workspace),
                        "sessionId": "blocked",
                        "isSidechain": False,
                        "timestamp": "2026-03-09T00:00:00+09:00",
                        "message": {"role": "user", "content": "blocked"},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            os.chmod(blocked, 0)
            try:
                completed = subprocess.run(
                    [
                        "python3",
                        str(PREPARE),
                        "--workspace",
                        str(workspace),
                        "--claude-root",
                        str(claude_root),
                        "--codex-history-file",
                        str(root / "missing-history.jsonl"),
                        "--codex-sessions-root",
                        str(root / "missing-sessions"),
                    ],
                    cwd=str(REPO_ROOT),
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                os.chmod(blocked, stat.S_IRUSR | stat.S_IWUSR)

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            claude_status = next(item for item in payload["sources"] if item["name"] == "claude-history")
            self.assertEqual(claude_status["status"], "skipped")
            self.assertEqual(claude_status["reason"], "permission_denied")

    def test_prepare_ignores_broken_jsonl_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            claude_root = root / "claude"
            broken = claude_root / "repo" / "broken.jsonl"
            broken.parent.mkdir(parents=True, exist_ok=True)
            broken.write_text(
                textwrap.dedent(
                    f"""
                    not-json
                    {json.dumps({"type":"user","cwd":str(workspace),"sessionId":"ok","isSidechain":False,"timestamp":"2026-03-09T00:00:00+09:00","message":{"role":"user","content":"review this"}})}
                    {json.dumps({"type":"assistant","cwd":str(workspace),"sessionId":"ok","isSidechain":False,"timestamp":"2026-03-09T00:01:00+09:00","message":{"role":"assistant","content":[{"type":"text","text":"findings first"}]}})}
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "python3",
                    str(PREPARE),
                    "--workspace",
                    str(workspace),
                    "--claude-root",
                    str(claude_root),
                    "--codex-history-file",
                    str(root / "missing-history.jsonl"),
                    "--codex-sessions-root",
                    str(root / "missing-sessions"),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["summary"]["total_packets"], 1)


if __name__ == "__main__":
    unittest.main()
