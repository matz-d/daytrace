#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
AGGREGATE = PLUGIN_ROOT / "scripts" / "aggregate.py"


def write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def make_source_entry(
    name: str,
    command: str,
    *,
    supports_date_range: bool,
    supports_all_sessions: bool,
    confidence_category: str,
    scope_mode: str,
    platforms: list[str] | None = None,
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
        "prerequisites": [],
        "confidence_category": confidence_category,
    }


class AggregateContractTests(unittest.TestCase):
    maxDiff = None

    def run_aggregate(self, sources_file: Path, *extra_args: str) -> tuple[dict[str, object], subprocess.CompletedProcess[str]]:
        store_path = sources_file.parent / "daytrace.sqlite3"
        completed = subprocess.run(
            [
                "python3",
                str(AGGREGATE),
                "--sources-file",
                str(sources_file),
                "--store-path",
                str(store_path),
                *extra_args,
            ],
            cwd=str(PLUGIN_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "success", msg=completed.stdout)
        return payload, completed

    def create_contract_fixture(self, root: Path) -> tuple[Path, Path]:
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        workspace_source = root / "workspace_source.py"
        ai_source = root / "ai_source.py"
        browser_source = root / "browser_source.py"
        invalid_json_source = root / "invalid_json_source.py"

        write_file(
            workspace_source,
            textwrap.dedent(
                """
                import json
                import sys

                args = sys.argv[1:]
                workspace = args[args.index("--workspace") + 1] if "--workspace" in args else None
                since = args[args.index("--since") + 1] if "--since" in args else None
                until = args[args.index("--until") + 1] if "--until" in args else None
                print(json.dumps({
                    "status": "success",
                    "source": "workspace-source",
                    "events": [
                        {
                            "source": "workspace-source",
                            "timestamp": "2026-03-11T10:07:00+09:00",
                            "type": "commit",
                            "summary": "Refactor aggregate entrypoint",
                            "details": {
                                "workspace": workspace,
                                "since": since,
                                "until": until
                            },
                            "confidence": "high"
                        }
                    ]
                }))
                """
            ).strip(),
        )
        write_file(
            ai_source,
            textwrap.dedent(
                """
                import json
                import sys

                args = sys.argv[1:]
                print(json.dumps({
                    "status": "success",
                    "source": "ai-source",
                    "events": [
                        {
                            "source": "ai-source",
                            "timestamp": "2026-03-11T10:00:00+09:00",
                            "type": "session_summary",
                            "summary": "Discussed aggregate contract coverage",
                            "details": {
                                "all_sessions": "--all-sessions" in args
                            },
                            "confidence": "medium"
                        }
                    ]
                }))
                """
            ).strip(),
        )
        write_file(
            browser_source,
            textwrap.dedent(
                """
                import json

                print(json.dumps({
                    "status": "success",
                    "source": "browser-source",
                    "events": [
                        {
                            "source": "browser-source",
                            "timestamp": "2026-03-11T11:00:00+09:00",
                            "type": "browser_visit",
                            "summary": "Opened architecture refresh plan",
                            "details": {
                                "url": "https://example.test/architecture-refresh"
                            },
                            "confidence": "low"
                        }
                    ]
                }))
                """
            ).strip(),
        )
        write_file(invalid_json_source, "print('not json')")

        sources_file = root / "sources.json"
        write_file(
            sources_file,
            json.dumps(
                [
                    make_source_entry(
                        "workspace-source",
                        f"python3 {workspace_source}",
                        supports_date_range=True,
                        supports_all_sessions=False,
                        confidence_category="git",
                        scope_mode="workspace",
                    ),
                    make_source_entry(
                        "ai-source",
                        f"python3 {ai_source}",
                        supports_date_range=True,
                        supports_all_sessions=True,
                        confidence_category="ai_history",
                        scope_mode="all-day",
                    ),
                    make_source_entry(
                        "browser-source",
                        f"python3 {browser_source}",
                        supports_date_range=False,
                        supports_all_sessions=False,
                        confidence_category="browser",
                        scope_mode="all-day",
                    ),
                    make_source_entry(
                        "invalid-json-source",
                        f"python3 {invalid_json_source}",
                        supports_date_range=False,
                        supports_all_sessions=False,
                        confidence_category="other",
                        scope_mode="all-day",
                    ),
                    make_source_entry(
                        "unsupported-source",
                        f"python3 {browser_source}",
                        supports_date_range=False,
                        supports_all_sessions=False,
                        confidence_category="other",
                        scope_mode="workspace",
                        platforms=["win32"],
                    ),
                ],
                ensure_ascii=False,
            ),
        )
        return sources_file, workspace

    def create_strict_forwarding_fixture(
        self,
        root: Path,
        *,
        expected_workspace: Path,
        expected_since: str,
        expected_until: str,
        require_all_sessions: bool,
    ) -> Path:
        strict_source = root / "strict_forwarding_source.py"
        write_file(
            strict_source,
            textwrap.dedent(
                f"""
                import json
                import sys

                args = sys.argv[1:]
                workspace = args[args.index("--workspace") + 1] if "--workspace" in args else None
                since = args[args.index("--since") + 1] if "--since" in args else None
                until = args[args.index("--until") + 1] if "--until" in args else None
                all_sessions = "--all-sessions" in args
                success = (
                    workspace == {str(expected_workspace.resolve())!r}
                    and since == {expected_since!r}
                    and until == {expected_until!r}
                    and all_sessions == {require_all_sessions!r}
                )
                payload = {{
                    "status": "success" if success else "skipped",
                    "source": "strict-source",
                    "events": [],
                }}
                if success:
                    payload["events"] = [
                        {{
                            "source": "strict-source",
                            "timestamp": "2026-03-11T09:30:00+09:00",
                            "type": "session_summary",
                            "summary": "Forwarding contract accepted",
                            "details": {{
                                "workspace": workspace,
                                "since": since,
                                "until": until,
                                "all_sessions": all_sessions,
                            }},
                            "confidence": "medium",
                        }}
                    ]
                else:
                    payload["reason"] = "unexpected_args"
                print(json.dumps(payload))
                """
            ).strip(),
        )

        sources_file = root / "sources.json"
        write_file(
            sources_file,
            json.dumps(
                [
                    make_source_entry(
                        "strict-source",
                        f"python3 {strict_source}",
                        supports_date_range=True,
                        supports_all_sessions=True,
                        confidence_category="ai_history",
                        scope_mode="all-day",
                    )
                ],
                ensure_ascii=False,
            ),
        )
        return sources_file

    def create_unsupported_only_sources(self, root: Path) -> Path:
        sources_file = root / "sources.json"
        write_file(
            sources_file,
            json.dumps(
                [
                    make_source_entry(
                        "unsupported-source",
                        "python3 /tmp/does-not-matter.py",
                        supports_date_range=False,
                        supports_all_sessions=False,
                        confidence_category="other",
                        scope_mode="workspace",
                        platforms=["win32"],
                    )
                ],
                ensure_ascii=False,
            ),
        )
        return sources_file

    def test_top_level_contract_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace = self.create_contract_fixture(Path(temp_dir))
            payload, _ = self.run_aggregate(
                sources_file,
                "--workspace",
                str(workspace),
                "--since",
                "2026-03-11",
                "--until",
                "2026-03-11",
                "--all-sessions",
            )

            for key in ("status", "generated_at", "workspace", "filters", "config", "sources", "timeline", "groups", "summary"):
                self.assertIn(key, payload)
            self.assertEqual(payload["workspace"], str(workspace.resolve()))
            self.assertEqual(
                payload["filters"],
                {
                    "since": "2026-03-11",
                    "until": "2026-03-11",
                    "date": None,
                    "all_sessions": True,
                    "group_window": 15,
                    "max_span": 60,
                },
            )
            self.assertEqual(payload["config"]["group_window_minutes"], 15)
            self.assertEqual(payload["config"]["max_span_minutes"], 60)
            self.assertEqual(payload["config"]["evidence_limit"], 5)
            self.assertEqual(Path(payload["config"]["sources_file"]), sources_file.resolve())

    def test_sources_contract_shape_and_status_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace = self.create_contract_fixture(Path(temp_dir))
            payload, completed = self.run_aggregate(sources_file, "--workspace", str(workspace), "--all-sessions")

            sources = {entry["name"]: entry for entry in payload["sources"]}
            self.assertEqual(set(sources), {"ai-source", "browser-source", "invalid-json-source", "unsupported-source", "workspace-source"})
            for entry in sources.values():
                for field in ("name", "status", "scope", "events_count"):
                    self.assertIn(field, entry)
                if "command" in entry:
                    self.assertIsInstance(entry["command"], list)
                if "duration_sec" in entry:
                    self.assertIsInstance(entry["duration_sec"], float)

            self.assertEqual(sources["workspace-source"]["status"], "success")
            self.assertEqual(sources["workspace-source"]["scope"], "workspace")
            self.assertEqual(sources["workspace-source"]["events_count"], 1)

            self.assertEqual(sources["ai-source"]["status"], "success")
            self.assertEqual(sources["ai-source"]["scope"], "all-day")
            self.assertEqual(sources["ai-source"]["events_count"], 1)

            self.assertEqual(sources["browser-source"]["status"], "success")
            self.assertEqual(sources["browser-source"]["scope"], "all-day")

            self.assertEqual(sources["invalid-json-source"]["status"], "error")
            self.assertEqual(sources["invalid-json-source"]["scope"], "all-day")
            self.assertIn("message", sources["invalid-json-source"])

            self.assertEqual(sources["unsupported-source"]["status"], "skipped")
            self.assertEqual(sources["unsupported-source"]["scope"], "workspace")
            self.assertEqual(sources["unsupported-source"]["reason"], "unsupported_platform")

            self.assertIn("Source preflight:", completed.stderr)
            self.assertIn("skipped=unsupported-source(unsupported_platform)", completed.stderr)

    def test_timeline_contract_and_sort_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace = self.create_contract_fixture(Path(temp_dir))
            payload, _ = self.run_aggregate(
                sources_file,
                "--workspace",
                str(workspace),
                "--since",
                "2026-03-11",
                "--until",
                "2026-03-11",
                "--all-sessions",
            )

            timeline = payload["timeline"]
            self.assertEqual([event["timestamp"] for event in timeline], sorted(event["timestamp"] for event in timeline))
            self.assertEqual([event["source"] for event in timeline], ["ai-source", "workspace-source", "browser-source"])
            for event in timeline:
                for field in ("source", "timestamp", "type", "summary", "details", "confidence", "group_id"):
                    self.assertIn(field, event)
                self.assertIsInstance(event["details"], dict)

    def test_groups_contract_and_grouping_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace = self.create_contract_fixture(Path(temp_dir))
            payload, _ = self.run_aggregate(
                sources_file,
                "--workspace",
                str(workspace),
                "--since",
                "2026-03-11",
                "--until",
                "2026-03-11",
                "--all-sessions",
            )

            groups = payload["groups"]
            self.assertEqual(len(groups), 2)
            for group in groups:
                for field in (
                    "id",
                    "start_timestamp",
                    "end_timestamp",
                    "summary",
                    "confidence",
                    "sources",
                    "confidence_categories",
                    "source_count",
                    "event_count",
                    "evidence",
                    "events",
                ):
                    self.assertIn(field, group)
                self.assertLessEqual(len(group["evidence"]), 5)
                for evidence in group["evidence"]:
                    self.assertEqual(set(evidence), {"timestamp", "source", "type", "summary"})
                for event in group["events"]:
                    self.assertEqual(event["group_id"], group["id"])

            first_group = groups[0]
            self.assertEqual(first_group["id"], "group-001")
            self.assertEqual(first_group["confidence"], "high")
            self.assertEqual(first_group["sources"], ["ai-source", "workspace-source"])
            self.assertEqual(first_group["confidence_categories"], ["ai_history", "git"])
            self.assertEqual(first_group["source_count"], 2)
            self.assertEqual(first_group["event_count"], 2)
            self.assertEqual(first_group["summary"], "Refactor aggregate entrypoint + 1 related activities")

            second_group = groups[1]
            self.assertEqual(second_group["id"], "group-002")
            self.assertEqual(second_group["confidence"], "low")
            self.assertEqual(second_group["sources"], ["browser-source"])
            self.assertEqual(second_group["summary"], "Opened architecture refresh plan")

    def test_summary_contract_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace = self.create_contract_fixture(Path(temp_dir))
            payload, _ = self.run_aggregate(sources_file, "--workspace", str(workspace), "--all-sessions")

            self.assertEqual(
                payload["summary"],
                {
                    "source_status_counts": {"success": 3, "skipped": 1, "error": 1},
                    "total_events": 3,
                    "total_groups": 2,
                    "no_sources_available": False,
                },
            )

    def test_summary_no_sources_available_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file = self.create_unsupported_only_sources(Path(temp_dir))
            payload, completed = self.run_aggregate(sources_file)

            self.assertEqual(payload["timeline"], [])
            self.assertEqual(payload["groups"], [])
            self.assertEqual(payload["summary"]["source_status_counts"], {"success": 0, "skipped": 1, "error": 0})
            self.assertTrue(payload["summary"]["no_sources_available"])
            self.assertIn("available=none", completed.stderr)

    def test_workspace_since_until_and_all_sessions_are_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            sources_file = self.create_strict_forwarding_fixture(
                root,
                expected_workspace=workspace,
                expected_since="2026-03-11T00:00:00+09:00",
                expected_until="2026-03-11T23:59:59+09:00",
                require_all_sessions=True,
            )

            payload, _ = self.run_aggregate(
                sources_file,
                "--workspace",
                str(workspace),
                "--since",
                "2026-03-11T00:00:00+09:00",
                "--until",
                "2026-03-11T23:59:59+09:00",
                "--all-sessions",
            )

            self.assertEqual(payload["sources"][0]["status"], "success")
            self.assertEqual(payload["timeline"][0]["details"]["all_sessions"], True)
            self.assertEqual(payload["timeline"][0]["details"]["workspace"], str(workspace.resolve()))

    def test_date_shorthand_is_resolved_into_forwarded_since_until(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            sources_file = self.create_strict_forwarding_fixture(
                root,
                expected_workspace=workspace,
                expected_since="2026-03-11",
                expected_until="2026-03-11",
                require_all_sessions=False,
            )

            payload, _ = self.run_aggregate(
                sources_file,
                "--workspace",
                str(workspace),
                "--date",
                "2026-03-11",
            )

            self.assertEqual(payload["filters"]["date"], "2026-03-11")
            self.assertEqual(payload["filters"]["since"], None)
            self.assertEqual(payload["filters"]["until"], None)
            self.assertEqual(payload["sources"][0]["status"], "success")

    def test_downstream_smoke_fields_for_daily_report_and_post_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace = self.create_contract_fixture(Path(temp_dir))
            payload, _ = self.run_aggregate(sources_file, "--workspace", str(workspace), "--all-sessions")

            success_sources = [source for source in payload["sources"] if source["status"] == "success"]
            self.assertEqual({source["scope"] for source in success_sources}, {"all-day", "workspace"})

            primary_group = payload["groups"][0]
            for field in ("summary", "confidence", "sources", "confidence_categories", "event_count", "events", "evidence"):
                self.assertIn(field, primary_group)

            first_event = payload["timeline"][0]
            for field in ("summary", "type", "source", "timestamp", "group_id"):
                self.assertIn(field, first_event)

            for field in ("source_status_counts", "total_events", "total_groups", "no_sources_available"):
                self.assertIn(field, payload["summary"])


    def test_no_store_path_returns_valid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace = self.create_contract_fixture(Path(temp_dir))
            completed = subprocess.run(
                [
                    "python3",
                    str(AGGREGATE),
                    "--sources-file",
                    str(sources_file),
                    "--workspace",
                    str(workspace),
                    "--all-sessions",
                    "--no-store",
                ],
                cwd=str(PLUGIN_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertIsNone(payload["config"]["store_path"])
            self.assertNotIn("store_error", payload["config"])
            self.assertGreater(len(payload["timeline"]), 0)
            for event in payload["timeline"]:
                self.assertIn("group_id", event)


if __name__ == "__main__":
    unittest.main()
