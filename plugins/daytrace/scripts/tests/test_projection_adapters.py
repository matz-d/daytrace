#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from derived_store import persist_patterns_from_prepare


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
DAILY_PROJECTION = PLUGIN_ROOT / "scripts" / "daily_report_projection.py"
POST_PROJECTION = PLUGIN_ROOT / "scripts" / "post_draft_projection.py"
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


class ProjectionAdapterTests(unittest.TestCase):
    maxDiff = None

    def create_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        workspace_source = root / "workspace_source.py"
        ai_source = root / "ai_source.py"
        browser_source = root / "browser_source.py"
        write_file(
            workspace_source,
            textwrap.dedent(
                """
                import json
                import sys

                args = sys.argv[1:]
                print(json.dumps({
                    "status": "success",
                    "source": "workspace-source",
                    "events": [
                        {
                            "source": "workspace-source",
                            "timestamp": "2026-03-12T09:00:00+09:00",
                            "type": "commit",
                            "summary": "Persist workspace event",
                            "details": {"workspace": args[args.index("--workspace") + 1]},
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

    def run_cli(
        self,
        script: Path,
        store_path: Path,
        workspace: Path,
        sources_file: Path,
        *extra_args: str,
        all_sessions: bool = True,
    ) -> dict:
        command = [
            "python3",
            str(script),
            "--sources-file",
            str(sources_file),
            "--workspace",
            str(workspace),
            "--since",
            "2026-03-12",
            "--until",
            "2026-03-12",
            "--store-path",
            str(store_path),
            *extra_args,
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
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "success", msg=completed.stdout)
        return payload

    def run_aggregate(self, sources_file: Path, workspace: Path, store_path: Path) -> dict:
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
        self.assertEqual(payload["status"], "success", msg=completed.stdout)
        return payload

    def test_daily_projection_hydrates_missing_store_and_returns_aggregate_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))

            payload = self.run_cli(DAILY_PROJECTION, store_path, workspace, sources_file)

            self.assertTrue(store_path.exists())
            self.assertEqual(len(payload["timeline"]), 3)
            self.assertEqual(len(payload["groups"]), 2)
            self.assertEqual(payload["summary"]["source_status_counts"]["success"], 3)
            self.assertEqual(payload["groups"][0]["confidence_categories"], ["ai_history", "git"])
            self.assertTrue(any(source["name"] == "workspace-source" and source["scope"] == "workspace" for source in payload["sources"]))
            self.assertTrue(any(source["name"] == "ai-source" and source["scope"] == "all-day" for source in payload["sources"]))
            self.assertTrue(any(source["name"] == "browser-source" and source["scope"] == "all-day" for source in payload["sources"]))

    def test_daily_projection_reuses_existing_store_without_hydrate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            aggregate_payload = self.run_aggregate(sources_file, workspace, store_path)

            payload = self.run_cli(DAILY_PROJECTION, store_path, workspace, sources_file, "--no-hydrate")

            self.assertEqual(payload["summary"], aggregate_payload["summary"])
            self.assertEqual(len(payload["sources"]), len(aggregate_payload["sources"]))
            self.assertEqual(len(payload["timeline"]), len(aggregate_payload["timeline"]))
            self.assertEqual(len(payload["groups"]), len(aggregate_payload["groups"]))

    def test_daily_projection_errors_when_sources_registry_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sources_file, workspace, store_path = self.create_fixture(root)
            self.run_aggregate(sources_file, workspace, store_path)
            broken_sources = root / "broken-sources.json"
            write_file(broken_sources, "{not-json")

            completed = subprocess.run(
                [
                    "python3",
                    str(DAILY_PROJECTION),
                    "--sources-file",
                    str(broken_sources),
                    "--workspace",
                    str(workspace),
                    "--since",
                    "2026-03-12",
                    "--until",
                    "2026-03-12",
                    "--all-sessions",
                    "--store-path",
                    str(store_path),
                    "--no-hydrate",
                ],
                cwd=str(PLUGIN_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 1)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "error")
            self.assertIn("failed to load sources from", payload["message"])

    def test_daily_projection_no_hydrate_on_empty_store_returns_empty_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))

            payload = self.run_cli(DAILY_PROJECTION, store_path, workspace, sources_file, "--no-hydrate")

            self.assertEqual(payload["sources"], [])
            self.assertEqual(payload["timeline"], [])
            self.assertEqual(payload["groups"], [])
            self.assertTrue(payload["summary"]["no_sources_available"])

    def test_projection_timeline_has_group_id_matching_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(sources_file, workspace, store_path)

            payload = self.run_cli(DAILY_PROJECTION, store_path, workspace, sources_file, "--no-hydrate")

            self.assertGreater(len(payload["timeline"]), 0)
            for event in payload["timeline"]:
                self.assertIn("group_id", event, f"timeline event missing group_id: {event.get('summary')}")
            group_ids = {group["id"] for group in payload["groups"]}
            for event in payload["timeline"]:
                self.assertIn(event["group_id"], group_ids)
            for group in payload["groups"]:
                for event in group["events"]:
                    self.assertEqual(event["group_id"], group["id"])

    def test_post_projection_timeline_has_group_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(sources_file, workspace, store_path)

            payload = self.run_cli(POST_PROJECTION, store_path, workspace, sources_file, "--no-hydrate", all_sessions=False)

            for event in payload["timeline"]:
                self.assertIn("group_id", event, f"post-draft timeline event missing group_id: {event.get('summary')}")

    def test_post_projection_includes_cached_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file, workspace, store_path = self.create_fixture(Path(temp_dir))
            self.run_aggregate(sources_file, workspace, store_path)
            persist_patterns_from_prepare(
                {
                    "status": "success",
                    "source": "skill-miner-prepare",
                    "candidates": [
                        {
                            "candidate_id": "candidate-001",
                            "label": "Review workflow",
                            "score": 0.82,
                            "support": {"total_packets": 3},
                            "session_refs": ["codex:abc", "claude:def"],
                            "evidence_items": [
                                {
                                    "session_ref": "codex:abc",
                                    "timestamp": "2026-03-12T09:00:00+09:00",
                                    "source": "codex-history",
                                    "summary": "Review findings",
                                }
                            ],
                        }
                    ],
                    "summary": {"total_candidates": 1},
                    "config": {
                        "workspace": str(workspace.resolve()),
                        "observation_mode": "workspace",
                        "days": 7,
                        "effective_days": 7,
                    },
                },
                store_path=store_path,
            )

            payload = self.run_cli(POST_PROJECTION, store_path, workspace, sources_file, "--no-hydrate", all_sessions=False)

            self.assertEqual(len(payload["patterns"]), 1)
            self.assertEqual(payload["patterns"][0]["label"], "Review workflow")
            self.assertEqual(payload["pattern_context"]["observation_mode"], "workspace")


if __name__ == "__main__":
    unittest.main()
