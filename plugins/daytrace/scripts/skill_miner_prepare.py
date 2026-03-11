#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common import emit, ensure_datetime, error_response, resolve_workspace
from skill_miner_common import (
    CLAUDE_SOURCE,
    CODEX_SOURCE,
    DEFAULT_GAP_HOURS,
    DEFAULT_MAX_UNCLUSTERED,
    DEFAULT_RESEARCH_REF_LIMIT,
    DEFAULT_TOP_N,
    GENERIC_TASK_SHAPES,
    GENERIC_TOOL_SIGNATURES,
    PREPARE_SOURCE,
    extract_known_commands,
    build_claude_session_ref,
    build_codex_session_ref,
    build_candidate_quality,
    build_research_brief,
    build_research_targets,
    build_packet,
    candidate_label,
    candidate_score,
    candidate_sort_key,
    claude_message_text,
    codex_command_names,
    codex_message_text,
    compact_snippet,
    compare_iso_timestamps,
    earliest_iso_timestamp,
    jaccard_score,
    load_jsonl,
    overlap_score,
    packet_sort_key,
    recent_packet_count,
    stable_block_keys,
    tokenize,
    annotate_unclustered_packet,
    workspace_matches,
)


DEFAULT_CLAUDE_ROOT = Path.home() / ".claude" / "projects"
DEFAULT_CODEX_HISTORY = Path.home() / ".codex" / "history.jsonl"
DEFAULT_CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
DEFAULT_OBSERVATION_DAYS = 7
WORKSPACE_ADAPTIVE_EXPANDED_DAYS = 30
WORKSPACE_ADAPTIVE_MIN_PACKETS = 4
WORKSPACE_ADAPTIVE_MIN_CANDIDATES = 1
CLUSTER_MERGE_THRESHOLD = 0.60
CLUSTER_NEAR_MATCH_THRESHOLD = 0.45

# v2 target mix:
# - task_shapes: 0.30 (split between shared-shape overlap and exact specific-shape bonus)
# - snippet / intent: 0.25
# - artifacts: 0.20
# - rules: 0.20
# - tools: 0.05
SIMILARITY_TASK_SHAPES_WEIGHT = 0.22
SIMILARITY_SPECIFIC_SHAPE_BONUS = 0.08
SIMILARITY_INTENT_WEIGHT = 0.15
SIMILARITY_SNIPPET_WEIGHT = 0.10
SIMILARITY_ARTIFACT_WEIGHT = 0.20
SIMILARITY_RULE_WEIGHT = 0.20
SIMILARITY_TOOL_WEIGHT = 0.05
SIMILARITY_GENERIC_ONLY_PENALTY = 0.08
SIMILARITY_WEIGHT_TOTAL = (
    SIMILARITY_TASK_SHAPES_WEIGHT
    + SIMILARITY_SPECIFIC_SHAPE_BONUS
    + SIMILARITY_INTENT_WEIGHT
    + SIMILARITY_SNIPPET_WEIGHT
    + SIMILARITY_ARTIFACT_WEIGHT
    + SIMILARITY_RULE_WEIGHT
    + SIMILARITY_TOOL_WEIGHT
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare compressed skill-miner candidates from raw Claude/Codex history.")
    parser.add_argument("--workspace", default=".", help="Workspace path to filter by. Ignored with --all-sessions.")
    parser.add_argument("--all-sessions", action="store_true", help="Ignore workspace filtering while keeping the configured day window.")
    parser.add_argument("--days", type=int, default=DEFAULT_OBSERVATION_DAYS, help="Limit packets to the last N days.")
    parser.add_argument("--claude-root", default=str(DEFAULT_CLAUDE_ROOT), help="Claude projects root.")
    parser.add_argument("--codex-history-file", default=str(DEFAULT_CODEX_HISTORY), help="Codex history.jsonl path.")
    parser.add_argument("--codex-sessions-root", default=str(DEFAULT_CODEX_SESSIONS), help="Codex sessions root.")
    parser.add_argument("--gap-hours", type=int, default=DEFAULT_GAP_HOURS, help="Hours of inactivity that split Claude logical sessions.")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="Maximum number of candidates to return.")
    parser.add_argument(
        "--max-unclustered",
        type=int,
        default=DEFAULT_MAX_UNCLUSTERED,
        help="Maximum number of unclustered packets to include.",
    )
    parser.add_argument(
        "--dump-intents",
        action="store_true",
        help="Include anonymized primary_intent samples and summary metrics for B0 observation.",
    )
    return parser


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, index: int) -> int:
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def union(self, left: int, right: int) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def source_status(name: str, status: str, **extra: Any) -> dict[str, Any]:
    payload = {"name": name, "status": status}
    payload.update(extra)
    return payload


