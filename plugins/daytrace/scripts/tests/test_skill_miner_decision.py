#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

REPO_ROOT = Path(__file__).resolve().parents[4]
DECISION = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "skill_miner_decision.py"


def sample_proposal() -> dict:
    return {
        "ready": [
            {
                "candidate_id": "c1",
                "decision_key": "d1",
                "label": "ready candidate",
                "suggested_kind": "skill",
            }
        ],
        "needs_research": [
            {
                "candidate_id": "c2",
                "decision_key": "d2",
                "label": "research candidate",
                "suggested_kind": "CLAUDE.md",
            }
        ],
        "rejected": [],
    }


class SkillMinerDecisionCliTests(unittest.TestCase):
    def run_cli(self, proposal_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(DECISION), "--proposal-file", str(proposal_path), *extra],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_adopt_completed_persists_adopt_without_carry_forward(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            proposal_path = root / "proposal.json"
            output_path = root / "decision.json"
            proposal_path.write_text(json.dumps(sample_proposal()), encoding="utf-8")

            completed = self.run_cli(
                proposal_path,
                "--candidate-index",
                "1",
                "--decision",
                "adopt",
                "--completion-state",
                "completed",
                "--output-file",
                str(output_path),
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["decision"]["candidate_id"], "c1")
            self.assertEqual(payload["decision"]["user_decision"], "adopt")
            self.assertFalse(payload["decision"]["carry_forward"])
            written = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(written["decisions"][0]["user_decision"], "adopt")

    def test_adopt_pending_normalizes_to_defer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            proposal_path = root / "proposal.json"
            proposal_path.write_text(json.dumps(sample_proposal()), encoding="utf-8")

            completed = self.run_cli(
                proposal_path,
                "--candidate-id",
                "c2",
                "--decision",
                "adopt",
                "--completion-state",
                "pending",
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["decision"]["candidate_id"], "c2")
            self.assertEqual(payload["decision"]["user_decision"], "defer")
            self.assertTrue(payload["decision"]["carry_forward"])
            self.assertEqual(payload["normalization"]["reason"], "adopt_pending_normalized_to_defer")

    def test_reject_keeps_carry_forward_true(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            proposal_path = root / "proposal.json"
            proposal_path.write_text(json.dumps(sample_proposal()), encoding="utf-8")

            completed = self.run_cli(
                proposal_path,
                "--candidate-id",
                "c1",
                "--decision",
                "reject",
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["decision"]["user_decision"], "reject")
            self.assertTrue(payload["decision"]["carry_forward"])

    def test_candidate_id_lookup_strips_input_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            proposal_path = root / "proposal.json"
            proposal_path.write_text(json.dumps(sample_proposal()), encoding="utf-8")

            completed = self.run_cli(
                proposal_path,
                "--candidate-id",
                "c1 ",
                "--decision",
                "defer",
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["decision"]["candidate_id"], "c1")
            self.assertEqual(payload["decision"]["user_decision"], "defer")

    def test_invalid_ready_index_returns_error_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            proposal_path = root / "proposal.json"
            proposal_path.write_text(json.dumps(sample_proposal()), encoding="utf-8")

            completed = self.run_cli(
                proposal_path,
                "--candidate-index",
                "2",
                "--decision",
                "defer",
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "error")
            self.assertIn("--candidate-index must be between 1 and 1", payload["message"])


if __name__ == "__main__":
    unittest.main()
