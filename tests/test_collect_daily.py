#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from conftest import PLUGIN_ROOT

from aggregate_core import report_day_for_local_time

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
            today = report_day_for_local_time(datetime.now().astimezone())
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


if __name__ == "__main__":
    unittest.main()
