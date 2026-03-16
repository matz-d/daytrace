#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
RESEARCH_JUDGE = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "skill_miner_research_judge.py"


class SkillMinerResearchJudgeCLITests(unittest.TestCase):
    def test_cli_judges_candidate_from_prepare_and_detail_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate_file = root / "prepare.json"
            detail_file = root / "detail.json"
            candidate_file.write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "candidate_id": "candidate-review",
                                "label": "review changes (review, code)",
                                "quality_flags": [],
                                "session_refs": ["codex:a:1", "codex:b:2"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            detail_file.write_text(
                json.dumps(
                    {
                        "details": [
                            {
                                "session_ref": "codex:a:1",
                                "messages": [
                                    {"role": "user", "text": "Review this PR and return findings by severity."},
                                    {"role": "assistant", "text": "I will inspect the diff and list findings first."},
                                ],
                                "tool_calls": [{"name": "rg", "count": 2}, {"name": "git", "count": 1}],
                            },
                            {
                                "session_ref": "codex:b:2",
                                "messages": [
                                    {"role": "user", "text": "Review another PR and keep the findings-first format."},
                                    {"role": "assistant", "text": "I will inspect files and summarize findings with line refs."},
                                ],
                                "tool_calls": [{"name": "rg", "count": 1}, {"name": "git", "count": 1}],
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(RESEARCH_JUDGE),
                    "--candidate-file",
                    str(candidate_file),
                    "--candidate-id",
                    "candidate-review",
                    "--detail-file",
                    str(detail_file),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["source"], "skill-miner-research-judge")
            self.assertEqual(payload["candidate_id"], "candidate-review")
            self.assertEqual(payload["judgment"]["recommendation"], "promote_ready")
            self.assertEqual(payload["judgment"]["proposed_triage_status"], "ready")


if __name__ == "__main__":
    unittest.main()
