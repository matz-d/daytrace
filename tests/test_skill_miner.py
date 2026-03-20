#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None

from conftest import PROJECT_ROOT, PLUGIN_ROOT

from skill_miner_common import (
    apply_tool_result_metadata,
    annotate_unclustered_packet,
    build_candidate_content_key,
    build_candidate_decision_key,
    build_candidate_quality,
    build_tool_call_detail,
    build_proposal_sections,
    candidate_label,
    compact_snippet,
    codex_tool_result_metadata,
    extract_referenced_files,
    infer_workflow_signals,
    judge_research_candidate,
)
from derived_store import get_observations
import skill_miner_prepare
from skill_miner_prepare import (
    _store_slice_bounds,
    apply_decision_states_to_candidates,
    build_candidate_comparison,
    filter_packets_by_days,
    load_latest_decision_states,
    read_claude_packets,
    read_codex_packets,
    read_store_packets,
)


PREPARE = PLUGIN_ROOT / "scripts" / "skill_miner_prepare.py"
DETAIL = PLUGIN_ROOT / "scripts" / "skill_miner_detail.py"
RESEARCH_JUDGE = PLUGIN_ROOT / "scripts" / "skill_miner_research_judge.py"
PROPOSAL = PLUGIN_ROOT / "scripts" / "skill_miner_proposal.py"
AGGREGATE = PLUGIN_ROOT / "scripts" / "aggregate.py"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


