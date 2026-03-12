#!/usr/bin/env python3

from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from derived_store import (
    ACTIVITY_DERIVATION_VERSION,
    PATTERN_DERIVATION_VERSION,
    SLICE_COMPLETE,
    SLICE_EMPTY,
    SLICE_PARTIAL,
    SLICE_STALE,
    evaluate_slice_completeness,
    get_activities,
    get_observations,
    get_patterns,
    persist_patterns_from_prepare,
)


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


class DerivedStoreTests(unittest.TestCase):
    maxDiff = None

    def create_fixture(self, root: Path, *, workspace_summary: str = "Persist workspace event") -> tuple[Path, Path, Path]:
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
                            "timestamp": "2026-03-12T09:00:00+09:00",
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

    def run_aggregate(self, sources_file: Path, workspace: Path, store_path: Path) -> None:
        completed = subprocess.run(
            [
                "python3",
                str(AGGREGATE),
                "--sources-file",
                str(sources_file),
                "--workspace",
                str(workspace),
                "--since",
                "2026-03-12",
                "--until",
                "2026-03-12",
                "--all-sessions",
                "--store-path",
                str(store_path),
            ],
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

    def test_get_activities_derives_and_persists_grouped_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(sources_file, workspace, store_path)

            activities = get_activities(store_path, workspace=workspace, since="2026-03-12", until="2026-03-12T23:59:59+09:00")
            self.assertEqual(len(activities), 2)
            self.assertEqual(activities[0]["derivation_version"], ACTIVITY_DERIVATION_VERSION)
            self.assertEqual(activities[0]["confidence"], "high")
            self.assertEqual(activities[0]["activity"]["summary"], "2 activities from ai-source, workspace-source")
            self.assertEqual(activities[1]["summary"], "Opened derived layer note")

            connection = sqlite3.connect(store_path)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM activities").fetchone()[0], 2)

    def test_get_activities_rebuilds_when_observations_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sources_file, workspace, store_path = self.create_fixture(root, workspace_summary="Initial workspace summary")
            self.run_aggregate(sources_file, workspace, store_path)
            first = get_activities(store_path, workspace=workspace, since="2026-03-12", until="2026-03-12T23:59:59+09:00")
            self.assertEqual(first[0]["activity"]["events"][0]["summary"], "Initial workspace summary")

            sources_file, workspace, _ = self.create_fixture(root, workspace_summary="Updated workspace summary")
            self.run_aggregate(sources_file, workspace, store_path)
            updated = get_activities(store_path, workspace=workspace, since="2026-03-12", until="2026-03-12T23:59:59+09:00")
            self.assertEqual(updated[0]["activity"]["events"][0]["summary"], "Updated workspace summary")

    def test_persist_patterns_from_prepare_and_query(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "daytrace.sqlite3"
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            payload = {
                "status": "success",
                "source": "skill-miner-prepare",
                "candidates": [
                    {
                        "candidate_id": "candidate-001",
                        "label": "Review workflow",
                        "score": 0.82,
                        "support": {"total_packets": 3},
                        "session_refs": ["codex:abc", "claude:def"],
                        "evidence_items": [{"session_ref": "codex:abc", "timestamp": "2026-03-12T09:00:00+09:00", "source": "codex-history", "summary": "Review findings"}],
                    }
                ],
                "summary": {"total_candidates": 1},
                "config": {
                    "workspace": str(workspace.resolve()),
                    "observation_mode": "workspace",
                    "days": 7,
                    "effective_days": 7,
                },
            }

            persist_patterns_from_prepare(payload, store_path=store_path)
            patterns = get_patterns(store_path, workspace=workspace, observation_mode="workspace", days=7)
            self.assertEqual(len(patterns), 1)
            self.assertEqual(patterns[0]["derivation_version"], PATTERN_DERIVATION_VERSION)
            self.assertEqual(patterns[0]["pattern"]["candidate_id"], "candidate-001")
            self.assertEqual(patterns[0]["label"], "Review workflow")

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
