#!/usr/bin/env python3

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from chrome_history import collapse_visits, normalize_url

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "chrome_history.py"
JST = timezone(timedelta(hours=9))


def chrome_timestamp(value: datetime) -> int:
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    return int((value.astimezone(timezone.utc) - epoch).total_seconds() * 1_000_000)


def write_history_db(path: Path, rows: list[tuple[str, str, int, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE urls (
                id INTEGER PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT,
                last_visit_time INTEGER NOT NULL,
                visit_count INTEGER NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO urls(url, title, last_visit_time, visit_count) VALUES (?, ?, ?, ?)",
            rows,
        )
        connection.commit()


class ChromeHistoryTests(unittest.TestCase):
    def test_cli_discovers_profiles_collapses_urls_and_filters_by_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_history_db(
                root / "Default" / "History",
                [
                    (
                        "https://example.com/daytrace?tab=overview",
                        "DayTrace overview",
                        chrome_timestamp(datetime(2026, 3, 12, 9, 0, tzinfo=JST)),
                        2,
                    ),
                    (
                        "https://example.com/daytrace?tab=details",
                        "DayTrace details",
                        chrome_timestamp(datetime(2026, 3, 12, 10, 0, tzinfo=JST)),
                        3,
                    ),
                    (
                        "https://example.com/old",
                        "Old page",
                        chrome_timestamp(datetime(2026, 3, 10, 10, 0, tzinfo=JST)),
                        1,
                    ),
                ],
            )
            write_history_db(
                root / "Profile 1" / "History",
                [
                    (
                        "https://example.com/notes#fragment",
                        "Notes page",
                        chrome_timestamp(datetime(2026, 3, 12, 11, 0, tzinfo=JST)),
                        1,
                    ),
                ],
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--root",
                    str(root),
                    "--since",
                    "2026-03-12T00:00:00+09:00",
                    "--until",
                    "2026-03-12T23:59:59+09:00",
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["profiles"], ["Default", "Profile 1"])
            self.assertEqual(len(payload["events"]), 2)

            default_event = next(event for event in payload["events"] if event["details"]["profile"] == "Default")
            self.assertEqual(default_event["details"]["url"], "https://example.com/daytrace")
            self.assertEqual(default_event["details"]["visit_count"], 5)
            self.assertEqual(default_event["details"]["title"], "DayTrace details")

            profile_event = next(event for event in payload["events"] if event["details"]["profile"] == "Profile 1")
            self.assertEqual(profile_event["details"]["url"], "https://example.com/notes")
            self.assertEqual(profile_event["details"]["visit_count"], 1)

    def test_normalize_url_drops_query_string(self) -> None:
        self.assertEqual(
            normalize_url("https://github.com/matz-d/daytrace?tab=readme#top"),
            "https://github.com/matz-d/daytrace",
        )

    def test_collapse_visits_merges_same_normalized_url(self) -> None:
        rows = [
            ("Default", "https://github.com/", "GitHub", 13416800000000000, 2),
            ("Default", "https://github.com/", "GitHub", 13416800010000000, 3),
            ("Profile 1", "https://github.com/", "GitHub", 13416800020000000, 1),
        ]
        collapsed = sorted(collapse_visits(rows), key=lambda item: (str(item["profile"]), str(item["url"])))

        self.assertEqual(len(collapsed), 2)
        self.assertEqual(collapsed[0]["profile"], "Default")
        self.assertEqual(collapsed[0]["visit_count"], 5)
        self.assertEqual(collapsed[1]["profile"], "Profile 1")
        self.assertEqual(collapsed[1]["visit_count"], 1)


if __name__ == "__main__":
    unittest.main()
