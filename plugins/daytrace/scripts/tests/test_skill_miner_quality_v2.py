#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from skill_miner_common import (
    apply_claude_md_immediate_rules,
    build_claude_md_immediate_apply_preview,
    build_proposal_sections,
    clean_user_message_text,
    compare_iso_timestamps,
    infer_task_shapes,
    infer_repeated_rules,
    judge_research_candidate,
    merge_judgment_into_candidate,
    stable_block_keys,
)
from skill_miner_prepare import (
    SIMILARITY_ARTIFACT_WEIGHT,
    SIMILARITY_WEIGHT_BUDGET,
    SIMILARITY_INTENT_WEIGHT,
    SIMILARITY_RULE_WEIGHT,
    SIMILARITY_SNIPPET_WEIGHT,
    SIMILARITY_SPECIFIC_SHAPE_BONUS,
    SIMILARITY_TASK_SHAPES_WEIGHT,
    SIMILARITY_TOOL_WEIGHT,
    SIMILARITY_WEIGHT_TOTAL,
    _build_similarity_features,
    _similarity_score_from_features,
    UnionFind,
    cluster_packets,
    similarity_score,
)


def make_packet(
    packet_id: str,
    *,
    primary_intent: str,
    snippets: list[str],
    task_shape: list[str],
    artifact_hints: list[str],
    repeated_rules: list[str],
    top_tool: str = "rg",
    tool_signature: list[str] | None = None,
    timestamp: str = "2026-03-09T00:00:00+09:00",
) -> dict[str, object]:
    return {
        "packet_version": 2,
        "packet_id": packet_id,
        "source": "codex-history",
        "session_ref": f"codex:{packet_id}:1",
        "session_id": packet_id,
        "workspace": "/tmp/workspace",
        "timestamp": timestamp,
        "top_tool": top_tool,
        "tool_signature": tool_signature or [top_tool, "sed"],
        "task_shape": task_shape,
        "artifact_hints": artifact_hints,
        "primary_intent": primary_intent,
        "full_user_intent": primary_intent,
        "primary_intent_source": "raw_user_message",
        "representative_snippets": snippets,
        "user_repeated_rules": [{"normalized": value, "raw_snippet": value} for value in repeated_rules],
        "assistant_repeated_rules": [],
        "repeated_rules": [{"normalized": value, "raw_snippet": value} for value in repeated_rules],
        "support": {"message_count": 4, "tool_call_count": len(tool_signature or [top_tool, "sed"])},
    }


def build_quality_metrics(candidates: list[dict[str, object]], unclustered: list[dict[str, object]]) -> dict[str, float]:
    oversized = sum(1 for candidate in candidates if "oversized_cluster" in candidate.get("quality_flags", []))
    proposal_ready = sum(1 for candidate in candidates if candidate.get("proposal_ready"))
    return {
        "oversized_cluster_rate": round(oversized / len(candidates), 3) if candidates else 0.0,
        "proposal_ready_count": float(proposal_ready),
        "zero_rate": 1.0 if proposal_ready == 0 else 0.0,
        "unclustered_count": float(len(unclustered)),
    }


def legacy_stable_block_keys(packet: dict[str, object]) -> list[str]:
    keys: list[str] = []
    top_tool = str(packet.get("top_tool") or "none")
    task_shapes = packet.get("task_shape") or []
    first_shape = str(task_shapes[0]) if task_shapes else "none"
    if top_tool != "none":
        keys.append(f"tool:{top_tool}")
    if first_shape != "none":
        keys.append(f"task:{first_shape}")
    if not keys:
        keys.append("misc")
    return keys


def legacy_similarity_score(left: dict[str, object], right: dict[str, object]) -> float:
    from skill_miner_common import compact_snippet, jaccard_score, overlap_score, tokenize

    left_tokens = set().union(*(tokenize(compact_snippet(item, left.get("workspace"))) for item in left.get("representative_snippets", [])))
    right_tokens = set().union(*(tokenize(compact_snippet(item, right.get("workspace"))) for item in right.get("representative_snippets", [])))
    snippet = jaccard_score(left_tokens, right_tokens)
    task_shapes = overlap_score(set(left.get("task_shape", [])), set(right.get("task_shape", [])))
    tools = jaccard_score(set(left.get("tool_signature", [])), set(right.get("tool_signature", [])))
    artifacts = overlap_score(set(left.get("artifact_hints", [])), set(right.get("artifact_hints", [])))
    rules = overlap_score(
        {item.get("normalized") for item in left.get("repeated_rules", [])},
        {item.get("normalized") for item in right.get("repeated_rules", [])},
    )
    return round((task_shapes * 0.40) + (snippet * 0.15) + (tools * 0.05) + (artifacts * 0.15) + (rules * 0.25), 3)


