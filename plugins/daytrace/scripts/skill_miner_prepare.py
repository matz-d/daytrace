#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import defaultdict
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
    PREPARE_SOURCE,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare compressed skill-miner candidates from raw Claude/Codex history.")
    parser.add_argument("--workspace", default=".", help="Workspace path to filter by. Ignored with --all-sessions.")
    parser.add_argument("--all-sessions", action="store_true", help="Ignore workspace filtering and scan all sessions.")
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
                    tools.extend(_commands_from_text(text))

                packet_start = min(timestamps, default=None)
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
            start_timestamp = str(meta.get("timestamp") or _min_history_timestamp(history_entry.get("timestamps", [])) or (min(timestamps) if timestamps else ""))
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


def _commands_from_text(text: str) -> list[str]:
    from skill_miner_common import extract_known_commands

    return extract_known_commands(text)


def _min_history_timestamp(values: list[Any]) -> str | None:
    best = None
    for value in values:
        current = ensure_datetime(value)
        if current is None:
            continue
        candidate = current.isoformat()
        if best is None or candidate < best:
            best = candidate
    return best


def similarity_score(left: dict[str, Any], right: dict[str, Any]) -> float:
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
                if score >= 0.60:
                    union_find.union(left_index, right_index)
                elif 0.45 <= score < 0.60:
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

    latest_timestamp = max((packet.get("timestamp") for packet in sorted_packets if packet.get("timestamp")), default=None)
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
        candidates, unclustered, stats = cluster_packets(all_packets)
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
            },
            "config": {
                "gap_hours": args.gap_hours,
                "top_n": args.top_n,
                "max_unclustered": args.max_unclustered,
                "workspace": str(workspace) if workspace else None,
                "all_sessions": args.all_sessions,
            },
        }
        emit(payload)
    except Exception as exc:
        emit(error_response(PREPARE_SOURCE, str(exc)))


if __name__ == "__main__":
    main()