class SkillMinerTests(unittest.TestCase):
    def test_extract_referenced_files_strips_only_workspace_boundary(self) -> None:
        workspace = "/home/user/project"
        files = extract_referenced_files(
            [
                {
                    "command": (
                        "python3 /home/user/project/src/app.py "
                        "/home/user/project-other/file.py"
                    )
                }
            ],
            workspace,
        )
        self.assertIn("src/app.py", files)
        self.assertIn("/home/user/project-other/file.py", files)
        self.assertNotIn("-other/file.py", files)

    def test_infer_workflow_signals_prefers_explicit_failure_and_retry_metadata(self) -> None:
        workspace = "/tmp/daytrace-workspace"
        failed_call = build_tool_call_detail(
            "pytest",
            {"cmd": "pytest plugins/daytrace/scripts/tests -q"},
            workspace=workspace,
            invocation_kind="exec_command",
            result_status="error",
            exit_code=1,
            error_excerpt="pytest failed",
        )
        retried_call = build_tool_call_detail(
            "pytest",
            {"cmd": "pytest plugins/daytrace/scripts/tests -q"},
            workspace=workspace,
            invocation_kind="exec_command",
            result_status="success",
            exit_code=0,
        )

        signals = infer_workflow_signals([], [], [failed_call, retried_call], workspace)

        self.assertEqual(set(signals["flags"]), {"failure", "retry"})
        self.assertTrue(any("Explicit tool failure" in item["snippet"] for item in signals["failure_hints"]))
        self.assertTrue(any("Retry after explicit failure" in item["snippet"] for item in signals["retry_hints"]))

    def test_missing_codex_result_metadata_preserves_heuristic_signal_fallback(self) -> None:
        workspace = "/tmp/daytrace-workspace"
        detail = build_tool_call_detail(
            "pytest",
            {"cmd": "pytest plugins/daytrace/scripts/tests -q"},
            workspace=workspace,
            invocation_kind="exec_command",
        )
        metadata = codex_tool_result_metadata({"type": "function_call_output", "call_id": "call-1"}, workspace)

        self.assertEqual(metadata, {})
        updated = apply_tool_result_metadata(detail, metadata, workspace)
        self.assertNotIn("result_status", updated)

        signals = infer_workflow_signals(["The previous run failed. Please retry it."], [], [updated], workspace)

        self.assertEqual(set(signals["flags"]), {"failure", "retry"})
        self.assertTrue(signals["failure_hints"])
        self.assertTrue(signals["retry_hints"])

    def test_success_result_metadata_does_not_promote_message_to_error_excerpt(self) -> None:
        workspace = "/tmp/daytrace-workspace"
        metadata = codex_tool_result_metadata(
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "status": "success",
                "message": f"stdout-like text from {workspace}/result.txt",
            },
            workspace,
        )

        self.assertEqual(metadata, {"result_status": "success"})
        detail = build_tool_call_detail(
            "python3",
            {"cmd": "python3 script.py"},
            workspace=workspace,
            invocation_kind="exec_command",
        )
        updated = apply_tool_result_metadata(detail, metadata, workspace)
        self.assertEqual(updated["result_status"], "success")
        self.assertNotIn("error_excerpt", updated)

    def test_read_codex_packets_splits_failed_tool_phase_from_followup_pivot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            history_file = root / "codex" / "history.jsonl"
            sessions_root = root / "codex" / "sessions"
            session_id = "codex-split"

            write_jsonl(
                history_file,
                [
                    {
                        "session_id": session_id,
                        "ts": "2026-03-12T09:00:00+09:00",
                        "text": "Review the diff and summarize findings.",
                    }
                ],
            )
            write_jsonl(
                sessions_root / "2026" / "03" / "12" / "rollout-split.jsonl",
                [
                    {
                        "timestamp": "2026-03-12T09:00:00+09:00",
                        "type": "session_meta",
                        "payload": {"id": session_id, "timestamp": "2026-03-12T09:00:00+09:00", "cwd": str(workspace)},
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
                            "type": "function_call",
                            "id": "call-1",
                            "name": "exec_command",
                            "arguments": json.dumps({"cmd": "pytest plugins/daytrace/scripts/tests -q"}),
                        },
                    },
                    {
                        "timestamp": "2026-03-12T09:00:03+09:00",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": "call-1",
                            "status": "error",
                            "exit_code": 1,
                            "stderr": "pytest failed",
                        },
                    },
                    {
                        "timestamp": "2026-03-12T09:00:04+09:00",
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "Instead, draft release notes."},
                    },
                    {
                        "timestamp": "2026-03-12T09:00:05+09:00",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Switching to release note drafting."}],
                        },
                    },
                ],
            )

            packets, source = read_codex_packets(history_file, sessions_root, workspace, 8)

            self.assertEqual(source["status"], "success")
            self.assertEqual(len(packets), 2)
            self.assertEqual(packets[0]["workflow_signals"]["counts"]["failure"], 1)
            self.assertEqual(packets[0]["workflow_signals"]["flags"], ["failure"])
            self.assertIn("Instead, draft release notes.", packets[1]["full_user_intent"])

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

    def _require_new_york_tz(self) -> "ZoneInfo":
        if ZoneInfo is None:
            self.skipTest("zoneinfo is unavailable")
        try:
            return ZoneInfo("America/New_York")
        except Exception as exc:  # pragma: no cover - depends on system tzdata
            self.skipTest(f"America/New_York timezone unavailable: {exc}")

    def _filter_packets_at(self, packets: list[dict[str, object]], *, now: datetime, tz: "ZoneInfo", days: int) -> tuple[list[dict[str, object]], str | None]:
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tzinfo=None):  # type: ignore[override]
                if tzinfo is None:
                    return now.replace(tzinfo=None)
                return now.astimezone(tzinfo)

        with patch.object(skill_miner_prepare, "LOCAL_TZ", tz), patch.object(skill_miner_prepare, "datetime", FixedDateTime):
            return filter_packets_by_days(packets, days)

    def create_wrapper_heavy_fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        claude_root = root / "claude"
        codex_history = root / "codex" / "history.jsonl"
        codex_sessions = root / "codex" / "sessions"

        claude_file = claude_root / "repo" / "session-wrapper.jsonl"
        write_jsonl(
            claude_file,
            [
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-wrapper",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T11:00:00+09:00",
                    "message": {"role": "user", "content": "<command-name>/clear</command-name> <command-message>clear</command-message>"},
                },
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-wrapper",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T11:00:15+09:00",
                    "message": {"role": "user", "content": "<command-name>/simplify</command-name> <command-message>simplify</command-message>"},
                },
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-wrapper",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T11:00:30+09:00",
                    "message": {"role": "user", "content": "<task-notification>subagent started</task-notification>"},
                },
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-wrapper",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T11:01:00+09:00",
                    "message": {
                        "role": "user",
                        "content": (
                            f"Inspect {workspace}/plugins/daytrace/scripts/skill_miner_prepare.py with `rg` and `git diff`, "
                            "then write a markdown report about raw/store parity and include research targets."
                        ),
                    },
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-wrapper",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T11:02:00+09:00",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": "I will inspect the parity issue with rg, git diff, and python3, then write findings in markdown.",
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-wrapper",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T20:30:00+09:00",
                    "message": {"role": "user", "content": "<command-name>/clear</command-name> <command-message>clear</command-message>"},
                },
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-wrapper",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T20:30:15+09:00",
                    "message": {"role": "user", "content": "<command-name>/simplify</command-name> <command-message>simplify</command-message>"},
                },
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-wrapper",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T20:30:30+09:00",
                    "message": {"role": "user", "content": "<task-notification>subagent started</task-notification>"},
                },
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-wrapper",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T20:31:00+09:00",
                    "message": {
                        "role": "user",
                        "content": (
                            f"Inspect {workspace}/plugins/daytrace/scripts/skill_miner_prepare.py with `rg` and `git diff`, "
                            "then write another markdown report about raw/store parity and keep the research targets."
                        ),
                    },
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-wrapper",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T20:32:00+09:00",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": "I will inspect the script again with rg, git diff, and python3, then write the parity findings in markdown.",
                            }
                        ],
                    },
                },
            ],
        )

        write_jsonl(
            codex_history,
            [
                {"session_id": "codex-wrapper", "ts": 1773021000, "text": "Start a parity review session."},
                {"session_id": "codex-wrapper", "ts": 1773021030, "text": "Keep the same wrapper handling as before."},
                {"session_id": "codex-wrapper", "ts": 1773021060, "text": "Use the existing workflow and avoid unrelated changes."},
                {
                    "session_id": "codex-wrapper",
                    "ts": 1773021090,
                    "text": (
                        f"Inspect {workspace}/plugins/daytrace/scripts/skill_miner_prepare.py, run `rg` and `git diff`, "
                        "and write a markdown parity report with research targets."
                    ),
                },
                {"session_id": "codex-wrapper-2", "ts": 1773053700, "text": "Start a second parity review session."},
                {"session_id": "codex-wrapper-2", "ts": 1773053730, "text": "Keep the same wrapper handling as before."},
                {"session_id": "codex-wrapper-2", "ts": 1773053760, "text": "Use the existing workflow and avoid unrelated changes."},
                {
                    "session_id": "codex-wrapper-2",
                    "ts": 1773053790,
                    "text": (
                        f"Inspect {workspace}/plugins/daytrace/scripts/skill_miner_prepare.py, run `rg` and `git diff`, "
                        "and write another markdown parity report with research targets."
                    ),
                },
                {"session_id": "codex-build", "ts": 1773024600, "text": "Implement another feature and update config."},
            ],
        )

        wrapper_rollout = codex_sessions / "2026" / "03" / "09" / "rollout-wrapper.jsonl"
        wrapper_rollout_two = codex_sessions / "2026" / "03" / "09" / "rollout-wrapper-two.jsonl"
        build_rollout = codex_sessions / "2026" / "03" / "09" / "rollout-build.jsonl"
        write_jsonl(
            wrapper_rollout,
            [
                {
                    "timestamp": "2026-03-09T11:05:00+09:00",
                    "type": "session_meta",
                    "payload": {"id": "codex-wrapper", "timestamp": "2026-03-09T11:05:00+09:00", "cwd": str(workspace)},
                },
                {
                    "timestamp": "2026-03-09T11:05:01+09:00",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "Continue the parity fix and keep command signals."},
                },
                {
                    "timestamp": "2026-03-09T11:05:02+09:00",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "I will inspect the script, preserve rg/git/python3 signals, and report the drift."}],
                    },
                },
                {
                    "timestamp": "2026-03-09T11:05:03+09:00",
                    "type": "response_item",
                    "payload": {"type": "function_call", "name": "exec_command", "arguments": json.dumps({"cmd": "rg -n parity plugins/daytrace/scripts/skill_miner_prepare.py"})},
                },
                {
                    "timestamp": "2026-03-09T11:05:04+09:00",
                    "type": "response_item",
                    "payload": {"type": "function_call", "name": "exec_command", "arguments": json.dumps({"cmd": "git diff -- plugins/daytrace/scripts/skill_miner_prepare.py"})},
                },
                {
                    "timestamp": "2026-03-09T11:05:05+09:00",
                    "type": "response_item",
                    "payload": {"type": "function_call", "name": "exec_command", "arguments": json.dumps({"cmd": "python3 plugins/daytrace/scripts/skill_miner_prepare.py --help"})},
                },
            ],
        )
        write_jsonl(
            wrapper_rollout_two,
            [
                {
                    "timestamp": "2026-03-09T20:35:00+09:00",
                    "type": "session_meta",
                    "payload": {"id": "codex-wrapper-2", "timestamp": "2026-03-09T20:35:00+09:00", "cwd": str(workspace)},
                },
                {
                    "timestamp": "2026-03-09T20:35:01+09:00",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "Continue the parity fix and keep command signals."},
                },
                {
                    "timestamp": "2026-03-09T20:35:02+09:00",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "I will inspect the script, preserve rg/git/python3 signals, and report the drift again."}],
                    },
                },
                {
                    "timestamp": "2026-03-09T20:35:03+09:00",
                    "type": "response_item",
                    "payload": {"type": "function_call", "name": "exec_command", "arguments": json.dumps({"cmd": "rg -n parity plugins/daytrace/scripts/skill_miner_prepare.py"})},
                },
                {
                    "timestamp": "2026-03-09T20:35:04+09:00",
                    "type": "response_item",
                    "payload": {"type": "function_call", "name": "exec_command", "arguments": json.dumps({"cmd": "git diff -- plugins/daytrace/scripts/skill_miner_prepare.py"})},
                },
                {
                    "timestamp": "2026-03-09T20:35:05+09:00",
                    "type": "response_item",
                    "payload": {"type": "function_call", "name": "exec_command", "arguments": json.dumps({"cmd": "python3 plugins/daytrace/scripts/skill_miner_prepare.py --help"})},
                },
            ],
        )
        write_jsonl(
            build_rollout,
            [
                {
                    "timestamp": "2026-03-09T12:10:00+09:00",
                    "type": "session_meta",
                    "payload": {"id": "codex-build", "timestamp": "2026-03-09T12:10:00+09:00", "cwd": str(workspace)},
                },
                {
                    "timestamp": "2026-03-09T12:10:01+09:00",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "Implement another feature and edit config."},
                },
                {
                    "timestamp": "2026-03-09T12:10:02+09:00",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "I will implement the feature and update the config."}],
                    },
                },
            ],
        )

        return workspace, claude_root, codex_history, codex_sessions

    def create_claude_contamination_fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        claude_root = root / "claude"
        codex_history = root / "codex" / "history.jsonl"
        codex_sessions = root / "codex" / "sessions"
        write_jsonl(codex_history, [])

        main_file = claude_root / "repo" / "session-main.jsonl"
        write_jsonl(
            main_file,
            [
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-main",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T09:00:00+09:00",
                    "message": {"role": "user", "content": "Review src/app.py and return findings first."},
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-main",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T09:00:10+09:00",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "toolu_read",
                                "name": "Read",
                                "input": {"file_path": str(workspace / "src" / "app.py")},
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-main",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T09:00:11+09:00",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "tool_use_id": "toolu_read",
                                "type": "tool_result",
                                "content": "1→from __future__ import annotations\n2→def helper():\n3→    pass",
                                "is_error": False,
                            }
                        ],
                    },
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-main",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T09:00:30+09:00",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "I will inspect the file and report findings by severity."}],
                    },
                },
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-main",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T09:30:00+09:00",
                    "message": {
                        "role": "user",
                        "content": "<command-name>/clear</command-name> <command-message>clear</command-message>",
                    },
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-main",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T09:30:15+09:00",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "I will inspect unrelated files and summarize the structure."}],
                    },
                },
            ],
        )

        sidechain_file = claude_root / "repo" / "subagents" / "agent-side.jsonl"
        write_jsonl(
            sidechain_file,
            [
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-side",
                    "isSidechain": True,
                    "timestamp": "2026-03-09T10:00:00+09:00",
                    "message": {
                        "role": "user",
                        "content": "Explore the skill structure and return the full content of each SKILL.md file.",
                    },
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-side",
                    "isSidechain": True,
                    "timestamp": "2026-03-09T10:00:20+09:00",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "I will inspect the skill files and summarize the structure."}],
                    },
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
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "success", msg=completed.stdout)
        return payload

    def write_sources_file(self, root: Path, claude_root: Path, codex_history: Path, codex_sessions: Path) -> Path:
        sources_file = root / "sources.json"
        sources_file.write_text(
            json.dumps(
                [
                    {
                        "name": "claude-history",
                        "command": f"python3 {PLUGIN_ROOT / 'scripts' / 'claude_history.py'} --root {claude_root}",
                        "required": False,
                        "timeout_sec": 30,
                        "platforms": ["darwin", "linux"],
                        "supports_date_range": True,
                        "supports_all_sessions": True,
                        "scope_mode": "all-day",
                        "prerequisites": [],
                        "confidence_category": "ai_history",
                    },
                    {
                        "name": "codex-history",
                        "command": f"python3 {PLUGIN_ROOT / 'scripts' / 'codex_history.py'} --history-file {codex_history} --sessions-root {codex_sessions}",
                        "required": False,
                        "timeout_sec": 30,
                        "platforms": ["darwin", "linux"],
                        "supports_date_range": True,
                        "supports_all_sessions": True,
                        "scope_mode": "all-day",
                        "prerequisites": [],
                        "confidence_category": "ai_history",
                    },
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return sources_file

    def seed_store(self, workspace: Path, claude_root: Path, codex_history: Path, codex_sessions: Path, store_path: Path) -> None:
        sources_file = self.write_sources_file(store_path.parent, claude_root, codex_history, codex_sessions)
        completed = subprocess.run(
            [
                "python3",
                str(AGGREGATE),
                "--sources-file",
                str(sources_file),
                "--workspace",
                str(workspace),
                "--since",
                "2026-03-01",
                "--until",
                "2026-03-12",
                "--store-path",
                str(store_path),
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)

    def invalidate_store_skill_miner_packets(self, store_path: Path, *, drop_key: str) -> None:
        connection = sqlite3.connect(store_path)
        rows = connection.execute(
            """
            SELECT id, source_name, details_json
            FROM observations
            WHERE source_name IN ('claude-history', 'codex-history')
            """
        ).fetchall()
        for observation_id, source_name, details_json in rows:
            details = json.loads(str(details_json))
            if source_name == "claude-history":
                if str(details.get("packet_id") or "").strip():
                    details.pop(drop_key, None)
                summary_packet = details.get("ai_observation")
                if isinstance(summary_packet, dict):
                    summary_packet.pop(drop_key, None)
                ai_observation_packets = details.get("ai_observation_packets", [])
                if isinstance(ai_observation_packets, list):
                    for packet in ai_observation_packets:
                        if isinstance(packet, dict):
                            packet.pop(drop_key, None)
                logical_packets = details.get("logical_packets", [])
                if isinstance(logical_packets, list):
                    for logical_packet in logical_packets:
                        if not isinstance(logical_packet, dict):
                            continue
                        packet = logical_packet.get("ai_observation")
                        if isinstance(packet, dict):
                            packet.pop(drop_key, None)
                        packet = logical_packet.get("skill_miner_packet")
                        if isinstance(packet, dict):
                            packet.pop(drop_key, None)
            else:
                if str(details.get("packet_id") or "").strip():
                    details.pop(drop_key, None)
                packet = details.get("ai_observation")
                if isinstance(packet, dict):
                    packet.pop(drop_key, None)
                ai_observation_packets = details.get("ai_observation_packets", [])
                if isinstance(ai_observation_packets, list):
                    for item in ai_observation_packets:
                        if isinstance(item, dict):
                            item.pop(drop_key, None)
                packet = details.get("skill_miner_packet")
                if isinstance(packet, dict):
                    packet.pop(drop_key, None)
            connection.execute(
                "UPDATE observations SET details_json = ? WHERE id = ?",
                (json.dumps(details, ensure_ascii=False), int(observation_id)),
            )
        connection.commit()
        connection.close()

    def override_claude_packet_observations(self, store_path: Path, **updates: object) -> None:
        connection = sqlite3.connect(store_path)
        rows = connection.execute(
            """
            SELECT id, details_json
            FROM observations
            WHERE source_name = 'claude-history' AND observation_kind = 'packet'
            """
        ).fetchall()
        for observation_id, details_json in rows:
            details = json.loads(str(details_json))
            if isinstance(details, dict):
                details.update(updates)
            connection.execute(
                "UPDATE observations SET details_json = ? WHERE id = ?",
                (json.dumps(details, ensure_ascii=False), int(observation_id)),
            )
        connection.commit()
        connection.close()

    def override_claude_packet_observation(self, store_path: Path, packet_id: str, **updates: object) -> None:
        connection = sqlite3.connect(store_path)
        row = connection.execute(
            """
            SELECT id, details_json
            FROM observations
            WHERE source_name = 'claude-history'
              AND observation_kind = 'packet'
              AND json_extract(details_json, '$.packet_id') = ?
            LIMIT 1
            """,
            (packet_id,),
        ).fetchone()
        self.assertIsNotNone(row, msg=f"missing Claude packet observation for {packet_id}")
        observation_id, details_json = row
        details = json.loads(str(details_json))
        self.assertIsInstance(details, dict)
        details.update(updates)
        connection.execute(
            "UPDATE observations SET details_json = ? WHERE id = ?",
            (json.dumps(details, ensure_ascii=False), int(observation_id)),
        )
        connection.commit()
        connection.close()

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
            self.assertIn(candidate["confidence"], {"medium", "strong"})
            self.assertTrue(candidate["proposal_ready"])
            self.assertEqual(candidate["triage_status"], "ready")
            self.assertIn("evidence_summary", candidate)
            self.assertGreaterEqual(len(candidate["research_targets"]), 2)
            self.assertTrue(all("session_ref" in item for item in candidate["research_targets"]))
            self.assertIn("research_brief", candidate)
            self.assertIn("questions", candidate["research_brief"])
            self.assertEqual(payload["unclustered"][0]["triage_status"], "rejected")
            self.assertFalse(payload["unclustered"][0]["proposal_ready"])

            snippets = "\n".join(candidate["representative_examples"] + payload["unclustered"][0]["representative_snippets"])
            self.assertNotIn(str(workspace), snippets)
            self.assertIn("[WORKSPACE]", snippets)
            self.assertNotIn("?a=1", snippets)
            masked_url = compact_snippet("See https://example.com/path?a=1#frag", str(workspace))
            self.assertEqual(masked_url, "See https://example.com")

    def test_prepare_can_use_store_backed_observations_with_legacy_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)

            payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "store",
                "--store-path",
                str(store_path),
                "--compare-legacy",
            )

            self.assertEqual(payload["config"]["input_source"], "store")
            self.assertEqual(payload["config"]["input_fidelity"], "canonical")
            self.assertGreaterEqual(payload["summary"]["total_packets"], 2)
            self.assertGreaterEqual(len(payload["candidates"]), 1)
            self.assertIn("comparison", payload)
            self.assertGreaterEqual(payload["comparison"]["legacy_candidate_count"], 1)
            self.assertGreaterEqual(payload["comparison"]["label_overlap_ratio"], 0.5)
            self.assertEqual(payload["comparison"]["warnings"], [])
            self.assertEqual(payload["config"]["pattern_persist"]["status"], "persisted")

    def test_prepare_auto_hydrates_store_for_workspace_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"
            sources_file = self.write_sources_file(root, claude_root, codex_history, codex_sessions)

            payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "auto",
                "--store-path",
                str(store_path),
                "--sources-file",
                str(sources_file),
                "--compare-legacy",
            )

            self.assertEqual(payload["config"]["input_source"], "store")
            self.assertGreaterEqual(len(payload["candidates"]), 1)
            self.assertIn("comparison", payload)
            self.assertGreaterEqual(payload["comparison"]["legacy_candidate_count"], 1)
            self.assertEqual(payload["config"]["store_hydration"]["status"], "hydrated")

    def test_prepare_store_hydrates_missing_workspace_slice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"
            sources_file = self.write_sources_file(root, claude_root, codex_history, codex_sessions)

            payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "store",
                "--store-path",
                str(store_path),
                "--sources-file",
                str(sources_file),
                "--compare-legacy",
            )

            self.assertEqual(payload["config"]["input_source"], "store")
            self.assertGreaterEqual(len(payload["candidates"]), 1)
            self.assertIn("comparison", payload)
            self.assertEqual(payload["config"]["store_hydration"]["status"], "hydrated")

    def test_prepare_auto_reports_store_hydration_failure_before_falling_back_to_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"
            missing_sources = root / "missing-sources.json"

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
                    "--input-source",
                    "auto",
                    "--store-path",
                    str(store_path),
                    "--sources-file",
                    str(missing_sources),
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success", msg=completed.stdout)
            self.assertEqual(payload["config"]["input_source"], "raw")
            self.assertTrue(payload["config"]["store_hydration"]["attempted"])
            self.assertEqual(payload["config"]["store_hydration"]["status"], "failed")
            self.assertTrue(payload["config"]["store_hydration"]["message"])
            self.assertIn("[warn] store hydration failed", completed.stderr)

    def test_store_slice_bounds_are_stable_within_same_day(self) -> None:
        reference_now = datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc).astimezone()
        later_same_day = reference_now + timedelta(minutes=5)

        self.assertEqual(
            _store_slice_bounds(reference_now=reference_now, days=30),
            _store_slice_bounds(reference_now=later_same_day, days=30),
        )

    def test_filter_packets_by_days_keeps_spring_forward_packets_on_boundary_day(self) -> None:
        new_york = self._require_new_york_tz()
        packets = [
            {"packet_id": "spring-a", "timestamp": "2026-03-08T01:59:00-05:00"},
            {"packet_id": "spring-b", "timestamp": "2026-03-08T03:01:00-04:00"},
        ]

        filtered, date_window_start = self._filter_packets_at(
            packets,
            now=datetime(2026, 3, 15, 12, 0, tzinfo=new_york),
            tz=new_york,
            days=7,
        )

        self.assertEqual([packet["packet_id"] for packet in filtered], ["spring-a", "spring-b"])
        self.assertEqual(date_window_start, "2026-03-08T00:00:00-05:00")

    def test_filter_packets_by_days_keeps_fall_back_packets_in_repeated_hour(self) -> None:
        new_york = self._require_new_york_tz()
        packets = [
            {"packet_id": "fall-a", "timestamp": "2026-11-01T01:59:00-04:00"},
            {"packet_id": "fall-b", "timestamp": "2026-11-01T01:01:00-05:00"},
        ]

        filtered, date_window_start = self._filter_packets_at(
            packets,
            now=datetime(2026, 11, 8, 12, 0, tzinfo=new_york),
            tz=new_york,
            days=7,
        )

        self.assertEqual([packet["packet_id"] for packet in filtered], ["fall-a", "fall-b"])
        self.assertEqual(date_window_start, "2026-11-01T00:00:00-04:00")

    def test_prepare_store_input_ignores_non_numeric_tool_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            import sqlite3

            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)

            connection = sqlite3.connect(store_path)
            row = connection.execute(
                """
                SELECT id, details_json
                FROM observations
                WHERE source_name = 'codex-history' AND event_type = 'tool_call'
                LIMIT 1
                """
            ).fetchone()
            self.assertIsNotNone(row)
            observation_id = int(row[0])
            details = json.loads(str(row[1]))
            self.assertIsInstance(details.get("tools"), list)
            details["tools"][0]["count"] = "abc"
            connection.execute(
                "UPDATE observations SET details_json = ? WHERE id = ?",
                (json.dumps(details, ensure_ascii=False), observation_id),
            )
            connection.commit()
            connection.close()

            payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "store",
                "--store-path",
                str(store_path),
            )

            self.assertEqual(payload["config"]["input_source"], "store")
            self.assertGreaterEqual(payload["summary"]["total_packets"], 1)

    def test_store_seed_preserves_logical_packets_and_command_signals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)

            connection = sqlite3.connect(store_path)
            claude_row = connection.execute(
                """
                SELECT details_json
                FROM observations
                WHERE source_name = 'claude-history' AND event_type = 'session_summary'
                LIMIT 1
                """
            ).fetchone()
            codex_row = connection.execute(
                """
                SELECT details_json
                FROM observations
                WHERE source_name = 'codex-history' AND event_type = 'tool_call' AND details_json LIKE '%codex-review%'
                LIMIT 1
                """
            ).fetchone()
            connection.close()

            self.assertIsNotNone(claude_row)
            self.assertIsNotNone(codex_row)

            connection = sqlite3.connect(store_path)
            packet_counts = connection.execute(
                """
                SELECT source_name, COUNT(*)
                FROM observations
                WHERE observation_kind = 'packet'
                GROUP BY source_name
                """
            ).fetchall()
            connection.close()

            claude_details = json.loads(str(claude_row[0]))
            self.assertEqual(claude_details["logical_packet_count"], 2)
            self.assertEqual(
                [packet["started_at"] for packet in claude_details["logical_packets"]],
                ["2026-03-09T00:00:00+09:00", "2026-03-09T09:30:00+09:00"],
            )
            self.assertIn("Review another PR under", claude_details["logical_packets"][1]["user_highlights"][0])
            self.assertIn("/src/api.py", claude_details["logical_packets"][1]["user_highlights"][0])

            codex_details = json.loads(str(codex_row[0]))
            self.assertEqual(
                [item["name"] for item in codex_details["tools"]],
                ["rg", "git"],
            )
            self.assertIn("skill_miner_packet", claude_details["logical_packets"][0])
            self.assertEqual(codex_details["skill_miner_packet"]["packet_id"], "codex:codex-review:summary")
            self.assertEqual(dict(packet_counts), {"claude-history": 2, "codex-history": 2})

    def test_get_observations_defaults_to_event_rows_when_packet_rows_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)

            event_observations = get_observations(
                store_path,
                workspace=workspace,
                since="2026-03-09",
                until="2026-03-09T23:59:59+09:00",
                source_names=["claude-history", "codex-history"],
            )
            packet_observations = get_observations(
                store_path,
                workspace=workspace,
                since="2026-03-09",
                until="2026-03-09T23:59:59+09:00",
                source_names=["claude-history", "codex-history"],
                observation_kinds=["packet"],
            )

            self.assertTrue(event_observations)
            self.assertTrue(packet_observations)
            self.assertTrue(all(item["observation_kind"] == "event" for item in event_observations))
            self.assertTrue(all(item["observation_kind"] == "packet" for item in packet_observations))

    def test_prepare_store_matches_raw_candidate_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)

            raw_payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)
            store_payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "store",
                "--store-path",
                str(store_path),
                "--compare-legacy",
            )

            raw_candidate = raw_payload["candidates"][0]
            store_candidate = store_payload["candidates"][0]

            self.assertEqual(store_payload["summary"]["total_packets"], raw_payload["summary"]["total_packets"])
            self.assertEqual(store_candidate["label"], raw_candidate["label"])
            self.assertEqual(store_candidate["common_task_shapes"], raw_candidate["common_task_shapes"])
            self.assertEqual(store_candidate["artifact_hints"], raw_candidate["artifact_hints"])
            self.assertEqual(store_candidate["common_tool_signatures"], raw_candidate["common_tool_signatures"])
            self.assertEqual(store_candidate["triage_status"], raw_candidate["triage_status"])
            self.assertEqual(store_candidate["confidence"], raw_candidate["confidence"])
            self.assertEqual(
                [(item["source"], item["summary"]) for item in store_candidate["evidence_items"]],
                [(item["source"], item["summary"]) for item in raw_candidate["evidence_items"]],
            )
            self.assertEqual(
                [(item["reason"], item["session_ref"].split(":", 1)[0]) for item in store_candidate["research_targets"]],
                [(item["reason"], item["session_ref"].split(":", 1)[0]) for item in raw_candidate["research_targets"]],
            )
            self.assertEqual(
                store_payload["comparison"]["shared_labels"],
                [raw_candidate["label"]],
            )

    def test_store_packet_restoration_matches_raw_for_wrapper_heavy_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_wrapper_heavy_fixture(root)
            store_path = root / "daytrace.sqlite3"
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)

            raw_claude_packets, _ = read_claude_packets(claude_root, workspace, 8)
            raw_codex_packets, _ = read_codex_packets(codex_history, codex_sessions, workspace, 8)
            raw_packets = raw_claude_packets + raw_codex_packets
            store_packets, _store_statuses = read_store_packets(store_path, workspace=workspace, all_sessions=False, max_days=30)

            raw_by_packet = {packet["packet_id"]: packet for packet in raw_packets}
            store_by_packet = {packet["packet_id"]: packet for packet in store_packets}
            self.assertEqual(set(store_by_packet), set(raw_by_packet))
            self.assertTrue(all(packet["_fidelity"] == "original" for packet in raw_packets))
            self.assertTrue(all(packet["_fidelity"] == "canonical" for packet in store_packets))
            for packet_id, raw_packet in raw_by_packet.items():
                store_packet = store_by_packet[packet_id]
                for key in [
                    "packet_version",
                    "primary_intent",
                    "full_user_intent",
                    "primary_intent_source",
                    "intent_trace",
                    "constraints",
                    "acceptance_criteria",
                    "task_shape",
                    "artifact_hints",
                    "tool_signature",
                    "representative_snippets",
                    "user_repeated_rules",
                    "assistant_repeated_rules",
                ]:
                    self.assertEqual(store_packet[key], raw_packet[key], msg=f"{packet_id} {key}")

    def test_store_packet_restoration_rejects_stale_canonical_packets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_wrapper_heavy_fixture(root)
            store_path = root / "daytrace.sqlite3"
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)
            self.invalidate_store_skill_miner_packets(store_path, drop_key="packet_version")

            store_packets, _store_statuses = read_store_packets(store_path, workspace=workspace, all_sessions=False, max_days=30)

            self.assertTrue(store_packets)
            self.assertTrue(any(packet["_fidelity"] == "approximate" for packet in store_packets))

    def test_prepare_auto_falls_back_to_raw_when_store_canonical_packets_are_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_wrapper_heavy_fixture(root)
            store_path = root / "daytrace.sqlite3"
            sources_file = self.write_sources_file(root, claude_root, codex_history, codex_sessions)
            self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "auto",
                "--store-path",
                str(store_path),
                "--sources-file",
                str(sources_file),
            )
            self.invalidate_store_skill_miner_packets(store_path, drop_key="full_user_intent")

            payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "auto",
                "--store-path",
                str(store_path),
                "--sources-file",
                str(sources_file),
            )

            self.assertEqual(payload["config"]["input_source"], "raw")
            self.assertEqual(payload["config"]["input_fidelity"], "original")

    def test_prepare_store_skips_pattern_persist_for_approximate_store_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_wrapper_heavy_fixture(root)
            store_path = root / "daytrace.sqlite3"
            sources_file = self.write_sources_file(root, claude_root, codex_history, codex_sessions)
            self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "auto",
                "--store-path",
                str(store_path),
                "--sources-file",
                str(sources_file),
            )
            self.invalidate_store_skill_miner_packets(store_path, drop_key="user_repeated_rules")

            payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "store",
                "--store-path",
                str(store_path),
                "--sources-file",
                str(sources_file),
            )

            self.assertEqual(payload["config"]["input_source"], "store")
            self.assertEqual(payload["config"]["input_fidelity"], "approximate")
            self.assertEqual(payload["config"]["pattern_persist"]["status"], "skipped")
            self.assertEqual(payload["config"]["pattern_persist"]["reason"], "input_fidelity_approximate")

    def test_prepare_store_matches_raw_candidate_semantics_for_wrapper_heavy_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_wrapper_heavy_fixture(root)
            store_path = root / "daytrace.sqlite3"
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)

            raw_payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)
            store_payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "store",
                "--store-path",
                str(store_path),
                "--compare-legacy",
            )

            raw_candidate = raw_payload["candidates"][0]
            store_candidate = store_payload["candidates"][0]
            self.assertEqual(store_candidate["label"], raw_candidate["label"])
            self.assertEqual(store_candidate["common_task_shapes"], raw_candidate["common_task_shapes"])
            self.assertEqual(store_candidate["artifact_hints"], raw_candidate["artifact_hints"])
            self.assertEqual(store_candidate["common_tool_signatures"], raw_candidate["common_tool_signatures"])
            self.assertEqual(store_candidate["triage_status"], raw_candidate["triage_status"])
            self.assertEqual(store_candidate["confidence"], raw_candidate["confidence"])
            self.assertEqual(
                [(item["source"], item["summary"]) for item in store_candidate["evidence_items"]],
                [(item["source"], item["summary"]) for item in raw_candidate["evidence_items"]],
            )
            self.assertEqual(
                [(item["reason"], item["session_ref"].split(":", 1)[0]) for item in store_candidate["research_targets"]],
                [(item["reason"], item["session_ref"].split(":", 1)[0]) for item in raw_candidate["research_targets"]],
            )

    def test_read_store_packets_prefers_latest_observation_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_wrapper_heavy_fixture(root)
            store_path = root / "daytrace.sqlite3"
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)

            raw_claude_packets, _ = read_claude_packets(claude_root, workspace, 8)
            raw_codex_packets, _ = read_codex_packets(codex_history, codex_sessions, workspace, 8)
            store_packets, _ = read_store_packets(store_path, workspace=workspace, all_sessions=False, max_days=30)

            self.assertEqual(len(store_packets), len(raw_claude_packets) + len(raw_codex_packets))
            self.assertEqual(
                {packet["packet_id"] for packet in store_packets},
                {packet["packet_id"] for packet in raw_claude_packets + raw_codex_packets},
            )

    def test_prepare_store_preserves_ready_candidate_when_legacy_origin_metadata_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)

            for key in ("origin_hint", "user_signal_strength", "contamination_signals"):
                self.invalidate_store_skill_miner_packets(store_path, drop_key=key)

            raw_payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)
            store_payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "store",
                "--store-path",
                str(store_path),
            )

            raw_candidate = raw_payload["candidates"][0]
            store_candidate = store_payload["candidates"][0]
            self.assertEqual(store_candidate["label"], raw_candidate["label"])
            self.assertTrue(store_candidate["proposal_ready"])
            self.assertEqual(store_candidate["triage_status"], "ready")
            self.assertNotIn("origin_uncertain", store_candidate["quality_flags"])
            self.assertNotIn("low_user_signal", store_candidate["quality_flags"])

    def test_store_seed_includes_rollout_only_codex_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            write_jsonl(
                codex_sessions / "2026" / "03" / "09" / "rollout-rollout-only.jsonl",
                [
                    {
                        "timestamp": "2026-03-09T05:00:00+09:00",
                        "type": "session_meta",
                        "payload": {"id": "codex-rollout-only", "timestamp": "2026-03-09T05:00:00+09:00", "cwd": str(workspace)},
                    },
                    {
                        "timestamp": "2026-03-09T05:00:01+09:00",
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "Review the rollout-only session and keep the findings-first format."},
                    },
                    {
                        "timestamp": "2026-03-09T05:00:02+09:00",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "I will inspect the files and summarize findings by severity."}],
                        },
                    },
                    {
                        "timestamp": "2026-03-09T05:00:03+09:00",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "arguments": json.dumps({"cmd": "rg -n TODO src/server.py"}),
                        },
                    },
                ],
            )

            store_path = root / "daytrace.sqlite3"
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)
            store_packets, _ = read_store_packets(store_path, workspace=workspace, all_sessions=False, max_days=30)

            self.assertIn("codex:codex-rollout-only:000", {packet["packet_id"] for packet in store_packets})

    def test_read_claude_packets_skips_sidechain_and_tool_result_user_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, _codex_history, _codex_sessions = self.create_claude_contamination_fixture(root)

            packets, source = read_claude_packets(claude_root, workspace, 8)

            self.assertEqual(source["status"], "success")
            self.assertEqual(len(packets), 1)
            packet = packets[0]
            self.assertFalse(packet.get("is_sidechain", False))
            self.assertIn("Review src/app.py", packet["primary_intent"])
            self.assertNotIn("from __future__", packet["full_user_intent"])
            self.assertNotIn("Explore the skill structure", packet["full_user_intent"])
            self.assertNotIn("summarize the structure", packet["full_user_intent"])
            self.assertEqual(packet["origin_hint"], "human")
            self.assertEqual(packet["user_signal_strength"], "high")
            self.assertEqual(packet["contamination_signals"], [])

    def test_read_store_packets_skips_claude_sidechain_and_tool_result_contamination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_claude_contamination_fixture(root)
            store_path = root / "daytrace.sqlite3"
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)

            packets, statuses = read_store_packets(store_path, workspace=workspace, all_sessions=False, max_days=30)

            claude_packets = [packet for packet in packets if packet["source"] == "claude-history"]
            self.assertEqual(len(claude_packets), 1)
            packet = claude_packets[0]
            self.assertFalse(packet.get("is_sidechain", False))
            self.assertIn("Review src/app.py", packet["primary_intent"])
            self.assertNotIn("from __future__", packet["full_user_intent"])
            self.assertNotIn("summarize the structure", packet["full_user_intent"])
            self.assertEqual(packet["origin_hint"], "human")
            self.assertEqual(packet["user_signal_strength"], "high")
            self.assertEqual(packet["contamination_signals"], [])
            self.assertTrue(any(status["name"] == "claude-history" and status["status"] == "success" for status in statuses))

    def test_read_store_packets_rebuilds_filtered_claude_packet_rows_from_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)

            raw_claude_packets, _ = read_claude_packets(claude_root, workspace, 8)
            self.assertEqual(len(raw_claude_packets), 2)

            self.override_claude_packet_observation(
                store_path,
                raw_claude_packets[0]["packet_id"],
                primary_intent_source="summary_fallback",
            )

            packets, statuses = read_store_packets(store_path, workspace=workspace, all_sessions=False, max_days=30)

            claude_packets = [packet for packet in packets if packet["source"] == "claude-history"]
            self.assertEqual(
                {packet["packet_id"] for packet in claude_packets},
                {packet["packet_id"] for packet in raw_claude_packets},
            )
            self.assertTrue(any(status["name"] == "claude-history" and status["packets_count"] == 2 for status in statuses))

    def test_prepare_auto_falls_back_to_raw_when_store_slice_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"
            self.seed_store(workspace, claude_root, codex_history, codex_sessions, store_path)
            stale_sources_file = root / "stale-sources.json"
            stale_sources_file.write_text(
                json.dumps(
                    [
                        {
                            "name": "claude-history",
                            "command": f"python3 {PLUGIN_ROOT / 'scripts' / 'claude_history.py'} --root {claude_root} --synthetic-change",
                            "required": False,
                            "timeout_sec": 30,
                            "platforms": ["darwin", "linux"],
                            "supports_date_range": True,
                            "supports_all_sessions": True,
                            "scope_mode": "all-day",
                            "prerequisites": [],
                            "confidence_category": "ai_history",
                        },
                        {
                            "name": "codex-history",
                            "command": f"python3 {PLUGIN_ROOT / 'scripts' / 'codex_history.py'} --history-file {codex_history} --sessions-root {codex_sessions}",
                            "required": False,
                            "timeout_sec": 30,
                            "platforms": ["darwin", "linux"],
                            "supports_date_range": True,
                            "supports_all_sessions": True,
                            "scope_mode": "all-day",
                            "prerequisites": [],
                            "confidence_category": "ai_history",
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "auto",
                "--store-path",
                str(store_path),
                "--sources-file",
                str(stale_sources_file),
            )

            self.assertEqual(payload["config"]["input_source"], "raw")
            self.assertEqual(payload["config"]["input_fidelity"], "original")
            self.assertGreaterEqual(payload["summary"]["total_packets"], 2)

    def test_prepare_auto_reuses_store_on_repeated_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"
            sources_file = self.write_sources_file(root, claude_root, codex_history, codex_sessions)

            first_payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "auto",
                "--store-path",
                str(store_path),
                "--sources-file",
                str(sources_file),
            )

            second_payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "auto",
                "--store-path",
                str(store_path),
                "--sources-file",
                str(sources_file),
            )

            self.assertEqual(first_payload["config"]["input_source"], "store")
            self.assertEqual(second_payload["config"]["input_source"], "store")
            self.assertEqual(
                first_payload["summary"]["total_packets"],
                second_payload["summary"]["total_packets"],
            )
            self.assertEqual(
                first_payload["summary"]["total_candidates"],
                second_payload["summary"]["total_candidates"],
            )

    def test_prepare_all_sessions_store_backed_matches_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"
            sources_file = self.write_sources_file(root, claude_root, codex_history, codex_sessions)

            raw_payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--all-sessions",
                "--reference-date",
                "2026-03-10",
            )

            store_payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--all-sessions",
                "--reference-date",
                "2026-03-10",
                "--input-source",
                "auto",
                "--store-path",
                str(store_path),
                "--sources-file",
                str(sources_file),
            )

            self.assertEqual(store_payload["config"]["input_source"], "store")
            self.assertEqual(
                raw_payload["summary"]["total_candidates"],
                store_payload["summary"]["total_candidates"],
            )
            raw_labels = sorted(c["label"] for c in raw_payload["candidates"])
            store_labels = sorted(c["label"] for c in store_payload["candidates"])
            self.assertEqual(raw_labels, store_labels)

    def test_prepare_skips_pattern_persist_on_empty_store_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            store_path = root / "daytrace.sqlite3"
            empty_claude = root / "empty_claude"
            empty_claude.mkdir()
            empty_codex_history = root / "empty_codex" / "history.jsonl"
            empty_codex_history.parent.mkdir(parents=True, exist_ok=True)
            empty_codex_history.write_text("", encoding="utf-8")
            empty_codex_sessions = root / "empty_codex" / "sessions"
            empty_codex_sessions.mkdir(parents=True, exist_ok=True)

            import sqlite3
            from store import bootstrap_store
            bootstrap_store(store_path)

            payload = self.run_prepare(
                workspace,
                empty_claude,
                empty_codex_history,
                empty_codex_sessions,
                "--input-source",
                "store",
                "--store-path",
                str(store_path),
            )

            self.assertEqual(payload["summary"]["no_sources_available"], True)
            connection = sqlite3.connect(store_path)
            pattern_count = connection.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
            self.assertEqual(pattern_count, 0, "patterns should not be persisted for empty results")
            connection.close()
            self.assertEqual(payload["config"]["pattern_persist"]["status"], "skipped")
            self.assertEqual(payload["config"]["pattern_persist"]["reason"], "no_candidates")

    def test_prepare_reports_pattern_persist_failure_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            broken_store_path = root / "broken-store"
            broken_store_path.mkdir()

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
                    "--store-path",
                    str(broken_store_path),
                    "--top-n",
                    "5",
                    "--max-unclustered",
                    "5",
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success", msg=completed.stdout)
            self.assertEqual(payload["config"]["pattern_persist"]["status"], "failed")
            self.assertIn("[warn] pattern persistence failed", completed.stderr)

    def test_prepare_does_not_replace_patterns_on_unsafe_raw_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"

            first_payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--store-path",
                str(store_path),
            )
            self.assertEqual(first_payload["config"]["pattern_persist"]["status"], "persisted")
            expected_labels = sorted(candidate["label"] for candidate in first_payload["candidates"])

            missing_history = root / "missing" / "history.jsonl"
            missing_sessions = root / "missing" / "sessions"
            second_payload = self.run_prepare(
                workspace,
                claude_root,
                missing_history,
                missing_sessions,
                "--store-path",
                str(store_path),
            )
            self.assertEqual(second_payload["config"]["pattern_persist"]["status"], "skipped")
            self.assertIn(
                second_payload["config"]["pattern_persist"]["reason"],
                {"no_candidates", "source_status_not_success:codex-history"},
            )

            connection = sqlite3.connect(store_path)
            pattern_count = connection.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
            labels = [row[0] for row in connection.execute("SELECT label FROM patterns ORDER BY label ASC").fetchall()]
            connection.close()
            self.assertGreater(pattern_count, 0)
            self.assertEqual(labels, expected_labels)

    def test_prepare_auto_falls_back_to_raw_when_store_slice_stays_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            store_path = root / "daytrace.sqlite3"
            partial_sources_file = root / "partial-sources.json"
            partial_sources_file.write_text(
                json.dumps(
                    [
                        {
                            "name": "claude-history",
                            "command": f"python3 {PLUGIN_ROOT / 'scripts' / 'claude_history.py'} --root {claude_root}",
                            "required": False,
                            "timeout_sec": 30,
                            "platforms": ["darwin", "linux"],
                            "supports_date_range": True,
                            "supports_all_sessions": True,
                            "scope_mode": "all-day",
                            "prerequisites": [],
                            "confidence_category": "ai_history",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(AGGREGATE),
                    "--sources-file",
                    str(partial_sources_file),
                    "--workspace",
                    str(workspace),
                    "--since",
                    "2026-03-01",
                    "--until",
                    "2026-03-12",
                    "--store-path",
                    str(store_path),
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)

            broken_sources_file = root / "broken-sources.json"
            broken_sources_file.write_text(
                json.dumps(
                    [
                        {
                            "name": "claude-history",
                            "command": f"python3 {PLUGIN_ROOT / 'scripts' / 'claude_history.py'} --root {claude_root}",
                            "required": False,
                            "timeout_sec": 30,
                            "platforms": ["darwin", "linux"],
                            "supports_date_range": True,
                            "supports_all_sessions": True,
                            "scope_mode": "all-day",
                            "prerequisites": [],
                            "confidence_category": "ai_history",
                        },
                        {
                            "name": "codex-history",
                            "command": (
                                f"python3 {PLUGIN_ROOT / 'scripts' / 'codex_history.py'} "
                                f"--history-file {root / 'missing' / 'history.jsonl'} "
                                f"--sessions-root {root / 'missing' / 'sessions'}"
                            ),
                            "required": False,
                            "timeout_sec": 30,
                            "platforms": ["darwin", "linux"],
                            "supports_date_range": True,
                            "supports_all_sessions": True,
                            "scope_mode": "all-day",
                            "prerequisites": [],
                            "confidence_category": "ai_history",
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--input-source",
                "auto",
                "--store-path",
                str(store_path),
                "--sources-file",
                str(broken_sources_file),
            )

            self.assertEqual(payload["config"]["input_source"], "raw")
            self.assertEqual(payload["config"]["input_fidelity"], "original")

    def test_build_candidate_comparison_emits_warning_for_low_overlap(self) -> None:
        comparison = build_candidate_comparison(
            [{"label": "Review workflow"}, {"label": "Build workflow"}],
            [{"label": "Research workflow"}],
        )

        self.assertEqual(len(comparison["shared_labels"]), 0)
        self.assertEqual(comparison["label_overlap_ratio"], 0.0)
        self.assertEqual(len(comparison["warnings"]), 1)

    def test_prepare_reports_effective_observation_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(Path(temp_dir))
            # Use a fixed reference date one day after the fixture data (2026-03-09) so the
            # 7-day window includes those packets without relying on the real clock.
            payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions, "--reference-date", "2026-03-10")

            self.assertEqual(payload["config"]["days"], 7)
            self.assertEqual(payload["config"]["effective_days"], 7)
            self.assertEqual(payload["config"]["input_fidelity"], "original")
            self.assertEqual(payload["config"]["observation_mode"], "workspace")
            self.assertTrue(payload["config"]["adaptive_window"]["enabled"])
            self.assertFalse(payload["config"]["adaptive_window"]["expanded"])
            self.assertNotIn("adaptive_window_expanded", payload["summary"])
            self.assertIsNotNone(payload["config"]["date_window_start"])

    def test_candidate_quality_flags_oversized_generic_cluster_for_research(self) -> None:
        candidate = {
            "support": {
                "total_packets": 9,
                "claude_packets": 4,
                "codex_packets": 5,
                "recent_packets_7d": 6,
            },
            "common_task_shapes": ["review_changes", "search_code", "summarize_findings"],
            "common_tool_signatures": ["rg", "sed", "bash", "read"],
            "artifact_hints": ["review", "report"],
            "rule_hints": ["findings-first"],
            "representative_examples": [
                "Review this PR and summarize findings by severity.",
                "Investigate the logs and summarize the root cause.",
            ],
        }

        quality = build_candidate_quality(candidate, total_packets_all=12)

        self.assertEqual(quality["triage_status"], "needs_research")
        self.assertFalse(quality["proposal_ready"])
        self.assertIn(quality["confidence"], {"weak", "insufficient"})
        self.assertIn("oversized_cluster", quality["quality_flags"])
        self.assertIn("generic_task_shape", quality["quality_flags"])
        self.assertIn("generic_tools", quality["quality_flags"])

    def test_candidate_quality_holds_low_user_signal_candidate_for_research(self) -> None:
        candidate = {
            "support": {
                "total_packets": 5,
                "claude_packets": 5,
                "codex_packets": 0,
                "recent_packets_7d": 5,
                "contaminated_packets": 2,
            },
            "common_task_shapes": ["implement_feature"],
            "common_tool_signatures": ["python3", "pytest"],
            "artifact_hints": ["code"],
            "rule_hints": [],
            "representative_examples": [
                "Implement the feature and run tests.",
                "Implement the feature and run tests.",
            ],
            "origin_hint": "unknown",
            "user_signal_strength": "low",
            "contamination_signals": ["assistant_fallback", "summary_fallback"],
        }

        quality = build_candidate_quality(candidate, total_packets_all=12)

        self.assertEqual(quality["triage_status"], "needs_research")
        self.assertFalse(quality["proposal_ready"])
        self.assertIn("low_user_signal", quality["quality_flags"])
        self.assertIn("origin_uncertain", quality["quality_flags"])
        self.assertIn("contaminated_candidate", quality["quality_flags"])

    def test_prepare_includes_research_targets_for_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(Path(temp_dir))
            payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)
            candidate = payload["candidates"][0]

            self.assertIn("research_targets", candidate)
            self.assertLessEqual(len(candidate["research_targets"]), 5)
            reasons = {item["reason"] for item in candidate["research_targets"]}
            self.assertTrue(reasons & {"representative", "fallback", "near_match"})
            self.assertTrue(all(item["session_ref"] for item in candidate["research_targets"]))
            self.assertIn("objective", candidate["research_brief"])
            self.assertGreaterEqual(len(candidate["research_brief"]["questions"]), 3)
            self.assertGreaterEqual(len(candidate["research_brief"]["decision_rules"]), 3)

    def test_prepare_suppresses_non_carry_forward_candidate_from_decision_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            first_payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)
            candidate = first_payload["candidates"][0]
            decision_log = root / "decision-log.jsonl"
            write_jsonl(
                decision_log,
                [
                    {
                        "record_type": "skill_miner_decision_stub",
                        "candidate_id": candidate["candidate_id"],
                        "decision_key": build_candidate_decision_key(candidate),
                        "label": candidate["label"],
                        "suggested_kind": "CLAUDE.md",
                        "intent_trace": candidate.get("intent_trace", []),
                        "constraints": candidate.get("constraints", []),
                        "acceptance_criteria": candidate.get("acceptance_criteria", []),
                        "user_decision": "adopt",
                        "carry_forward": False,
                        "recorded_at": "2026-03-18T00:00:00+09:00",
                    }
                ],
            )

            payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--decision-log-path",
                str(decision_log),
            )

            labels = {item["label"] for item in payload["candidates"]}
            self.assertNotIn(candidate["label"], labels)
            self.assertEqual(payload["summary"]["decision_log_suppressed_candidates"], 1)
            self.assertEqual(payload["config"]["decision_log"]["matched_candidates"], 1)

    def test_prepare_keeps_carry_forward_candidate_and_attaches_prior_decision_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            first_payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)
            candidate = first_payload["candidates"][0]
            decision_log = root / "decision-log.jsonl"
            write_jsonl(
                decision_log,
                [
                    {
                        "record_type": "skill_miner_decision_stub",
                        "candidate_id": candidate["candidate_id"],
                        "decision_key": build_candidate_decision_key(candidate),
                        "label": candidate["label"],
                        "suggested_kind": "CLAUDE.md",
                        "intent_trace": candidate.get("intent_trace", []),
                        "constraints": candidate.get("constraints", []),
                        "acceptance_criteria": candidate.get("acceptance_criteria", []),
                        "user_decision": "defer",
                        "carry_forward": True,
                        "recorded_at": "2026-03-18T00:00:00+09:00",
                    }
                ],
            )

            payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--decision-log-path",
                str(decision_log),
            )

            matched = next(item for item in payload["candidates"] if item["label"] == candidate["label"])
            self.assertEqual(matched["prior_decision_state"]["user_decision"], "defer")
            self.assertEqual(payload["summary"]["decision_log_suppressed_candidates"], 0)
            self.assertEqual(payload["config"]["decision_log"]["matched_candidates"], 1)

    def test_prepare_matches_legacy_decision_log_row_without_decision_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            first_payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)
            candidate = first_payload["candidates"][0]
            decision_log = root / "decision-log.jsonl"
            write_jsonl(
                decision_log,
                [
                    {
                        "record_type": "skill_miner_decision_stub",
                        "candidate_id": candidate["candidate_id"],
                        "label": candidate["label"],
                        "suggested_kind": "CLAUDE.md",
                        "intent_trace": candidate.get("intent_trace", []),
                        "constraints": candidate.get("constraints", []),
                        "acceptance_criteria": candidate.get("acceptance_criteria", []),
                        "user_decision": "defer",
                        "carry_forward": True,
                        "recorded_at": "2026-03-18T00:00:00+09:00",
                    }
                ],
            )

            payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--decision-log-path",
                str(decision_log),
            )

            matched = next(item for item in payload["candidates"] if item["label"] == candidate["label"])
            self.assertEqual(matched["prior_decision_state"]["user_decision"], "defer")
            self.assertEqual(payload["config"]["decision_log"]["matched_candidates"], 1)

    def test_prepare_resurfaces_rejected_candidate_when_support_grew(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(root)
            first_payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)
            candidate = first_payload["candidates"][0]
            self.assertGreaterEqual(candidate["support"]["total_packets"], 2)
            decision_log = root / "decision-log.jsonl"
            write_jsonl(
                decision_log,
                [
                    {
                        "record_type": "skill_miner_decision_stub",
                        "candidate_id": candidate["candidate_id"],
                        "decision_key": build_candidate_decision_key(candidate),
                        "label": candidate["label"],
                        "suggested_kind": "CLAUDE.md",
                        "intent_trace": candidate.get("intent_trace", []),
                        "constraints": candidate.get("constraints", []),
                        "acceptance_criteria": candidate.get("acceptance_criteria", []),
                        "user_decision": "reject",
                        "carry_forward": True,
                        "observation_count": 1,
                        "recorded_at": "2026-03-18T00:00:00+09:00",
                    }
                ],
            )

            payload = self.run_prepare(
                workspace,
                claude_root,
                codex_history,
                codex_sessions,
                "--decision-log-path",
                str(decision_log),
            )

            matched = next(item for item in payload["candidates"] if item["label"] == candidate["label"])
            self.assertEqual(matched["prior_decision_state"]["user_decision"], "reject")
            self.assertEqual(matched["prior_decision_state"]["observation_count"], 1)
            self.assertEqual(payload["summary"]["decision_log_suppressed_candidates"], 0)

    def test_issue_sized_cluster_is_held_for_research(self) -> None:
        candidate = {
            "label": "review changes (review, markdown)",
            "support": {
                "total_packets": 63,
                "claude_packets": 31,
                "codex_packets": 32,
                "recent_packets_7d": 48,
            },
            "common_task_shapes": ["review_changes", "search_code", "summarize_findings"],
            "common_tool_signatures": ["sed", "rg", "read", "bash"],
            "artifact_hints": ["review", "markdown", "report"],
            "rule_hints": ["file-line-refs", "findings-first"],
            "representative_examples": [
                "Review a proposed memo and list factual findings with references.",
                "Search the codebase and summarize findings from logs and docs.",
            ],
            "research_targets": [
                {"session_ref": "codex:one:1", "reason": "representative"},
                {"session_ref": "codex:two:2", "reason": "near_match"},
            ],
        }

        quality = build_candidate_quality(candidate, total_packets_all=75)

        self.assertEqual(quality["triage_status"], "needs_research")
        self.assertFalse(quality["proposal_ready"])
        self.assertIn("oversized_cluster", quality["quality_flags"])

    def test_judge_research_candidate_promotes_coherent_review_pattern(self) -> None:
        candidate = {
            "label": "review changes (review, code)",
            "quality_flags": [],
        }
        details = [
            {
                "session_ref": "codex:a:1",
                "messages": [
                    {"role": "user", "text": "Review this PR and return findings by severity."},
                    {"role": "assistant", "text": "I will inspect the diff and list findings first with file references."},
                ],
                "tool_calls": [{"name": "rg", "count": 2}, {"name": "git", "count": 1}],
            },
            {
                "session_ref": "codex:b:2",
                "messages": [
                    {"role": "user", "text": "Review another PR and keep the findings-first format."},
                    {"role": "assistant", "text": "I will inspect files and summarize findings by severity with line refs."},
                ],
                "tool_calls": [{"name": "rg", "count": 1}, {"name": "git", "count": 1}],
            },
        ]

        judgment = judge_research_candidate(candidate, details)

        self.assertEqual(judgment["recommendation"], "promote_ready")
        self.assertEqual(judgment["proposed_triage_status"], "ready")
        self.assertIn(judgment["proposed_confidence"], {"medium", "strong"})

    def test_judge_research_candidate_splits_mixed_objectives(self) -> None:
        candidate = {
            "label": "review changes (review, markdown)",
            "quality_flags": ["oversized_cluster", "generic_task_shape", "generic_tools"],
        }
        details = [
            {
                "session_ref": "codex:a:1",
                "messages": [
                    {"role": "user", "text": "Review this PR and return findings by severity."},
                    {"role": "assistant", "text": "I will inspect the diff and list findings first."},
                ],
                "tool_calls": [{"name": "rg", "count": 2}],
            },
            {
                "session_ref": "codex:b:2",
                "messages": [
                    {"role": "user", "text": "Investigate failing logs and identify the root cause."},
                    {"role": "assistant", "text": "I will inspect the logs and summarize the failure pattern."},
                ],
                "tool_calls": [{"name": "sed", "count": 1}],
            },
            {
                "session_ref": "codex:c:3",
                "messages": [
                    {"role": "user", "text": "Prepare a daily report draft from today's work."},
                    {"role": "assistant", "text": "I will create a report with action items and summary."},
                ],
                "tool_calls": [{"name": "python3", "count": 1}],
            },
        ]

        judgment = judge_research_candidate(candidate, details)

        self.assertEqual(judgment["recommendation"], "split_candidate")
        self.assertEqual(judgment["proposed_triage_status"], "needs_research")
        self.assertTrue(judgment["split_suggestions"])

    def test_research_judge_cli_reads_prepare_and_detail_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(Path(temp_dir))
            payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)
            candidate = payload["candidates"][0]
            refs = candidate["research_targets"][:2]

            detail_completed = subprocess.run(
                [
                    "python3",
                    str(DETAIL),
                    "--refs",
                    *[item["session_ref"] for item in refs],
                    "--gap-hours",
                    "8",
                    "--codex-history-file",
                    str(codex_history),
                    "--codex-sessions-root",
                    str(codex_sessions),
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(detail_completed.returncode, 0, msg=detail_completed.stderr)
            detail_payload = json.loads(detail_completed.stdout)

            candidate_file = Path(temp_dir) / "prepare.json"
            detail_file = Path(temp_dir) / "detail.json"
            candidate_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            detail_file.write_text(json.dumps(detail_payload, ensure_ascii=False), encoding="utf-8")

            judge_completed = subprocess.run(
                [
                    "python3",
                    str(RESEARCH_JUDGE),
                    "--candidate-file",
                    str(candidate_file),
                    "--candidate-id",
                    candidate["candidate_id"],
                    "--detail-file",
                    str(detail_file),
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(judge_completed.returncode, 0, msg=judge_completed.stderr)
            judgment_payload = json.loads(judge_completed.stdout)
            self.assertEqual(judgment_payload["status"], "success")
            self.assertEqual(judgment_payload["source"], "skill-miner-research-judge")
            self.assertIn("judgment", judgment_payload)

    def test_build_proposal_sections_separates_ready_and_rejected(self) -> None:
        prepare_payload = {
            "candidates": [
                {
                    "candidate_id": "cand-ready",
                    "label": "review changes (code, report)",
                    "confidence": "medium",
                    "proposal_ready": True,
                    "triage_status": "ready",
                    "evidence_summary": "3 packets / Claude 2 / Codex 1",
                },
                {
                    "candidate_id": "cand-research",
                    "label": "review changes (review, markdown)",
                    "confidence": "weak",
                    "proposal_ready": False,
                    "triage_status": "needs_research",
                    "confidence_reason": "oversized cluster",
                    "evidence_summary": "64 packets / flags: oversized_cluster",
                },
            ],
            "unclustered": [
                {
                    "packet_id": "codex:single",
                    "confidence_reason": "single observed packet only",
                }
            ],
        }

        sections = build_proposal_sections(prepare_payload)

        self.assertEqual(len(sections["ready"]), 1)
        self.assertEqual(len(sections["needs_research"]), 1)
        self.assertEqual(len(sections["rejected"]), 1)
        self.assertIn("## 提案（固定化を推奨）", sections["markdown"])
        self.assertIn("## 有望候補（もう少し観測が必要）", sections["markdown"])
        self.assertIn("## 観測ノート", sections["markdown"])
        self.assertIsNotNone(sections["selection_prompt"])

    def test_proposal_cli_formats_sections_from_prepare_and_judgment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepare_payload = {
                "candidates": [
                    {
                        "candidate_id": "cand-1",
                        "label": "review changes (review, markdown)",
                        "confidence": "insufficient",
                        "proposal_ready": False,
                        "triage_status": "needs_research",
                        "evidence_summary": "64 packets / flags: oversized_cluster",
                        "quality_flags": ["oversized_cluster"],
                    }
                ],
                "unclustered": [],
            }
            judgment_payload = {
                "status": "success",
                "source": "skill-miner-research-judge",
                "candidate_id": "cand-1",
                "judgment": {
                    "recommendation": "promote_ready",
                    "proposed_triage_status": "ready",
                    "proposed_confidence": "medium",
                    "summary": "recommendation=promote_ready / sampled_refs=3",
                },
            }

            prepare_file = Path(temp_dir) / "prepare.json"
            judge_file = Path(temp_dir) / "judge.json"
            prepare_file.write_text(json.dumps(prepare_payload, ensure_ascii=False), encoding="utf-8")
            judge_file.write_text(json.dumps(judgment_payload, ensure_ascii=False), encoding="utf-8")

            completed = subprocess.run(
                [
                    "python3",
                    str(PROPOSAL),
                    "--prepare-file",
                    str(prepare_file),
                    "--judge-file",
                    str(judge_file),
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["source"], "skill-miner-proposal")
            self.assertEqual(len(payload["ready"]), 1)
            self.assertEqual(payload["ready"][0]["candidate_id"], "cand-1")
            self.assertIn("どの候補をドラフト化しますか？", payload["markdown"])

    def test_build_proposal_sections_handles_zero_ready_candidates(self) -> None:
        prepare_payload = {
            "candidates": [
                {
                    "candidate_id": "cand-research",
                    "label": "review changes (review, markdown)",
                    "confidence": "insufficient",
                    "proposal_ready": False,
                    "triage_status": "needs_research",
                    "confidence_reason": "oversized cluster",
                    "evidence_summary": "64 packets / flags: oversized_cluster",
                }
            ],
            "unclustered": [
                {
                    "packet_id": "codex:single",
                    "confidence_reason": "single observed packet only",
                }
            ],
        }

        sections = build_proposal_sections(prepare_payload)

        self.assertEqual(sections["summary"]["ready_count"], 0)
        self.assertEqual(sections["summary"]["needs_research_count"], 1)
        self.assertEqual(sections["summary"]["rejected_count"], 1)
        self.assertIsNone(sections["selection_prompt"])
        self.assertIn("### 観測範囲", sections["markdown"])
        self.assertIn("今回は有力候補なし", sections["markdown"])

    def test_candidate_label_prefers_cluster_signals(self) -> None:
        label = candidate_label(
            {
                "common_task_shapes": ["review_changes"],
                "artifact_hints": ["code", "report"],
                "primary_intent": "本日のAI予測をチャットに送信。Macのパスです",
            }
        )

        self.assertEqual(label, "review changes (code, report)")

    def test_unclustered_packets_are_not_proposal_ready(self) -> None:
        packet = annotate_unclustered_packet(
            {
                "packet_id": "codex:single",
                "support": {"message_count": 2, "tool_call_count": 0},
            }
        )

        self.assertEqual(packet["confidence"], "insufficient")
        self.assertFalse(packet["proposal_ready"])
        self.assertEqual(packet["triage_status"], "rejected")
        self.assertIn("unclustered_only", packet["quality_flags"])

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
                cwd=str(PROJECT_ROOT),
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
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertTrue(payload["summary"]["no_sources_available"])
            self.assertEqual(payload["candidates"], [])

    @unittest.skipIf(os.getuid() == 0, "root bypasses file permissions")
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
                    cwd=str(PROJECT_ROOT),
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

    def test_prepare_excludes_error_source_packets_from_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, claude_root, _codex_history, codex_sessions = self.create_fixture(root)
            broken_history = root / "broken-history"
            broken_history.mkdir()
            write_jsonl(
                claude_root / "repo" / "session-b.jsonl",
                [
                    {
                        "type": "user",
                        "cwd": str(workspace),
                        "sessionId": "claude-review-2",
                        "isSidechain": False,
                        "timestamp": "2026-03-10T08:00:00+09:00",
                        "message": {
                            "role": "user",
                            "content": f"Review another server PR under {workspace}/src/server.py and keep findings-first output.",
                        },
                    },
                    {
                        "type": "assistant",
                        "cwd": str(workspace),
                        "sessionId": "claude-review-2",
                        "isSidechain": False,
                        "timestamp": "2026-03-10T08:05:00+09:00",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "I will inspect the diff and list findings by severity with file-line refs."}
                            ],
                        },
                    },
                ],
            )

            payload = self.run_prepare(workspace, claude_root, broken_history, codex_sessions)

            self.assertTrue(any(status["name"] == "codex-history" and status["status"] == "error" for status in payload["sources"]))
            self.assertGreaterEqual(len(payload["candidates"]), 1)
            for candidate in payload["candidates"]:
                self.assertEqual(candidate["support"]["codex_packets"], 0)
                self.assertTrue(all(item["source"] == "claude-history" for item in candidate.get("evidence_items", [])))

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
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["summary"]["total_packets"], 1)

    def test_content_key_stable_across_suggested_kind_change(self) -> None:
        base = {
            "label": "Review workflow",
            "intent_trace": ["Review PR", "findings-first"],
            "constraints": ["Do not spam"],
            "acceptance_criteria": ["Line refs"],
        }
        as_hook = {**base, "suggested_kind": "hook"}
        as_skill = {**base, "suggested_kind": "skill"}
        self.assertEqual(build_candidate_content_key(as_hook), build_candidate_content_key(as_skill))
        self.assertNotEqual(build_candidate_decision_key(as_hook), build_candidate_decision_key(as_skill))

    def test_apply_decision_states_primary_match_has_no_migration_flag(self) -> None:
        candidate = {
            "candidate_id": "c1",
            "label": "Review workflow",
            "suggested_kind": "skill",
            "intent_trace": ["Review PR"],
            "constraints": [],
            "acceptance_criteria": [],
            "triage_status": "ready",
            "proposal_ready": True,
            "quality_flags": [],
            "support": {"total_packets": 3},
        }
        dk = build_candidate_decision_key(candidate)
        ck = build_candidate_content_key(candidate)
        state = {
            "decision_key": dk,
            "content_key": ck,
            "suggested_kind": "skill",
            "carry_forward": True,
            "user_decision": None,
            "intent_trace": ["Review PR"],
            "observation_count": 0,
        }
        retained, app = apply_decision_states_to_candidates([dict(candidate)], {dk: state}, {ck: state})
        self.assertEqual(len(retained), 1)
        self.assertNotIn("classification_migrated", retained[0])
        self.assertEqual(retained[0]["prior_decision_state"]["suggested_kind"], "skill")
        self.assertEqual(app["content_key_migrations"], 0)

    def test_apply_decision_states_secondary_match_sets_classification_migrated(self) -> None:
        shared = {
            "candidate_id": "c1",
            "label": "Review workflow",
            "intent_trace": ["Review PR"],
            "constraints": [],
            "acceptance_criteria": [],
            "triage_status": "ready",
            "proposal_ready": True,
            "quality_flags": [],
            "support": {"total_packets": 3},
        }
        prior = {**shared, "suggested_kind": "hook"}
        current = {**shared, "suggested_kind": "skill"}
        dk_prior = build_candidate_decision_key(prior)
        ck = build_candidate_content_key(prior)
        state = {
            "decision_key": dk_prior,
            "content_key": ck,
            "suggested_kind": "hook",
            "carry_forward": True,
            "user_decision": "defer",
            "intent_trace": ["Review PR"],
            "observation_count": 2,
            "recorded_at": "2026-03-18T00:00:00+09:00",
        }
        retained, app = apply_decision_states_to_candidates([current], {dk_prior: state}, {ck: state})
        self.assertEqual(len(retained), 1)
        self.assertTrue(retained[0].get("classification_migrated"))
        self.assertEqual(retained[0]["prior_decision_state"]["user_decision"], "defer")
        self.assertEqual(app["content_key_migrations"], 1)
        self.assertEqual(app["matched_candidates"], 1)

    def test_apply_decision_states_secondary_skipped_when_kind_unchanged(self) -> None:
        """Same content_key and same kind but decision_key miss: do not attach prior (edge case)."""
        shared = {
            "candidate_id": "c1",
            "label": "Review workflow",
            "intent_trace": ["Review PR"],
            "constraints": [],
            "acceptance_criteria": [],
            "suggested_kind": "skill",
            "triage_status": "ready",
            "proposal_ready": True,
            "quality_flags": [],
            "support": {"total_packets": 3},
        }
        wrong_dk = "0" * 16
        ck = build_candidate_content_key(shared)
        state = {
            "decision_key": wrong_dk,
            "content_key": ck,
            "suggested_kind": "skill",
            "carry_forward": True,
            "user_decision": None,
            "observation_count": 0,
        }
        retained, app = apply_decision_states_to_candidates([dict(shared)], {}, {ck: state})
        self.assertEqual(len(retained), 1)
        self.assertNotIn("prior_decision_state", retained[0])
        self.assertEqual(app["content_key_migrations"], 0)
        self.assertEqual(app["matched_candidates"], 0)

    def test_load_latest_decision_states_indexes_content_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "log.jsonl"
            row = {
                "record_type": "skill_miner_decision_stub",
                "decision_key": "aaaabbbbccccdddd",
                "label": "Review workflow",
                "suggested_kind": "hook",
                "intent_trace": ["Review PR"],
                "constraints": [],
                "acceptance_criteria": [],
                "carry_forward": True,
                "recorded_at": "2026-03-18T00:00:00+09:00",
            }
            ck = build_candidate_content_key(row)
            row["content_key"] = ck
            write_jsonl(path, [row])
            by_dk, by_ck, status = load_latest_decision_states(path)
            self.assertEqual(status["status"], "loaded")
            self.assertEqual(len(by_dk), 1)
            self.assertEqual(len(by_ck), 1)
            self.assertEqual(by_ck[ck]["suggested_kind"], "hook")
            self.assertEqual(by_ck[ck]["content_key"], ck)


if __name__ == "__main__":
    unittest.main()
