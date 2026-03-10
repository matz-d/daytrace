#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from skill_miner_common import annotate_unclustered_packet, build_candidate_quality, build_proposal_sections, candidate_label, compact_snippet, judge_research_candidate


REPO_ROOT = Path(__file__).resolve().parents[4]
PREPARE = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "skill_miner_prepare.py"
DETAIL = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "skill_miner_detail.py"
RESEARCH_JUDGE = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "skill_miner_research_judge.py"
PROPOSAL = REPO_ROOT / "plugins" / "daytrace" / "scripts" / "skill_miner_proposal.py"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


class SkillMinerTests(unittest.TestCase):
    def create_fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        claude_root = root / "claude"
        codex_history = root / "codex" / "history.jsonl"
        codex_sessions = root / "codex" / "sessions"

        claude_file = claude_root / "repo" / "session-a.jsonl"
        write_jsonl(
            claude_file,
            [
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-review",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T00:00:00+09:00",
                    "message": {
                        "role": "user",
                        "content": (
                            f"Please review [WORKSPACE] findings in {workspace}/src/app.py and summarize by severity. "
                            "See https://example.com/path?a=1#frag"
                        ),
                    },
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-review",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T00:05:00+09:00",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "I will review the diff and list findings by severity with file and line references."}
                        ],
                    },
                },
                {
                    "type": "user",
                    "cwd": str(workspace),
                    "sessionId": "claude-review",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T09:30:00+09:00",
                    "message": {
                        "role": "user",
                        "content": f"Review another PR under {workspace}/src/api.py and keep the same findings-first format.",
                    },
                },
                {
                    "type": "assistant",
                    "cwd": str(workspace),
                    "sessionId": "claude-review",
                    "isSidechain": False,
                    "timestamp": "2026-03-09T09:40:00+09:00",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "I will inspect the files and return findings first, severity ordered, with file-line refs."}
                        ],
                    },
                },
            ],
        )

        write_jsonl(
            codex_history,
            [
                {
                    "session_id": "codex-review",
                    "ts": 1772985600,
                    "text": f"Please review the PR in {workspace}/server.py and return findings with severity ordering.",
                },
                {
                    "session_id": "codex-build",
                    "ts": 1772992800,
                    "text": "Implement a new CLI command and update the config file.",
                },
            ],
        )

        review_rollout = codex_sessions / "2026" / "03" / "09" / "rollout-review.jsonl"
        build_rollout = codex_sessions / "2026" / "03" / "09" / "rollout-build.jsonl"

        write_jsonl(
            review_rollout,
            [
                {
                    "timestamp": "2026-03-09T01:00:00+09:00",
                    "type": "session_meta",
                    "payload": {
                        "id": "codex-review",
                        "timestamp": "2026-03-09T01:00:00+09:00",
                        "cwd": str(workspace),
                    },
                },
                {
                    "timestamp": "2026-03-09T01:00:01+09:00",
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": f"Review this PR in {workspace}/server.py and report findings first.",
                    },
                },
                {
                    "timestamp": "2026-03-09T01:00:02+09:00",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "I will inspect files and summarize findings by severity."}],
                    },
                },
                {
                    "timestamp": "2026-03-09T01:00:03+09:00",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "arguments": json.dumps({"cmd": "rg -n TODO src && sed -n '1,20p' src/server.py"}),
                    },
                },
                {
                    "timestamp": "2026-03-09T01:00:04+09:00",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "arguments": json.dumps({"cmd": "git diff -- src/server.py"}),
                    },
                },
            ],
        )

        write_jsonl(
            build_rollout,
            [
                {
                    "timestamp": "2026-03-09T03:00:00+09:00",
                    "type": "session_meta",
                    "payload": {
                        "id": "codex-build",
                        "timestamp": "2026-03-09T03:00:00+09:00",
                        "cwd": str(workspace),
                    },
                },
                {
                    "timestamp": "2026-03-09T03:00:01+09:00",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "Implement a new CLI command and edit config."},
                },
                {
                    "timestamp": "2026-03-09T03:00:02+09:00",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "I will implement the feature and update the config."}],
                    },
                },
                {
                    "timestamp": "2026-03-09T03:00:03+09:00",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "arguments": json.dumps({"cmd": "python3 scripts/build.py"}),
                    },
                },
            ],
        )

        return workspace, claude_root, codex_history, codex_sessions

    def run_prepare(self, workspace: Path, claude_root: Path, codex_history: Path, codex_sessions: Path) -> dict:
        completed = subprocess.run(
            [
                "python3",
                str(PREPARE),
                "--workspace",
                str(workspace),
                "--claude-root",
                str(claude_root),
                "--codex-history-file",
                str(codex_history),
                "--codex-sessions-root",
                str(codex_sessions),
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

    def test_prepare_builds_candidates_and_masks_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(Path(temp_dir))
            payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)

            self.assertEqual(payload["summary"]["total_packets"], 4)
            self.assertGreaterEqual(payload["summary"]["block_count"], 1)
            self.assertEqual(len(payload["candidates"]), 1)
            candidate = payload["candidates"][0]
            self.assertEqual(candidate["support"]["total_packets"], 3)
            self.assertEqual(candidate["support"]["claude_packets"], 2)
            self.assertEqual(candidate["support"]["codex_packets"], 1)
            self.assertIn("review_changes", candidate["common_task_shapes"])
            self.assertIn("summarize_findings", candidate["common_task_shapes"])
            self.assertIn("rg", candidate["common_tool_signatures"])
            self.assertEqual(len(candidate["session_refs"]), 3)
            self.assertGreater(candidate["score"], 0)
            self.assertIn(candidate["confidence"], {"medium", "strong"})
            self.assertTrue(candidate["proposal_ready"])
            self.assertEqual(candidate["triage_status"], "ready")
            self.assertIn("evidence_summary", candidate)
            self.assertGreaterEqual(len(candidate["research_targets"]), 2)
            self.assertTrue(all("session_ref" in item for item in candidate["research_targets"]))
            self.assertIn("research_brief", candidate)
            self.assertIn("questions", candidate["research_brief"])
            self.assertEqual(payload["unclustered"][0]["triage_status"], "rejected")
            self.assertFalse(payload["unclustered"][0]["proposal_ready"])

            snippets = "\n".join(candidate["representative_examples"] + payload["unclustered"][0]["representative_snippets"])
            self.assertNotIn(str(workspace), snippets)
            self.assertIn("[WORKSPACE]", snippets)
            self.assertNotIn("?a=1", snippets)
            masked_url = compact_snippet("See https://example.com/path?a=1#frag", str(workspace))
            self.assertEqual(masked_url, "See https://example.com")

    def test_candidate_quality_flags_oversized_generic_cluster_for_research(self) -> None:
        candidate = {
            "support": {
                "total_packets": 9,
                "claude_packets": 4,
                "codex_packets": 5,
                "recent_packets_7d": 6,
            },
            "common_task_shapes": ["review_changes", "search_code", "summarize_findings"],
            "common_tool_signatures": ["rg", "sed", "bash", "read"],
            "artifact_hints": ["review", "report"],
            "rule_hints": ["findings-first"],
            "representative_examples": [
                "Review this PR and summarize findings by severity.",
                "Investigate the logs and summarize the root cause.",
            ],
        }

        quality = build_candidate_quality(candidate, total_packets_all=12)

        self.assertEqual(quality["triage_status"], "needs_research")
        self.assertFalse(quality["proposal_ready"])
        self.assertIn(quality["confidence"], {"weak", "insufficient"})
        self.assertIn("oversized_cluster", quality["quality_flags"])
        self.assertIn("generic_task_shape", quality["quality_flags"])
        self.assertIn("generic_tools", quality["quality_flags"])

    def test_prepare_includes_research_targets_for_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(Path(temp_dir))
            payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)
            candidate = payload["candidates"][0]

            self.assertIn("research_targets", candidate)
            self.assertLessEqual(len(candidate["research_targets"]), 5)
            reasons = {item["reason"] for item in candidate["research_targets"]}
            self.assertTrue(reasons & {"representative", "fallback"})
            self.assertTrue(all(item["session_ref"] in candidate["session_refs"] for item in candidate["research_targets"]))
            self.assertIn("objective", candidate["research_brief"])
            self.assertGreaterEqual(len(candidate["research_brief"]["questions"]), 3)
            self.assertGreaterEqual(len(candidate["research_brief"]["decision_rules"]), 3)

    def test_issue_sized_cluster_is_held_for_research(self) -> None:
        candidate = {
            "label": "review changes (review, markdown)",
            "support": {
                "total_packets": 63,
                "claude_packets": 31,
                "codex_packets": 32,
                "recent_packets_7d": 48,
            },
            "common_task_shapes": ["review_changes", "search_code", "summarize_findings"],
            "common_tool_signatures": ["sed", "rg", "read", "bash"],
            "artifact_hints": ["review", "markdown", "report"],
            "rule_hints": ["file-line-refs", "findings-first"],
            "representative_examples": [
                "Review a proposed memo and list factual findings with references.",
                "Search the codebase and summarize findings from logs and docs.",
            ],
            "research_targets": [
                {"session_ref": "codex:one:1", "reason": "representative"},
                {"session_ref": "codex:two:2", "reason": "near_match"},
            ],
        }

        quality = build_candidate_quality(candidate, total_packets_all=75)

        self.assertEqual(quality["triage_status"], "needs_research")
        self.assertFalse(quality["proposal_ready"])
        self.assertIn("oversized_cluster", quality["quality_flags"])

    def test_judge_research_candidate_promotes_coherent_review_pattern(self) -> None:
        candidate = {
            "label": "review changes (review, code)",
            "quality_flags": [],
        }
        details = [
            {
                "session_ref": "codex:a:1",
                "messages": [
                    {"role": "user", "text": "Review this PR and return findings by severity."},
                    {"role": "assistant", "text": "I will inspect the diff and list findings first with file references."},
                ],
                "tool_calls": [{"name": "rg", "count": 2}, {"name": "git", "count": 1}],
            },
            {
                "session_ref": "codex:b:2",
                "messages": [
                    {"role": "user", "text": "Review another PR and keep the findings-first format."},
                    {"role": "assistant", "text": "I will inspect files and summarize findings by severity with line refs."},
                ],
                "tool_calls": [{"name": "rg", "count": 1}, {"name": "git", "count": 1}],
            },
        ]

        judgment = judge_research_candidate(candidate, details)

        self.assertEqual(judgment["recommendation"], "promote_ready")
        self.assertEqual(judgment["proposed_triage_status"], "ready")
        self.assertIn(judgment["proposed_confidence"], {"medium", "strong"})

    def test_judge_research_candidate_splits_mixed_objectives(self) -> None:
        candidate = {
            "label": "review changes (review, markdown)",
            "quality_flags": ["oversized_cluster", "generic_task_shape", "generic_tools"],
        }
        details = [
            {
                "session_ref": "codex:a:1",
                "messages": [
                    {"role": "user", "text": "Review this PR and return findings by severity."},
                    {"role": "assistant", "text": "I will inspect the diff and list findings first."},
                ],
                "tool_calls": [{"name": "rg", "count": 2}],
            },
            {
                "session_ref": "codex:b:2",
                "messages": [
                    {"role": "user", "text": "Investigate failing logs and identify the root cause."},
                    {"role": "assistant", "text": "I will inspect the logs and summarize the failure pattern."},
                ],
                "tool_calls": [{"name": "sed", "count": 1}],
            },
            {
                "session_ref": "codex:c:3",
                "messages": [
                    {"role": "user", "text": "Prepare a daily report draft from today's work."},
                    {"role": "assistant", "text": "I will create a report with action items and summary."},
                ],
                "tool_calls": [{"name": "python3", "count": 1}],
            },
        ]

        judgment = judge_research_candidate(candidate, details)

        self.assertEqual(judgment["recommendation"], "split_candidate")
        self.assertEqual(judgment["proposed_triage_status"], "needs_research")
        self.assertTrue(judgment["split_suggestions"])

    def test_research_judge_cli_reads_prepare_and_detail_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(Path(temp_dir))
            payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)
            candidate = payload["candidates"][0]
            refs = candidate["research_targets"][:2]

            detail_completed = subprocess.run(
                [
                    "python3",
                    str(DETAIL),
                    "--refs",
                    *[item["session_ref"] for item in refs],
                    "--gap-hours",
                    "8",
                    "--codex-history-file",
                    str(codex_history),
                    "--codex-sessions-root",
                    str(codex_sessions),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(detail_completed.returncode, 0, msg=detail_completed.stderr)
            detail_payload = json.loads(detail_completed.stdout)

            candidate_file = Path(temp_dir) / "prepare.json"
            detail_file = Path(temp_dir) / "detail.json"
            candidate_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            detail_file.write_text(json.dumps(detail_payload, ensure_ascii=False), encoding="utf-8")

            judge_completed = subprocess.run(
                [
                    "python3",
                    str(RESEARCH_JUDGE),
                    "--candidate-file",
                    str(candidate_file),
                    "--candidate-id",
                    candidate["candidate_id"],
                    "--detail-file",
                    str(detail_file),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(judge_completed.returncode, 0, msg=judge_completed.stderr)
            judgment_payload = json.loads(judge_completed.stdout)
            self.assertEqual(judgment_payload["status"], "success")
            self.assertEqual(judgment_payload["source"], "skill-miner-research-judge")
            self.assertIn("judgment", judgment_payload)

    def test_build_proposal_sections_separates_ready_and_rejected(self) -> None:
        prepare_payload = {
            "candidates": [
                {
                    "candidate_id": "cand-ready",
                    "label": "review changes (code, report)",
                    "confidence": "medium",
                    "proposal_ready": True,
                    "triage_status": "ready",
                    "evidence_summary": "3 packets / Claude 2 / Codex 1",
                },
                {
                    "candidate_id": "cand-research",
                    "label": "review changes (review, markdown)",
                    "confidence": "weak",
                    "proposal_ready": False,
                    "triage_status": "needs_research",
                    "confidence_reason": "oversized cluster",
                    "evidence_summary": "64 packets / flags: oversized_cluster",
                },
            ],
            "unclustered": [
                {
                    "packet_id": "codex:single",
                    "confidence_reason": "single observed packet only",
                }
            ],
        }

        sections = build_proposal_sections(prepare_payload)

        self.assertEqual(len(sections["ready"]), 1)
        self.assertEqual(len(sections["needs_research"]), 1)
        self.assertEqual(len(sections["rejected"]), 1)
        self.assertIn("## 提案成立", sections["markdown"])
        self.assertIn("## 追加調査待ち", sections["markdown"])
        self.assertIn("## 今回は見送り", sections["markdown"])
        self.assertIsNotNone(sections["selection_prompt"])

    def test_proposal_cli_formats_sections_from_prepare_and_judgment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prepare_payload = {
                "candidates": [
                    {
                        "candidate_id": "cand-1",
                        "label": "review changes (review, markdown)",
                        "confidence": "insufficient",
                        "proposal_ready": False,
                        "triage_status": "needs_research",
                        "evidence_summary": "64 packets / flags: oversized_cluster",
                        "quality_flags": ["oversized_cluster"],
                    }
                ],
                "unclustered": [],
            }
            judgment_payload = {
                "status": "success",
                "source": "skill-miner-research-judge",
                "candidate_id": "cand-1",
                "judgment": {
                    "recommendation": "promote_ready",
                    "proposed_triage_status": "ready",
                    "proposed_confidence": "medium",
                    "summary": "recommendation=promote_ready / sampled_refs=3",
                },
            }

            prepare_file = Path(temp_dir) / "prepare.json"
            judge_file = Path(temp_dir) / "judge.json"
            prepare_file.write_text(json.dumps(prepare_payload, ensure_ascii=False), encoding="utf-8")
            judge_file.write_text(json.dumps(judgment_payload, ensure_ascii=False), encoding="utf-8")

            completed = subprocess.run(
                [
                    "python3",
                    str(PROPOSAL),
                    "--prepare-file",
                    str(prepare_file),
                    "--judge-file",
                    str(judge_file),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["source"], "skill-miner-proposal")
            self.assertEqual(len(payload["ready"]), 1)
            self.assertEqual(payload["ready"][0]["candidate_id"], "cand-1")
            self.assertIn("どの候補をドラフト化しますか？", payload["markdown"])

    def test_build_proposal_sections_handles_zero_ready_candidates(self) -> None:
        prepare_payload = {
            "candidates": [
                {
                    "candidate_id": "cand-research",
                    "label": "review changes (review, markdown)",
                    "confidence": "insufficient",
                    "proposal_ready": False,
                    "triage_status": "needs_research",
                    "confidence_reason": "oversized cluster",
                    "evidence_summary": "64 packets / flags: oversized_cluster",
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
        self.assertEqual(sections["summary"]["rejected_count"], 1)
        self.assertIsNone(sections["selection_prompt"])
        self.assertIn("今回は有力候補なし", sections["markdown"])

    def test_candidate_label_prefers_cluster_signals(self) -> None:
        label = candidate_label(
            {
                "common_task_shapes": ["review_changes"],
                "artifact_hints": ["code", "report"],
                "primary_intent": "本日のAI予測をチャットに送信。Macのパスです",
            }
        )

        self.assertEqual(label, "review changes (code, report)")

    def test_unclustered_packets_are_not_proposal_ready(self) -> None:
        packet = annotate_unclustered_packet(
            {
                "packet_id": "codex:single",
                "support": {"message_count": 2, "tool_call_count": 0},
            }
        )

        self.assertEqual(packet["confidence"], "insufficient")
        self.assertFalse(packet["proposal_ready"])
        self.assertEqual(packet["triage_status"], "rejected")
        self.assertIn("unclustered_only", packet["quality_flags"])

    def test_detail_resolves_prepare_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, claude_root, codex_history, codex_sessions = self.create_fixture(Path(temp_dir))
            payload = self.run_prepare(workspace, claude_root, codex_history, codex_sessions)
            refs = payload["candidates"][0]["session_refs"][:2]

            completed = subprocess.run(
                [
                    "python3",
                    str(DETAIL),
                    "--refs",
                    *refs,
                    "--gap-hours",
                    "8",
                    "--codex-history-file",
                    str(codex_history),
                    "--codex-sessions-root",
                    str(codex_sessions),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            details_payload = json.loads(completed.stdout)
            self.assertEqual(details_payload["status"], "success", msg=completed.stdout)
            self.assertEqual(len(details_payload["errors"]), 0)
            self.assertEqual(len(details_payload["details"]), 2)

            codex_detail = next(item for item in details_payload["details"] if item["source"] == "codex-history")
            claude_detail = next(item for item in details_payload["details"] if item["source"] == "claude-history")

            self.assertTrue(any(message["role"] == "user" for message in codex_detail["messages"]))
            self.assertTrue(any(tool["name"] == "rg" for tool in codex_detail["tool_calls"]))
            self.assertTrue(any("findings" in message["text"].lower() for message in claude_detail["messages"]))

    def test_prepare_handles_missing_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(
                [
                    "python3",
                    str(PREPARE),
                    "--workspace",
                    str(workspace),
                    "--claude-root",
                    str(root / "missing-claude"),
                    "--codex-history-file",
                    str(root / "missing-history.jsonl"),
                    "--codex-sessions-root",
                    str(root / "missing-sessions"),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertTrue(payload["summary"]["no_sources_available"])
            self.assertEqual(payload["candidates"], [])

    def test_prepare_handles_permission_denied(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            claude_root = root / "claude"
            blocked = claude_root / "repo" / "blocked.jsonl"
            blocked.parent.mkdir(parents=True, exist_ok=True)
            blocked.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "cwd": str(workspace),
                        "sessionId": "blocked",
                        "isSidechain": False,
                        "timestamp": "2026-03-09T00:00:00+09:00",
                        "message": {"role": "user", "content": "blocked"},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            os.chmod(blocked, 0)
            try:
                completed = subprocess.run(
                    [
                        "python3",
                        str(PREPARE),
                        "--workspace",
                        str(workspace),
                        "--claude-root",
                        str(claude_root),
                        "--codex-history-file",
                        str(root / "missing-history.jsonl"),
                        "--codex-sessions-root",
                        str(root / "missing-sessions"),
                    ],
                    cwd=str(REPO_ROOT),
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                os.chmod(blocked, stat.S_IRUSR | stat.S_IWUSR)

            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            claude_status = next(item for item in payload["sources"] if item["name"] == "claude-history")
            self.assertEqual(claude_status["status"], "skipped")
            self.assertEqual(claude_status["reason"], "permission_denied")

    def test_prepare_ignores_broken_jsonl_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            claude_root = root / "claude"
            broken = claude_root / "repo" / "broken.jsonl"
            broken.parent.mkdir(parents=True, exist_ok=True)
            broken.write_text(
                textwrap.dedent(
                    f"""
                    not-json
                    {json.dumps({"type":"user","cwd":str(workspace),"sessionId":"ok","isSidechain":False,"timestamp":"2026-03-09T00:00:00+09:00","message":{"role":"user","content":"review this"}})}
                    {json.dumps({"type":"assistant","cwd":str(workspace),"sessionId":"ok","isSidechain":False,"timestamp":"2026-03-09T00:01:00+09:00","message":{"role":"assistant","content":[{"type":"text","text":"findings first"}]}})}
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "python3",
                    str(PREPARE),
                    "--workspace",
                    str(workspace),
                    "--claude-root",
                    str(claude_root),
                    "--codex-history-file",
                    str(root / "missing-history.jsonl"),
                    "--codex-sessions-root",
                    str(root / "missing-sessions"),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["summary"]["total_packets"], 1)


if __name__ == "__main__":
    unittest.main()
