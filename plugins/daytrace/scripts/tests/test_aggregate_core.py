#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from aggregate_core import (
    build_command,
    build_groups,
    build_preflight_summary,
    build_summary,
    collect_timeline,
    group_confidence,
    normalize_event,
    normalize_source_payload,
    resolve_date_filters,
    select_sources,
    source_availability,
)


def make_source(
    name: str,
    *,
    command: str = "python3 source.py",
    supports_date_range: bool = True,
    supports_all_sessions: bool = True,
    scope_mode: str = "all-day",
    platforms: list[str] | None = None,
    prerequisites: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "command": command,
        "required": False,
        "timeout_sec": 5,
        "platforms": platforms or ["darwin", "linux"],
        "supports_date_range": supports_date_range,
        "supports_all_sessions": supports_all_sessions,
        "scope_mode": scope_mode,
        "prerequisites": prerequisites or [],
    }


class AggregateCoreTests(unittest.TestCase):
    maxDiff = None

    def test_resolve_date_filters_supports_shorthand(self) -> None:
        now = datetime(2026, 3, 12, 8, 0, tzinfo=timezone.utc)
        self.assertEqual(resolve_date_filters("today", None, None, now=now), ("2026-03-12", "2026-03-12"))
        self.assertEqual(resolve_date_filters("yesterday", None, None, now=now), ("2026-03-11", "2026-03-11"))
        self.assertEqual(resolve_date_filters(None, "2026-03-01", "2026-03-02", now=now), ("2026-03-01", "2026-03-02"))
        with self.assertRaises(ValueError):
            resolve_date_filters("today", "2026-03-01", None, now=now)

    def test_build_command_resolves_script_and_forwards_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script_path = root / "source.py"
            script_path.write_text("print('ok')", encoding="utf-8")
            workspace = root / "workspace"
            workspace.mkdir()
            source = make_source(name="ai-source")

            command = build_command(
                source,
                workspace=workspace,
                since="2026-03-11",
                until="2026-03-12",
                all_sessions=True,
                script_dir=root,
            )

            self.assertEqual(command[0], "python3")
            self.assertEqual(command[1], str(script_path))
            self.assertEqual(
                command[2:],
                [
                    "--workspace",
                    str(workspace),
                    "--since",
                    "2026-03-11",
                    "--until",
                    "2026-03-12",
                    "--all-sessions",
                ],
            )

    def test_normalize_event_fills_defaults_and_rejects_invalid(self) -> None:
        normalized = normalize_event(
            {
                "timestamp": "2026-03-11T09:00:00+09:00",
                "type": "session_summary",
                "summary": "Reviewed aggregate contract",
                "details": "raw text",
                "confidence": "medium",
            },
            "ai-source",
        )
        assert normalized is not None
        self.assertEqual(normalized["source"], "ai-source")
        self.assertEqual(normalized["details"], {"raw_details": "raw text"})
        self.assertIsNone(
            normalize_event(
                {"timestamp": "2026-03-11T09:00:00+09:00", "type": "session_summary", "summary": "bad", "details": {}},
                "ai-source",
            )
        )
        with self.assertRaises(ValueError):
            normalize_event(
                {"timestamp": "invalid", "type": "session_summary", "summary": "bad", "details": {}, "confidence": "medium"},
                "ai-source",
            )

    def test_normalize_source_payload_filters_invalid_events(self) -> None:
        source = make_source(name="workspace-source", scope_mode="workspace")
        payload = {
            "status": "success",
            "events": [
                {
                    "timestamp": "2026-03-11T10:00:00+09:00",
                    "type": "commit",
                    "summary": "Keep this event",
                    "details": {},
                    "confidence": "high",
                },
                "drop this event",
            ],
        }

        normalized = normalize_source_payload(source, payload, command=["python3", "source.py"], duration_sec=1.234)
        self.assertEqual(normalized["status"], "success")
        self.assertEqual(normalized["scope"], "workspace")
        self.assertEqual(len(normalized["events"]), 1)
        self.assertEqual(normalized["events"][0]["source"], "workspace-source")
        self.assertEqual(normalized["duration_sec"], 1.234)

    def test_select_sources_and_preflight_summary_capture_platform_and_missing_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runnable_script = root / "runnable.py"
            runnable_script.write_text("print('ok')", encoding="utf-8")
            sources = [
                make_source(name="runnable", command=f"python3 {runnable_script.name}"),
                make_source(name="missing", command="python3 missing.py"),
                make_source(name="unsupported", platforms=["win32"], scope_mode="workspace"),
            ]

            runnable_sources, skipped_sources = select_sources(sources, source_names=None, platform_name="darwin")
            self.assertEqual([source["name"] for source in runnable_sources], ["runnable", "missing"])
            self.assertEqual(skipped_sources[0]["source"], "unsupported")

            summary = build_preflight_summary(runnable_sources, skipped_sources, workspace=root, script_dir=root)
            self.assertIn("available=runnable", summary)
            self.assertIn("unavailable=missing(command_missing)", summary)
            self.assertIn("skipped=unsupported(unsupported_platform)", summary)

    def test_source_availability_supports_path_prerequisite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            existing_path = root / "existing.txt"
            existing_path.write_text("ok", encoding="utf-8")
            script_path = root / "source.py"
            script_path.write_text("print('ok')", encoding="utf-8")
            source = make_source(
                name="path-check",
                command=f"python3 {script_path.name}",
                prerequisites=[{"type": "path_exists", "path": str(existing_path)}],
            )
            status, reason = source_availability(source, root, script_dir=root)
            self.assertEqual((status, reason), ("available", None))

    def test_grouping_confidence_and_summary_are_pure(self) -> None:
        timeline = [
            {
                "source": "ai-source",
                "timestamp": "2026-03-11T10:00:00+09:00",
                "type": "session_summary",
                "summary": "Discussed plan",
                "details": {},
                "confidence": "medium",
            },
            {
                "source": "workspace-source",
                "timestamp": "2026-03-11T10:10:00+09:00",
                "type": "commit",
                "summary": "Applied patch",
                "details": {},
                "confidence": "high",
            },
            {
                "source": "browser-source",
                "timestamp": "2026-03-11T11:00:00+09:00",
                "type": "browser_visit",
                "summary": "Opened doc",
                "details": {},
                "confidence": "low",
            },
        ]
        groups = build_groups(
            timeline,
            group_window_minutes=15,
            confidence_categories_by_source={
                "ai-source": ["ai_history"],
                "workspace-source": ["git"],
                "browser-source": ["browser"],
            },
            evidence_limit=1,
        )

        self.assertEqual(group_confidence({"git", "ai_history"}), "high")
        self.assertEqual(group_confidence({"git"}), "medium")
        self.assertEqual(group_confidence({"browser"}), "low")
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["confidence"], "high")
        self.assertEqual(groups[0]["event_count"], 2)
        self.assertEqual(len(groups[0]["evidence"]), 1)
        self.assertEqual(groups[0]["events"][0]["group_id"], "group-001")

    def test_collect_timeline_and_build_summary_are_cli_independent(self) -> None:
        source_results = [
            {
                "status": "success",
                "source": "b",
                "scope": "all-day",
                "events": [
                    {"source": "b", "timestamp": "2026-03-11T11:00:00+09:00", "type": "browser_visit", "summary": "later", "details": {}, "confidence": "low"}
                ],
            },
            {
                "status": "error",
                "source": "c",
                "scope": "workspace",
                "events": [],
            },
            {
                "status": "success",
                "source": "a",
                "scope": "workspace",
                "events": [
                    {"source": "a", "timestamp": "2026-03-11T10:00:00+09:00", "type": "commit", "summary": "earlier", "details": {}, "confidence": "high"}
                ],
            },
        ]
        timeline = collect_timeline(source_results)
        self.assertEqual([event["source"] for event in timeline], ["a", "b"])

        groups = build_groups(timeline, group_window_minutes=0, confidence_categories_by_source={}, evidence_limit=5)
        summary = build_summary(source_results, timeline, groups)
        self.assertEqual(summary["source_status_counts"], {"success": 2, "skipped": 0, "error": 1})
        self.assertEqual(summary["total_events"], 2)
        self.assertEqual(summary["total_groups"], 2)
        self.assertFalse(summary["no_sources_available"])


if __name__ == "__main__":
    unittest.main()
