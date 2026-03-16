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

REPO_ROOT = Path(__file__).resolve().parents[4]
PREPARE = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "skill_miner_prepare.py"
PROPOSAL = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "skill_miner_proposal.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
CLAUDE_FIXTURE = FIXTURES_DIR / "e2e_claude_history_source.json"
WORKSPACE_FIXTURE = FIXTURES_DIR / "e2e_workspace_file_activity_source.json"


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
) -> dict[str, object]:
    return {
        "name": name,
        "command": command,
        "required": False,
        "timeout_sec": 5,
        "platforms": ["darwin", "linux"],
        "supports_date_range": supports_date_range,
        "supports_all_sessions": supports_all_sessions,
        "scope_mode": scope_mode,
        "prerequisites": [],
        "confidence_category": confidence_category,
    }


class E2EPipelineTests(unittest.TestCase):
    maxDiff = None

    def _write_fixture_source_stub(self, root: Path) -> Path:
        stub_path = root / "fixture_source.py"
        write_file(
            stub_path,
            textwrap.dedent(
                """
                import json
                import sys
                from pathlib import Path

                fixture_path = Path(sys.argv[1])
                workspace = sys.argv[2]
                raw = fixture_path.read_text(encoding="utf-8").replace("__WORKSPACE__", workspace)
                payload = json.loads(raw)
                print(json.dumps(payload, ensure_ascii=False))
                """
            ).strip(),
        )
        return stub_path

    def _run_aggregate_imported(self, *, sources_file: Path, store_path: Path, workspace: Path) -> dict[str, object]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(
            sys,
            "argv",
            [
                "aggregate.py",
                "--sources-file",
                str(sources_file),
                "--store-path",
                str(store_path),
                "--workspace",
                str(workspace),
                "--all-sessions",
                "--since",
                "2026-03-08",
                "--until",
                "2026-03-17",
            ],
        ):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                aggregate.main()
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "success", msg=stdout.getvalue())
        self.assertIn("Source preflight:", stderr.getvalue())
        return payload

    def _run_prepare(self, *, workspace: Path, store_path: Path, sources_file: Path) -> dict[str, object]:
        completed = subprocess.run(
            [
                "python3",
                str(PREPARE),
                "--workspace",
                str(workspace),
                "--all-sessions",
                "--input-source",
                "auto",
                "--store-path",
                str(store_path),
                "--sources-file",
                str(sources_file),
                "--days",
                "7",
                "--top-n",
                "5",
                "--max-unclustered",
                "5",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "success", msg=completed.stdout)
        return payload

    def _run_proposal(self, prepare_file: Path) -> dict[str, object]:
        completed = subprocess.run(
            ["python3", str(PROPOSAL), "--prepare-file", str(prepare_file)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "success", msg=completed.stdout)
        return payload

    def test_fixture_backed_pipeline_runs_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir()
            store_path = root / "daytrace.sqlite3"
            source_stub = self._write_fixture_source_stub(root)
            sources_file = root / "sources.json"
            sources_file.write_text(
                json.dumps(
                    [
                        make_source_entry(
                            "claude-history",
                            f"python3 {source_stub} {CLAUDE_FIXTURE} {workspace}",
                            supports_date_range=True,
                            supports_all_sessions=True,
                            confidence_category="ai_history",
                            scope_mode="all-day",
                        ),
                        make_source_entry(
                            "workspace-file-activity",
                            f"python3 {source_stub} {WORKSPACE_FIXTURE} {workspace}",
                            supports_date_range=True,
                            supports_all_sessions=False,
                            confidence_category="file_activity",
                            scope_mode="workspace",
                        ),
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            aggregate_payload = self._run_aggregate_imported(
                sources_file=sources_file,
                store_path=store_path,
                workspace=workspace,
            )

            self.assertIn("sources", aggregate_payload)
            self.assertIn("timeline", aggregate_payload)
            self.assertIn("groups", aggregate_payload)
            self.assertIn("summary", aggregate_payload)
            self.assertEqual(len(aggregate_payload["sources"]), 2)
            self.assertGreaterEqual(len(aggregate_payload["timeline"]), 10)
            self.assertGreaterEqual(len(aggregate_payload["groups"]), 2)

            prepare_payload = self._run_prepare(
                workspace=workspace,
                store_path=store_path,
                sources_file=sources_file,
            )
            self.assertGreaterEqual(len(prepare_payload["candidates"]), 1)

            prepare_file = root / "prepare.json"
            prepare_file.write_text(json.dumps(prepare_payload), encoding="utf-8")
            proposal_payload = self._run_proposal(prepare_file)

            self.assertIn("## 提案", str(proposal_payload["markdown"]))


if __name__ == "__main__":
    unittest.main()
