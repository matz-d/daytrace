#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATE = REPO_ROOT / "scripts" / "aggregate.py"


def write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


class AggregateCliTests(unittest.TestCase):
    def run_aggregate(self, sources_file: Path) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["python3", str(AGGREGATE), "--sources-file", str(sources_file), "--all-sessions"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "success", msg=completed.stdout)
        return completed

    def test_aggregate_merges_parallel_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            git_stub = temp_path / "git_stub.py"
            claude_stub = temp_path / "claude_stub.py"
            chrome_stub = temp_path / "chrome_stub.py"
            error_stub = temp_path / "error_stub.py"

            write_file(
                git_stub,
                textwrap.dedent(
                    """
                    import json
                    print(json.dumps({
                        "status": "success",
                        "source": "git-history",
                        "events": [
                            {
                                "source": "git-history",
                                "timestamp": "2026-03-09T10:00:00+09:00",
                                "type": "commit",
                                "summary": "Commit one",
                                "details": {},
                                "confidence": "high"
                            }
                        ]
                    }))
                    """
                ).strip(),
            )
            write_file(
                claude_stub,
                textwrap.dedent(
                    """
                    import json
                    print(json.dumps({
                        "status": "success",
                        "source": "claude-history",
                        "events": [
                            {
                                "source": "claude-history",
                                "timestamp": "2026-03-09T10:05:00+09:00",
                                "type": "session_summary",
                                "summary": "Claude summary",
                                "details": {},
                                "confidence": "medium"
                            }
                        ]
                    }))
                    """
                ).strip(),
            )
            write_file(
                chrome_stub,
                textwrap.dedent(
                    """
                    import json
                    print(json.dumps({
                        "status": "success",
                        "source": "chrome-history",
                        "events": [
                            {
                                "source": "chrome-history",
                                "timestamp": "2026-03-09T11:00:00+09:00",
                                "type": "browser_visit",
                                "summary": "Browser event",
                                "details": {},
                                "confidence": "low"
                            }
                        ]
                    }))
                    """
                ).strip(),
            )
            write_file(error_stub, "print('not json')")

            sources_file = temp_path / "sources.json"
            write_file(
                sources_file,
                json.dumps(
                    [
                        {
                            "name": "git-history",
                            "command": f"python3 {git_stub}",
                            "required": False,
                            "timeout_sec": 5,
                            "platforms": ["darwin", "linux"],
                            "supports_date_range": True,
                            "supports_all_sessions": False,
                        },
                        {
                            "name": "claude-history",
                            "command": f"python3 {claude_stub}",
                            "required": False,
                            "timeout_sec": 5,
                            "platforms": ["darwin", "linux"],
                            "supports_date_range": True,
                            "supports_all_sessions": True,
                        },
                        {
                            "name": "chrome-history",
                            "command": f"python3 {chrome_stub}",
                            "required": False,
                            "timeout_sec": 5,
                            "platforms": ["darwin", "linux"],
                            "supports_date_range": True,
                            "supports_all_sessions": False,
                        },
                        {
                            "name": "broken-source",
                            "command": f"python3 {error_stub}",
                            "required": False,
                            "timeout_sec": 5,
                            "platforms": ["darwin", "linux"],
                            "supports_date_range": False,
                            "supports_all_sessions": False,
                        },
                        {
                            "name": "unsupported-source",
                            "command": f"python3 {chrome_stub}",
                            "required": False,
                            "timeout_sec": 5,
                            "platforms": ["win32"],
                            "supports_date_range": False,
                            "supports_all_sessions": False,
                        },
                    ],
                    ensure_ascii=False,
                ),
            )

            completed = self.run_aggregate(sources_file)
            payload = json.loads(completed.stdout)
            self.assertEqual(len(payload["timeline"]), 3)
            self.assertEqual(len(payload["groups"]), 2)
            self.assertEqual(payload["groups"][0]["confidence"], "high")
            self.assertEqual(payload["groups"][1]["confidence"], "low")
            self.assertEqual(payload["summary"]["source_status_counts"]["success"], 3)
            self.assertEqual(payload["summary"]["source_status_counts"]["error"], 1)
            self.assertEqual(payload["summary"]["source_status_counts"]["skipped"], 1)
            self.assertEqual(payload["groups"][0]["sources"], ["claude-history", "git-history"])
            self.assertTrue(any(source["name"] == "broken-source" and source["status"] == "error" for source in payload["sources"]))
            self.assertTrue(any(source["name"] == "unsupported-source" and source["status"] == "skipped" for source in payload["sources"]))
            self.assertIn("Source preflight:", completed.stderr)
            self.assertIn("available=", completed.stderr)
            self.assertIn("skipped=unsupported-source(unsupported_platform)", completed.stderr)

    def test_aggregate_handles_zero_runnable_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            sources_file = temp_path / "sources.json"
            write_file(
                sources_file,
                json.dumps(
                    [
                        {
                            "name": "unsupported-source",
                            "command": "python3 /tmp/does-not-matter.py",
                            "required": False,
                            "timeout_sec": 5,
                            "platforms": ["win32"],
                            "supports_date_range": False,
                            "supports_all_sessions": False,
                        }
                    ],
                    ensure_ascii=False,
                ),
            )

            completed = self.run_aggregate(sources_file)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["timeline"], [])
            self.assertEqual(payload["groups"], [])
            self.assertTrue(payload["summary"]["no_sources_available"])
            self.assertEqual(payload["summary"]["source_status_counts"]["skipped"], 1)
            self.assertIn("available=none", completed.stderr)


if __name__ == "__main__":
    unittest.main()
