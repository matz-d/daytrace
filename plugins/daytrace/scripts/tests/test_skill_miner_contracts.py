#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from skill_miner_prepare import build_parser, read_claude_packets, read_codex_packets


REPO_ROOT = Path(__file__).resolve().parents[4]
PREPARE = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "skill_miner_prepare.py"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


class SkillMinerContractTests(unittest.TestCase):
    def create_recent_fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        recent_a = (now - timedelta(days=2)).isoformat()
        recent_b = (now - timedelta(days=1, hours=4)).isoformat()
        recent_c = (now - timedelta(hours=20)).isoformat()

        claude_root = root / "claude"
        claude_file = claude_root / "repo" / "session-a.jsonl"
        write_jsonl(
            claude_file,
            [
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-review",
                    "isSidechain": False,
                    "timestamp": recent_a,
                    "message": {"role": "user", "content": f"Review {workspace}/src/app.py and return findings first."},
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-review",
                    "isSidechain": False,
                    "timestamp": (datetime.fromisoformat(recent_a) + timedelta(minutes=3)).isoformat(),
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "I will inspect files and return findings by severity."}]},
                },
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-review",
                    "isSidechain": False,
                    "timestamp": recent_b,
                    "message": {"role": "user", "content": f"Review {workspace}/src/api.py with the same findings-first format."},
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-review",
                    "isSidechain": False,
                    "timestamp": (datetime.fromisoformat(recent_b) + timedelta(minutes=5)).isoformat(),
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "I will keep the findings-first review format."}]},
                },
            ],
        )

        codex_history = root / "codex" / "history.jsonl"
        codex_sessions = root / "codex" / "sessions"
        write_jsonl(
            codex_history,
            [
                {
                    "session_id": "codex-review",
                    "ts": int(datetime.fromisoformat(recent_c).timestamp()),
                    "text": f"Review {workspace}/server.py and report findings first.",
                }
            ],
        )
        write_jsonl(
            codex_sessions / "2026" / "03" / "11" / "rollout-review.jsonl",
            [
                {
                    "timestamp": recent_c,
                    "type": "session_meta",
                    "payload": {"id": "codex-review", "timestamp": recent_c, "cwd": str(workspace)},
                },
                {
                    "timestamp": (datetime.fromisoformat(recent_c) + timedelta(seconds=1)).isoformat(),
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": f"Review {workspace}/server.py and keep findings first."},
                },
                {
                    "timestamp": (datetime.fromisoformat(recent_c) + timedelta(seconds=2)).isoformat(),
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "I will inspect the diff and summarize findings by severity."}],
                    },
                },
                {
                    "timestamp": (datetime.fromisoformat(recent_c) + timedelta(seconds=3)).isoformat(),
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "arguments": json.dumps({"cmd": "rg -n TODO src/server.py"}),
                    },
                },
            ],
        )

        return workspace, claude_root, codex_history, codex_sessions

    def create_old_fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        old_a = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        old_b = (datetime.now(timezone.utc) - timedelta(days=19, hours=10)).isoformat()

        claude_root = root / "claude"
        claude_file = claude_root / "repo" / "session-old.jsonl"
        write_jsonl(
            claude_file,
            [
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-old",
                    "isSidechain": False,
                    "timestamp": old_a,
                    "message": {"role": "user", "content": f"Review {workspace}/src/review.py and return findings first with severity ordering."},
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-old",
                    "isSidechain": False,
                    "timestamp": (datetime.fromisoformat(old_a) + timedelta(minutes=2)).isoformat(),
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "I will inspect the diff and summarize findings by severity."}]},
                },
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-old",
                    "isSidechain": False,
                    "timestamp": old_b,
                    "message": {"role": "user", "content": f"Review {workspace}/src/review.py again and keep the same findings-first severity format."},
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-old",
                    "isSidechain": False,
                    "timestamp": (datetime.fromisoformat(old_b) + timedelta(minutes=2)).isoformat(),
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "I will keep the findings-first review format and summarize findings by severity."}]},
                },
            ],
        )

        return workspace, claude_root, root / "missing-history.jsonl", root / "missing-sessions"

    def create_all_sessions_scope_fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        workspace = root / "workspace-a"
        other_workspace = root / "workspace-b"
        workspace.mkdir(parents=True, exist_ok=True)
        other_workspace.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        old_timestamp = (now - timedelta(days=20)).isoformat()
        recent_timestamp = (now - timedelta(days=2)).isoformat()

        claude_root = root / "claude"
        write_jsonl(
            claude_root / "repo" / "session-workspace-old.jsonl",
            [
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-old-workspace",
                    "isSidechain": False,
                    "timestamp": old_timestamp,
                    "message": {"role": "user", "content": f"Review {workspace}/src/app.py and return findings first."},
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-old-workspace",
                    "isSidechain": False,
                    "timestamp": (datetime.fromisoformat(old_timestamp) + timedelta(minutes=2)).isoformat(),
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "I will summarize findings by severity."}]},
                },
            ],
        )
        write_jsonl(
            claude_root / "repo" / "session-other-recent.jsonl",
            [
                {
                    "type": "user",
                    "cwd": str(other_workspace),
                    "sessionId": "claude-recent-global",
                    "isSidechain": False,
                    "timestamp": recent_timestamp,
                    "message": {"role": "user", "content": f"Review {other_workspace}/src/server.py and return findings first."},
                },
                {
                    "type": "assistant",
                    "cwd": str(other_workspace),
                    "sessionId": "claude-recent-global",
                    "isSidechain": False,
                    "timestamp": (datetime.fromisoformat(recent_timestamp) + timedelta(minutes=1)).isoformat(),
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "I will inspect the files and summarize findings by severity."}]},
                },
            ],
        )

        return workspace, claude_root, root / "missing-history.jsonl", root / "missing-sessions"

    def create_workspace_switch_fixture(self, root: Path) -> tuple[Path, Path]:
        workspace = root / "workspace-a"
        other_workspace = root / "workspace-b"
        workspace.mkdir(parents=True, exist_ok=True)
        other_workspace.mkdir(parents=True, exist_ok=True)

        base = datetime.now(timezone.utc)
        claude_root = root / "claude"
        claude_file = claude_root / "repo" / "session-switch.jsonl"
        write_jsonl(
            claude_file,
            [
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-switch",
                    "isSidechain": False,
                    "timestamp": base.isoformat(),
                    "message": {"role": "user", "content": f"Review {workspace}/src/app.py and return findings first."},
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-switch",
                    "isSidechain": False,
                    "timestamp": (base + timedelta(minutes=2)).isoformat(),
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "I will inspect files and return findings by severity."}]},
                },
                {
                    "type": "user",
                    "cwd": str(other_workspace),
                    "sessionId": "claude-switch",
                    "isSidechain": False,
                    "timestamp": (base + timedelta(minutes=5)).isoformat(),
                    "message": {"role": "user", "content": f"Prepare report for {other_workspace}/notes.md."},
                },
                {
                    "type": "assistant",
                    "cwd": str(other_workspace),
                    "sessionId": "claude-switch",
                    "isSidechain": False,
                    "timestamp": (base + timedelta(minutes=7)).isoformat(),
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "I will prepare the markdown draft."}]},
                },
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-switch",
                    "isSidechain": False,
                    "timestamp": (base + timedelta(minutes=10)).isoformat(),
                    "message": {"role": "user", "content": f"Review {workspace}/src/api.py with the same findings-first format."},
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-switch",
                    "isSidechain": False,
                    "timestamp": (base + timedelta(minutes=12)).isoformat(),
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "I will keep the findings-first review format."}]},
                },
            ],
        )
        return workspace, claude_root

    def create_invalid_meta_timestamp_fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        fallback_timestamp = "2026-03-10T09:00:00+09:00"
        claude_root = root / "claude"
        codex_history = root / "codex" / "history.jsonl"
        codex_sessions = root / "codex" / "sessions"
        write_jsonl(
            codex_history,
            [
                {
                    "session_id": "codex-bad-meta",
                    "ts": int(datetime.fromisoformat(fallback_timestamp).timestamp()),
                    "text": f"Review {workspace}/server.py and report findings first.",
                }
            ],
        )
        write_jsonl(
            codex_sessions / "2026" / "03" / "11" / "rollout-bad-meta.jsonl",
            [
                {
                    "timestamp": fallback_timestamp,
                    "type": "session_meta",
                    "payload": {"id": "codex-bad-meta", "timestamp": "not-a-timestamp", "cwd": str(workspace)},
                },
                {
                    "timestamp": (datetime.fromisoformat(fallback_timestamp) + timedelta(seconds=1)).isoformat(),
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": f"Review {workspace}/server.py and keep findings first."},
                },
            ],
        )

        return workspace, claude_root, codex_history, codex_sessions

    def run_prepare(self, workspace: Path, claude_root: Path, codex_history: Path, codex_sessions: Path, *extra_args: str) -> dict:
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
                *extra_args,
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

    def test_parser_defaults_days_to_seven(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        self.assertEqual(args.days, 7)

    def test_prepare_workspace_mode_starts_with_seven_day_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root, codex_history, codex_sessions = self.create_recent_fixture(Path(temp_dir))
            payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)

            self.assertEqual(payload["config"]["days"], 7)
            self.assertEqual(payload["config"]["effective_days"], 7)
            self.assertFalse(payload["config"]["all_sessions"])
            self.assertEqual(payload["config"]["observation_mode"], "workspace")
            self.assertIsNotNone(payload["config"]["date_window_start"])
            self.assertTrue(payload["config"]["adaptive_window"]["enabled"])
            self.assertFalse(payload["config"]["adaptive_window"]["expanded"])
            self.assertFalse(payload["summary"]["adaptive_window_expanded"])
            self.assertGreaterEqual(payload["summary"]["total_packets"], 3)

    def test_prepare_workspace_mode_expands_to_thirty_days_when_sparse(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root, codex_history, codex_sessions = self.create_old_fixture(Path(temp_dir))
            payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)

            self.assertFalse(payload["config"]["all_sessions"])
            self.assertEqual(payload["config"]["effective_days"], 30)
            self.assertEqual(payload["config"]["observation_mode"], "workspace")
            self.assertTrue(payload["config"]["adaptive_window"]["enabled"])
            self.assertTrue(payload["config"]["adaptive_window"]["expanded"])
            self.assertEqual(payload["config"]["adaptive_window"]["reason"], "insufficient_packets")
            self.assertEqual(payload["config"]["adaptive_window"]["initial_packet_count"], 0)
            self.assertEqual(payload["config"]["adaptive_window"]["initial_candidate_count"], 0)
            self.assertTrue(payload["summary"]["adaptive_window_expanded"])
            self.assertEqual(payload["summary"]["total_packets"], 2)
            self.assertEqual(len(payload["candidates"]), 1)
            self.assertIsNotNone(payload["config"]["date_window_start"])

    def test_prepare_all_sessions_removes_workspace_filter_but_keeps_day_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root, codex_history, codex_sessions = self.create_all_sessions_scope_fixture(Path(temp_dir))
            payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions, "--all-sessions")

            self.assertTrue(payload["config"]["all_sessions"])
            self.assertIsNone(payload["config"]["workspace"])
            self.assertEqual(payload["config"]["effective_days"], 7)
            self.assertEqual(payload["config"]["observation_mode"], "all-sessions")
            self.assertFalse(payload["config"]["adaptive_window"]["enabled"])
            self.assertFalse(payload["config"]["adaptive_window"]["expanded"])
            self.assertFalse(payload["summary"]["adaptive_window_expanded"])
            self.assertIsNotNone(payload["config"]["date_window_start"])
            self.assertEqual(payload["summary"]["total_packets"], 1)
            self.assertEqual(payload["candidates"], [])

    def test_prepare_candidate_includes_evidence_items_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root, codex_history, codex_sessions = self.create_recent_fixture(Path(temp_dir))
            payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)

            candidate = payload["candidates"][0]
            evidence_items = candidate["evidence_items"]
            self.assertLessEqual(len(evidence_items), 3)
            self.assertGreaterEqual(len(evidence_items), 2)
            for item in evidence_items:
                self.assertEqual(set(item.keys()), {"session_ref", "timestamp", "source", "summary"})
                self.assertTrue(item["session_ref"])
                self.assertTrue(item["timestamp"])
                self.assertTrue(item["source"])
                self.assertTrue(item["summary"])

    def test_prepare_dump_intents_includes_summary_and_anonymized_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root, codex_history, codex_sessions = self.create_recent_fixture(Path(temp_dir))
            payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions, "--dump-intents")

            self.assertIn("intent_analysis", payload)
            summary = payload["intent_analysis"]["summary"]
            self.assertIn("generic_rate", summary)
            self.assertIn("synonym_split_rate", summary)
            self.assertIn("specificity_distribution", summary)
            self.assertEqual(set(summary["specificity_distribution"].keys()), {"high", "medium", "low"})

            items = payload["intent_analysis"]["items"]
            self.assertTrue(items)
            first = items[0]
            self.assertEqual(set(first.keys()), {"sample_id", "timestamp", "source", "primary_intent", "specificity", "is_generic"})
            self.assertNotIn(str(workspace), first["primary_intent"])

    def test_read_claude_packets_splits_when_workspace_switches_away_and_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root = self.create_workspace_switch_fixture(Path(temp_dir))

            packets, source = read_claude_packets(claude_root, workspace, gap_hours=8)

            self.assertEqual(source["status"], "success")
            self.assertEqual(len(packets), 2)
            self.assertTrue(all(packet["workspace"] == str(workspace) for packet in packets))
            self.assertEqual([packet["packet_id"] for packet in packets], ["claude:repo:session-switch:000", "claude:repo:session-switch:001"])

    def test_read_codex_packets_falls_back_when_meta_timestamp_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _claude_root, codex_history, codex_sessions = self.create_invalid_meta_timestamp_fixture(Path(temp_dir))

            packets, source = read_codex_packets(codex_history, codex_sessions, workspace)

            self.assertEqual(source["status"], "success")
            self.assertEqual(len(packets), 1)
            expected_epoch = int(datetime.fromisoformat("2026-03-10T09:00:00+09:00").timestamp())
            actual_epoch = int(datetime.fromisoformat(packets[0]["timestamp"]).timestamp())
            self.assertEqual(actual_epoch, expected_epoch)
            self.assertEqual(packets[0]["session_ref"], f"codex:codex-bad-meta:{expected_epoch}")


if __name__ == "__main__":
    unittest.main()
