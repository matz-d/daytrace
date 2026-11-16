#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from conftest import PLUGIN_ROOT
from helpers import make_source_entry, write_file

AGGREGATE = PLUGIN_ROOT / "scripts" / "aggregate.py"
READ_LOG = PLUGIN_ROOT / "scripts" / "read_log.py"


def write_source(path: Path, source: str, events: list[dict[str, object]]) -> None:
    write_file(
        path,
        textwrap.dedent(
            f"""
            import json
            print(json.dumps({{"status": "success", "source": {source!r}, "events": {json.dumps(events)!s}}}))
            """
        ).strip(),
    )


def event(source: str, timestamp: str, summary: str) -> dict[str, object]:
    return {
        "source": source,
        "timestamp": timestamp,
        "type": "note",
        "summary": summary,
        "details": {},
        "confidence": "medium",
    }


class ReadLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.store = self.root / "daytrace.sqlite3"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def sources_file(self, name: str, entries: list[tuple[str, list[dict[str, object]], str]]) -> Path:
        registry = []
        for source, events, category in entries:
            script = self.root / f"{name}_{source}.py"
            write_source(script, source, events)
            registry.append(
                make_source_entry(
                    source,
                    f"python3 {script}",
                    supports_date_range=True,
                    supports_all_sessions=True,
                    confidence_category=category,
                    scope_mode="all-day",
                )
            )
        path = self.root / f"{name}.json"
        write_file(path, json.dumps(registry))
        return path

    def collect(self, sources_file: Path, day: str) -> None:
        completed = subprocess.run(
            [
                "python3",
                str(AGGREGATE),
                "--sources-file",
                str(sources_file),
                "--workspace",
                str(self.workspace),
                "--date",
                day,
                "--all-sessions",
                "--store-path",
                str(self.store),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)

    def read(self, *extra: str) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["python3", str(READ_LOG), "--workspace", str(self.workspace), "--store-path", str(self.store), *extra],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        return completed

    def test_same_event_from_two_registries_is_read_once(self) -> None:
        shared = [event("claude-history", "2026-03-12T01:00:00+00:00", "Claude session: 見積を直して")]
        self.collect(self.sources_file("plugin", [("claude-history", shared, "ai_history")]), "2026-03-12")
        self.collect(self.sources_file("bizflow", [("claude-history", shared, "ai_history")]), "2026-03-12")

        payload = json.loads(self.read("--date", "2026-03-12").stdout)

        self.assertEqual(payload["counts"], {"claude-history": 1})

    def test_source_filter_and_text_format(self) -> None:
        self.collect(
            self.sources_file(
                "plugin",
                [
                    ("claude-history", [event("claude-history", "2026-03-12T01:00:00+00:00", "Claude session: 見積")], "ai_history"),
                    ("git-history", [event("git-history", "2026-03-12T02:30:00+00:00", "Fix typo")], "git"),
                ],
            ),
            "2026-03-12",
        )

        filtered = json.loads(self.read("--date", "2026-03-12", "--source", "git-history").stdout)
        text = self.read("--date", "2026-03-12", "--format", "text").stdout.splitlines()

        self.assertEqual(filtered["counts"], {"git-history": 1})
        self.assertEqual(len(text), 2)
        self.assertIn("claude-history  note  Claude session: 見積", text[0])
        self.assertIn("git-history  note  Fix typo", text[1])


if __name__ == "__main__":
    unittest.main()
