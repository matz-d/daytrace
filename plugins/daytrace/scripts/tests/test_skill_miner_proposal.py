#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from skill_miner_common import DEFAULT_TOP_N, build_proposal_sections, merge_judgment_into_candidate
from skill_miner_proposal import (
    build_evidence_chain_lines,
    build_markdown,
    load_judgments,
    proposal_item_lines,
    rejected_item_lines,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
PROPOSAL = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "skill_miner_proposal.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
GOLDEN_PREPARE = FIXTURES_DIR / "skill_miner_proposal_prepare.json"
GOLDEN_MARKDOWN = FIXTURES_DIR / "golden_proposal.md"


def _render_markdown_from_fixture() -> str:
    completed = subprocess.run(
        ["python3", str(PROPOSAL), "--prepare-file", str(GOLDEN_PREPARE)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    payload = json.loads(completed.stdout)
    if payload.get("status") != "success":
        raise AssertionError(payload)
    return str(payload["markdown"])


def _update_golden_markdown() -> None:
    GOLDEN_MARKDOWN.write_text(_render_markdown_from_fixture(), encoding="utf-8")


if "--update-golden" in sys.argv:
    sys.argv.remove("--update-golden")
    _update_golden_markdown()


def _ready_candidate(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "candidate_id": "c1",
        "label": "Review workflow",
        "triage_status": "ready",
        "proposal_ready": True,
        "confidence": "moderate",
        "suggested_kind": "CLAUDE.md",
        "evidence_items": [
            {"timestamp": "2026-03-09T10:00:00+09:00", "source": "claude-history", "summary": "Review PR and list findings"},
            {"timestamp": "2026-03-09T11:00:00+09:00", "source": "codex-history", "summary": "Review server code"},
        ],
        "evidence_summary": "Repeated review pattern with findings-first format",
        "confidence_reason": "2+ evidence items with matching intent",
    }
    base.update(overrides)
    return base


def _needs_research_candidate(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "candidate_id": "c2",
        "label": "Build automation",
        "triage_status": "needs_research",
        "proposal_ready": False,
        "confidence": "weak",
        "suggested_kind": "skill",
        "evidence_items": [
            {"timestamp": "2026-03-09T14:00:00+09:00", "source": "claude-history", "summary": "Run build script"},
        ],
        "evidence_summary": "Build-related activity observed",
        "confidence_reason": "追加調査が必要",
    }
    base.update(overrides)
    return base


def _prepare_payload(
    candidates: list[dict[str, Any]] | None = None,
    unclustered: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": "success",
        "candidates": candidates or [],
        "unclustered": unclustered or [],
        "summary": {"total_packets": 5, "total_candidates": len(candidates or [])},
    }


class ProposalSectionsTests(unittest.TestCase):
    """Tests for build_proposal_sections (the core logic in skill_miner_common)."""

    def test_ready_candidates_sorted_into_ready_section(self) -> None:
        payload = _prepare_payload(candidates=[_ready_candidate()])
        result = build_proposal_sections(payload)

        self.assertEqual(result["summary"]["ready_count"], 1)
        self.assertEqual(result["summary"]["needs_research_count"], 0)
        self.assertEqual(result["ready"][0]["label"], "Review workflow")
        self.assertIsNotNone(result["selection_prompt"])

    def test_needs_research_sorted_correctly(self) -> None:
        payload = _prepare_payload(candidates=[_needs_research_candidate()])
        result = build_proposal_sections(payload)

        self.assertEqual(result["summary"]["ready_count"], 0)
        self.assertEqual(result["summary"]["needs_research_count"], 1)
        self.assertIsNone(result["selection_prompt"])

    def test_mixed_candidates_sorted_into_correct_sections(self) -> None:
        payload = _prepare_payload(candidates=[
            _ready_candidate(),
            _needs_research_candidate(),
            {
                "candidate_id": "c3",
                "label": "Misc pattern",
                "triage_status": "rejected",
                "proposal_ready": False,
                "confidence": "insufficient",
                "confidence_reason": "single occurrence",
            },
        ])
        result = build_proposal_sections(payload)

        self.assertEqual(result["summary"]["ready_count"], 1)
        self.assertEqual(result["summary"]["needs_research_count"], 1)
        self.assertEqual(result["summary"]["rejected_count"], 1)

    def test_unclustered_packets_go_to_rejected(self) -> None:
        unclustered = [
            {
                "packet_id": "claude:repo:sess:000",
                "source": "claude-history",
                "primary_intent": "one-off task",
                "timestamp": "2026-03-09T12:00:00+09:00",
            },
        ]
        payload = _prepare_payload(unclustered=unclustered)
        result = build_proposal_sections(payload)

        self.assertEqual(result["summary"]["rejected_count"], 1)
        self.assertEqual(result["summary"]["ready_count"], 0)

    def test_empty_prepare_payload_returns_all_empty_sections(self) -> None:
        result = build_proposal_sections(_prepare_payload())

        self.assertEqual(result["summary"]["ready_count"], 0)
        self.assertEqual(result["summary"]["needs_research_count"], 0)
        self.assertEqual(result["summary"]["rejected_count"], 0)
        self.assertIsNone(result["selection_prompt"])
        self.assertIn("今回は有力候補なし", result["markdown"])

    def test_markdown_contains_section_headers(self) -> None:
        payload = _prepare_payload(candidates=[_ready_candidate()])
        result = build_proposal_sections(payload)

        self.assertIn("## 提案成立", result["markdown"])
        self.assertIn("## 追加調査待ち", result["markdown"])
        self.assertIn("## 今回は見送り", result["markdown"])


class JudgmentMergeTests(unittest.TestCase):
    """Tests for merge_judgment_into_candidate."""

    def test_promote_ready_updates_triage_status(self) -> None:
        candidate = _needs_research_candidate()
        judgment = {
            "judgment": {
                "recommendation": "promote_ready",
                "proposed_triage_status": "ready",
                "proposed_confidence": "moderate",
                "summary": "Pattern confirmed by deep review",
                "reasons": ["Multiple matching sessions found"],
            },
        }
        merged = merge_judgment_into_candidate(candidate, judgment)

        self.assertEqual(merged["triage_status"], "ready")
        self.assertTrue(merged["proposal_ready"])
        self.assertEqual(merged["confidence"], "moderate")
        self.assertIn("research_judgment", merged)

    def test_reject_candidate_updates_triage_status(self) -> None:
        candidate = _needs_research_candidate()
        judgment = {
            "judgment": {
                "recommendation": "reject_candidate",
                "proposed_triage_status": "rejected",
                "proposed_confidence": "insufficient",
                "summary": "Not a real pattern",
            },
        }
        merged = merge_judgment_into_candidate(candidate, judgment)

        self.assertEqual(merged["triage_status"], "rejected")
        self.assertFalse(merged["proposal_ready"])

    def test_no_judgment_preserves_candidate(self) -> None:
        candidate = _ready_candidate()
        merged = merge_judgment_into_candidate(candidate, None)

        self.assertEqual(merged["label"], candidate["label"])
        self.assertEqual(merged["triage_status"], candidate["triage_status"])

    def test_promote_ready_clears_weak_semantic_flag(self) -> None:
        candidate = _needs_research_candidate(
            quality_flags=["weak_semantic_cohesion", "generic_task_shape"],
        )
        judgment = {
            "judgment": {
                "recommendation": "promote_ready",
                "proposed_triage_status": "ready",
                "proposed_confidence": "moderate",
            },
        }
        merged = merge_judgment_into_candidate(candidate, judgment)

        self.assertNotIn("weak_semantic_cohesion", merged.get("quality_flags", []))
        self.assertIn("generic_task_shape", merged.get("quality_flags", []))

    def test_judgment_with_sections_routes_correctly(self) -> None:
        """Promoted candidate should appear in ready section of proposal."""
        candidate = _needs_research_candidate()
        judgment_payload = {
            "candidate_id": "c2",
            "judgment": {
                "recommendation": "promote_ready",
                "proposed_triage_status": "ready",
                "proposed_confidence": "moderate",
                "summary": "Confirmed pattern",
            },
        }
        payload = _prepare_payload(candidates=[candidate])
        result = build_proposal_sections(
            payload,
            judgments_by_candidate_id={"c2": judgment_payload},
        )

        self.assertEqual(result["summary"]["ready_count"], 1)
        self.assertEqual(result["summary"]["needs_research_count"], 0)


class MarkdownFormatTests(unittest.TestCase):
    """Tests for proposal markdown rendering."""

    def test_evidence_chain_lines_renders_items(self) -> None:
        candidate = _ready_candidate()
        lines = build_evidence_chain_lines(candidate)

        self.assertTrue(any("根拠" in line for line in lines))
        self.assertTrue(any("claude-history" in line for line in lines))

    def test_evidence_chain_fallback_when_no_items(self) -> None:
        candidate = _ready_candidate(evidence_items=[], evidence_summary="fallback text")
        lines = build_evidence_chain_lines(candidate)

        self.assertTrue(any("fallback text" in line for line in lines))

    def test_proposal_item_lines_with_classification(self) -> None:
        lines = proposal_item_lines(1, _ready_candidate(), include_classification=True)
        text = "\n".join(lines)

        self.assertIn("Review workflow", text)
        self.assertIn("分類: CLAUDE.md", text)
        self.assertIn("期待効果", text)

    def test_proposal_item_lines_without_classification(self) -> None:
        lines = proposal_item_lines(1, _needs_research_candidate(), include_classification=False)
        text = "\n".join(lines)

        self.assertIn("Build automation", text)
        self.assertIn("保留理由", text)
        self.assertNotIn("分類", text)

    def test_rejected_item_lines_format(self) -> None:
        candidate = {"label": "One-off task", "confidence_reason": "single occurrence"}
        lines = rejected_item_lines(1, candidate)
        text = "\n".join(lines)

        self.assertIn("One-off task", text)
        self.assertIn("理由: single occurrence", text)

    def test_build_markdown_with_ready_includes_selection_prompt(self) -> None:
        markdown = build_markdown([_ready_candidate()], [], [])
        self.assertIn("どの候補をドラフト化しますか", markdown)

    def test_build_markdown_without_ready_shows_no_candidates(self) -> None:
        markdown = build_markdown([], [_needs_research_candidate()], [])
        self.assertIn("今回は有力候補なし", markdown)
        self.assertNotIn("どの候補をドラフト化しますか", markdown)

    def test_build_markdown_limits_rejected_to_five(self) -> None:
        rejected = [
            {"label": f"Rejected-{i}", "confidence_reason": "reason"}
            for i in range(10)
        ]
        markdown = build_markdown([], [], rejected)
        self.assertIn("Rejected-4", markdown)
        self.assertNotIn("Rejected-5", markdown)

    def test_build_markdown_renders_all_ready_candidates_up_to_default_top_n(self) -> None:
        ready = [
            _ready_candidate(candidate_id=f"ready-{index}", label=f"Ready-{index}")
            for index in range(1, DEFAULT_TOP_N + 1)
        ]

        markdown = build_markdown(ready, [], [])

        for index in range(1, DEFAULT_TOP_N + 1):
            self.assertIn(f"{index}. Ready-{index}", markdown)

    def test_build_markdown_renders_all_needs_research_candidates_up_to_default_top_n(self) -> None:
        needs_research = [
            _needs_research_candidate(candidate_id=f"needs-{index}", label=f"Needs-{index}")
            for index in range(1, DEFAULT_TOP_N + 1)
        ]

        markdown = build_markdown([], needs_research, [])

        for index in range(1, DEFAULT_TOP_N + 1):
            self.assertIn(f"{index}. Needs-{index}", markdown)

    def test_build_markdown_truncates_rejected_section_to_current_limit(self) -> None:
        rejected = [
            {"label": f"Rejected-{index}", "confidence_reason": "reason"}
            for index in range(10)
        ]

        markdown = build_markdown([], [], rejected)

        for index in range(5):
            self.assertIn(f"Rejected-{index}", markdown)
        self.assertNotIn("Rejected-5", markdown)


class ProposalCLITests(unittest.TestCase):
    """Integration tests for skill_miner_proposal.py CLI."""

    def test_cli_produces_valid_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepare_file = Path(temp_dir) / "prepare.json"
            prepare_file.write_text(
                json.dumps(_prepare_payload(candidates=[_ready_candidate()])),
                encoding="utf-8",
            )

            completed = subprocess.run(
                ["python3", str(PROPOSAL), "--prepare-file", str(prepare_file)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["source"], "skill-miner-proposal")
            self.assertEqual(payload["summary"]["ready_count"], 1)
            self.assertIn("## 提案成立", payload["markdown"])

    def test_cli_with_judgment_file_promotes_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepare_file = Path(temp_dir) / "prepare.json"
            prepare_file.write_text(
                json.dumps(_prepare_payload(candidates=[_needs_research_candidate()])),
                encoding="utf-8",
            )

            judge_file = Path(temp_dir) / "judge.json"
            judge_file.write_text(
                json.dumps({
                    "candidate_id": "c2",
                    "judgment": {
                        "recommendation": "promote_ready",
                        "proposed_triage_status": "ready",
                        "proposed_confidence": "moderate",
                        "summary": "Confirmed after deep review",
                    },
                }),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python3", str(PROPOSAL),
                    "--prepare-file", str(prepare_file),
                    "--judge-file", str(judge_file),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["summary"]["ready_count"], 1)
            self.assertEqual(payload["summary"]["needs_research_count"], 0)

    def test_cli_markdown_matches_golden_fixture(self) -> None:
        self.assertEqual(
            _render_markdown_from_fixture(),
            GOLDEN_MARKDOWN.read_text(encoding="utf-8").rstrip("\n"),
        )

    def test_cli_with_missing_prepare_file_returns_error(self) -> None:
        completed = subprocess.run(
            ["python3", str(PROPOSAL), "--prepare-file", "/nonexistent/prepare.json"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")

    def test_cli_empty_prepare_returns_all_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepare_file = Path(temp_dir) / "prepare.json"
            prepare_file.write_text(
                json.dumps(_prepare_payload()),
                encoding="utf-8",
            )

            completed = subprocess.run(
                ["python3", str(PROPOSAL), "--prepare-file", str(prepare_file)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["summary"]["ready_count"], 0)
            self.assertEqual(payload["summary"]["needs_research_count"], 0)
            self.assertEqual(payload["summary"]["rejected_count"], 0)


class LoadJudgmentsTests(unittest.TestCase):
    """Tests for the load_judgments helper."""

    def test_loads_multiple_judgment_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            j1 = Path(temp_dir) / "j1.json"
            j2 = Path(temp_dir) / "j2.json"
            j1.write_text(json.dumps({"candidate_id": "c1", "judgment": {"recommendation": "promote_ready"}}))
            j2.write_text(json.dumps({"candidate_id": "c2", "judgment": {"recommendation": "reject_candidate"}}))

            result = load_judgments([str(j1), str(j2)])

            self.assertEqual(len(result), 2)
            self.assertIn("c1", result)
            self.assertIn("c2", result)

    def test_skips_entries_without_candidate_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            j1 = Path(temp_dir) / "j1.json"
            j1.write_text(json.dumps({"judgment": {"recommendation": "promote_ready"}}))

            result = load_judgments([str(j1)])

            self.assertEqual(len(result), 0)


if __name__ == "__main__":
    unittest.main()
