#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import emit, error_response
from skill_miner_common import PROPOSAL_SOURCE, build_proposal_sections


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build proposal sections from skill-miner prepare output and optional research judgments.")
    parser.add_argument("--prepare-file", required=True, help="Path to the JSON file produced by skill_miner_prepare.py.")
    parser.add_argument("--judge-file", action="append", default=[], help="Path to a JSON file produced by skill_miner_research_judge.py.")
    return parser


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def load_judgments(paths: list[str]) -> dict[str, dict[str, Any]]:
    judgments: dict[str, dict[str, Any]] = {}
    for raw_path in paths:
        payload = load_json(Path(raw_path).expanduser().resolve())
        candidate_id = payload.get("candidate_id")
        if isinstance(candidate_id, str) and candidate_id:
            judgments[candidate_id] = payload
    return judgments


def build_evidence_chain_lines(candidate: dict[str, Any]) -> list[str]:
    lines = ["   根拠:"]
    evidence_items = candidate.get("evidence_items") or []
    if not isinstance(evidence_items, list) or not evidence_items:
        fallback = str(candidate.get("evidence_summary") or "n/a")
        lines.append(f"   - {fallback}")
        return lines

    for item in evidence_items[:3]:
        if not isinstance(item, dict):
            continue
        timestamp = str(item.get("timestamp") or "").strip() or "unknown time"
        source = str(item.get("source") or "").strip() or "unknown source"
        summary = str(item.get("summary") or "").strip() or "summary unavailable"
        lines.append(f"   - {timestamp} {source}: {summary}")
    return lines


def proposal_item_lines(index: int, candidate: dict[str, Any], *, include_classification: bool) -> list[str]:
    lines = [f"{index}. {candidate.get('label', 'Unnamed candidate')}"]
    if include_classification:
        lines.append(f"   分類: {candidate.get('suggested_kind', 'TBD')}")
    lines.append(f"   confidence: {candidate.get('confidence', 'unknown')}")
    lines.extend(build_evidence_chain_lines(candidate))
    if include_classification:
        lines.append(f"   期待効果: {candidate.get('label', 'この候補')} の再利用フローを安定化できる")
    else:
        judgment = candidate.get("research_judgment")
        if isinstance(judgment, dict):
            lines.append(f"   保留理由: {judgment.get('summary', candidate.get('confidence_reason', '追加調査が必要'))}")
        else:
            lines.append(f"   保留理由: {candidate.get('confidence_reason', '追加調査が必要')}")
    return lines


def rejected_item_lines(index: int, candidate: dict[str, Any]) -> list[str]:
    label = candidate.get("label") or candidate.get("primary_intent") or candidate.get("packet_id") or "reference item"
    reason = candidate.get("confidence_reason") or candidate.get("evidence_summary") or "根拠不足"
    return [
        f"{index}. {label}",
        f"   理由: {reason}",
    ]


def build_markdown(ready: list[dict[str, Any]], needs_research: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> str:
    lines: list[str] = ["## 提案成立"]
    if ready:
        for index, candidate in enumerate(ready, start=1):
            lines.extend(proposal_item_lines(index, candidate, include_classification=True))
    else:
        lines.append("今回は有力候補なし")

    lines.append("")
    lines.append("## 追加調査待ち")
    if needs_research:
        for index, candidate in enumerate(needs_research, start=1):
            lines.extend(proposal_item_lines(index, candidate, include_classification=False))
    else:
        lines.append("なし")

    lines.append("")
    lines.append("## 今回は見送り")
    if rejected:
        for index, candidate in enumerate(rejected[:5], start=1):
            lines.extend(rejected_item_lines(index, candidate))
    else:
        lines.append("なし")

    if ready:
        lines.append("")
        lines.append("どの候補をドラフト化しますか？番号か候補名で指定してください。")
    return "\n".join(lines)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        prepare_payload = load_json(Path(args.prepare_file).expanduser().resolve())
        judgments = load_judgments(args.judge_file)
        proposal = build_proposal_sections(prepare_payload, judgments_by_candidate_id=judgments)
        proposal["markdown"] = build_markdown(
            proposal.get("ready", []),
            proposal.get("needs_research", []),
            proposal.get("rejected", []),
        )
        emit(
            {
                "status": "success",
                "source": PROPOSAL_SOURCE,
                **proposal,
            }
        )
    except Exception as exc:
        emit(error_response(PROPOSAL_SOURCE, str(exc)))


if __name__ == "__main__":
    main()
