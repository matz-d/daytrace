#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from aggregate_core import (
    build_command,
    build_groups,
    build_preflight_summary,
    build_summary,
    collect_timeline,
    group_confidence,
    normalize_event,
    normalize_source_payload,
    report_day_for_local_time,
    resolve_date_filters,
    select_sources,
    source_availability,
)
from common import ensure_datetime


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
        # Local 08:00 UTC → report day = calendar day (hour >= 6)
        now = datetime(2026, 3, 12, 8, 0, tzinfo=timezone.utc)
        self.assertEqual(resolve_date_filters("today", None, None, now=now), ("2026-03-12", "2026-03-12"))
        self.assertEqual(resolve_date_filters("yesterday", None, None, now=now), ("2026-03-11", "2026-03-11"))
        self.assertEqual(resolve_date_filters(None, "2026-03-01", "2026-03-02", now=now), ("2026-03-01", "2026-03-02"))
        with self.assertRaises(ValueError):
            resolve_date_filters("today", "2026-03-01", None, now=now)

    def test_resolve_date_filters_before_six_am_uses_previous_calendar_day(self) -> None:
        # Local 03:00 on calendar Mar 12 → report "today" = Mar 11
        now = datetime(2026, 3, 12, 3, 0, tzinfo=timezone.utc)
        self.assertEqual(report_day_for_local_time(now), date(2026, 3, 11))
        self.assertEqual(resolve_date_filters("today", None, None, now=now), ("2026-03-11", "2026-03-11"))
        self.assertEqual(resolve_date_filters("yesterday", None, None, now=now), ("2026-03-10", "2026-03-10"))

    def test_report_day_for_local_time_respects_timezone(self) -> None:
        # 03:00 in Tokyo on Mar 12 → still Mar 12 local date but hour < 6 → previous calendar day in local tz
        jst = ZoneInfo("Asia/Tokyo")
        now = datetime(2026, 3, 12, 3, 0, tzinfo=jst)
        self.assertEqual(report_day_for_local_time(now), date(2026, 3, 11))
        self.assertEqual(resolve_date_filters("today", None, None, now=now), ("2026-03-11", "2026-03-11"))
        # 10:00 Tokyo Mar 12 → report day Mar 12
        now_late = datetime(2026, 3, 12, 10, 0, tzinfo=jst)
        self.assertEqual(resolve_date_filters("today", None, None, now=now_late), ("2026-03-12", "2026-03-12"))
        self.assertEqual(resolve_date_filters("yesterday", None, None, now=now_late), ("2026-03-11", "2026-03-11"))

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


    def test_max_span_breaks_long_rolling_chain(self) -> None:
        """A chain of events every 14 min should be split when total span exceeds max_span."""
        timeline = []
        for i in range(8):
            h, m = divmod(i * 14, 60)
            timeline.append(
                {
                    "source": "a",
                    "timestamp": f"2026-03-11T{10 + h:02d}:{m:02d}:00+09:00",
                    "type": "commit",
                    "summary": f"event-{i}",
                    "details": {},
                    "confidence": "high",
                }
            )
        # 8 events at 0,14,28,42,56,70,84,98 min — total span 98 min.
        # Without max_span: 1 group. With max_span=60: should split.
        groups_no_limit = build_groups(
            timeline,
            group_window_minutes=15,
            confidence_categories_by_source={"a": ["git"]},
            max_span_minutes=0,
        )
        self.assertEqual(len(groups_no_limit), 1, "max_span=0 should produce 1 group")

        groups_limited = build_groups(
            timeline,
            group_window_minutes=15,
            confidence_categories_by_source={"a": ["git"]},
            max_span_minutes=60,
        )
        self.assertGreater(len(groups_limited), 1, "max_span=60 should split a 98-min chain")
        for group in groups_limited:
            start = ensure_datetime(group["start_timestamp"])
            end = ensure_datetime(group["end_timestamp"])
            self.assertLessEqual((end - start).total_seconds(), 60 * 60 + 1)

    def test_scope_breakdown_and_mixed_scope(self) -> None:
        timeline = [
            {
                "source": "git-source",
                "timestamp": "2026-03-11T10:00:00+09:00",
                "type": "commit",
                "summary": "fix",
                "details": {},
                "confidence": "high",
            },
            {
                "source": "claude-source",
                "timestamp": "2026-03-11T10:05:00+09:00",
                "type": "session_summary",
                "summary": "chat",
                "details": {},
                "confidence": "medium",
            },
        ]
        groups = build_groups(
            timeline,
            group_window_minutes=15,
            confidence_categories_by_source={
                "git-source": ["git"],
                "claude-source": ["ai_history"],
            },
            scope_mode_by_source={
                "git-source": "workspace",
                "claude-source": "all-day",
            },
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(sorted(groups[0]["scope_breakdown"]), ["all-day", "workspace"])
        self.assertTrue(groups[0]["mixed_scope"])

        # Single-scope group should not be mixed
        groups_single = build_groups(
            timeline[:1],
            group_window_minutes=15,
            confidence_categories_by_source={"git-source": ["git"]},
            scope_mode_by_source={"git-source": "workspace"},
        )
        self.assertEqual(groups_single[0]["scope_breakdown"], ["workspace"])
        self.assertFalse(groups_single[0]["mixed_scope"])

    def test_confidence_breakdown_counts_per_category(self) -> None:
        timeline = [
            {"source": "git-source", "timestamp": "2026-03-11T10:00:00+09:00", "type": "commit", "summary": "c1", "details": {}, "confidence": "high"},
            {"source": "git-source", "timestamp": "2026-03-11T10:02:00+09:00", "type": "commit", "summary": "c2", "details": {}, "confidence": "high"},
            {"source": "browser-source", "timestamp": "2026-03-11T10:05:00+09:00", "type": "visit", "summary": "v1", "details": {}, "confidence": "low"},
        ]
        groups = build_groups(
            timeline,
            group_window_minutes=15,
            confidence_categories_by_source={
                "git-source": ["git"],
                "browser-source": ["browser"],
            },
        )
        self.assertEqual(len(groups), 1)
        breakdown = groups[0]["confidence_breakdown"]
        self.assertEqual(breakdown["git"], 2)
        self.assertEqual(breakdown["browser"], 1)

    def test_salience_based_evidence_prefers_git_over_browser(self) -> None:
        """With default salience, git events should appear before browser events in evidence."""
        timeline = [
            {"source": "browser", "timestamp": "2026-03-11T10:00:00+09:00", "type": "visit", "summary": "browsed", "details": {}, "confidence": "low"},
            {"source": "browser", "timestamp": "2026-03-11T10:01:00+09:00", "type": "visit", "summary": "browsed2", "details": {}, "confidence": "low"},
            {"source": "git", "timestamp": "2026-03-11T10:02:00+09:00", "type": "commit", "summary": "committed", "details": {}, "confidence": "high"},
        ]
        groups = build_groups(
            timeline,
            group_window_minutes=15,
            confidence_categories_by_source={
                "browser": ["browser"],
                "git": ["git"],
            },
            evidence_limit=2,
        )
        self.assertEqual(len(groups), 1)
        # Git should come first in evidence despite being later in timeline
        self.assertEqual(groups[0]["evidence"][0]["source"], "git")
        self.assertEqual(groups[0]["evidence_overflow_count"], 1)

    def test_browser_only_large_group_is_flagged_for_share_exclusion(self) -> None:
        timeline = [
            {
                "source": "browser",
                "timestamp": f"2026-03-11T10:{index:02d}:00+09:00",
                "type": "visit",
                "summary": f"page-{index}",
                "details": {
                    "host": "x.com" if index < 5 else "google.com",
                    "flow_key": "home",
                    "visit_count": 3,
                    "page_count": 1,
                    "compressed": index < 3,
                },
                "confidence": "low",
            }
            for index in range(10)
        ]
        groups = build_groups(
            timeline,
            group_window_minutes=15,
            confidence_categories_by_source={"browser": ["browser"]},
        )

        self.assertEqual(len(groups), 1)
        share_policy = groups[0]["share_policy"]
        self.assertTrue(share_policy["auto_exclude_from_share"])
        self.assertEqual(share_policy["recommended_visibility"], "private_only")
        self.assertIn("oversized_browser_cluster", share_policy["reasons"])
        self.assertIn("share_sensitive_browser_hosts", share_policy["reasons"])
        self.assertEqual(groups[0]["browser_context"]["host_count"], 2)

    def test_large_cumulative_visit_count_without_dense_daily_activity_stays_caution_only(self) -> None:
        timeline = [
            {
                "source": "browser",
                "timestamp": "2026-03-11T10:00:00+09:00",
                "type": "visit",
                "summary": "one page",
                "details": {
                    "host": "example.com",
                    "flow_key": "article",
                    "visit_count": 999,
                    "page_count": 1,
                    "compressed": False,
                },
                "confidence": "low",
            },
            {
                "source": "browser",
                "timestamp": "2026-03-11T10:05:00+09:00",
                "type": "visit",
                "summary": "second page",
                "details": {
                    "host": "example.com",
                    "flow_key": "article",
                    "visit_count": 888,
                    "page_count": 1,
                    "compressed": False,
                },
                "confidence": "low",
            },
        ]
        groups = build_groups(
            timeline,
            group_window_minutes=15,
            confidence_categories_by_source={"browser": ["browser"]},
        )

        self.assertEqual(len(groups), 1)
        share_policy = groups[0]["share_policy"]
        self.assertFalse(share_policy["auto_exclude_from_share"])
        self.assertEqual(share_policy["recommended_visibility"], "share_with_caution")
        self.assertNotIn("high_browser_page_volume", share_policy["reasons"])


if __name__ == "__main__":
    unittest.main()
