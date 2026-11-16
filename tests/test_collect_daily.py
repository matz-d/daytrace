#!/usr/bin/env python3

from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import textwrap
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from conftest import PLUGIN_ROOT

from collect_daily import days_to_collect
from store import bootstrap_store

COLLECT = PLUGIN_ROOT / "scripts" / "collect_daily.py"
READ_LOG = PLUGIN_ROOT / "scripts" / "read_log.py"


def make_fixture(root: Path) -> tuple[Path, Path, Path]:
    """One workspace-scoped source that emits an event at 07:30 local time on the requested day."""
    workspace = root / "workspace"
    workspace.mkdir()
    source = root / "file_source.py"
    source.write_text(
        textwrap.dedent(
            """
            import json
            import sys
            from datetime import datetime, timezone

            args = sys.argv[1:]
            day = args[args.index("--since") + 1][:10]
            local = datetime.fromisoformat(day + "T07:30:00").astimezone()
            print(json.dumps({
                "status": "success",
                "source": "workspace-file-activity",
                "events": [{
                    "source": "workspace-file-activity",
                    "timestamp": local.astimezone(timezone.utc).isoformat(),
                    "type": "untracked_file",
                    "summary": "Untracked file activity: notes.md",
                    "details": {},
                    "confidence": "low"
                }]
            }))
            """
        ).strip(),
        encoding="utf-8",
    )
    sources_file = root / "sources.json"
    sources_file.write_text(
        json.dumps(
            [
                {
                    "name": "workspace-file-activity",
                    "command": f"python3 {source}",
                    "required": False,
                    "timeout_sec": 5,
                    "platforms": ["darwin", "linux"],
                    "supports_date_range": True,
                    "supports_all_sessions": False,
                    "scope_mode": "workspace",
                    "prerequisites": [],
                    "confidence_category": "file_activity",
                }
            ]
        ),
        encoding="utf-8",
    )
    return workspace, sources_file, root / "daytrace.sqlite3"


def run(command: list[str]) -> dict:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)


class CollectDailyTests(unittest.TestCase):
    def test_collects_missing_yesterday_once_then_only_today(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, sources_file, store_path = make_fixture(Path(temp_dir))
            command = [
                "python3",
                str(COLLECT),
                "--workspace",
                str(workspace),
                "--store-path",
                str(store_path),
                "--sources-file",
                str(sources_file),
            ]
            today = datetime.now().astimezone().date()
            yesterday = today - timedelta(days=1)

            first = run(command)
            second = run(command)

            self.assertEqual(first["status"], "success")
            self.assertEqual([item["date"] for item in first["runs"]], [yesterday.isoformat(), today.isoformat()])
            self.assertEqual([item["date"] for item in second["runs"]], [today.isoformat()])

            # The 07:30 local event is before UTC midnight in UTC+ zones and must still be read back.
            log = run(
                [
                    "python3",
                    str(READ_LOG),
                    "--workspace",
                    str(workspace),
                    "--store-path",
                    str(store_path),
                    "--date",
                    yesterday.isoformat(),
                ]
            )
            self.assertEqual(log["counts"], {"workspace-file-activity": 1})

    def test_failed_source_is_reported_without_failing_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, sources_file, store_path = make_fixture(root)
            broken = root / "broken_source.py"
            broken.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
            registry = json.loads(sources_file.read_text(encoding="utf-8"))
            registry.append({**registry[0], "name": "claude-history", "command": f"python3 {broken}", "scope_mode": "all-day"})
            sources_file.write_text(json.dumps(registry), encoding="utf-8")

            result = run(
                [
                    "python3",
                    str(COLLECT),
                    "--workspace",
                    str(workspace),
                    "--store-path",
                    str(store_path),
                    "--sources-file",
                    str(sources_file),
                ]
            )

            self.assertEqual(result["status"], "success")
            statuses = {source["name"]: source["status"] for source in result["runs"][-1]["sources"]}
            self.assertEqual(statuses, {"claude-history": "error", "workspace-file-activity": "success"})

    def test_unusable_registry_fails_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, sources_file, store_path = make_fixture(root)
            sources_file.write_text("not json", encoding="utf-8")

            completed = subprocess.run(
                [
                    "python3",
                    str(COLLECT),
                    "--workspace",
                    str(workspace),
                    "--store-path",
                    str(store_path),
                    "--sources-file",
                    str(sources_file),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 1)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "error")
            self.assertTrue(all(item["status"] == "error" for item in payload["runs"]))

    def test_yesterday_is_collected_again_until_a_run_after_the_day_ended(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            store_path = root / "daytrace.sqlite3"
            bootstrap_store(store_path)
            now = datetime(2026, 3, 13, 8, 0).astimezone()

            def store_yesterday_run(collected_at: str) -> None:
                with sqlite3.connect(store_path) as connection:
                    connection.execute("DELETE FROM source_runs")
                    connection.execute(
                        """
                        INSERT INTO source_runs (
                            run_fingerprint, source_name, source_id, identity_version, manifest_fingerprint,
                            confidence_categories_json, command_fingerprint, status, scope_mode, workspace,
                            requested_date, since_value, until_value, all_sessions, filters_json, command_json,
                            reason, message, duration_sec, events_count, collected_at
                        ) VALUES ('r', 'workspace-file-activity', 'w', '1', 'm', '[]', 'c', 'success', 'workspace',
                            ?, '2026-03-12', '2026-03-12', '2026-03-12', 1, '{}', '[]', NULL, NULL, 0.1, 1, ?)
                        """,
                        (str(workspace.resolve()), collected_at),
                    )
                    connection.commit()

            self.assertEqual(days_to_collect(store_path, workspace.resolve(), now), ["2026-03-12", "2026-03-13"])

            # Collected at 23:45 on the day itself: the last 15 minutes are still missing.
            store_yesterday_run(datetime(2026, 3, 12, 23, 45).astimezone().isoformat())
            self.assertEqual(days_to_collect(store_path, workspace.resolve(), now), ["2026-03-12", "2026-03-13"])

            # Collected after midnight: yesterday is complete and left alone.
            store_yesterday_run(datetime(2026, 3, 13, 0, 10).astimezone().isoformat())
            self.assertEqual(days_to_collect(store_path, workspace.resolve(), now), ["2026-03-13"])


if __name__ == "__main__":
    unittest.main()
