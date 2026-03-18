#!/usr/bin/env python3
"""Tests for hackathon repair-plan additions:
- infer_suggested_kind / infer_suggested_kind_details
- _is_oversized_and_unresolved
- build_skill_scaffold_context
- _observation_stats_lines / _growth_signal_lines
- build_proposal_sections oversized-cluster guard
- build_proposal_markdown enriched 0-candidate output
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from skill_miner_common import (
    _degraded_mode_lines,
    _growth_signal_lines,
    _is_oversized_and_unresolved,
    _observation_stats_lines,
    build_next_step_stub,
    build_observation_contract,
    build_proposal_markdown,
    build_proposal_sections,
    build_skill_scaffold_context,
    infer_suggested_kind,
    infer_suggested_kind_details,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_candidate(
    *,
    candidate_id: str = "c1",
    label: str = "test-candidate",
    common_task_shapes: list[str] | None = None,
    artifact_hints: list[str] | None = None,
    rule_hints: list[str] | None = None,
    tool_signature: list[str] | None = None,
    quality_flags: list[str] | None = None,
    triage_status: str = "ready",
    proposal_ready: bool = True,
    suggested_kind: str | None = None,
    research_judgment: dict | None = None,
    total_packets: int = 3,
    evidence_items: list[dict] | None = None,
    representative_examples: list[str] | None = None,
    constraints: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
) -> dict:
    candidate: dict = {
        "candidate_id": candidate_id,
        "label": label,
        "common_task_shapes": common_task_shapes or [],
        "artifact_hints": artifact_hints or [],
        "rule_hints": rule_hints or [],
        "tool_signature": tool_signature or [],
        "quality_flags": quality_flags or [],
        "triage_status": triage_status,
        "proposal_ready": proposal_ready,
        "support": {"total_packets": total_packets, "claude_packets": 1, "codex_packets": 1},
        "confidence": "medium",
        "confidence_reason": "test",
        "evidence_summary": "test evidence",
        "evidence_items": evidence_items or [],
        "representative_examples": representative_examples or [],
        "constraints": constraints or [],
        "acceptance_criteria": acceptance_criteria or [],
    }
    if suggested_kind is not None:
        candidate["suggested_kind"] = suggested_kind
    if research_judgment is not None:
        candidate["research_judgment"] = research_judgment
    return candidate


def _make_prepare_payload(
    candidates: list[dict] | None = None,
    unclustered: list[dict] | None = None,
    total_packets: int = 20,
    total_candidates: int | None = None,
    days: int = 7,
) -> dict:
    candidates = candidates or []
    return {
        "candidates": candidates,
        "unclustered": unclustered or [],
        "config": {"effective_days": days, "all_sessions": True},
        "sources": [
            {"name": "claude-history", "status": "success"},
            {"name": "codex-history", "status": "success"},
        ],
        "summary": {
            "total_packets": total_packets,
            "total_candidates": total_candidates if total_candidates is not None else len(candidates),
        },
    }


# ---------------------------------------------------------------------------
# infer_suggested_kind / infer_suggested_kind_details
# ---------------------------------------------------------------------------

class TestInferSuggestedKind(unittest.TestCase):

    def test_claude_md_from_rule_hints(self):
        """rule_hints containing CLAUDE_MD_RULE_NAMES → CLAUDE.md"""
        candidate = _make_candidate(rule_hints=["always-do", "format-rule"])
        self.assertEqual(infer_suggested_kind(candidate), "CLAUDE.md")

    def test_claude_md_from_artifact(self):
        """artifact_hints containing 'claude-md' → CLAUDE.md"""
        candidate = _make_candidate(artifact_hints=["claude-md"])
        self.assertEqual(infer_suggested_kind(candidate), "CLAUDE.md")

    def test_hook_from_task_shapes(self):
        """All top shapes in HOOK_SHAPES → hook"""
        candidate = _make_candidate(common_task_shapes=["run_tests"])
        self.assertEqual(infer_suggested_kind(candidate), "hook")

    def test_skill_from_task_shapes(self):
        """task_shapes containing SKILL_SHAPES → skill"""
        candidate = _make_candidate(common_task_shapes=["prepare_report"], artifact_hints=["report"])
        self.assertEqual(infer_suggested_kind(candidate), "skill")

    def test_agent_from_agent_shapes_with_support(self):
        """AGENT_SHAPES with high packet count → agent"""
        candidate = _make_candidate(
            common_task_shapes=["summarize_findings"],
            rule_hints=["findings-first"],
            total_packets=5,
        )
        # agent requires total_packets >= 4 AND (agent_shapes OR rule_hints)
        # BUT CLAUDE_MD_RULE_NAMES includes 'findings-first', so it hits CLAUDE.md first
        # Let's use a non-CLAUDE_MD rule
        candidate["rule_hints"] = ["custom-rule"]
        result = infer_suggested_kind(candidate)
        self.assertEqual(result, "agent")

    def test_default_fallback_is_skill(self):
        """No distinguishing features → skill fallback"""
        candidate = _make_candidate(common_task_shapes=["implement_feature"])
        self.assertEqual(infer_suggested_kind(candidate), "skill")

    def test_details_returns_reason(self):
        """infer_suggested_kind_details includes reason string"""
        candidate = _make_candidate(rule_hints=["always-do"])
        details = infer_suggested_kind_details(candidate)
        self.assertIn("kind", details)
        self.assertIn("reason", details)
        self.assertEqual(details["kind"], "CLAUDE.md")


# ---------------------------------------------------------------------------
# _is_oversized_and_unresolved
# ---------------------------------------------------------------------------

class TestIsOversizedAndUnresolved(unittest.TestCase):

    def test_no_oversized_flag(self):
        candidate = _make_candidate(quality_flags=[])
        self.assertFalse(_is_oversized_and_unresolved(candidate))

    def test_oversized_without_judgment(self):
        candidate = _make_candidate(quality_flags=["oversized_cluster"])
        self.assertTrue(_is_oversized_and_unresolved(candidate))

    def test_oversized_with_non_promote_judgment(self):
        candidate = _make_candidate(
            quality_flags=["oversized_cluster"],
            research_judgment={"recommendation": "keep_needs_research"},
        )
        self.assertTrue(_is_oversized_and_unresolved(candidate))

    def test_oversized_with_promote_ready(self):
        candidate = _make_candidate(
            quality_flags=["oversized_cluster"],
            research_judgment={"recommendation": "promote_ready"},
        )
        self.assertFalse(_is_oversized_and_unresolved(candidate))


# ---------------------------------------------------------------------------
# build_proposal_sections — oversized cluster guard
# ---------------------------------------------------------------------------

class TestBuildProposalSectionsOversizedGuard(unittest.TestCase):

    def test_oversized_demoted_to_needs_research(self):
        """Oversized cluster in ready should be demoted to needs_research."""
        candidate = _make_candidate(
            quality_flags=["oversized_cluster"],
            triage_status="ready",
            proposal_ready=True,
            suggested_kind="CLAUDE.md",
        )
        payload = _make_prepare_payload(candidates=[candidate])
        result = build_proposal_sections(payload)
        self.assertEqual(len(result["ready"]), 0)
        self.assertEqual(len(result["needs_research"]), 1)
        self.assertIn("巨大クラスタ", result["needs_research"][0].get("confidence_reason", ""))

    def test_oversized_promoted_stays_ready(self):
        """Oversized cluster with promote_ready judgment should stay in ready."""
        candidate = _make_candidate(
            quality_flags=["oversized_cluster"],
            triage_status="ready",
            proposal_ready=True,
            suggested_kind="CLAUDE.md",
            research_judgment={"recommendation": "promote_ready"},
        )
        payload = _make_prepare_payload(candidates=[candidate])
        result = build_proposal_sections(payload)
        self.assertEqual(len(result["ready"]), 1)
        self.assertEqual(len(result["needs_research"]), 0)

    def test_normal_candidate_not_affected(self):
        """Non-oversized ready candidate passes through normally."""
        candidate = _make_candidate(
            quality_flags=[],
            triage_status="ready",
            proposal_ready=True,
            suggested_kind="CLAUDE.md",
        )
        payload = _make_prepare_payload(candidates=[candidate])
        result = build_proposal_sections(payload)
        self.assertEqual(len(result["ready"]), 1)


# ---------------------------------------------------------------------------
# _observation_stats_lines
# ---------------------------------------------------------------------------

class TestObservationStatsLines(unittest.TestCase):

    def test_returns_stats_with_metadata(self):
        metadata = {
            "summary": {"total_packets": 15, "total_candidates": 3},
            "config": {"effective_days": 7},
            "sources": [
                {"name": "claude-history", "status": "success"},
                {"name": "codex-history", "status": "skipped"},
            ],
        }
        lines = _observation_stats_lines(metadata)
        self.assertTrue(any("15件" in line for line in lines))
        self.assertTrue(any("7日間" in line for line in lines))
        self.assertTrue(any("claude-history" in line for line in lines))
        # skipped source should not appear
        self.assertFalse(any("codex-history" in line for line in lines))

    def test_returns_lines_with_empty_metadata(self):
        lines = _observation_stats_lines(None)
        self.assertIsInstance(lines, list)
        self.assertTrue(len(lines) >= 1)


# ---------------------------------------------------------------------------
# _growth_signal_lines
# ---------------------------------------------------------------------------

class TestGrowthSignalLines(unittest.TestCase):

    def test_returns_empty_for_no_candidates(self):
        self.assertEqual(_growth_signal_lines([]), [])

    def test_returns_header_and_items(self):
        candidates = [
            {"label": "pattern-a", "support": {"total_packets": 5}},
            {"label": "pattern-b", "support": {"total_packets": 3}},
        ]
        lines = _growth_signal_lines(candidates)
        self.assertIn("成長兆候", lines[0])
        self.assertTrue(any("pattern-a" in line for line in lines))
        self.assertTrue(any("pattern-b" in line for line in lines))

    def test_limits_to_three(self):
        candidates = [{"label": f"p{i}", "support": {"total_packets": i}} for i in range(6)]
        lines = _growth_signal_lines(candidates)
        # header + max 3 items = 4 lines
        self.assertLessEqual(len(lines), 4)


# ---------------------------------------------------------------------------
# build_proposal_markdown — enriched 0-candidate output
# ---------------------------------------------------------------------------

class TestBuildProposalMarkdownEnriched(unittest.TestCase):

    def test_zero_ready_includes_observation_stats(self):
        metadata = _make_prepare_payload(total_packets=20, total_candidates=5, days=7)
        needs_research = [
            _make_candidate(label="growing-pattern", triage_status="needs_research", total_packets=4),
        ]
        markdown = build_proposal_markdown([], needs_research, [], metadata=metadata)
        self.assertIn("観測サマリ", markdown)
        self.assertIn("20件", markdown)
        self.assertIn("成長兆候", markdown)
        self.assertIn("growing-pattern", markdown)

    def test_zero_ready_zero_needs_research(self):
        metadata = _make_prepare_payload(total_packets=5, total_candidates=0, days=3)
        markdown = build_proposal_markdown([], [], [], metadata=metadata)
        self.assertIn("観測サマリ", markdown)
        self.assertNotIn("成長兆候", markdown)

    def test_nonempty_ready_skips_enriched(self):
        metadata = _make_prepare_payload(total_packets=20, total_candidates=5)
        ready = [
            _make_candidate(label="ready-one", suggested_kind="CLAUDE.md"),
        ]
        markdown = build_proposal_markdown(ready, [], [], metadata=metadata)
        self.assertNotIn("観測サマリ:", markdown)

    def test_degraded_lines_are_rendered_when_sources_or_fidelity_are_degraded(self):
        metadata = _make_prepare_payload(total_packets=9, total_candidates=2)
        metadata["config"]["input_fidelity"] = "approximate"
        metadata["config"]["adaptive_window"] = {
            "expanded": True,
            "reason": "insufficient_candidates",
            "initial_days": 7,
            "fallback_days": 30,
        }
        metadata["sources"] = [
            {"name": "claude-history", "status": "success"},
            {"name": "codex-history", "status": "skipped", "reason": "not_found"},
        ]
        markdown = build_proposal_markdown([], [], [], metadata=metadata)
        self.assertIn("入力の一部が近似復元データ", markdown)
        self.assertIn("観測窓を 7日 -> 30日", markdown)
        self.assertIn("degraded", markdown)


class TestDegradedModeLines(unittest.TestCase):

    def test_empty_metadata_returns_empty_list(self):
        self.assertEqual(_degraded_mode_lines(None), [])

    def test_returns_lines_for_adaptive_and_source_degrade(self):
        metadata = {
            "config": {
                "input_fidelity": "approximate",
                "adaptive_window": {"expanded": True, "reason": "insufficient_packets", "initial_days": 7, "fallback_days": 30},
            },
            "sources": [
                {"name": "claude-history", "status": "success"},
                {"name": "codex-history", "status": "error", "message": "timeout"},
            ],
        }
        lines = _degraded_mode_lines(metadata)
        self.assertTrue(any("近似復元データ" in line for line in lines))
        self.assertTrue(any("自動拡張" in line for line in lines))
        self.assertTrue(any("codex-history(timeout)" in line for line in lines))


class TestObservationContract(unittest.TestCase):

    def test_contract_unifies_degraded_approximate_and_adaptive_window(self):
        metadata = {
            "config": {
                "effective_days": 30,
                "days": 7,
                "all_sessions": False,
                "workspace": "/tmp/daytrace",
                "observation_mode": "workspace",
                "input_fidelity": "approximate",
                "adaptive_window": {
                    "enabled": True,
                    "expanded": True,
                    "reason": "insufficient_packets",
                    "initial_days": 7,
                    "fallback_days": 30,
                },
            },
            "sources": [
                {"name": "claude-history", "status": "success"},
                {"name": "codex-history", "status": "error", "message": "timeout"},
            ],
        }

        contract = build_observation_contract(metadata)

        self.assertEqual(contract["mode"], "workspace")
        self.assertTrue(contract["approximate"])
        self.assertTrue(contract["degraded"])
        self.assertTrue(contract["adaptive_window_expanded"])
        self.assertEqual(contract["adaptive_window"]["initial_days"], 7)
        self.assertEqual(contract["adaptive_window"]["effective_days"], 30)
        self.assertEqual(contract["degraded_sources"][0]["name"], "codex-history")


class TestNextStepStub(unittest.TestCase):

    def test_hook_candidate_builds_minimal_next_step_stub(self):
        candidate = _make_candidate(
            label="Run tests before close",
            common_task_shapes=["run_tests"],
            rule_hints=["tests-before-close"],
            suggested_kind="hook",
            constraints=["Do not run for docs-only changes."],
        )

        stub = build_next_step_stub(candidate)

        self.assertIsNotNone(stub)
        self.assertEqual(stub["kind"], "hook")
        self.assertEqual(stub["trigger_event"], "Stop")
        self.assertIn("hook にしてください", stub["prompt"])

    def test_agent_candidate_builds_minimal_next_step_stub(self):
        candidate = _make_candidate(
            label="Review steward",
            common_task_shapes=["summarize_findings"],
            rule_hints=["custom-review-rule"],
            suggested_kind="agent",
            representative_examples=["Review changes and summarize findings."],
            acceptance_criteria=["Include file and line references."],
        )

        stub = build_next_step_stub(candidate)

        self.assertIsNotNone(stub)
        self.assertEqual(stub["kind"], "agent")
        self.assertIn("agent にしてください", stub["prompt"])
        self.assertTrue(stub["behavior_rules"])


# ---------------------------------------------------------------------------
# build_skill_scaffold_context
# ---------------------------------------------------------------------------

class TestBuildSkillScaffoldContext(unittest.TestCase):

    def test_basic_structure(self):
        candidate = _make_candidate(
            label="daily report helper",
            common_task_shapes=["prepare_report"],
            artifact_hints=["report", "markdown"],
            rule_hints=["findings-first"],
            representative_examples=["example 1", "example 2"],
            evidence_items=[{"summary": "observed 3 times", "timestamp": "2026-03-01", "source": "claude"}],
        )
        ctx = build_skill_scaffold_context(candidate)
        self.assertEqual(ctx["skill_name"], "daily-report-helper")
        self.assertIn("prepare report", ctx["goal"])
        self.assertEqual(ctx["task_shapes"], ["prepare_report"])
        self.assertEqual(ctx["artifact_hints"], ["report", "markdown"])
        self.assertEqual(ctx["rule_hints"], ["findings-first"])
        self.assertEqual(len(ctx["representative_examples"]), 2)
        self.assertEqual(len(ctx["evidence_summaries"]), 1)
        self.assertEqual(ctx["observation_count"], 3)
        self.assertEqual(ctx["source_diversity"], 2)  # both claude and codex packets > 0

    def test_empty_candidate(self):
        ctx = build_skill_scaffold_context({})
        self.assertEqual(ctx["skill_name"], "unnamed-skill")
        self.assertEqual(ctx["observation_count"], 0)


if __name__ == "__main__":
    unittest.main()
