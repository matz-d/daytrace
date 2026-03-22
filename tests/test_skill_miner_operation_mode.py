#!/usr/bin/env python3

from __future__ import annotations

import unittest

from conftest import PROJECT_ROOT, PLUGIN_ROOT

from skill_miner_common import (
    _build_observed_history_summary,
    _infer_skill_operation_mode,
    build_skill_creator_handoff,
)


def _infer(label: str = "", **kwargs) -> tuple[str, str]:
    defaults = {
        "task_shapes": [],
        "artifact_hints": [],
        "rule_hints": [],
        "representative_examples": [],
        "intent_trace": [],
        "evidence_summaries": [],
    }
    defaults.update(kwargs)
    return _infer_skill_operation_mode(label, **defaults)


class TestInferSkillOperationMode(unittest.TestCase):
    # --- fallback ---

    def test_empty_input_returns_maintenance_update(self) -> None:
        mode, _ = _infer()
        self.assertEqual(mode, "maintenance_update")

    # --- creation ---

    def test_creation_keyword_in_label(self) -> None:
        mode, _ = _infer("create new template")
        self.assertEqual(mode, "creation")

    def test_creation_japanese(self) -> None:
        mode, _ = _infer("新規作成 scaffold")
        self.assertEqual(mode, "creation")

    # --- maintenance_update ---

    def test_maintenance_beats_creation_when_stronger(self) -> None:
        mode, _ = _infer(
            "update existing config",
            task_shapes=["edit patch refresh"],
        )
        self.assertEqual(mode, "maintenance_update")

    def test_maintenance_japanese(self) -> None:
        mode, _ = _infer("既存設定を更新して修正する")
        self.assertEqual(mode, "maintenance_update")

    def test_maintenance_vs_creation_equal_count_favors_neither(self) -> None:
        # "create" (1 creation) + "update" (1 maintenance) → maintenance > creation is False, fallback
        # Actually: creation_hits=1, maintenance_hits=1, maintenance > creation is False
        # Next: aggregate=0, verify=0, investigate=0, creation_hits>0 → creation
        mode, _ = _infer("create update")
        self.assertEqual(mode, "creation")

    # --- backfill ---

    def test_backfill_keyword(self) -> None:
        mode, _ = _infer("backfill missing coverage")
        self.assertEqual(mode, "backfill_gap_fill")

    def test_backfill_japanese(self) -> None:
        mode, _ = _infer("欠損データを補完する")
        self.assertEqual(mode, "backfill_gap_fill")

    # --- aggregation ---

    def test_aggregation_keyword(self) -> None:
        mode, _ = _infer("aggregate daily report summary")
        self.assertEqual(mode, "aggregation")

    def test_aggregation_japanese(self) -> None:
        mode, _ = _infer("週次の集約レポート")
        self.assertEqual(mode, "aggregation")

    # --- verification ---

    def test_verification_aggregate_plus_verify(self) -> None:
        mode, _ = _infer("validate collected report summary")
        self.assertEqual(mode, "verification")

    def test_verification_japanese(self) -> None:
        mode, _ = _infer("集計結果を検証する")
        self.assertEqual(mode, "verification")

    # --- investigation ---

    def test_investigation_keyword(self) -> None:
        mode, _ = _infer("investigate the root cause", intent_trace=["analyze logs"])
        self.assertEqual(mode, "investigation")

    def test_investigation_japanese(self) -> None:
        mode, _ = _infer("原因を調査して分析する")
        self.assertEqual(mode, "investigation")

    def test_investigation_blocked_by_maintenance(self) -> None:
        # investigate + maintenance → maintenance wins (investigate requires maintenance==0)
        mode, _ = _infer("investigate and update existing config")
        self.assertNotEqual(mode, "investigation")

    # --- workflow_orchestration ---

    def test_workflow_backfill_plus_aggregate(self) -> None:
        mode, _ = _infer("backfill missing data then aggregate report")
        self.assertEqual(mode, "workflow_orchestration")

    def test_workflow_high_flow_hits(self) -> None:
        mode, _ = _infer("workflow: step1 then step2 after completion")
        self.assertEqual(mode, "workflow_orchestration")

    def test_workflow_three_categories_active(self) -> None:
        # maintenance + backfill + verify → 3 categories → workflow
        mode, _ = _infer("update missing items and verify coverage")
        self.assertEqual(mode, "workflow_orchestration")

    def test_workflow_japanese(self) -> None:
        mode, _ = _infer("不足を埋めてから集約する")
        self.assertEqual(mode, "workflow_orchestration")

    # --- signals from non-label fields ---

    def test_signals_from_task_shapes(self) -> None:
        mode, _ = _infer("generic task", task_shapes=["backfill gap data"])
        self.assertEqual(mode, "backfill_gap_fill")

    def test_signals_from_evidence_summaries(self) -> None:
        mode, _ = _infer(
            "generic task",
            evidence_summaries=["report summary collected weekly"],
        )
        self.assertEqual(mode, "aggregation")

    def test_signals_from_intent_trace(self) -> None:
        mode, _ = _infer("generic task", intent_trace=["explore and research this area"])
        self.assertEqual(mode, "investigation")

    # --- return type ---

    def test_returns_tuple_with_reason(self) -> None:
        result = _infer("create new scaffold")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], str)
        self.assertIsInstance(result[1], str)
        self.assertTrue(len(result[1]) > 0)

    # --- ASCII word boundaries (avoid substring false positives) ---

    def test_renewal_does_not_count_as_new_creation(self) -> None:
        mode, _ = _infer("renewal contract paperwork")
        self.assertEqual(mode, "maintenance_update")

    def test_news_does_not_count_as_new_creation(self) -> None:
        mode, _ = _infer("publish weekly news digest")
        self.assertEqual(mode, "maintenance_update")

    def test_newton_does_not_count_as_new_creation(self) -> None:
        mode, _ = _infer("newton method convergence")
        self.assertEqual(mode, "maintenance_update")

    def test_editor_does_not_count_as_edit_maintenance(self) -> None:
        mode, _ = _infer("open file in vscode editor")
        self.assertEqual(mode, "maintenance_update")

    def test_checkout_does_not_count_as_check_verification(self) -> None:
        mode, _ = _infer("git checkout feature branch")
        self.assertEqual(mode, "maintenance_update")

    def test_standalone_edit_still_maintenance(self) -> None:
        mode, _ = _infer("edit the config file")
        self.assertEqual(mode, "maintenance_update")

    def test_standalone_check_still_verification_signal_with_aggregate(self) -> None:
        mode, _ = _infer("check report summary after collect")
        self.assertEqual(mode, "verification")

    def test_standalone_new_still_creation(self) -> None:
        mode, _ = _infer("add brand new module")
        self.assertEqual(mode, "creation")


