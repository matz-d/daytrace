#!/usr/bin/env python3

from __future__ import annotations

import json
import sqlite3
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


class StoreTests(unittest.TestCase):
    maxDiff = None

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
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
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
