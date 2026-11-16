#!/usr/bin/env python3

from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import textwrap
import unittest
from datetime import datetime
from pathlib import Path

from conftest import PLUGIN_ROOT

from derived_store import (
    SLICE_COMPLETE,
    SLICE_DEGRADED,
    SLICE_EMPTY,
    SLICE_PARTIAL,
    SLICE_STALE,
    evaluate_slice_completeness,
    get_observations,
    get_source_runs,
    get_slice_source_runs,
)


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


class DerivedStoreTests(unittest.TestCase):
    maxDiff = None

    def create_fixture(
        self,
        root: Path,
        *,
        workspace_summary: str = "Persist workspace event",
        workspace_timestamp: str = "2026-03-12T09:00:00+09:00",
    ) -> tuple[Path, Path, Path]:
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        workspace_source = root / "workspace_source.py"
        ai_source = root / "ai_source.py"
        browser_source = root / "browser_source.py"
        write_file(
            workspace_source,
            textwrap.dedent(
                f"""
                import json
                import sys

                args = sys.argv[1:]
                print(json.dumps({{
                    "status": "success",
                    "source": "workspace-source",
                    "events": [
                        {{
                            "source": "workspace-source",
                            "timestamp": {workspace_timestamp!r},
                            "type": "commit",
                            "summary": {workspace_summary!r},
                            "details": {{"workspace": args[args.index("--workspace") + 1]}},
                            "confidence": "high"
                        }}
                    ]
                }}))
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
                            "timestamp": "2026-03-12T09:05:00+09:00",
                            "type": "session_summary",
                            "summary": "Persist all-day event",
                            "details": {"all_sessions": "--all-sessions" in args},
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
                            "timestamp": "2026-03-12T11:00:00+09:00",
                            "type": "browser_visit",
                            "summary": "Opened derived layer note",
                            "details": {"url": "https://example.test/derived"},
                            "confidence": "low"
                        }
                    ]
                }))
                """
            ).strip(),
        )

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
                ],
                ensure_ascii=False,
            ),
        )
        return sources_file, workspace, root / "daytrace.sqlite3"

    def run_aggregate(
        self,
        sources_file: Path,
        workspace: Path,
        store_path: Path,
        *,
        since: str = "2026-03-12",
        until: str = "2026-03-12",
        all_sessions: bool = True,
    ) -> None:
        command = [
            "python3",
            str(AGGREGATE),
            "--sources-file",
            str(sources_file),
            "--workspace",
            str(workspace),
            "--since",
            since,
            "--until",
            until,
            "--store-path",
            str(store_path),
        ]
        if all_sessions:
            command.append("--all-sessions")
        completed = subprocess.run(
            command,
            cwd=str(PLUGIN_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)

    def test_get_observations_returns_normalized_rows_with_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(sources_file, workspace, store_path)

            observations = get_observations(store_path, workspace=workspace, since="2026-03-12", until="2026-03-12T23:59:59+09:00")
            self.assertEqual(len(observations), 3)
            self.assertEqual(observations[0]["source_name"], "workspace-source")
            self.assertEqual(observations[0]["event"]["summary"], "Persist workspace event")
            self.assertEqual(observations[0]["confidence_categories"], ["git"])
            self.assertEqual(observations[1]["confidence_categories"], ["ai_history"])

    def test_get_observations_fail_soft_on_corrupted_json_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(sources_file, workspace, store_path)

            with sqlite3.connect(store_path) as connection:
                connection.execute(
                    """
                    UPDATE source_runs
                    SET confidence_categories_json = '{'
                    """
                )
                connection.execute(
                    """
                    UPDATE observations
                    SET details_json = '{',
                        event_json = '{'
                    """
                )
                connection.commit()

            observations = get_observations(store_path, workspace=workspace, since="2026-03-12", until="2026-03-12T23:59:59+09:00")
            self.assertTrue(observations)
            self.assertEqual(observations[0]["confidence_categories"], [])
            self.assertEqual(observations[0]["details"], {})
            self.assertEqual(observations[0]["event"], {})
            self.assertIn("decode_warnings", observations[0])

    def test_get_source_runs_fail_soft_on_corrupted_json_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(sources_file, workspace, store_path)

            with sqlite3.connect(store_path) as connection:
                connection.execute(
                    """
                    UPDATE source_runs
                    SET confidence_categories_json = '{',
                        filters_json = '{',
                        command_json = '{'
                    """
                )
                connection.commit()

            source_runs = get_source_runs(store_path, workspace=workspace, all_sessions=True)
            self.assertTrue(source_runs)
            self.assertEqual(source_runs[0]["confidence_categories"], [])
            self.assertEqual(source_runs[0]["filters"], {})
            self.assertEqual(source_runs[0]["command"], [])
            self.assertIn("decode_warnings", source_runs[0])

    def test_evaluate_slice_completeness_reuses_covering_broader_slice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(
                sources_file,
                workspace,
                store_path,
                since="2026-03-01",
                until="2026-03-31",
            )

            result = evaluate_slice_completeness(
                store_path,
                workspace=workspace,
                since="2026-03-12",
                until="2026-03-12",
                all_sessions=True,
                expected_source_names={"workspace-source", "ai-source", "browser-source"},
            )
            selected_runs = get_slice_source_runs(
                store_path,
                workspace=workspace,
                since="2026-03-12",
                until="2026-03-12",
                all_sessions=True,
            )

            self.assertEqual(result["status"], SLICE_COMPLETE)
            self.assertEqual([run["source_name"] for run in selected_runs], ["ai-source", "browser-source", "workspace-source"])

    def test_get_slice_source_runs_prefers_narrower_covering_run_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(
                sources_file,
                workspace,
                store_path,
                since="2026-03-01",
                until="2026-03-31",
            )
            self.run_aggregate(
                sources_file,
                workspace,
                store_path,
                since="2026-03-12",
                until="2026-03-12",
            )

            selected_runs = get_slice_source_runs(
                store_path,
                workspace=workspace,
                since="2026-03-12",
                until="2026-03-12",
                all_sessions=True,
            )

            self.assertEqual(len(selected_runs), 3)
            self.assertEqual(len({run["run_fingerprint"] for run in selected_runs}), 3)

    def test_evaluate_slice_completeness_empty_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "daytrace.sqlite3"
            result = evaluate_slice_completeness(
                store_path,
                workspace=Path(temp_dir) / "workspace",
                since="2026-03-12",
                until="2026-03-12",
                expected_source_names={"workspace-source", "ai-source"},
            )
            self.assertEqual(result["status"], SLICE_EMPTY)
            self.assertEqual(result["missing_sources"], ["ai-source", "workspace-source"])

    def test_evaluate_slice_completeness_partial(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(sources_file, workspace, store_path)
            result = evaluate_slice_completeness(
                store_path,
                workspace=workspace,
                since="2026-03-12",
                until="2026-03-12",
                all_sessions=True,
                expected_source_names={"workspace-source", "ai-source", "browser-source", "extra-source"},
            )
            self.assertEqual(result["status"], SLICE_PARTIAL)
            self.assertIn("extra-source", result["missing_sources"])

    def test_evaluate_slice_completeness_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(sources_file, workspace, store_path)
            result = evaluate_slice_completeness(
                store_path,
                workspace=workspace,
                since="2026-03-12",
                until="2026-03-12",
                all_sessions=True,
                expected_source_names={"workspace-source", "ai-source", "browser-source"},
            )
            self.assertEqual(result["status"], SLICE_COMPLETE)
            self.assertEqual(result["missing_sources"], [])

    def test_evaluate_slice_completeness_reports_skipped_sources_as_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sources_file, workspace, store_path = self.create_fixture(root)
            base_sources = json.loads(sources_file.read_text(encoding="utf-8"))
            expanded_sources_file = root / "sources-with-skipped.json"
            expanded_sources_file.write_text(
                json.dumps(
                    base_sources
                    + [
                        make_source_entry(
                            "skipped-source",
                            "python3 skipped_source.py",
                            supports_date_range=True,
                            supports_all_sessions=True,
                            confidence_category="other",
                            scope_mode="all-day",
                            platforms=["win32"],
                        )
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.run_aggregate(expanded_sources_file, workspace, store_path)
            result = evaluate_slice_completeness(
                store_path,
                workspace=workspace,
                since="2026-03-12",
                until="2026-03-12",
                all_sessions=True,
                expected_source_names={"workspace-source", "ai-source", "browser-source", "skipped-source"},
            )
            self.assertEqual(result["status"], SLICE_DEGRADED)
            self.assertEqual(result["skipped_sources"], ["skipped-source"])

    def test_evaluate_slice_completeness_stale_when_manifest_fingerprint_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(sources_file, workspace, store_path)
            result = evaluate_slice_completeness(
                store_path,
                workspace=workspace,
                since="2026-03-12",
                until="2026-03-12",
                all_sessions=True,
                expected_source_names={"workspace-source", "ai-source", "browser-source"},
                expected_fingerprints={"workspace-source": "0" * 64},
            )
            self.assertEqual(result["status"], SLICE_STALE)
            self.assertEqual(result["stale_sources"], ["workspace-source"])

    def test_get_observations_from_broader_slice_respects_time_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(
                sources_file,
                workspace,
                store_path,
                since="2026-03-01",
                until="2026-03-31",
            )

            # Query a time window that excludes the first two events (09:00, 09:05)
            observations = get_observations(
                store_path,
                workspace=workspace,
                since="2026-03-12T10:00:00+09:00",
                until="2026-03-12T23:59:59+09:00",
                source_run_ids=[
                    int(run["source_run_id"])
                    for run in get_slice_source_runs(
                        store_path,
                        workspace=workspace,
                        since="2026-03-12",
                        until="2026-03-12",
                        all_sessions=True,
                    )
                ],
            )

            self.assertEqual(len(observations), 1)
            self.assertEqual(observations[0]["source_name"], "browser-source")

    def test_get_observations_keeps_morning_events_before_utc_midnight(self) -> None:
        # Claude and Codex write UTC timestamps. 07:30 JST is 22:30 UTC on the
        # previous day, and comparing it as a string against a +09:00 bound
        # used to drop every event before 09:00 JST from a day query.
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(
                Path(temp_dir),
                workspace_timestamp="2026-03-11T22:30:00+00:00",
            )
            self.run_aggregate(sources_file, workspace, store_path, since="2026-03-12", until="2026-03-12")

            observations = get_observations(
                store_path,
                workspace=workspace,
                since="2026-03-12T00:00:00+09:00",
                until="2026-03-12T23:59:59.999999+09:00",
                all_sessions=True,
            )

            self.assertIn("workspace-source", {observation["source_name"] for observation in observations})
            self.assertTrue(all(observation["occurred_at"].endswith("+00:00") for observation in observations))

    def test_get_observations_daily_runs_only_skips_range_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(sources_file, workspace, store_path, since="2026-03-01", until="2026-03-31")

            observations = get_observations(
                store_path,
                workspace=workspace,
                since="2026-03-12",
                until="2026-03-12",
                all_sessions=True,
                daily_runs_only=True,
            )

            self.assertEqual(observations, [])
