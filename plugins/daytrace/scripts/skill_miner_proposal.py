#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import emit, error_response
from skill_miner_common import (
    PROPOSAL_SOURCE,
    build_evidence_chain_lines,
    build_proposal_markdown as build_markdown,
    build_proposal_sections,
    proposal_item_lines,
    rejected_item_lines,
)


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


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        prepare_payload = load_json(Path(args.prepare_file).expanduser().resolve())
        judgments = load_judgments(args.judge_file)
        proposal = build_proposal_sections(prepare_payload, judgments_by_candidate_id=judgments)
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
