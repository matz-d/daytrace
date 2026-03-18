#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import aggregate
REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATE = REPO_ROOT / "scripts" / "aggregate.py"


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


class AggregateCliTests(unittest.TestCase):
    def run_aggregate(
        self,
        sources_file: Path,
        *extra_args: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        store_path = sources_file.parent / "daytrace.sqlite3"
        completed = subprocess.run(
            [
                "python3",
                str(AGGREGATE),
                "--sources-file",
                str(sources_file),
                "--store-path",
                str(store_path),
                "--all-sessions",
                *extra_args,
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=env,
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
                        "source": "repo-source",
                        "events": [
                            {
                                "source": "repo-source",
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
                        "source": "assistant-source",
                        "events": [
                            {
                                "source": "assistant-source",
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
                        "source": "browser-source",
                        "events": [
                            {
                                "source": "browser-source",
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
                            "name": "repo-source",
                            "command": f"python3 {git_stub}",
                            "required": False,
                            "timeout_sec": 5,
                            "platforms": ["darwin", "linux"],
                            "supports_date_range": True,
                            "supports_all_sessions": False,
                            "scope_mode": "workspace",
                            "prerequisites": [],
                            "confidence_category": "git",
                        },
                        {
                            "name": "assistant-source",
                            "command": f"python3 {claude_stub}",
                            "required": False,
                            "timeout_sec": 5,
                            "platforms": ["darwin", "linux"],
                            "supports_date_range": True,
                            "supports_all_sessions": True,
                            "scope_mode": "all-day",
                            "prerequisites": [],
                            "confidence_category": "ai_history",
                        },
                        {
                            "name": "browser-source",
                            "command": f"python3 {chrome_stub}",
                            "required": False,
                            "timeout_sec": 5,
                            "platforms": ["darwin", "linux"],
                            "supports_date_range": True,
                            "supports_all_sessions": False,
                            "scope_mode": "all-day",
                            "prerequisites": [],
                            "confidence_category": "browser",
                        },
                        {
                            "name": "broken-source",
                            "command": f"python3 {error_stub}",
                            "required": False,
                            "timeout_sec": 5,
                            "platforms": ["darwin", "linux"],
                            "supports_date_range": False,
                            "supports_all_sessions": False,
                            "scope_mode": "all-day",
                            "prerequisites": [],
                            "confidence_category": "other",
                        },
                        {
                            "name": "unsupported-source",
                            "command": f"python3 {chrome_stub}",
                            "required": False,
                            "timeout_sec": 5,
                            "platforms": ["win32"],
                            "supports_date_range": False,
                            "supports_all_sessions": False,
                            "scope_mode": "workspace",
                            "prerequisites": [],
                            "confidence_category": "other",
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
            self.assertEqual(payload["groups"][0]["sources"], ["assistant-source", "repo-source"])
            self.assertEqual(payload["groups"][0]["confidence_categories"], ["ai_history", "git"])
            self.assertTrue(all("scope" in source for source in payload["sources"]))
            self.assertTrue(
                any(source["name"] == "assistant-source" and source["scope"] == "all-day" for source in payload["sources"])
            )
            self.assertTrue(
                any(source["name"] == "repo-source" and source["scope"] == "workspace" for source in payload["sources"])
            )
            self.assertTrue(
                any(source["name"] == "browser-source" and source["scope"] == "all-day" for source in payload["sources"])
            )
            self.assertTrue(
                any(source["name"] == "broken-source" and source["scope"] == "all-day" for source in payload["sources"])
            )
            self.assertTrue(any(source["name"] == "broken-source" and source["status"] == "error" for source in payload["sources"]))
            self.assertTrue(any(source["name"] == "unsupported-source" and source["status"] == "skipped" for source in payload["sources"]))
            self.assertIn("Source preflight:", completed.stderr)
            self.assertIn("available=", completed.stderr)
            self.assertIn("skipped=unsupported-source(unsupported_platform)", completed.stderr)

    def test_aggregate_all_error_sources_keep_sources_but_emit_no_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            err_a = temp_path / "err_a.py"
            err_b = temp_path / "err_b.py"
            sources_file = temp_path / "sources.json"

            for path, name in ((err_a, "err-a"), (err_b, "err-b")):
                write_file(
                    path,
                    textwrap.dedent(
                        f"""
                        import json

                        print(json.dumps({{
                            "status": "error",
                            "source": "{name}",
                            "message": "simulated failure",
                            "events": []
                        }}))
                        """
                    ).strip(),
                )

            write_file(
                sources_file,
                json.dumps(
                    [
                        make_source_entry(
                            "err-a",
                            f"python3 {err_a}",
                            supports_date_range=True,
                            supports_all_sessions=True,
                            confidence_category="other",
                            scope_mode="all-day",
                        ),
                        make_source_entry(
                            "err-b",
                            f"python3 {err_b}",
                            supports_date_range=True,
                            supports_all_sessions=True,
                            confidence_category="other",
                            scope_mode="workspace",
                        ),
                    ],
                    ensure_ascii=False,
                ),
            )

            completed = self.run_aggregate(sources_file)
            payload = json.loads(completed.stdout)

            self.assertEqual(len(payload["sources"]), 2)
            self.assertTrue(all(source["status"] == "error" for source in payload["sources"]))
            self.assertEqual(payload["timeline"], [])
            self.assertEqual(payload["groups"], [])
            self.assertEqual(payload["summary"]["total_events"], 0)
            self.assertEqual(payload["summary"]["source_status_counts"], {"success": 0, "skipped": 0, "error": 2})

    def test_aggregate_excludes_error_source_events_from_timeline_and_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            success_stub = temp_path / "success_stub.py"
            error_stub = temp_path / "error_stub.py"
            sources_file = temp_path / "sources.json"

            write_file(
                success_stub,
                textwrap.dedent(
                    """
                    import json

                    print(json.dumps({
                        "status": "success",
                        "source": "success-source",
                        "events": [
                            {
                                "source": "success-source",
                                "timestamp": "2026-03-09T10:00:00+09:00",
                                "type": "commit",
                                "summary": "success event",
                                "details": {},
                                "confidence": "high"
                            }
                        ]
                    }))
                    """
                ).strip(),
            )
            write_file(
                error_stub,
                textwrap.dedent(
                    """
                    import json

                    print(json.dumps({
                        "status": "error",
                        "source": "error-source",
                        "message": "simulated failure",
                        "events": [
                            {
                                "source": "error-source",
                                "timestamp": "2026-03-09T10:01:00+09:00",
                                "type": "commit",
                                "summary": "should not reach aggregate timeline",
                                "details": {},
                                "confidence": "low"
                            }
                        ]
                    }))
                    """
                ).strip(),
            )

            write_file(
                sources_file,
                json.dumps(
                    [
                        make_source_entry(
                            "success-source",
                            f"python3 {success_stub}",
                            supports_date_range=True,
                            supports_all_sessions=True,
                            confidence_category="git",
                            scope_mode="workspace",
                        ),
                        make_source_entry(
                            "error-source",
                            f"python3 {error_stub}",
                            supports_date_range=True,
                            supports_all_sessions=True,
                            confidence_category="other",
                            scope_mode="all-day",
                        ),
                    ],
                    ensure_ascii=False,
                ),
            )

            completed = self.run_aggregate(sources_file)
            payload = json.loads(completed.stdout)

            self.assertEqual([event["source"] for event in payload["timeline"]], ["success-source"])
            self.assertEqual(len(payload["groups"]), 1)
            self.assertEqual(payload["groups"][0]["sources"], ["success-source"])
            self.assertEqual(payload["summary"]["source_status_counts"], {"success": 1, "skipped": 0, "error": 1})
            self.assertTrue(any(source["name"] == "error-source" and source["status"] == "error" for source in payload["sources"]))

    def test_aggregate_store_persistence_is_fail_soft_per_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            git_stub = temp_path / "git_stub.py"
            ai_stub = temp_path / "ai_stub.py"
            sources_file = temp_path / "sources.json"

            write_file(
                git_stub,
                textwrap.dedent(
                    """
                    import json
                    print(json.dumps({
                        "status": "success",
                        "source": "repo-source",
                        "events": [
                            {
                                "source": "repo-source",
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
                ai_stub,
                textwrap.dedent(
                    """
                    import json
                    print(json.dumps({
                        "status": "success",
                        "source": "assistant-source",
                        "events": [
                            {
                                "source": "assistant-source",
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
                sources_file,
                json.dumps(
                    [
                        make_source_entry(
                            "repo-source",
                            f"python3 {git_stub}",
                            supports_date_range=True,
                            supports_all_sessions=True,
                            confidence_category="git",
                            scope_mode="workspace",
                        ),
                        make_source_entry(
                            "assistant-source",
                            f"python3 {ai_stub}",
                            supports_date_range=True,
                            supports_all_sessions=True,
                            confidence_category="ai_history",
                            scope_mode="all-day",
                        ),
                    ],
                    ensure_ascii=False,
                ),
            )

            persisted_sources: list[str] = []

            def fake_persist(result: dict[str, object], source: dict[str, object], **_: object) -> None:
                persisted_sources.append(str(source["name"]))
                if source["name"] == "assistant-source":
                    raise RuntimeError("simulated persist failure")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("aggregate.persist_source_result", side_effect=fake_persist):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "aggregate.py",
                        "--sources-file",
                        str(sources_file),
                        "--store-path",
                        str(temp_path / "daytrace.sqlite3"),
                        "--all-sessions",
                    ],
                ):
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        aggregate.main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "success")
            self.assertEqual(set(persisted_sources), {"assistant-source", "repo-source"})
            self.assertEqual(payload["config"]["store_error"], "assistant-source: simulated persist failure")
            self.assertEqual(payload["config"]["store_errors"], ["assistant-source: simulated persist failure"])
            self.assertIn("[warn] store persistence failed for assistant-source", stderr.getvalue())

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
                            "scope_mode": "workspace",
                            "prerequisites": [],
                            "confidence_category": "other",
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

    def test_group_window_can_be_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_stub = temp_path / "source_stub.py"
            write_file(
                source_stub,
                textwrap.dedent(
                    """
                    import json
                    print(json.dumps({
                        "status": "success",
                        "source": "repo-source",
                        "events": [
                            {"source":"repo-source","timestamp":"2026-03-09T10:00:00+09:00","type":"commit","summary":"first","details":{},"confidence":"high"},
                            {"source":"repo-source","timestamp":"2026-03-09T10:10:00+09:00","type":"commit","summary":"second","details":{},"confidence":"high"}
                        ]
                    }))
                    """
                ).strip(),
            )
            sources_file = temp_path / "sources.json"
            write_file(
                sources_file,
                json.dumps(
                    [{
                        "name": "repo-source",
                        "command": f"python3 {source_stub}",
                        "required": False,
                        "timeout_sec": 5,
                        "platforms": ["darwin", "linux"],
                        "supports_date_range": True,
                        "supports_all_sessions": False,
                        "scope_mode": "workspace",
                        "prerequisites": [],
                        "confidence_category": "git"
                    }],
                    ensure_ascii=False,
                ),
            )
            completed = self.run_aggregate(sources_file, "--group-window", "5")
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["config"]["group_window_minutes"], 5)
            self.assertEqual(len(payload["groups"]), 2)
            self.assertEqual(payload["sources"][0]["scope"], "workspace")

    def test_all_sessions_date_today_keeps_all_day_scope_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            all_day_stub = temp_path / "all_day_stub.py"
            write_file(
                all_day_stub,
                textwrap.dedent(
                    """
                    import json
                    import sys

                    args = sys.argv[1:]
                    since = args[args.index("--since") + 1] if "--since" in args else None
                    until = args[args.index("--until") + 1] if "--until" in args else None
                    payload = {
                        "status": "success" if "--all-sessions" in args and since and since == until else "skipped",
                        "source": "all-day-source",
                        "events": []
                    }
                    if payload["status"] == "success":
                        payload["events"] = [
                            {
                                "source": "all-day-source",
                                "timestamp": "2026-03-11T09:00:00+09:00",
                                "type": "session_summary",
                                "summary": f"all-day event for {since}",
                                "details": {},
                                "confidence": "medium"
                            }
                        ]
                    else:
                        payload["reason"] = "unexpected_args"
                    print(json.dumps(payload))
                    """
                ).strip(),
            )
            sources_file = temp_path / "sources.json"
            write_file(
                sources_file,
                json.dumps(
                    [
                        make_source_entry(
                            "all-day-source",
                            f"python3 {all_day_stub}",
                            supports_date_range=True,
                            supports_all_sessions=True,
                            confidence_category="ai_history",
                            scope_mode="all-day",
                        )
                    ],
                    ensure_ascii=False,
                ),
            )

            completed = self.run_aggregate(sources_file, "--date", "today")
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["sources"][0]["name"], "all-day-source")
            self.assertEqual(payload["sources"][0]["scope"], "all-day")
            self.assertEqual(payload["sources"][0]["status"], "success")
            self.assertEqual(payload["sources"][0]["events_count"], 1)
            self.assertEqual(len(payload["timeline"]), 1)
            self.assertEqual(payload["timeline"][0]["source"], "all-day-source")

    def test_workspace_argument_is_forwarded_for_workspace_scope_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            workspace_path = temp_path / "workspace"
            workspace_path.mkdir()
            workspace_stub = temp_path / "workspace_stub.py"
            write_file(
                workspace_stub,
                textwrap.dedent(
                    f"""
                    import json
                    import sys

                    args = sys.argv[1:]
                    workspace = args[args.index("--workspace") + 1] if "--workspace" in args else None
                    payload = {{
                        "status": "success" if workspace == {str(workspace_path.resolve())!r} else "skipped",
                        "source": "workspace-source",
                        "events": []
                    }}
                    if payload["status"] == "success":
                        payload["events"] = [
                            {{
                                "source": "workspace-source",
                                "timestamp": "2026-03-11T10:00:00+09:00",
                                "type": "file_change",
                                "summary": "workspace scoped event",
                                "details": {{}},
                                "confidence": "low"
                            }}
                        ]
                    else:
                        payload["reason"] = "workspace_not_forwarded"
                    print(json.dumps(payload))
                    """
                ).strip(),
            )
            sources_file = temp_path / "sources.json"
            write_file(
                sources_file,
                json.dumps(
                    [
                        make_source_entry(
                            "workspace-source",
                            f"python3 {workspace_stub}",
                            supports_date_range=False,
                            supports_all_sessions=False,
                            confidence_category="file_activity",
                            scope_mode="workspace",
                        )
                    ],
                    ensure_ascii=False,
                ),
            )

            completed = self.run_aggregate(sources_file, "--workspace", str(workspace_path))
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["sources"][0]["name"], "workspace-source")
            self.assertEqual(payload["sources"][0]["scope"], "workspace")
            self.assertEqual(payload["sources"][0]["status"], "success")
            self.assertEqual(payload["sources"][0]["events_count"], 1)
            self.assertEqual(len(payload["timeline"]), 1)

    def test_aggregate_returns_non_zero_on_fatal_error(self) -> None:
        missing_sources = Path("/tmp/daytrace-missing-sources.json")
        completed = subprocess.run(
            ["python3", str(AGGREGATE), "--sources-file", str(missing_sources)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("No such file", payload["message"])

    def test_aggregate_rejects_negative_max_span(self) -> None:
        completed = subprocess.run(
            ["python3", str(AGGREGATE), "--max-span", "-1"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["message"], "--max-span must be >= 0")

    def test_aggregate_discovers_and_runs_user_drop_in_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            built_in_stub = root / "built_in_stub.py"
            user_stub = root / "user_stub.py"
            write_file(
                built_in_stub,
                textwrap.dedent(
                    """
                    import json

                    print(json.dumps({
                        "status": "success",
                        "source": "built-in-source",
                        "events": []
                    }))
                    """
                ).strip(),
            )
            write_file(
                user_stub,
                textwrap.dedent(
                    """
                    import json

                    print(json.dumps({
                        "status": "success",
                        "source": "user-drop-in",
                        "events": [
                            {
                                "source": "user-drop-in",
                                "timestamp": "2026-03-12T09:15:00+09:00",
                                "type": "file_change",
                                "summary": "Captured user drop-in source",
                                "details": {},
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
                            "built-in-source",
                            f"python3 {built_in_stub}",
                            supports_date_range=False,
                            supports_all_sessions=False,
                            confidence_category="git",
                            scope_mode="workspace",
                        )
                    ],
                    ensure_ascii=False,
                ),
            )
            user_sources_dir = root / "sources.d"
            user_sources_dir.mkdir()
            write_file(
                user_sources_dir / "user_drop_in.json",
                json.dumps(
                    {
                        **make_source_entry(
                            "user-drop-in",
                            f"python3 {user_stub}",
                            supports_date_range=False,
                            supports_all_sessions=False,
                            confidence_category="file_activity",
                            scope_mode="workspace",
                        )
                    },
                    ensure_ascii=False,
                ),
            )

            completed = self.run_aggregate(
                sources_file,
                "--workspace",
                str(workspace),
                "--user-sources-dir",
                str(user_sources_dir),
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual([source["name"] for source in payload["sources"]], ["built-in-source", "user-drop-in"])
            self.assertTrue(any(event["source"] == "user-drop-in" for event in payload["timeline"]))
            self.assertEqual(payload["config"]["user_sources_dir"], str(user_sources_dir.resolve()))

    def test_aggregate_reports_invalid_user_manifest_machine_readably(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sources_file = root / "sources.json"
            write_file(
                sources_file,
                json.dumps(
                    [
                        make_source_entry(
                            "built-in-source",
                            "python3 /tmp/ok.py",
                            supports_date_range=False,
                            supports_all_sessions=False,
                            confidence_category="git",
                            scope_mode="workspace",
                        )
                    ]
                ),
            )
            user_sources_dir = root / "sources.d"
            user_sources_dir.mkdir()
            write_file(
                user_sources_dir / "invalid_manifest.json",
                json.dumps(
                    {
                        "name": "broken-user-drop-in",
                        "command": "python3 /tmp/broken.py",
                        "required": False,
                        "timeout_sec": 5,
                        "platforms": ["darwin", "linux"],
                        "supports_date_range": True,
                        "supports_all_sessions": False,
                        "scope_mode": "invalid-scope",
                        "prerequisites": [],
                        "confidence_category": "file_activity",
                    },
                    ensure_ascii=False,
                ),
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(AGGREGATE),
                    "--sources-file",
                    str(sources_file),
                    "--user-sources-dir",
                    str(user_sources_dir),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "error")
            self.assertIn("registry_errors", payload)
            self.assertEqual(payload["registry_errors"][0]["kind"], "invalid_manifest")
            self.assertEqual(Path(payload["registry_errors"][0]["path"]).name, "invalid_manifest.json")


if __name__ == "__main__":
    unittest.main()