def read_claude_packets(root: Path, workspace: Path | None, gap_hours: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not root.exists():
        return [], source_status(CLAUDE_SOURCE, "skipped", reason="not_found", root=str(root))

    packets: list[dict[str, Any]] = []
    try:
        jsonl_files = sorted(root.glob("**/*.jsonl"))
        for path in jsonl_files:
            records = load_jsonl(path)
            packet_records: list[dict[str, Any]] = []
            last_timestamp = None
            last_sidechain = None
            packet_index = 0

            def flush_packet() -> None:
                nonlocal packet_records, packet_index
                if not packet_records:
                    return
                user_messages: list[str] = []
                assistant_messages: list[str] = []
                tools: list[str] = []
                timestamps: list[str] = []
                cwd = None
                session_id = None
                for record in packet_records:
                    timestamps.append(str(record.get("timestamp")))
                    cwd = record.get("cwd") or cwd
                    session_id = record.get("sessionId") or session_id
                    text = claude_message_text(record.get("message"))
                    if record.get("type") == "user":
                        user_messages.append(text)
                    else:
                        assistant_messages.append(text)
                    message = record.get("message")
                    if isinstance(message, dict) and isinstance(message.get("content"), list):
                        for item in message["content"]:
                            if isinstance(item, dict) and item.get("type") == "tool_use":
                                name = str(item.get("name") or "").lower()
                                if name:
                                    tools.append(name)
                    tools.extend(extract_known_commands(text))

                packet_start = earliest_iso_timestamp(timestamps)
                workspace_str = str(cwd) if cwd else None
                session_ref = build_claude_session_ref(str(path), packet_start)
                packet = build_packet(
                    packet_id=f"claude:{path.parent.name}:{path.stem}:{packet_index:03d}",
                    source=CLAUDE_SOURCE,
                    session_ref=session_ref,
                    session_id=str(session_id) if session_id else None,
                    workspace=workspace_str,
                    timestamp=packet_start,
                    user_messages=user_messages,
                    assistant_messages=assistant_messages,
                    tools=tools,
                )
                packets.append(packet)
                packet_index += 1
                packet_records = []

            for record in records:
                record_type = record.get("type")
                if record_type not in {"user", "assistant"}:
                    continue
                if record.get("isMeta"):
                    continue
                cwd = record.get("cwd")
                if not workspace_matches(cwd, workspace):
                    if packet_records:
                        flush_packet()
                        last_timestamp = None
                        last_sidechain = None
                    continue
                timestamp_value = record.get("timestamp")
                current_timestamp = ensure_datetime(timestamp_value)
                if current_timestamp is None:
                    continue
                current_sidechain = bool(record.get("isSidechain"))
                should_split = False
                if packet_records and last_timestamp is not None:
                    gap_seconds = current_timestamp.timestamp() - last_timestamp.timestamp()
                    if gap_seconds >= gap_hours * 60 * 60:
                        should_split = True
                if packet_records and last_sidechain is not None and current_sidechain != last_sidechain:
                    should_split = True
                if should_split:
                    flush_packet()
                packet_records.append(record)
                last_timestamp = current_timestamp
                last_sidechain = current_sidechain

            flush_packet()
        return packets, source_status(CLAUDE_SOURCE, "success", packets_count=len(packets))
    except PermissionError as exc:
        return [], source_status(CLAUDE_SOURCE, "skipped", reason="permission_denied", message=str(exc), root=str(root))
    except Exception as exc:  # pragma: no cover - defensive surface
        return [], source_status(CLAUDE_SOURCE, "error", message=str(exc), root=str(root))


def read_codex_packets(history_file: Path, sessions_root: Path, workspace: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not history_file.exists() or not sessions_root.exists():
        return [], source_status(
            CODEX_SOURCE,
            "skipped",
            reason="not_found",
            history_file=str(history_file),
            sessions_root=str(sessions_root),
        )

    packets: list[dict[str, Any]] = []
    try:
        history_by_session: dict[str, dict[str, Any]] = defaultdict(lambda: {"user_messages": [], "timestamps": []})
        for record in load_jsonl(history_file):
            session_id = record.get("session_id")
            if not session_id:
                continue
            history_by_session[session_id]["timestamps"].append(record.get("ts"))
            text = str(record.get("text") or "")
            if text:
                history_by_session[session_id]["user_messages"].append(text)

        rollout_files = sorted(sessions_root.glob("**/rollout-*.jsonl"))
        for rollout in rollout_files:
            records = load_jsonl(rollout)
            meta = None
            for record in records:
                if record.get("type") == "session_meta":
                    payload = record.get("payload", {})
                    if payload.get("id"):
                        meta = payload
                        break
            if not meta:
                continue
            cwd = meta.get("cwd")
            if not workspace_matches(cwd, workspace):
                continue

            session_id = str(meta.get("id"))
            user_messages: list[str] = []
            assistant_messages: list[str] = []
            tools: list[str] = []
            timestamps: list[str] = []
            for record in records:
                record_type = record.get("type")
                timestamp = record.get("timestamp")
                if record_type == "event_msg" and record.get("payload", {}).get("type") == "user_message":
                    message = str(record.get("payload", {}).get("message") or "")
                    if message:
                        user_messages.append(message)
                        if timestamp:
                            timestamps.append(str(timestamp))
                elif record_type == "response_item":
                    payload = record.get("payload", {})
                    payload_type = payload.get("type")
                    if payload_type == "message" and payload.get("role") == "assistant":
                        text = codex_message_text(payload)
                        if text:
                            assistant_messages.append(text)
                            if timestamp:
                                timestamps.append(str(timestamp))
                    elif payload_type == "function_call":
                        tools.extend(codex_command_names(payload))

            history_entry = history_by_session.get(session_id, {})
            user_messages = history_entry.get("user_messages", []) + user_messages
            start_timestamp = (
                earliest_iso_timestamp([meta.get("timestamp")])
                or earliest_iso_timestamp(history_entry.get("timestamps", []))
                or earliest_iso_timestamp(timestamps)
                or ""
            )
            if not user_messages and not assistant_messages:
                continue
            packet = build_packet(
                packet_id=f"codex:{session_id}",
                source=CODEX_SOURCE,
                session_ref=build_codex_session_ref(session_id, start_timestamp),
                session_id=session_id,
                workspace=str(cwd) if cwd else None,
                timestamp=start_timestamp or None,
                user_messages=user_messages,
                assistant_messages=assistant_messages,
                tools=tools,
            )
            packets.append(packet)
        return packets, source_status(CODEX_SOURCE, "success", packets_count=len(packets))
    except PermissionError as exc:
        return [], source_status(
            CODEX_SOURCE,
            "skipped",
            reason="permission_denied",
            message=str(exc),
            history_file=str(history_file),
            sessions_root=str(sessions_root),
        )
    except Exception as exc:  # pragma: no cover - defensive surface
        return [], source_status(CODEX_SOURCE, "error", message=str(exc), history_file=str(history_file), sessions_root=str(sessions_root))



def _primary_non_generic_shape(packet: dict[str, Any]) -> str:
    task_shapes = [str(shape) for shape in packet.get("task_shape", []) if shape]
    return next((shape for shape in task_shapes if shape not in GENERIC_TASK_SHAPES), "")


def _rule_names(packet: dict[str, Any]) -> set[str]:
    return {
        str(item.get("normalized") or "")
        for item in packet.get("repeated_rules", [])
        if isinstance(item, dict) and item.get("normalized")
    }


def similarity_score(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_tokens = set().union(*(tokenize(compact_snippet(item, left.get("workspace"))) for item in left.get("representative_snippets", [])))
    right_tokens = set().union(*(tokenize(compact_snippet(item, right.get("workspace"))) for item in right.get("representative_snippets", [])))
    snippet = jaccard_score(left_tokens, right_tokens)
    intent = jaccard_score(tokenize(str(left.get("primary_intent") or "")), tokenize(str(right.get("primary_intent") or "")))
    left_task_shapes = set(left.get("task_shape", []))
    right_task_shapes = set(right.get("task_shape", []))
    left_tools = set(left.get("tool_signature", []))
    right_tools = set(right.get("tool_signature", []))
    task_shapes = overlap_score(left_task_shapes, right_task_shapes)
    tools = jaccard_score(left_tools, right_tools)
    artifacts = overlap_score(set(left.get("artifact_hints", [])), set(right.get("artifact_hints", [])))
    rules = overlap_score(_rule_names(left), _rule_names(right))
    left_specific = _primary_non_generic_shape(left)
    same_specific_shape = 1.0 if left_specific and left_specific == _primary_non_generic_shape(right) else 0.0
    generic_task_only = bool(left_task_shapes) and bool(right_task_shapes) and all(
        shape in GENERIC_TASK_SHAPES for shape in left_task_shapes | right_task_shapes
    )
    generic_tool_only = bool(left_tools) and bool(right_tools) and all(
        tool in GENERIC_TOOL_SIGNATURES for tool in left_tools | right_tools
    )
    score = (
        (task_shapes * SIMILARITY_TASK_SHAPES_WEIGHT)
        + (intent * SIMILARITY_INTENT_WEIGHT)
        + (snippet * SIMILARITY_SNIPPET_WEIGHT)
        + (artifacts * SIMILARITY_ARTIFACT_WEIGHT)
        + (rules * SIMILARITY_RULE_WEIGHT)
        + (tools * SIMILARITY_TOOL_WEIGHT)
        + (same_specific_shape * SIMILARITY_SPECIFIC_SHAPE_BONUS)
    )
    if generic_task_only and generic_tool_only and artifacts == 0.0 and rules == 0.0:
        score -= SIMILARITY_GENERIC_ONLY_PENALTY
    return round(max(0.0, min(score, 1.0)), 3)


def filter_packets_by_days(packets: list[dict[str, Any]], days: int) -> tuple[list[dict[str, Any]], str | None]:
    if days <= 0:
        raise ValueError("--days must be a positive integer")
    threshold = datetime.now(timezone.utc) - timedelta(days=days)
    filtered: list[dict[str, Any]] = []
    for packet in packets:
        timestamp = ensure_datetime(packet.get("timestamp"))
        if timestamp is None:
            continue
        if timestamp >= threshold:
            filtered.append(packet)
    return filtered, threshold.isoformat()


def prepare_window_result(packets: list[dict[str, Any]], days: int) -> dict[str, Any]:
    filtered_packets, date_window_start = filter_packets_by_days(packets, days)
    candidates, unclustered, stats = cluster_packets(filtered_packets)
    return {
        "packets": filtered_packets,
        "candidates": candidates,
        "unclustered": unclustered,
        "stats": stats,
        "date_window_start": date_window_start,
        "days": days,
    }


def adaptive_window_decision(window_result: dict[str, Any], initial_days: int) -> tuple[bool, str | None]:
    if initial_days >= WORKSPACE_ADAPTIVE_EXPANDED_DAYS:
        return False, None
    packet_count = len(window_result["packets"])
    candidate_count = len(window_result["candidates"])
    if packet_count < WORKSPACE_ADAPTIVE_MIN_PACKETS and candidate_count < WORKSPACE_ADAPTIVE_MIN_CANDIDATES:
        return True, "insufficient_packets"
    if candidate_count < WORKSPACE_ADAPTIVE_MIN_CANDIDATES:
        return True, "insufficient_candidates"
    return False, None


def evidence_summary_text(packet: dict[str, Any]) -> str:
    primary_intent = str(packet.get("primary_intent") or "").strip()
    if primary_intent:
        return compact_snippet(primary_intent, packet.get("workspace"), limit=96)
    snippets = packet.get("representative_snippets") or []
    for snippet in snippets:
        text = str(snippet or "").strip()
        if text:
            return compact_snippet(text, packet.get("workspace"), limit=96)
    return candidate_label(packet)


def build_evidence_items(group_packets: list[dict[str, Any]], limit: int = 3) -> list[dict[str, str]]:
    ranked_packets = sorted(
        group_packets,
        key=lambda packet: (
            1 if str(packet.get("primary_intent") or "").strip() else 0,
            int(packet.get("support", {}).get("message_count", 0)),
            compare_iso_timestamps(packet.get("timestamp")),
            str(packet.get("packet_id") or ""),
        ),
        reverse=True,
    )

    selected: list[dict[str, str]] = []
    selected_refs: set[str] = set()
    selected_summaries: set[str] = set()
    used_sources: set[str] = set()

    def try_add(packet: dict[str, Any], *, prefer_new_source: bool) -> bool:
        session_ref = str(packet.get("session_ref") or "").strip()
        timestamp = str(packet.get("timestamp") or "").strip()
        source = str(packet.get("source") or "").strip()
        summary = evidence_summary_text(packet)
        summary_key = summary.lower()
        if not session_ref or not timestamp or not source or not summary:
            return False
        if session_ref in selected_refs or summary_key in selected_summaries:
            return False
        if prefer_new_source and used_sources and source in used_sources:
            return False
        selected.append(
            {
                "session_ref": session_ref,
                "timestamp": timestamp,
                "source": source,
                "summary": summary,
            }
        )
        selected_refs.add(session_ref)
        selected_summaries.add(summary_key)
        used_sources.add(source)
        return True

    if not ranked_packets:
        return []

    # 1) First pick the most representative packet.
    representative = ranked_packets[0]
    try_add(representative, prefer_new_source=False)

    # 2) Then pick a supporting packet, preferring a different source/session.
    for packet in ranked_packets[1:]:
        if len(selected) >= limit:
            break
        if try_add(packet, prefer_new_source=True):
            break
    for packet in ranked_packets[1:]:
        if len(selected) >= limit:
            break
        if try_add(packet, prefer_new_source=False):
            break

    # 3) Finally pick the most heterogeneous supporting packet still inside the same candidate.
    anchor_summary = evidence_summary_text(representative)
    anchor_tokens = tokenize(anchor_summary)
    heterogeneous_packets = sorted(
        ranked_packets[1:],
        key=lambda packet: (
            jaccard_score(anchor_tokens, tokenize(evidence_summary_text(packet))),
            -int(packet.get("support", {}).get("message_count", 0)),
        ),
    )
    for packet in heterogeneous_packets:
        if len(selected) >= limit:
            break
        try_add(packet, prefer_new_source=False)

    return selected[:limit]


def classify_intent_specificity(packet: dict[str, Any]) -> str:
    intent = str(packet.get("primary_intent") or "").strip()
    tokens = tokenize(intent)
    task_shapes = [str(shape) for shape in packet.get("task_shape", []) if shape]
    has_non_generic_shape = any(shape not in GENERIC_TASK_SHAPES for shape in task_shapes)
    if has_non_generic_shape and len(tokens) >= 6:
        return "high"
    if has_non_generic_shape or len(tokens) >= 4:
        return "medium"
    return "low"


def is_generic_intent(packet: dict[str, Any]) -> bool:
    intent = str(packet.get("primary_intent") or "").strip()
    tokens = tokenize(intent)
    task_shapes = [str(shape) for shape in packet.get("task_shape", []) if shape]
    return not intent or len(tokens) < 4 or (bool(task_shapes) and all(shape in GENERIC_TASK_SHAPES for shape in task_shapes[:2]))


def estimate_synonym_split_rate(packets: list[dict[str, Any]]) -> float:
    unique_intents: list[str] = []
    token_sets: list[set[str]] = []
    for packet in packets:
        intent = str(packet.get("primary_intent") or "").strip()
        if not intent:
            continue
        lowered = intent.lower()
        if lowered in {value.lower() for value in unique_intents}:
            continue
        unique_intents.append(intent)
        token_sets.append(tokenize(intent))

    pair_count = 0
    near_pair_count = 0
    for index, left_tokens in enumerate(token_sets):
        for right_tokens in token_sets[index + 1 :]:
            pair_count += 1
            score = jaccard_score(left_tokens, right_tokens)
            if 0.25 <= score < 0.85:
                near_pair_count += 1
    if pair_count == 0:
        return 0.0
    return round(near_pair_count / pair_count, 3)


def build_intent_analysis(packets: list[dict[str, Any]], limit: int = 10) -> dict[str, Any]:
    specificity_distribution = Counter({"high": 0, "medium": 0, "low": 0})
    generic_count = 0
    items: list[dict[str, Any]] = []

    ordered_packets = sorted(
        packets,
        key=lambda packet: (
            compare_iso_timestamps(packet.get("timestamp")),
            str(packet.get("packet_id") or ""),
        ),
        reverse=True,
    )

    for index, packet in enumerate(ordered_packets[:limit], start=1):
        specificity = classify_intent_specificity(packet)
        specificity_distribution[specificity] += 1
        generic = is_generic_intent(packet)
        if generic:
            generic_count += 1
        items.append(
            {
                "sample_id": f"intent-{index:03d}",
                "timestamp": packet.get("timestamp"),
                "source": packet.get("source"),
                "primary_intent": evidence_summary_text(packet),
                "specificity": specificity,
                "is_generic": generic,
            }
        )

    for packet in ordered_packets[limit:]:
        specificity_distribution[classify_intent_specificity(packet)] += 1
        if is_generic_intent(packet):
            generic_count += 1

    total_packets = len(ordered_packets)
    generic_rate = round(generic_count / total_packets, 3) if total_packets else 0.0
    synonym_split_rate = estimate_synonym_split_rate(ordered_packets)

    return {
        "summary": {
            "total_packets": total_packets,
            "generic_rate": generic_rate,
            "synonym_split_rate": synonym_split_rate,
            "specificity_distribution": dict(specificity_distribution),
        },
        "items": items,
    }


def cluster_packets(packets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    if not packets:
        return [], [], {"block_count": 0, "block_comparisons": 0}

    sorted_packets = sorted(packets, key=packet_sort_key, reverse=True)
    packet_lookup = {str(packet.get("packet_id")): packet for packet in sorted_packets}
    blocks: dict[str, list[int]] = defaultdict(list)
    for index, packet in enumerate(sorted_packets):
        for key in stable_block_keys(packet):
            blocks[key].append(index)

    union_find = UnionFind(len(sorted_packets))
    near_matches_by_index: dict[int, list[dict[str, Any]]] = defaultdict(list)
    block_comparisons = 0
    seen_pairs: set[tuple[int, int]] = set()

    for block_indexes in blocks.values():
        for offset, left_index in enumerate(block_indexes):
            for right_index in block_indexes[offset + 1 :]:
                pair = (min(left_index, right_index), max(left_index, right_index))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                block_comparisons += 1
                score = similarity_score(sorted_packets[left_index], sorted_packets[right_index])
                if score >= CLUSTER_MERGE_THRESHOLD:
                    union_find.union(left_index, right_index)
                elif CLUSTER_NEAR_MATCH_THRESHOLD <= score < CLUSTER_MERGE_THRESHOLD:
                    near_matches_by_index[left_index].append(
                        {
                            "packet_id": sorted_packets[right_index]["packet_id"],
                            "score": score,
                            "primary_intent": sorted_packets[right_index]["primary_intent"],
                            "session_ref": sorted_packets[right_index].get("session_ref"),
                        }
                    )
                    near_matches_by_index[right_index].append(
                        {
                            "packet_id": sorted_packets[left_index]["packet_id"],
                            "score": score,
                            "primary_intent": sorted_packets[left_index]["primary_intent"],
                            "session_ref": sorted_packets[left_index].get("session_ref"),
                        }
                    )

    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(sorted_packets)):
        groups[union_find.find(index)].append(index)

    latest_timestamp = max(
        (str(packet.get("timestamp")) for packet in sorted_packets if packet.get("timestamp")),
        key=compare_iso_timestamps,
        default=None,
    )
    candidates: list[dict[str, Any]] = []
    unclustered: list[dict[str, Any]] = []

    total_packets_all = len(sorted_packets)
    for root, indexes in groups.items():
        group_packets = [sorted_packets[index] for index in indexes]
        if len(group_packets) == 1:
            unclustered.append(annotate_unclustered_packet(group_packets[0]))
            continue
        timestamps = [str(packet.get("timestamp") or "") for packet in group_packets if packet.get("timestamp")]
        support = {
            "total_packets": len(group_packets),
            "claude_packets": sum(1 for packet in group_packets if packet.get("source") == CLAUDE_SOURCE),
            "codex_packets": sum(1 for packet in group_packets if packet.get("source") == CODEX_SOURCE),
            "total_tool_calls": sum(int(packet.get("support", {}).get("tool_call_count", 0)) for packet in group_packets),
            "unique_workspaces": len({packet.get("workspace") for packet in group_packets if packet.get("workspace")}),
            "recent_packets_7d": recent_packet_count(timestamps, latest_timestamp),
        }
        task_shapes = _top_values([shape for packet in group_packets for shape in packet.get("task_shape", [])], 3)
        tool_signatures = _top_values([tool for packet in group_packets for tool in packet.get("tool_signature", [])], 5)
        artifact_hints = _top_values([hint for packet in group_packets for hint in packet.get("artifact_hints", [])], 3)
        rule_hints = _top_values(
            [item.get("normalized") for packet in group_packets for item in packet.get("repeated_rules", []) if item.get("normalized")],
            3,
        )
        representative_examples = _top_values([packet.get("primary_intent") for packet in group_packets if packet.get("primary_intent")], 2)
        if len(representative_examples) < 2:
            snippets = _top_values(
                [snippet for packet in group_packets for snippet in packet.get("representative_snippets", []) if snippet],
                2,
            )
            for snippet in snippets:
                if snippet not in representative_examples:
                    representative_examples.append(snippet)
                if len(representative_examples) >= 2:
                    break
        session_refs = [packet.get("session_ref") for packet in group_packets if packet.get("session_ref")]
        nearest_values: list[dict[str, Any]] = []
        for index in indexes:
            nearest_values.extend(near_matches_by_index.get(index, []))
        nearest = sorted(
            _dedupe_matches(nearest_values),
            key=lambda item: (float(item["score"]), str(item["packet_id"])),
            reverse=True,
        )[:3]
        research_targets = build_research_targets(
            group_packets,
            near_matches=nearest,
            packet_lookup=packet_lookup,
            limit=DEFAULT_RESEARCH_REF_LIMIT,
        )
        candidate = {
            "candidate_id": group_packets[0]["packet_id"].replace(":", "-"),
            "label": candidate_label(
                {
                    "common_task_shapes": task_shapes,
                    "artifact_hints": artifact_hints,
                    "rule_hints": rule_hints,
                    "primary_intent": group_packets[0].get("primary_intent"),
                }
            ),
            "score": 0.0,
            "support": support,
            "common_task_shapes": task_shapes,
            "common_tool_signatures": tool_signatures,
            "artifact_hints": artifact_hints,
            "rule_hints": rule_hints,
            "representative_examples": representative_examples,
            "session_refs": session_refs,
            "near_matches": nearest,
            "research_targets": research_targets,
            "evidence_items": build_evidence_items(group_packets),
        }
        candidate["score"] = candidate_score(support)
        candidate.update(build_candidate_quality(candidate, total_packets_all=total_packets_all))
        candidate["research_brief"] = build_research_brief(candidate)
        candidates.append(candidate)

    candidates.sort(key=candidate_sort_key, reverse=True)
    unclustered.sort(key=lambda packet: compare_iso_timestamps(packet.get("timestamp")), reverse=True)
    return candidates, unclustered, {"block_count": len(blocks), "block_comparisons": block_comparisons}


def _top_values(values: list[Any], limit: int) -> list[Any]:
    counts = defaultdict(int)
    ordered: list[Any] = []
    for value in values:
        if value is None:
            continue
        counts[value] += 1
        if value not in ordered:
            ordered.append(value)
    ordered.sort(key=lambda item: (counts[item], str(item)), reverse=True)
    return ordered[:limit]


def _dedupe_matches(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for value in values:
        packet_id = str(value.get("packet_id"))
        if packet_id in seen:
            continue
        seen.add(packet_id)
        deduped.append(value)
    return deduped


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        workspace = None if args.all_sessions else resolve_workspace(args.workspace)
        claude_root = Path(args.claude_root).expanduser().resolve()
        codex_history_file = Path(args.codex_history_file).expanduser().resolve()
        codex_sessions_root = Path(args.codex_sessions_root).expanduser().resolve()

        claude_packets, claude_status = read_claude_packets(claude_root, workspace, args.gap_hours)
        codex_packets, codex_status = read_codex_packets(codex_history_file, codex_sessions_root, workspace)
        all_packets = claude_packets + codex_packets

        initial_window = prepare_window_result(all_packets, args.days)
        effective_window = initial_window
        adaptive_expanded = False
        adaptive_reason = None
        if not args.all_sessions:
            should_expand, adaptive_reason = adaptive_window_decision(initial_window, args.days)
            if should_expand:
                effective_window = prepare_window_result(all_packets, WORKSPACE_ADAPTIVE_EXPANDED_DAYS)
                adaptive_expanded = True

        all_packets = effective_window["packets"]
        candidates = effective_window["candidates"]
        unclustered = effective_window["unclustered"]
        stats = effective_window["stats"]
        date_window_start = effective_window["date_window_start"]
        top_candidates = candidates[: max(0, args.top_n)]
        limited_unclustered = unclustered[: max(0, args.max_unclustered)]

        payload = {
            "status": "success",
            "source": PREPARE_SOURCE,
            "candidates": top_candidates,
            "unclustered": limited_unclustered,
            "sources": [claude_status, codex_status],
            "summary": {
                "total_packets": len(all_packets),
                "total_candidates": len(candidates),
                "returned_candidates": len(top_candidates),
                "returned_unclustered": len(limited_unclustered),
                "block_count": stats["block_count"],
                "block_comparisons": stats["block_comparisons"],
                "no_sources_available": len(all_packets) == 0,
                "adaptive_window_expanded": adaptive_expanded,
            },
            "config": {
                "days": args.days,
                "effective_days": effective_window["days"],
                "gap_hours": args.gap_hours,
                "top_n": args.top_n,
                "max_unclustered": args.max_unclustered,
                "workspace": str(workspace) if workspace else None,
                "all_sessions": args.all_sessions,
                "observation_mode": "all-sessions" if args.all_sessions else "workspace",
                "date_window_start": date_window_start,
                "adaptive_window": {
                    "enabled": not args.all_sessions,
                    "expanded": adaptive_expanded,
                    "fallback_days": WORKSPACE_ADAPTIVE_EXPANDED_DAYS,
                    "packet_threshold": WORKSPACE_ADAPTIVE_MIN_PACKETS,
                    "candidate_threshold": WORKSPACE_ADAPTIVE_MIN_CANDIDATES,
                    "reason": adaptive_reason if adaptive_expanded else None,
                    "initial_days": initial_window["days"],
                    "initial_packet_count": len(initial_window["packets"]),
                    "initial_candidate_count": len(initial_window["candidates"]),
                },
            },
        }
        if args.dump_intents:
            payload["intent_analysis"] = build_intent_analysis(all_packets)
        emit(payload)
    except Exception as exc:
        emit(error_response(PREPARE_SOURCE, str(exc)))


if __name__ == "__main__":
    main()