def legacy_cluster_packets(packets: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    from collections import defaultdict

    sorted_packets = sorted(packets, key=lambda packet: (str(packet.get("timestamp") or ""), str(packet.get("packet_id") or "")), reverse=True)
    blocks: dict[str, list[int]] = defaultdict(list)
    for index, packet in enumerate(sorted_packets):
        for key in legacy_stable_block_keys(packet):
            blocks[key].append(index)

    union_find = UnionFind(len(sorted_packets))
    seen_pairs: set[tuple[int, int]] = set()
    for block_indexes in blocks.values():
        for offset, left_index in enumerate(block_indexes):
            for right_index in block_indexes[offset + 1 :]:
                pair = (min(left_index, right_index), max(left_index, right_index))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                if legacy_similarity_score(sorted_packets[left_index], sorted_packets[right_index]) >= 0.60:
                    union_find.union(left_index, right_index)

    groups: dict[int, list[dict[str, object]]] = defaultdict(list)
    for index, packet in enumerate(sorted_packets):
        groups[union_find.find(index)].append(packet)

    candidates: list[dict[str, object]] = []
    unclustered: list[dict[str, object]] = []
    total_packets_all = len(sorted_packets)
    from skill_miner_common import build_candidate_quality

    for packets_in_group in groups.values():
        if len(packets_in_group) == 1:
            unclustered.append(packets_in_group[0])
            continue
        candidate = {
            "label": str(packets_in_group[0].get("packet_id")),
            "support": {
                "total_packets": len(packets_in_group),
                "claude_packets": 0,
                "codex_packets": len(packets_in_group),
                "recent_packets_7d": len(packets_in_group),
            },
            "common_task_shapes": list(packets_in_group[0].get("task_shape", [])),
            "common_tool_signatures": list(packets_in_group[0].get("tool_signature", [])),
            "artifact_hints": list(packets_in_group[0].get("artifact_hints", [])),
            "rule_hints": [item["normalized"] for item in packets_in_group[0].get("repeated_rules", [])],
            "representative_examples": [str(packet.get("primary_intent") or "") for packet in packets_in_group[:2]],
        }
        candidate.update(build_candidate_quality(candidate, total_packets_all=total_packets_all))
        candidates.append(candidate)
    return candidates, unclustered


class SkillMinerQualityV2Tests(unittest.TestCase):
    def test_similarity_score_weight_budget_matches_v2_targets(self) -> None:
        self.assertEqual(
            SIMILARITY_WEIGHT_BUDGET,
            {
                "task_shapes": 0.22,
                "specific_shape_bonus": 0.08,
                "intent": 0.15,
                "snippet": 0.10,
                "artifacts": 0.20,
                "rules": 0.20,
                "tools": 0.05,
            },
        )
        self.assertAlmostEqual(SIMILARITY_TASK_SHAPES_WEIGHT + SIMILARITY_SPECIFIC_SHAPE_BONUS, 0.30)
        self.assertAlmostEqual(SIMILARITY_INTENT_WEIGHT + SIMILARITY_SNIPPET_WEIGHT, 0.25)
        self.assertAlmostEqual(SIMILARITY_ARTIFACT_WEIGHT, 0.20)
        self.assertAlmostEqual(SIMILARITY_RULE_WEIGHT, 0.20)
        self.assertAlmostEqual(SIMILARITY_TOOL_WEIGHT, 0.05)
        self.assertAlmostEqual(SIMILARITY_WEIGHT_TOTAL, 1.0)

    def test_infer_task_shapes_prioritizes_specific_over_generic(self) -> None:
        shapes = infer_task_shapes(
            ["Implement a feature, update config, run tests, then inspect files and summarize findings."],
            ["pytest", "rg", "sed"],
        )

        self.assertEqual(shapes[:3], ["implement_feature", "edit_config", "run_tests"])

    def test_clean_user_message_text_keeps_command_args_and_request_body(self) -> None:
        cleaned = clean_user_message_text(
            "<command-name>/daily-report</command-name> <command-message>daily-report</command-message> "
            "<command-args>今日の日報を作成して</command-args>\n"
            "# Files mentioned by the user:\n## README.md: /tmp/workspace/README.md\n## My request for Codex:\n方向性を整理して"
        )

        self.assertIn("今日の日報を作成して", cleaned)
        self.assertIn("方向性を整理して", cleaned)
        self.assertNotIn("Files mentioned by the user", cleaned)
        self.assertNotIn("/daily-report", cleaned)

    def test_infer_repeated_rules_requires_two_distinct_user_messages(self) -> None:
        self.assertEqual(
            infer_repeated_rules(
                ["Review this PR and keep findings first."],
                "/tmp/workspace",
                role="user",
            ),
            [],
        )

        repeated = infer_repeated_rules(
            [
                "Review this PR and keep findings first.",
                "Review another PR and keep findings-first format.",
            ],
            "/tmp/workspace",
            role="user",
        )

        self.assertEqual([item["normalized"] for item in repeated], ["findings-first"])

    def test_infer_repeated_rules_matches_always_and_never_imperatives(self) -> None:
        repeated = infer_repeated_rules(
            [
                "Always include file and line references in the final review.",
                "Always include a short rationale after each finding.",
                "Never rewrite unrelated files during review.",
                "Never change formatting outside the touched hunk.",
            ],
            "/tmp/workspace",
            role="user",
        )

        self.assertEqual([item["normalized"] for item in repeated], ["always-do", "never-do"])

    def test_same_findings_format_is_classified_as_findings_first(self) -> None:
        repeated = infer_repeated_rules(
            [
                "Review this PR and keep the same findings format.",
                "Review another PR and keep the same findings format.",
            ],
            "/tmp/workspace",
            role="user",
        )

        self.assertEqual([item["normalized"] for item in repeated], ["findings-first"])

    def test_stable_block_keys_adds_composites_before_generic_tool_block(self) -> None:
        packet = make_packet(
            "pkt-composite",
            primary_intent="Review config changes and keep findings-first output.",
            snippets=["Review config changes and keep findings-first output."],
            task_shape=["review_changes", "inspect_files"],
            artifact_hints=["config"],
            repeated_rules=["findings-first"],
        )

        keys = stable_block_keys(packet)

        self.assertIn("task+artifact:review_changes:config", keys)
        self.assertIn("task+rule:review_changes:findings-first", keys)
        self.assertIn("artifact+rule:config:findings-first", keys)
        self.assertNotIn("tool:rg", keys)

    def test_similarity_score_weakens_generic_cluster_entry(self) -> None:
        left = make_packet(
            "pkt-left",
            primary_intent="Review the API change and list findings by severity.",
            snippets=["Review the API change and list findings by severity."],
            task_shape=["review_changes", "search_code"],
            artifact_hints=["review"],
            repeated_rules=["findings-first"],
        )
        right = make_packet(
            "pkt-right",
            primary_intent="Review the release note and keep the same findings-first format.",
            snippets=["Review the release note and keep the same findings-first format."],
            task_shape=["review_changes", "search_code"],
            artifact_hints=["markdown"],
            repeated_rules=["findings-first"],
        )

        self.assertLess(similarity_score(left, right), 0.60)
        self.assertGreaterEqual(legacy_similarity_score(left, right), 0.60)

    def test_similarity_feature_path_matches_public_wrapper(self) -> None:
        left = make_packet(
            "pkt-feature-left",
            primary_intent="Implement config sync and update /tmp/workspace/app/config.yaml safely.",
            snippets=["Implement config sync in /tmp/workspace/app/config.yaml and keep rollback notes."],
            task_shape=["implement_feature", "edit_config"],
            artifact_hints=["config"],
            repeated_rules=["tests-before-close"],
            top_tool="python3",
            tool_signature=["python3", "pytest"],
        )
        right = make_packet(
            "pkt-feature-right",
            primary_intent="Implement config sync and update /tmp/workspace/app/settings.yaml with tests.",
            snippets=["Implement config sync in /tmp/workspace/app/settings.yaml and keep rollback notes."],
            task_shape=["implement_feature", "edit_config"],
            artifact_hints=["config"],
            repeated_rules=["tests-before-close"],
            top_tool="python3",
            tool_signature=["python3", "pytest"],
        )

        wrapper_score = similarity_score(left, right)
        feature_score = _similarity_score_from_features(
            _build_similarity_features(left),
            _build_similarity_features(right),
        )

        self.assertEqual(feature_score, wrapper_score)

    def test_similarity_feature_path_matches_generic_only_penalty_case(self) -> None:
        left = make_packet(
            "pkt-generic-left",
            primary_intent="Review the change and summarize findings.",
            snippets=["Review the change and summarize findings."],
            task_shape=["review_changes", "search_code"],
            artifact_hints=[],
            repeated_rules=[],
            tool_signature=["rg", "read", "sed"],
        )
        right = make_packet(
            "pkt-generic-right",
            primary_intent="Review the diff and summarize findings.",
            snippets=["Review the diff and summarize findings."],
            task_shape=["review_changes", "inspect_files"],
            artifact_hints=[],
            repeated_rules=[],
            tool_signature=["rg", "read", "sed"],
        )

        left_features = _build_similarity_features(left)
        right_features = _build_similarity_features(right)

        self.assertTrue(left_features["generic_task_only"])
        self.assertTrue(right_features["generic_task_only"])
        self.assertTrue(left_features["generic_tool_only"])
        self.assertTrue(right_features["generic_tool_only"])
        self.assertEqual(
            _similarity_score_from_features(left_features, right_features),
            similarity_score(left, right),
        )

    def test_similarity_primary_artifact_match_stays_within_artifact_weight(self) -> None:
        left_features = {
            "snippet_tokens": set(),
            "intent_tokens": set(),
            "task_shape_set": set(),
            "tool_set": set(),
            "artifact_set": {"config"},
            "primary_artifact": "config",
            "rule_names": set(),
            "primary_non_generic_shape": "",
            "generic_task_only": False,
            "generic_tool_only": False,
        }
        right_features = {
            "snippet_tokens": set(),
            "intent_tokens": set(),
            "task_shape_set": set(),
            "tool_set": set(),
            "artifact_set": {"config"},
            "primary_artifact": "config",
            "rule_names": set(),
            "primary_non_generic_shape": "",
            "generic_task_only": False,
            "generic_tool_only": False,
        }

        self.assertEqual(
            _similarity_score_from_features(left_features, right_features),
            round(SIMILARITY_ARTIFACT_WEIGHT, 3),
        )

    def test_similarity_score_title_match_only_stays_within_intent_budget(self) -> None:
        left = {
            "workspace": "/tmp/workspace",
            "primary_intent": "Draft the fake skill proposal summary",
            "representative_snippets": [],
            "task_shape": [],
            "artifact_hints": [],
            "repeated_rules": [],
            "tool_signature": [],
        }
        right = {
            "workspace": "/tmp/workspace",
            "primary_intent": "Draft the fake skill proposal summary",
            "representative_snippets": [],
            "task_shape": [],
            "artifact_hints": [],
            "repeated_rules": [],
            "tool_signature": [],
        }

        self.assertEqual(similarity_score(left, right), round(SIMILARITY_INTENT_WEIGHT, 3))

    def test_similarity_score_path_match_only_stays_within_snippet_budget(self) -> None:
        left = {
            "workspace": "/tmp/workspace",
            "primary_intent": "",
            "representative_snippets": ["Inspect /tmp/workspace/fake_skills/demo_alpha.py"],
            "task_shape": [],
            "artifact_hints": [],
            "repeated_rules": [],
            "tool_signature": [],
        }
        right = {
            "workspace": "/tmp/workspace",
            "primary_intent": "",
            "representative_snippets": ["Inspect /tmp/workspace/fake_skills/demo_alpha.py"],
            "task_shape": [],
            "artifact_hints": [],
            "repeated_rules": [],
            "tool_signature": [],
        }

        self.assertEqual(similarity_score(left, right), round(SIMILARITY_SNIPPET_WEIGHT, 3))

    def test_similarity_score_full_match_is_clamped_to_one(self) -> None:
        packet = {
            "workspace": "/tmp/workspace",
            "primary_intent": "Implement the fake skill sync flow",
            "representative_snippets": ["Implement /tmp/workspace/fake_skills/sync_flow.py and keep fake tests green."],
            "task_shape": ["implement_feature", "run_tests"],
            "artifact_hints": ["code", "config"],
            "repeated_rules": [{"normalized": "tests-before-close", "raw_snippet": "tests-before-close"}],
            "tool_signature": ["python3", "pytest"],
        }

        self.assertEqual(similarity_score(packet, packet), 1.0)

    def test_similarity_score_full_mismatch_is_clamped_to_zero(self) -> None:
        left = {
            "workspace": None,
            "primary_intent": "nebula lattice zircon",
            "representative_snippets": ["aurora_quartz_v1"],
            "task_shape": ["implement_feature"],
            "artifact_hints": ["code"],
            "repeated_rules": [{"normalized": "tests-before-close", "raw_snippet": "tests-before-close"}],
            "tool_signature": ["python3", "pytest"],
        }
        right = {
            "workspace": None,
            "primary_intent": "saffron monolith cinder",
            "representative_snippets": ["umbra_helix_v9"],
            "task_shape": ["prepare_report"],
            "artifact_hints": ["markdown"],
            "repeated_rules": [{"normalized": "findings-first", "raw_snippet": "findings-first"}],
            "tool_signature": ["rg", "sed"],
        }

        self.assertEqual(similarity_score(left, right), 0.0)

    def test_compare_iso_timestamps_and_recent_count_respect_actual_time(self) -> None:
        packets = [
            make_packet(
                "pkt-older-boundary",
                primary_intent="Review API change and list findings by severity.",
                snippets=["Review API change and list findings by severity."],
                task_shape=["review_changes", "search_code"],
                artifact_hints=["review"],
                repeated_rules=["findings-first"],
                timestamp="2026-03-02T18:00:00+00:00",
            ),
            make_packet(
                "pkt-lexically-latest",
                primary_intent="Review release note and list findings by severity.",
                snippets=["Review release note and list findings by severity."],
                task_shape=["review_changes", "search_code"],
                artifact_hints=["review"],
                repeated_rules=["findings-first"],
                timestamp="2026-03-10T00:30:00+09:00",
            ),
            make_packet(
                "pkt-actual-latest",
                primary_intent="Review server diff and list findings by severity.",
                snippets=["Review server diff and list findings by severity."],
                task_shape=["review_changes", "search_code"],
                artifact_hints=["review"],
                repeated_rules=["findings-first"],
                timestamp="2026-03-09T23:45:00+00:00",
            ),
        ]

        ordered = sorted([packet["timestamp"] for packet in packets], key=compare_iso_timestamps, reverse=True)
        self.assertEqual(ordered[0], "2026-03-09T23:45:00+00:00")

        candidates, unclustered, _stats = cluster_packets(packets)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(unclustered, [])
        self.assertEqual(candidates[0]["support"]["recent_packets_7d"], 2)

    def test_oversized_cluster_goes_split_first_and_stays_needs_research(self) -> None:
        candidate = {
            "candidate_id": "cand-oversized",
            "label": "review changes (review, markdown)",
            "quality_flags": ["oversized_cluster", "generic_task_shape", "generic_tools"],
            "triage_status": "needs_research",
            "confidence": "weak",
            "proposal_ready": False,
        }
        details = [
            {
                "session_ref": "codex:r1:1",
                "messages": [
                    {"role": "user", "text": "Implement the API endpoint and add tests."},
                    {"role": "assistant", "text": "I will implement the feature and run tests before closing."},
                ],
                "tool_calls": [{"name": "python3", "count": 1}, {"name": "pytest", "count": 1}],
            },
            {
                "session_ref": "codex:r2:2",
                "messages": [
                    {"role": "user", "text": "Implement another CLI flag and add tests."},
                    {"role": "assistant", "text": "I will implement the feature and keep tests before close."},
                ],
                "tool_calls": [{"name": "python3", "count": 1}, {"name": "pytest", "count": 1}],
            },
            {
                "session_ref": "codex:r3:3",
                "messages": [
                    {"role": "user", "text": "Prepare the weekly status report draft in markdown."},
                    {"role": "assistant", "text": "I will prepare the report draft and write the markdown summary."},
                ],
                "tool_calls": [{"name": "python3", "count": 1}],
            },
            {
                "session_ref": "codex:r4:4",
                "messages": [
                    {"role": "user", "text": "Prepare another status report draft in markdown."},
                    {"role": "assistant", "text": "I will prepare the report draft and write the markdown summary."},
                ],
                "tool_calls": [{"name": "python3", "count": 1}],
            },
        ]

        judgment = judge_research_candidate(candidate, details)
        merged = merge_judgment_into_candidate(candidate, {"judgment": judgment})

        self.assertEqual(judgment["recommendation"], "split_candidate")
        self.assertEqual(set(judgment["split_suggestions"]), {"implement_feature", "prepare_report"})
        self.assertEqual(
            {item["split_label"]: item["triage_status"] for item in judgment["subcluster_triage"]},
            {"implement_feature": "ready", "prepare_report": "ready"},
        )
        self.assertEqual(merged["triage_status"], "needs_research")
        self.assertFalse(merged["proposal_ready"])

    def test_judge_can_recover_needs_research_candidate_to_ready(self) -> None:
        candidate = {
            "candidate_id": "cand-recover",
            "label": "review changes (review, code)",
            "quality_flags": ["oversized_cluster"],
            "triage_status": "needs_research",
            "confidence": "weak",
            "proposal_ready": False,
        }
        details = [
            {
                "session_ref": "codex:a:1",
                "messages": [
                    {"role": "user", "text": "Review this PR and return findings by severity."},
                    {"role": "assistant", "text": "I will inspect the diff and list findings first with line refs."},
                ],
                "tool_calls": [{"name": "rg", "count": 2}, {"name": "git", "count": 1}],
            },
            {
                "session_ref": "codex:b:2",
                "messages": [
                    {"role": "user", "text": "Review another PR and keep the findings-first format."},
                    {"role": "assistant", "text": "I will inspect files and list findings first with file-line refs."},
                ],
                "tool_calls": [{"name": "rg", "count": 1}, {"name": "git", "count": 1}],
            },
        ]

        judgment = judge_research_candidate(candidate, details)
        merged = merge_judgment_into_candidate(candidate, {"judgment": judgment})

        self.assertEqual(judgment["recommendation"], "promote_ready")
        self.assertEqual(merged["triage_status"], "ready")
        self.assertTrue(merged["proposal_ready"])

    def test_judge_ignores_unrelated_details_when_candidate_refs_are_known(self) -> None:
        candidate = {
            "candidate_id": "cand-review",
            "label": "review changes (review, code)",
            "session_refs": ["codex:a:1", "codex:b:2"],
            "quality_flags": ["oversized_cluster"],
            "triage_status": "needs_research",
            "confidence": "weak",
            "proposal_ready": False,
        }
        details = [
            {
                "session_ref": "codex:a:1",
                "messages": [
                    {"role": "user", "text": "Review this PR and return findings by severity."},
                    {"role": "assistant", "text": "I will inspect the diff and list findings first with line refs."},
                ],
                "tool_calls": [{"name": "rg", "count": 2}, {"name": "git", "count": 1}],
            },
            {
                "session_ref": "codex:b:2",
                "messages": [
                    {"role": "user", "text": "Review another PR and keep the findings-first format."},
                    {"role": "assistant", "text": "I will inspect files and list findings first with file-line refs."},
                ],
                "tool_calls": [{"name": "rg", "count": 1}, {"name": "git", "count": 1}],
            },
            {
                "session_ref": "codex:other:9",
                "messages": [
                    {"role": "user", "text": "Prepare the weekly status report draft in markdown."},
                    {"role": "assistant", "text": "I will prepare the report draft and write the markdown summary."},
                ],
                "tool_calls": [{"name": "python3", "count": 1}],
            },
            {
                "session_ref": "codex:other:10",
                "messages": [
                    {"role": "user", "text": "Prepare another status report draft in markdown."},
                    {"role": "assistant", "text": "I will prepare the report draft and write the markdown summary."},
                ],
                "tool_calls": [{"name": "python3", "count": 1}],
            },
        ]

        judgment = judge_research_candidate(candidate, details)

        self.assertEqual(judgment["recommendation"], "promote_ready")
        self.assertEqual(judgment["proposed_triage_status"], "ready")
        self.assertEqual(len(judgment["detail_signals"]), 2)

    def test_judge_rejects_low_overlap_before_split_when_rules_absent(self) -> None:
        candidate = {
            "candidate_id": "cand-low-overlap",
            "label": "mixed objectives",
            "quality_flags": [],
            "triage_status": "needs_research",
            "confidence": "weak",
            "proposal_ready": False,
        }
        details = [
            {
                "session_ref": "codex:a:1",
                "messages": [
                    {"role": "user", "text": "Review PR quasar-lambda and list findings."},
                    {"role": "assistant", "text": "I will inspect the diff and summarize findings."},
                ],
                "tool_calls": [{"name": "rg", "count": 1}],
            },
            {
                "session_ref": "codex:b:2",
                "messages": [
                    {"role": "user", "text": "Prepare weekly report for nebula metrics."},
                    {"role": "assistant", "text": "I will draft the report in markdown."},
                ],
                "tool_calls": [{"name": "python3", "count": 1}],
            },
        ]

        judgment = judge_research_candidate(candidate, details)

        self.assertEqual(judgment["recommendation"], "reject_candidate")
        self.assertEqual(judgment["proposed_triage_status"], "rejected")
        self.assertEqual(judgment["proposed_confidence"], "insufficient")

    def test_promote_ready_refreshes_evidence_summary_for_final_proposal(self) -> None:
        candidate = {
            "candidate_id": "cand-ready",
            "label": "review flow",
            "triage_status": "needs_research",
            "confidence": "weak",
            "proposal_ready": False,
            "evidence_summary": "8 packets / flags: oversized_cluster, weak_semantic_cohesion",
            "confidence_reason": "Need more detail before promotion.",
            "quality_flags": ["oversized_cluster", "weak_semantic_cohesion"],
            "suggested_kind": "skill",
            "evidence_items": [],
        }
        judgment = {
            "judgment": {
                "recommendation": "promote_ready",
                "proposed_triage_status": "ready",
                "proposed_confidence": "strong",
                "summary": "recommendation=promote_ready / sampled_refs=2 / primary_shapes=review_changes / avg_overlap=0.22",
            }
        }

        merged = merge_judgment_into_candidate(candidate, judgment)
        sections = build_proposal_sections({"candidates": [candidate], "unclustered": []}, {"cand-ready": judgment})

        self.assertEqual(
            merged["evidence_summary"],
            "recommendation=promote_ready / sampled_refs=2 / primary_shapes=review_changes / avg_overlap=0.22",
        )
        self.assertIn("recommendation=promote_ready / sampled_refs=2", sections["markdown"])
        self.assertNotIn("flags: oversized_cluster", sections["markdown"])

    def test_claude_md_immediate_apply_handles_missing_duplicate_and_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            missing = build_claude_md_immediate_apply_preview(root, ["Use pytest for verification."])
            self.assertEqual(missing["status"], "ready_to_apply")
            self.assertTrue(missing["missing_file"])
            self.assertIn("## DayTrace Suggested Rules", missing["preview"])
            applied_missing = apply_claude_md_immediate_rules(root, ["Use pytest for verification."])
            self.assertEqual(applied_missing["status"], "applied")
            self.assertTrue((root / "CLAUDE.md").exists())

            claude_md = root / "CLAUDE.md"
            claude_md.write_text(
                "# Repo Rules\n\n## DayTrace Suggested Rules\n\n- Use pytest for verification.\n- Keep findings first.\n",
                encoding="utf-8",
            )

            near_duplicate = build_claude_md_immediate_apply_preview(root, ["Use pytest verification."])
            self.assertEqual(near_duplicate["status"], "duplicate")

            same_direction_duplicate = build_claude_md_immediate_apply_preview(root, ["Always use pytest for verification."])
            self.assertEqual(same_direction_duplicate["status"], "duplicate")

            duplicate = build_claude_md_immediate_apply_preview(root, ["Use pytest for verification."])
            self.assertEqual(duplicate["status"], "duplicate")

            conflict = build_claude_md_immediate_apply_preview(root, ["Never use pytest for verification."])
            self.assertEqual(conflict["status"], "conflict")
            self.assertIn("- Never use pytest for verification.", conflict["preview"])

    def test_claude_md_immediate_apply_detects_conflicts_within_proposed_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            preview = build_claude_md_immediate_apply_preview(
                root,
                ["Use pytest for verification.", "Never use pytest for verification."],
            )

            self.assertEqual(preview["status"], "conflict")
            self.assertEqual(
                preview["conflicts"],
                [{"existing": "- Use pytest for verification.", "proposed": "- Never use pytest for verification."}],
            )

    def test_claude_md_immediate_apply_appends_only_to_daytrace_section_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            claude_md = root / "CLAUDE.md"
            claude_md.write_text(
                "# Repo Rules\n\n## DayTrace Suggested Rules\n\n- Keep findings first.\n\n## Other Section\n\nStay concise.\n",
                encoding="utf-8",
            )

            result = apply_claude_md_immediate_rules(root, ["Use pytest for verification."])
            updated = claude_md.read_text(encoding="utf-8")

            self.assertEqual(result["status"], "applied")
            self.assertIn("- Use pytest for verification.\n## Other Section", updated)
            self.assertNotIn("Stay concise.\n- Use pytest", updated)

    def test_proposal_zero_ready_and_evidence_items_passthrough(self) -> None:
        prepare_payload = {
            "candidates": [
                {
                    "candidate_id": "cand-research",
                    "label": "review changes (review, markdown)",
                    "confidence": "weak",
                    "proposal_ready": False,
                    "triage_status": "needs_research",
                    "confidence_reason": "oversized cluster",
                    "evidence_summary": "64 packets / flags: oversized_cluster",
                    "evidence_items": [
                        {
                            "session_ref": "codex:abc:1",
                            "timestamp": "2026-03-10T09:00:00+09:00",
                            "source": "codex-history",
                            "summary": "Keep findings-first review format.",
                        }
                    ],
                }
            ],
            "unclustered": [
                {
                    "packet_id": "codex:single",
                    "confidence_reason": "single observed packet only",
                }
            ],
        }

        sections = build_proposal_sections(prepare_payload)

        self.assertEqual(sections["summary"]["ready_count"], 0)
        self.assertEqual(sections["summary"]["needs_research_count"], 1)
        self.assertIn("今回は有力候補なし", sections["markdown"])
        self.assertIn("見送り理由の傾向", sections["markdown"])
        self.assertIn("2026-03-10T09:00:00+09:00 codex-history: Keep findings-first review format.", sections["markdown"])
        self.assertEqual(sections["needs_research"][0]["evidence_items"][0]["session_ref"], "codex:abc:1")

    def test_benchmark_metrics_improve_against_legacy_behavior(self) -> None:
        packets: list[dict[str, object]] = []
        for index in range(5):
            packets.append(
                make_packet(
                    f"review-{index}",
                    primary_intent="Review the backend PR and return findings by severity.",
                    snippets=["Review the backend PR and return findings by severity."],
                    task_shape=["review_changes", "search_code"],
                    artifact_hints=["review"],
                    repeated_rules=["findings-first"],
                    timestamp=f"2026-03-09T0{index}:00:00+09:00",
                )
            )
            packets.append(
                make_packet(
                    f"report-{index}",
                    primary_intent="Review the weekly report draft and keep the same findings-first format.",
                    snippets=["Review the weekly report draft and keep the same findings-first format."],
                    task_shape=["review_changes", "search_code"],
                    artifact_hints=["markdown"],
                    repeated_rules=["findings-first"],
                    timestamp=f"2026-03-10T0{index}:00:00+09:00",
                )
            )

        legacy_candidates, legacy_unclustered = legacy_cluster_packets(packets)
        current_candidates, current_unclustered, _stats = cluster_packets(packets)
        legacy_metrics = build_quality_metrics(legacy_candidates, legacy_unclustered)
        current_metrics = build_quality_metrics(current_candidates, current_unclustered)

        self.assertGreater(legacy_metrics["oversized_cluster_rate"], current_metrics["oversized_cluster_rate"])
        self.assertLess(legacy_metrics["proposal_ready_count"], current_metrics["proposal_ready_count"])
        self.assertGreater(legacy_metrics["zero_rate"], current_metrics["zero_rate"])


if __name__ == "__main__":
    unittest.main()
