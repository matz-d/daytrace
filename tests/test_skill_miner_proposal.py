#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from conftest import PROJECT_ROOT, PLUGIN_ROOT, FIXTURES_DIR

from skill_miner_common import DEFAULT_TOP_N, build_candidate_decision_key, build_proposal_sections, build_research_brief, merge_judgment_into_candidate
from skill_miner_proposal import (
    build_evidence_chain_lines,
    build_markdown,
    load_judgments,
    persist_skill_creator_handoffs,
    proposal_item_lines,
    rejected_item_lines,
)

PROPOSAL = PLUGIN_ROOT / "scripts" / "skill_miner_proposal.py"
GOLDEN_PREPARE = FIXTURES_DIR / "skill_miner_proposal_prepare.json"
GOLDEN_MARKDOWN = FIXTURES_DIR / "golden_proposal.md"


def _render_markdown_from_fixture() -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        decision_log = Path(temp_dir) / "decision-log.jsonl"
        handoff_dir = Path(temp_dir) / "handoffs"
        completed = subprocess.run(
            [
                "python3",
                str(PROPOSAL),
                "--prepare-file",
                str(GOLDEN_PREPARE),
                "--decision-log-path",
                str(decision_log),
                "--skill-creator-handoff-dir",
                str(handoff_dir),
            ],
            cwd=str(PROJECT_ROOT),
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
        "intent_trace": ["Review workflow", "Keep findings-first output"],
        "constraints": ["Do not edit unrelated files."],
        "acceptance_criteria": ["Include file and line references."],
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
        "config": {"effective_days": 7, "workspace": "/tmp/daytrace", "all_sessions": False},
        "sources": [
            {"name": "claude-history", "status": "success"},
            {"name": "codex-history", "status": "success"},
        ],
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

    def test_ready_candidate_without_suggested_kind_gets_skill_scaffold_context_and_handoff(self) -> None:
        candidate = _ready_candidate(
            suggested_kind="",
            label="Build automation",
            common_task_shapes=["implement_feature", "run_tests"],
            artifact_hints=["code"],
            rule_hints=[],
            support={"total_packets": 3, "claude_packets": 1, "codex_packets": 2},
        )

        result = build_proposal_sections(_prepare_payload(candidates=[candidate]))

        self.assertEqual(result["ready"][0]["suggested_kind"], "skill")
        self.assertEqual(result["ready"][0]["suggested_kind_source"], "heuristic")
        self.assertIn("skill_scaffold_context", result["ready"][0])
        self.assertIn("skill_creator_handoff", result["ready"][0])
        self.assertEqual(result["ready"][0]["skill_scaffold_context"]["skill_name"], "build-automation")
        self.assertEqual(result["ready"][0]["skill_creator_handoff"]["tool"], "skill-creator")
        self.assertEqual(result["ready"][0]["skill_creator_handoff"]["entrypoint"], "/skill-creator")
        self.assertEqual(result["decision_log_stub"][0]["recommended_action"], "adopt")
        self.assertEqual(result["learning_feedback"]["status"], "ready_candidates_available")

    def test_ready_hook_candidate_gets_next_step_stub(self) -> None:
        candidate = _ready_candidate(
            candidate_id="hook-1",
            label="Run tests before close",
            suggested_kind="hook",
            common_task_shapes=["run_tests"],
            common_tool_signatures=["pytest"],
        )

        result = build_proposal_sections(_prepare_payload(candidates=[candidate]))

        self.assertEqual(result["ready"][0]["next_step_stub"]["kind"], "hook")
        self.assertEqual(result["ready"][0]["next_step_stub"]["trigger_event"], "Stop")

    def test_decision_log_stub_carries_constraints_and_acceptance_criteria(self) -> None:
        payload = _prepare_payload(candidates=[_ready_candidate()])

        result = build_proposal_sections(payload)

        self.assertEqual(result["decision_log_stub"][0]["constraints"], ["Do not edit unrelated files."])
        self.assertEqual(result["decision_log_stub"][0]["acceptance_criteria"], ["Include file and line references."])

    def test_decision_log_stub_defaults_to_carry_forward_until_user_decides(self) -> None:
        payload = _prepare_payload(candidates=[_ready_candidate()])

        result = build_proposal_sections(payload)

        self.assertTrue(result["decision_log_stub"][0]["carry_forward"])
        self.assertEqual(result["decision_log_stub"][0]["decision_key"], build_candidate_decision_key(result["ready"][0]))

    def test_decision_log_stub_tracks_observation_counts(self) -> None:
        payload = _prepare_payload(
            candidates=[
                _ready_candidate(
                    support={"total_packets": 3},
                    prior_decision_state={"observation_count": 2},
                )
            ]
        )

        result = build_proposal_sections(payload)

        stub = result["decision_log_stub"][0]
        self.assertEqual(stub["observation_count"], 3)
        self.assertEqual(stub["prior_observation_count"], 2)
        self.assertEqual(stub["observation_delta"], 1)

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
        self.assertIn("### 観測範囲", result["markdown"])
        self.assertIn("今回は有力候補なし", result["markdown"])
        self.assertIn("検出候補数", result["markdown"])

    def test_needs_research_output_includes_learning_feedback_and_split_candidates(self) -> None:
        payload = _prepare_payload(
            candidates=[
                _needs_research_candidate(
                    split_suggestions=["review changes / review", "prepare report / markdown"],
                    quality_flags=["oversized_cluster"],
                    support={"total_packets": 4, "claude_packets": 2, "codex_packets": 2},
                )
            ]
        )

        result = build_proposal_sections(payload)

        self.assertEqual(result["learning_feedback"]["status"], "needs_more_observation")
        self.assertEqual(result["decision_log_stub"][0]["recommended_action"], "defer")
        self.assertEqual(
            result["learning_feedback"]["split_candidates"][0]["split_suggestions"],
            ["review changes / review", "prepare report / markdown"],
        )
        self.assertIn("次に育てやすい候補", result["markdown"])

    def test_split_judgment_materializes_ready_and_needs_research_children(self) -> None:
        parent = _needs_research_candidate(
            candidate_id="parent-1",
            label="Mixed workflow cluster",
            quality_flags=["oversized_cluster", "split_recommended"],
            session_refs=["codex:a:1", "codex:b:2", "codex:c:3"],
            evidence_items=[
                {"session_ref": "codex:a:1", "source": "codex-history", "summary": "Review PR and list findings"},
                {"session_ref": "codex:b:2", "source": "codex-history", "summary": "Review another PR with findings-first output"},
                {"session_ref": "codex:c:3", "source": "codex-history", "summary": "Prepare a weekly report draft"},
            ],
        )
        judgments = {
            "parent-1": {
                "judgment": {
                    "recommendation": "split_candidate",
                    "proposed_triage_status": "needs_research",
                    "proposed_confidence": "weak",
                    "summary": "recommendation=split_candidate / sampled_refs=3 / primary_shapes=review_changes, prepare_report / avg_overlap=0.11",
                    "split_suggestions": ["review_changes", "prepare_report"],
                    "subcluster_triage": [
                        {
                            "split_label": "review_changes",
                            "triage_status": "ready",
                            "confidence": "medium",
                            "session_refs": ["codex:a:1", "codex:b:2"],
                            "artifact_hint": "code",
                            "average_overlap": 0.24,
                        },
                        {
                            "split_label": "prepare_report",
                            "triage_status": "needs_research",
                            "confidence": "weak",
                            "session_refs": ["codex:c:3"],
                            "artifact_hint": "markdown",
                            "average_overlap": 0.0,
                        },
                    ],
                    "detail_signals": [
                        {
                            "session_ref": "codex:a:1",
                            "task_shapes": ["review_changes"],
                            "artifact_hints": ["code"],
                            "user_rule_hints": ["findings-first"],
                            "repeated_rules": ["findings-first"],
                            "constraints": ["Do not edit unrelated files."],
                            "acceptance_criteria": ["Include file and line references."],
                            "tool_names": ["rg", "git"],
                            "primary_intent": "Review PR and return findings by severity.",
                        },
                        {
                            "session_ref": "codex:b:2",
                            "task_shapes": ["review_changes"],
                            "artifact_hints": ["code"],
                            "user_rule_hints": ["findings-first"],
                            "repeated_rules": ["findings-first"],
                            "constraints": ["Do not edit unrelated files."],
                            "acceptance_criteria": ["Include file and line references."],
                            "tool_names": ["rg", "git"],
                            "primary_intent": "Review another PR and keep the findings-first format.",
                        },
                        {
                            "session_ref": "codex:c:3",
                            "task_shapes": ["prepare_report"],
                            "artifact_hints": ["markdown"],
                            "user_rule_hints": [],
                            "repeated_rules": [],
                            "constraints": [],
                            "acceptance_criteria": ["Summarize the weekly status clearly."],
                            "tool_names": ["python3"],
                            "primary_intent": "Prepare a weekly report draft in markdown.",
                        },
                    ],
                }
            }
        }

        result = build_proposal_sections(_prepare_payload(candidates=[parent]), judgments_by_candidate_id=judgments)

        self.assertEqual(result["summary"]["ready_count"], 1)
        self.assertEqual(result["summary"]["needs_research_count"], 1)
        self.assertEqual(result["summary"]["rejected_count"], 0)
        self.assertEqual(result["ready"][0]["split_origin"]["parent_candidate_id"], "parent-1")
        self.assertEqual(result["ready"][0]["common_task_shapes"], ["review_changes"])
        self.assertEqual(result["needs_research"][0]["common_task_shapes"], ["prepare_report"])
        self.assertTrue(result["ready"][0]["candidate_id"].startswith("parent-1--split-"))
        self.assertTrue(all(item["candidate_id"] != "parent-1" for item in result["decision_log_stub"]))
        self.assertIn("split from Mixed workflow cluster", result["ready"][0]["evidence_summary"])

    def test_markdown_contains_section_headers(self) -> None:
        payload = _prepare_payload(candidates=[_ready_candidate()])
        result = build_proposal_sections(payload)

        self.assertIn("## 提案（固定化を推奨）", result["markdown"])
        self.assertIn("## 有望候補（もう少し観測が必要）", result["markdown"])
        self.assertIn("## 観測ノート", result["markdown"])


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
        self.assertIn("weak_semantic_cohesion", merged.get("resolved_quality_flags", []))

    def test_promote_ready_resolves_research_blocking_flags(self) -> None:
        candidate = _needs_research_candidate(
            quality_flags=["oversized_cluster", "split_recommended", "near_match_dense", "generic_task_shape"],
        )
        judgment = {
            "judgment": {
                "recommendation": "promote_ready",
                "proposed_triage_status": "ready",
                "proposed_confidence": "strong",
            },
        }
        merged = merge_judgment_into_candidate(candidate, judgment)

        self.assertEqual(
            set(merged.get("resolved_quality_flags", [])),
            {"oversized_cluster", "split_recommended", "near_match_dense"},
        )
        self.assertNotIn("oversized_cluster", merged.get("quality_flags", []))
        self.assertNotIn("split_recommended", merged.get("quality_flags", []))
        self.assertNotIn("near_match_dense", merged.get("quality_flags", []))
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

    def test_promoted_candidate_markdown_discloses_resolved_flags(self) -> None:
        candidate = _needs_research_candidate(
            quality_flags=["split_recommended", "near_match_dense"],
            confidence_reason="mixed cluster before deep review",
        )
        judgment_payload = {
            "candidate_id": "c2",
            "judgment": {
                "recommendation": "promote_ready",
                "proposed_triage_status": "ready",
                "proposed_confidence": "strong",
                "summary": "Deep review confirmed one reusable build flow.",
            },
        }
        payload = _prepare_payload(candidates=[candidate])
        result = build_proposal_sections(
            payload,
            judgments_by_candidate_id={"c2": judgment_payload},
        )

        self.assertEqual(result["summary"]["ready_count"], 1)
        self.assertIn("研究で解消", result["markdown"])
        self.assertIn("分割推奨", result["markdown"])
        self.assertIn("近接クラスタ競合", result["markdown"])


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
        self.assertIn("固定先: CLAUDE.md", text)
        self.assertIn("期待効果", text)
        self.assertIn("制約", text)
        self.assertIn("受け入れ条件", text)

    def test_proposal_item_lines_without_classification(self) -> None:
        lines = proposal_item_lines(1, _needs_research_candidate(), include_classification=False)
        text = "\n".join(lines)

        self.assertIn("Build automation", text)
        self.assertIn("現状", text)
        self.assertIn("次のステップ", text)
        self.assertNotIn("固定先", text)

    def test_proposal_item_lines_for_skill_include_official_handoff(self) -> None:
        candidate = _ready_candidate(
            suggested_kind="skill",
            skill_scaffold_context={
                "goal": "build automation を再利用可能なスキルとして固定化する",
                "artifact_hints": ["code"],
                "rule_hints": ["tests-before-close"],
                "observation_count": 3,
                "representative_examples": ["Implement the build command and run tests before finishing."],
            },
            skill_creator_handoff={
                "tool": "skill-creator",
                "entrypoint": "/skill-creator",
                "suggested_invocation": "/skill-creator build-automation をスキルにしてください",
                "context_file": "/tmp/handoff.json",
            },
        )

        lines = proposal_item_lines(1, candidate, include_classification=True)
        text = "\n".join(lines)

        self.assertIn("scaffold goal", text)
        self.assertIn("scaffold要点", text)
        self.assertIn("scaffold例", text)
        self.assertIn("公式 handoff", text)
        self.assertIn("/skill-creator build-automation", text)

    def test_proposal_item_lines_for_hook_include_next_step_stub(self) -> None:
        candidate = _ready_candidate(
            suggested_kind="hook",
            next_step_stub={
                "kind": "hook",
                "prompt": "「Run tests before close を hook にしてください」と次セッションで指示",
                "trigger_event": "Stop",
                "action_summary": "関連変更があるときにテスト系コマンドを自動で実行する",
            },
        )

        lines = proposal_item_lines(1, candidate, include_classification=True)
        text = "\n".join(lines)

        self.assertIn("次ステップ", text)
        self.assertIn("trigger=Stop", text)

    def test_proposal_item_lines_show_contamination_note(self) -> None:
        candidate = _ready_candidate(
            suggested_kind="skill",
            origin_hint="unknown",
            user_signal_strength="low",
            contamination_signals=["assistant_fallback", "summary_fallback"],
        )

        lines = proposal_item_lines(1, candidate, include_classification=True)
        text = "\n".join(lines)

        self.assertIn("注記:", text)
        self.assertIn("origin=unknown", text)
        self.assertIn("user_signal=low", text)
        self.assertIn("assistant_fallback", text)

    def test_research_brief_includes_internal_scaffolding_question_for_contaminated_candidate(self) -> None:
        candidate = _needs_research_candidate(
            origin_hint="unknown",
            user_signal_strength="low",
            contamination_signals=["assistant_fallback"],
            quality_flags=["low_user_signal", "origin_uncertain"],
            research_targets=[{"session_ref": "claude:test:1", "reason": "representative"}],
        )

        brief = build_research_brief(candidate)

        self.assertTrue(any("real human request" in question for question in brief["questions"]))
        self.assertTrue(any("assistant fallback" in rule for rule in brief["decision_rules"]))

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
        self.assertIn("見送り理由の傾向", markdown)
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
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["source"], "skill-miner-proposal")
            self.assertEqual(payload["summary"]["ready_count"], 1)
            self.assertIn("## 提案（固定化を推奨）", payload["markdown"])

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
                cwd=str(PROJECT_ROOT),
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
            cwd=str(PROJECT_ROOT),
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
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["summary"]["ready_count"], 0)
            self.assertEqual(payload["summary"]["needs_research_count"], 0)
            self.assertEqual(payload["summary"]["rejected_count"], 0)

    def test_cli_persists_decision_log_and_skill_creator_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepare_file = Path(temp_dir) / "prepare.json"
            decision_log = Path(temp_dir) / "decision-log.jsonl"
            handoff_dir = Path(temp_dir) / "handoffs"
            prepare_file.write_text(
                json.dumps(
                    _prepare_payload(
                        candidates=[
                            _ready_candidate(
                                suggested_kind="",
                                label="Build automation",
                                common_task_shapes=["implement_feature", "run_tests"],
                                artifact_hints=["code"],
                                rule_hints=[],
                                support={"total_packets": 3, "claude_packets": 1, "codex_packets": 2},
                            )
                        ]
                    )
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(PROPOSAL),
                    "--prepare-file",
                    str(prepare_file),
                    "--decision-log-path",
                    str(decision_log),
                    "--skill-creator-handoff-dir",
                    str(handoff_dir),
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["persistence"]["decision_log"]["status"], "persisted")
            self.assertEqual(payload["persistence"]["skill_creator_handoff"]["status"], "persisted")
            self.assertTrue(decision_log.exists())
            rows = [json.loads(line) for line in decision_log.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["record_type"], "skill_miner_decision_stub")
            self.assertEqual(rows[0]["candidate_id"], "c1")
            self.assertEqual(rows[0]["recommended_action"], "adopt")
            self.assertTrue(rows[0]["carry_forward"])
            self.assertEqual(rows[0]["decision_key"], build_candidate_decision_key(payload["ready"][0]))
            handoff_items = payload["persistence"]["skill_creator_handoff"]["items"]
            self.assertEqual(len(handoff_items), 1)
            context_file = Path(handoff_items[0]["context_file"])
            self.assertTrue(context_file.exists())
            handoff_bundle = json.loads(context_file.read_text(encoding="utf-8"))
            self.assertEqual(handoff_bundle["record_type"], "skill_creator_handoff")
            self.assertEqual(handoff_bundle["context"]["skill_name"], "build-automation")
            self.assertIn("公式 handoff:", payload["markdown"])
            self.assertNotIn(str(context_file), payload["markdown"])

    def test_persist_skill_creator_handoffs_sanitizes_timestamp_fragment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            handoff_dir = Path(temp_dir) / "handoffs"
            proposal = {
                "ready": [
                    _ready_candidate(
                        suggested_kind="skill",
                        skill_scaffold_context={
                            "skill_name": "build-automation",
                            "goal": "build automation を再利用可能なスキルとして固定化する",
                        },
                        skill_creator_handoff={
                            "tool": "skill-creator",
                            "entrypoint": "/skill-creator",
                            "suggested_invocation": "/skill-creator build-automation をスキルにしてください",
                        },
                    )
                ]
            }

            result = persist_skill_creator_handoffs(
                proposal,
                handoff_dir=handoff_dir,
                recorded_at="2026-03-18T00:00:00+09:00",
            )

            self.assertEqual(result["status"], "persisted")
            context_file = Path(result["items"][0]["context_file"])
            self.assertTrue(context_file.exists())
            self.assertEqual(context_file.name.split("-", 1)[0], "20260318T0000000900")
            self.assertNotIn("+", context_file.name)
            self.assertNotIn(":", context_file.name)

    def test_cli_applies_user_decision_overlay_before_persisting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepare_file = Path(temp_dir) / "prepare.json"
            decision_log = Path(temp_dir) / "decision-log.jsonl"
            user_decision_file = Path(temp_dir) / "user-decision.json"
            prepare_file.write_text(
                json.dumps(_prepare_payload(candidates=[_ready_candidate()])),
                encoding="utf-8",
            )
            user_decision_file.write_text(
                json.dumps(
                    {
                        "decisions": [
                            {
                                "candidate_id": "c1",
                                "user_decision": "adopt",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(PROPOSAL),
                    "--prepare-file",
                    str(prepare_file),
                    "--decision-log-path",
                    str(decision_log),
                    "--user-decision-file",
                    str(user_decision_file),
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["user_decision_overlay"]["applied"], 1)
            rows = [json.loads(line) for line in decision_log.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(rows[0]["user_decision"], "adopt")
            self.assertFalse(rows[0]["carry_forward"])


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