class TestBuildSkillCreatorHandoffCoercion(unittest.TestCase):
    def test_observation_count_accepts_numeric_string(self) -> None:
        handoff = build_skill_creator_handoff(
            {
                "skill_name": "x",
                "goal": "g",
                "observation_count": "12",
                "source_diversity": "2",
            }
        )
        self.assertIn("observations=12", handoff["prompt"])

    def test_observation_count_invalid_string_defaults_zero(self) -> None:
        handoff = build_skill_creator_handoff(
            {
                "skill_name": "x",
                "goal": "g",
                "observation_count": "nope",
                "source_diversity": None,
            }
        )
        self.assertIn("observations=0", handoff["prompt"])
        self.assertIn("source_diversity=0", handoff["prompt"])


class TestBuildObservedHistorySummary(unittest.TestCase):
    def test_empty_input(self) -> None:
        result = _build_observed_history_summary(
            representative_examples=[],
            evidence_summaries=[],
            observation_count=0,
            source_diversity=0,
        )
        self.assertEqual(result, [])

    def test_observation_count_only(self) -> None:
        result = _build_observed_history_summary(
            representative_examples=[],
            evidence_summaries=[],
            observation_count=5,
            source_diversity=0,
        )
        self.assertEqual(result, ["観測件数: 5"])

    def test_source_diversity_only(self) -> None:
        result = _build_observed_history_summary(
            representative_examples=[],
            evidence_summaries=[],
            observation_count=0,
            source_diversity=2,
        )
        self.assertEqual(result, ["観測ソース種別数: 2"])

    def test_full_output(self) -> None:
        result = _build_observed_history_summary(
            representative_examples=["example one", "example two"],
            evidence_summaries=["summary one"],
            observation_count=10,
            source_diversity=2,
        )
        self.assertEqual(len(result), 5)
        self.assertEqual(result[0], "観測件数: 10")
        self.assertEqual(result[1], "観測ソース種別数: 2")
        self.assertTrue(result[2].startswith("代表例: "))
        self.assertTrue(result[3].startswith("代表例: "))
        self.assertTrue(result[4].startswith("履歴要約: "))

    def test_truncates_examples_to_two(self) -> None:
        result = _build_observed_history_summary(
            representative_examples=["a", "b", "c", "d"],
            evidence_summaries=[],
            observation_count=0,
            source_diversity=0,
        )
        example_lines = [line for line in result if line.startswith("代表例: ")]
        self.assertEqual(len(example_lines), 2)

    def test_truncates_summaries_to_two(self) -> None:
        result = _build_observed_history_summary(
            representative_examples=[],
            evidence_summaries=["s1", "s2", "s3"],
            observation_count=0,
            source_diversity=0,
        )
        summary_lines = [line for line in result if line.startswith("履歴要約: ")]
        self.assertEqual(len(summary_lines), 2)

    def test_skips_blank_examples(self) -> None:
        # Slice [:2] is applied first, so blanks at index 0-1 are taken and
        # filtered out by summarize_text; "valid" at index 2 is outside the slice.
        result = _build_observed_history_summary(
            representative_examples=["", "  ", "valid example"],
            evidence_summaries=[],
            observation_count=0,
            source_diversity=0,
        )
        example_lines = [line for line in result if line.startswith("代表例: ")]
        self.assertEqual(len(example_lines), 0)

    def test_blank_then_valid_within_slice(self) -> None:
        result = _build_observed_history_summary(
            representative_examples=["valid example", "  "],
            evidence_summaries=[],
            observation_count=0,
            source_diversity=0,
        )
        example_lines = [line for line in result if line.startswith("代表例: ")]
        self.assertEqual(len(example_lines), 1)
        self.assertIn("valid example", example_lines[0])


if __name__ == "__main__":
    unittest.main()
