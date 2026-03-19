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

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from store import bootstrap_store, persist_source_result


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


class StoreTests(unittest.TestCase):
    maxDiff = None

    def test_persist_source_result_normalizes_naive_collected_at(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            store_path = Path(temp_dir) / "daytrace.sqlite3"
            source = {
                "name": "workspace-source",
                "source_id": "workspace-source-v1",
                "source_identity": {"identity_version": "1"},
                "manifest_fingerprint": "a" * 64,
                "scope_mode": "workspace",
                "confidence_category": "git",
            }
            result = {
                "status": "success",
                "source": "workspace-source",
                "events": [
                    {
                        "source": "workspace-source",
                        "timestamp": "2026-03-12T09:00:00+09:00",
                        "type": "commit",
                        "summary": "Persist workspace event",
                        "details": {"workspace": str(workspace)},
                        "confidence": "high",
                    }
                ],
                "command": ["python3", "workspace_source.py"],
                "duration_sec": 0.1,
            }

            persist_source_result(
                result,
                source,
                workspace=workspace,
                requested_date=None,
                since="2026-03-12",
                until="2026-03-12",
                all_sessions=False,
                store_path=store_path,
                collected_at=datetime(2026, 3, 12, 10, 30, 0),
            )

            with sqlite3.connect(store_path) as connection:
                collected_at = connection.execute("SELECT collected_at FROM source_runs").fetchone()[0]
            self.assertRegex(collected_at, r"^2026-03-12T10:30:00[+-]\d{2}:\d{2}$")

    def create_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        workspace_source = root / "workspace_source.py"
        ai_source = root / "ai_source.py"
        write_file(
            workspace_source,
            textwrap.dedent(
                """
                import json
                import sys

                args = sys.argv[1:]
                since = args[args.index("--since") + 1] if "--since" in args else None
                until = args[args.index("--until") + 1] if "--until" in args else None
                workspace = args[args.index("--workspace") + 1] if "--workspace" in args else None
                print(json.dumps({
                    "status": "success",
                    "source": "workspace-source",
                    "events": [
                        {
                            "source": "workspace-source",
                            "timestamp": "2026-03-12T09:00:00+09:00",
                            "type": "commit",
                            "summary": "Persist workspace event",
                            "details": {"workspace": workspace, "since": since, "until": until},
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
                        "unsupported-source",
                        f"python3 {ai_source}",
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
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "success")

    def test_store_bootstrap_and_ingest_persist_source_runs_and_observations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(sources_file, workspace, store_path)

            with sqlite3.connect(store_path) as connection:
                connection.row_factory = sqlite3.Row
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM source_runs").fetchone()[0], 3)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2)

                workspace_row = connection.execute(
                    "SELECT * FROM source_runs WHERE source_name = 'workspace-source'"
                ).fetchone()
                self.assertIsNotNone(workspace_row)
                self.assertEqual(workspace_row["scope_mode"], "workspace")
                self.assertEqual(workspace_row["workspace"], str(workspace.resolve()))
                self.assertEqual(workspace_row["requested_date"], None)
                self.assertEqual(workspace_row["since_value"], "2026-03-12")
                self.assertEqual(workspace_row["until_value"], "2026-03-12")
                self.assertEqual(workspace_row["all_sessions"], 1)
                self.assertEqual(workspace_row["events_count"], 1)
                self.assertRegex(workspace_row["manifest_fingerprint"], r"^[0-9a-f]{64}$")
                self.assertEqual(json.loads(workspace_row["confidence_categories_json"]), ["git"])
                self.assertRegex(workspace_row["command_fingerprint"], r"^[0-9a-f]{64}$")

                observation_row = connection.execute(
                    "SELECT * FROM observations WHERE source_name = 'workspace-source'"
                ).fetchone()
                self.assertIsNotNone(observation_row)
                event_json = json.loads(observation_row["event_json"])
                self.assertEqual(event_json["source"], "workspace-source")
                self.assertEqual(event_json["type"], "commit")
                self.assertRegex(observation_row["event_fingerprint"], r"^[0-9a-f]{64}$")
                self.assertEqual(observation_row["observation_kind"], "event")

    def test_bootstrap_store_migrates_v2_observations_with_observation_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "daytrace.sqlite3"
            with sqlite3.connect(store_path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE source_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_fingerprint TEXT NOT NULL UNIQUE,
                        source_name TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        identity_version TEXT NOT NULL,
                        manifest_fingerprint TEXT NOT NULL,
                        confidence_categories_json TEXT NOT NULL DEFAULT '[]',
                        command_fingerprint TEXT NOT NULL,
                        status TEXT NOT NULL,
                        scope_mode TEXT NOT NULL,
                        workspace TEXT NOT NULL,
                        requested_date TEXT,
                        since_value TEXT,
                        until_value TEXT,
                        all_sessions INTEGER NOT NULL,
                        filters_json TEXT NOT NULL,
                        command_json TEXT NOT NULL,
                        reason TEXT,
                        message TEXT,
                        duration_sec REAL NOT NULL,
                        events_count INTEGER NOT NULL,
                        collected_at TEXT NOT NULL
                    );

                    CREATE TABLE observations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_run_id INTEGER NOT NULL,
                        event_fingerprint TEXT NOT NULL,
                        source_name TEXT NOT NULL,
                        scope_mode TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        confidence TEXT NOT NULL,
                        details_json TEXT NOT NULL,
                        event_json TEXT NOT NULL,
                        collected_at TEXT NOT NULL,
                        FOREIGN KEY(source_run_id) REFERENCES source_runs(id) ON DELETE CASCADE,
                        UNIQUE(source_run_id, event_fingerprint)
                    );
                    """
                )
                connection.execute(
                    """
                    INSERT INTO source_runs (
                        run_fingerprint, source_name, source_id, identity_version, manifest_fingerprint,
                        confidence_categories_json, command_fingerprint, status, scope_mode, workspace,
                        requested_date, since_value, until_value, all_sessions, filters_json, command_json,
                        reason, message, duration_sec, events_count, collected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "r" * 64,
                        "workspace-source",
                        "workspace-source-v1",
                        "1",
                        "m" * 64,
                        "[]",
                        "c" * 64,
                        "success",
                        "workspace",
                        "/tmp/workspace",
                        None,
                        "2026-03-12",
                        "2026-03-12",
                        0,
                        "{}",
                        "[]",
                        None,
                        None,
                        0.1,
                        1,
                        "2026-03-12T10:00:00+09:00",
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO observations (
                        source_run_id, event_fingerprint, source_name, scope_mode, occurred_at,
                        event_type, summary, confidence, details_json, event_json, collected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        "e" * 64,
                        "workspace-source",
                        "workspace",
                        "2026-03-12T09:00:00+09:00",
                        "commit",
                        "Persist workspace event",
                        "high",
                        "{}",
                        '{"source":"workspace-source","timestamp":"2026-03-12T09:00:00+09:00","type":"commit","summary":"Persist workspace event","details":{},"confidence":"high"}',
                        "2026-03-12T10:00:00+09:00",
                    ),
                )
                connection.execute("PRAGMA user_version = 2")
                connection.commit()

            bootstrap_store(store_path)

            with sqlite3.connect(store_path) as connection:
                connection.row_factory = sqlite3.Row
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
                observation_columns = {
                    str(row["name"]): str(row["type"]) for row in connection.execute("PRAGMA table_info(observations)").fetchall()
                }
                self.assertIn("observation_kind", observation_columns)
                row = connection.execute("SELECT observation_kind FROM observations").fetchone()
                self.assertEqual(row["observation_kind"], "event")

    def test_rerun_reuses_same_source_runs_without_duplicate_observations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(sources_file, workspace, store_path)
            self.run_aggregate(sources_file, workspace, store_path)

            with sqlite3.connect(store_path) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM source_runs").fetchone()[0], 3)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2)

    def test_aggregate_returns_success_when_store_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            store_path.parent.mkdir(parents=True, exist_ok=True)
            store_path.mkdir()  # directory, not file — causes sqlite3 to fail

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
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertIn("store_error", payload["config"])
            self.assertIn("[warn]", completed.stderr)
            self.assertGreater(len(payload["timeline"]), 0)

    def test_store_can_be_rebuilt_after_db_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(sources_file, workspace, store_path)
            store_path.unlink()
            self.run_aggregate(sources_file, workspace, store_path)

            with sqlite3.connect(store_path) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM source_runs").fetchone()[0], 3)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
