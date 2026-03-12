#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aggregate_core import load_expected_sources, resolve_sources_file_path
from common import current_platform, emit, ensure_datetime, error_response, resolve_workspace
from derived_store import SLICE_COMPLETE, evaluate_slice_completeness, get_observations, persist_patterns_from_prepare
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
from store import resolve_store_path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CLAUDE_ROOT = Path.home() / ".claude" / "projects"
DEFAULT_CODEX_HISTORY = Path.home() / ".codex" / "history.jsonl"
DEFAULT_CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
DEFAULT_SOURCES_FILE = SCRIPT_DIR / "sources.json"
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
    parser.add_argument(
        "--input-source",
        choices=["raw", "store", "auto"],
        default="raw",
        help="Choose raw history, store-backed observations, or auto fallback.",
    )
    parser.add_argument("--store-path", help="Path to the DayTrace SQLite store. Used for store-backed prepare and pattern persistence.")
    parser.add_argument("--sources-file", help="Path to sources.json used when validating store-backed auto input.")
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
    parser.add_argument(
        "--compare-legacy",
        action="store_true",
        help="When using store-backed prepare, also compute a raw-history comparison summary.",
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


def collect_raw_packets(
    *,
    workspace: Path | None,
    claude_root: Path,
    codex_history_file: Path,
    codex_sessions_root: Path,
    gap_hours: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    claude_packets, claude_status = read_claude_packets(claude_root, workspace, gap_hours)
    codex_packets, codex_status = read_codex_packets(codex_history_file, codex_sessions_root, workspace)
    return claude_packets + codex_packets, [claude_status, codex_status]


def _dedupe_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for observation in observations:
        key = (str(observation["source_name"]), str(observation["event_fingerprint"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(observation)
    return deduped


def _packet_from_claude_observation(observation: dict[str, Any]) -> dict[str, Any]:
    details = observation.get("details", {})
    if not isinstance(details, dict):
        details = {}
    session_id = str(details.get("session_id") or "").strip() or None
    file_path = str(details.get("file_path") or "").strip()
    summary = str(observation.get("summary") or "")
    summary_prefix = "Claude session: "
    first_prompt = summary[len(summary_prefix) :] if summary.startswith(summary_prefix) else summary

    user_messages: list[str] = []
    if first_prompt:
        user_messages.append(first_prompt)
    user_highlights = details.get("user_highlights")
    if isinstance(user_highlights, list):
        user_messages.extend(str(item) for item in user_highlights if item)
    elif not user_messages:
        highlights = details.get("highlights")
        if isinstance(highlights, list):
            user_messages.extend(str(item) for item in highlights if item)

    assistant_messages: list[str] = []
    assistant_highlights = details.get("assistant_highlights")
    if isinstance(assistant_highlights, list):
        assistant_messages.extend(str(item) for item in assistant_highlights if item)
    assistant_summary = str(details.get("assistant_summary") or "").strip()
    if assistant_summary:
        assistant_messages.append(assistant_summary)

    session_ref = build_claude_session_ref(
        file_path or f"store:{session_id or observation['event_fingerprint']}",
        str(observation["occurred_at"]),
    )
    return build_packet(
        packet_id=f"claude-store:{session_id or observation['event_fingerprint']}",
        source=CLAUDE_SOURCE,
        session_ref=session_ref,
        session_id=session_id,
        workspace=str(details.get("cwd") or observation.get("workspace") or ""),
        timestamp=str(observation["occurred_at"]),
        user_messages=user_messages,
        assistant_messages=assistant_messages,
        tools=[],
    )


def _packet_from_codex_observations(observations: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(observations, key=lambda item: compare_iso_timestamps(item.get("occurred_at")))
    anchor = ordered[-1]
    session_id = None
    workspace = None
    timestamps: list[str] = []
    user_messages: list[str] = []
    assistant_messages: list[str] = []
    tools: list[str] = []

    for observation in ordered:
        details = observation.get("details", {})
        if not isinstance(details, dict):
            details = {}
        timestamps.append(str(observation["occurred_at"]))
        if session_id is None:
            raw_session_id = str(details.get("session_id") or "").strip()
            session_id = raw_session_id or None
        if workspace is None:
            raw_workspace = str(details.get("cwd") or "").strip()
            workspace = raw_workspace or None

        event_type = str(observation.get("event_type") or "")
        if event_type == "commentary":
            user_highlights = details.get("user_highlights")
            if isinstance(user_highlights, list):
                user_messages.extend(str(item) for item in user_highlights if item)
            assistant_highlights = details.get("assistant_highlights")
            if isinstance(assistant_highlights, list):
                assistant_messages.extend(str(item) for item in assistant_highlights if item)
            summary = str(observation.get("summary") or "").strip()
            if summary:
                user_messages.append(summary)
        elif event_type == "session_meta":
            summary = str(observation.get("summary") or "").strip()
            if summary:
                assistant_messages.append(summary)
        elif event_type == "tool_call":
            tool_items = details.get("tools")
            if isinstance(tool_items, list):
                for tool in tool_items:
                    if not isinstance(tool, dict):
                        continue
                    name = str(tool.get("name") or "").strip().lower()
                    try:
                        count = int(tool.get("count") or 0)
                    except (TypeError, ValueError):
                        count = 0
                    if name and count > 0:
                        tools.extend([name] * count)

    timestamp = max(timestamps, key=compare_iso_timestamps)
    session_ref = build_codex_session_ref(session_id or f"store-{anchor['event_fingerprint']}", timestamp)
    return build_packet(
        packet_id=f"codex-store:{session_id or anchor['event_fingerprint']}",
        source=CODEX_SOURCE,
        session_ref=session_ref,
        session_id=session_id,
        workspace=workspace,
        timestamp=timestamp,
        user_messages=user_messages,
        assistant_messages=assistant_messages,
        tools=tools,
    )


def read_store_packets(
    store_path: Path,
    *,
    workspace: Path | None,
    all_sessions: bool,
    max_days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    threshold = (datetime.now(timezone.utc).astimezone() - timedelta(days=max_days)).isoformat()
    observations = get_observations(
        store_path,
        workspace=workspace,
        since=threshold,
        all_sessions=all_sessions,
        source_names=[CLAUDE_SOURCE, CODEX_SOURCE],
    )
    deduped_observations = _dedupe_observations(observations)
    claude_observations = [observation for observation in deduped_observations if observation["source_name"] == CLAUDE_SOURCE]
    codex_observations = [observation for observation in deduped_observations if observation["source_name"] == CODEX_SOURCE]

    packets = [_packet_from_claude_observation(observation) for observation in claude_observations]
    codex_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in codex_observations:
        details = observation.get("details", {})
        session_id = None
        if isinstance(details, dict):
            raw_session_id = str(details.get("session_id") or "").strip()
            session_id = raw_session_id or None
        codex_groups[session_id or str(observation["event_fingerprint"])].append(observation)
    for group in codex_groups.values():
        packets.append(_packet_from_codex_observations(group))

    statuses = [
        source_status(
            CLAUDE_SOURCE,
            "success" if claude_observations else "skipped",
            packets_count=len(claude_observations),
            reason=None if claude_observations else "store_empty",
        ),
        source_status(
            CODEX_SOURCE,
            "success" if codex_observations else "skipped",
            packets_count=len(codex_groups),
            reason=None if codex_observations else "store_empty",
        ),
    ]
    return packets, statuses


SKILL_MINER_EXPECTED_SOURCES = {CLAUDE_SOURCE, CODEX_SOURCE}



def _store_slice_sufficient(
    store_path: Path,
    *,
    workspace: Path | None,
    expected_sources_workspace: Path,
    all_sessions: bool,
    max_days: int,
    sources_file: str | None,
) -> bool:
    """Check if auto mode can safely reuse the current store slice."""
    threshold = (datetime.now(timezone.utc).astimezone() - timedelta(days=max_days)).isoformat()
    resolved_sources_file = resolve_sources_file_path(
        sources_file,
        default_sources_file=DEFAULT_SOURCES_FILE,
    )
    try:
        expected_names, expected_fingerprints = load_expected_sources(
            resolved_sources_file,
            platform_name=current_platform(),
            workspace=expected_sources_workspace,
            script_dir=SCRIPT_DIR,
            restrict_to_names=SKILL_MINER_EXPECTED_SOURCES,
        )
    except Exception as exc:
        print(f"[warn] failed to load sources from {resolved_sources_file}: {exc}", file=sys.stderr)
        return False
    completeness = evaluate_slice_completeness(
        store_path,
        workspace=workspace,
        since=threshold,
        all_sessions=all_sessions,
        expected_source_names=expected_names,
        expected_fingerprints=expected_fingerprints or None,
    )
    return completeness["status"] == SLICE_COMPLETE


def _build_similarity_features(packet: dict[str, Any]) -> dict[str, Any]:
    workspace = packet.get("workspace")
    snippets = packet.get("representative_snippets", [])
    snippet_tokens = set().union(*(tokenize(compact_snippet(item, workspace)) for item in snippets)) if snippets else set()
    intent_tokens = tokenize(str(packet.get("primary_intent") or ""))
    task_shape_set = set(packet.get("task_shape", []))
    tool_set = set(packet.get("tool_signature", []))
    task_shapes_strs = [str(shape) for shape in packet.get("task_shape", []) if shape]
    primary_non_generic = next((shape for shape in task_shapes_strs if shape not in GENERIC_TASK_SHAPES), "")
    rule_names = {
        str(item.get("normalized") or "")
        for item in packet.get("repeated_rules", [])
        if isinstance(item, dict) and item.get("normalized")
    }
    return {
        "snippet_tokens": snippet_tokens,
        "intent_tokens": intent_tokens,
        "task_shape_set": task_shape_set,
        "tool_set": tool_set,
        "artifact_set": set(packet.get("artifact_hints", [])),
        "rule_names": rule_names,
        "primary_non_generic_shape": primary_non_generic,
        "generic_task_only": bool(task_shape_set) and task_shape_set <= GENERIC_TASK_SHAPES,
        "generic_tool_only": bool(tool_set) and tool_set <= GENERIC_TOOL_SIGNATURES,
    }


def _similarity_score_from_features(left: dict[str, Any], right: dict[str, Any]) -> float:
    snippet = jaccard_score(left["snippet_tokens"], right["snippet_tokens"])
    intent = jaccard_score(left["intent_tokens"], right["intent_tokens"])
    task_shapes = overlap_score(left["task_shape_set"], right["task_shape_set"])
    tools = jaccard_score(left["tool_set"], right["tool_set"])
    artifacts = overlap_score(left["artifact_set"], right["artifact_set"])
    rules = overlap_score(left["rule_names"], right["rule_names"])
    left_specific = left["primary_non_generic_shape"]
    same_specific_shape = 1.0 if left_specific and left_specific == right["primary_non_generic_shape"] else 0.0
    generic_task_only = left["generic_task_only"] and right["generic_task_only"]
    generic_tool_only = left["generic_tool_only"] and right["generic_tool_only"]
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


def similarity_score(left: dict[str, Any], right: dict[str, Any]) -> float:
    return _similarity_score_from_features(
        _build_similarity_features(left),
        _build_similarity_features(right),
    )


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
    features_by_index = [_build_similarity_features(packet) for packet in sorted_packets]
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
                score = _similarity_score_from_features(features_by_index[left_index], features_by_index[right_index])
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


def build_candidate_comparison(selected_candidates: list[dict[str, Any]], legacy_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    selected_labels = [str(candidate.get("label") or "") for candidate in selected_candidates if candidate.get("label")]
    legacy_labels = [str(candidate.get("label") or "") for candidate in legacy_candidates if candidate.get("label")]
    selected_set = set(selected_labels)
    legacy_set = set(legacy_labels)
    return {
        "selected_candidate_count": len(selected_candidates),
        "legacy_candidate_count": len(legacy_candidates),
        "shared_labels": sorted(selected_set & legacy_set),
        "selected_only_labels": sorted(selected_set - legacy_set),
        "legacy_only_labels": sorted(legacy_set - selected_set),
    }


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        resolved_workspace = resolve_workspace(args.workspace)
        workspace = None if args.all_sessions else resolved_workspace
        claude_root = Path(args.claude_root).expanduser().resolve()
        codex_history_file = Path(args.codex_history_file).expanduser().resolve()
        codex_sessions_root = Path(args.codex_sessions_root).expanduser().resolve()
        max_window_days = WORKSPACE_ADAPTIVE_EXPANDED_DAYS if not args.all_sessions else args.days
        resolved_store_path = resolve_store_path(args.store_path) if args.store_path else None

        selected_input_source = "raw"
        source_statuses: list[dict[str, Any]] = []
        if args.input_source in {"store", "auto"}:
            if resolved_store_path is None:
                raise ValueError("--store-path is required when --input-source is store or auto")
            store_packets, store_statuses = read_store_packets(
                resolved_store_path,
                workspace=workspace,
                all_sessions=args.all_sessions,
                max_days=max(max_window_days, args.days),
            )
            if args.input_source == "store":
                all_packets = store_packets
                source_statuses = store_statuses
                selected_input_source = "store"
            elif store_packets and _store_slice_sufficient(
                resolved_store_path,
                workspace=workspace,
                expected_sources_workspace=resolved_workspace,
                all_sessions=args.all_sessions,
                max_days=max(max_window_days, args.days),
                sources_file=args.sources_file,
            ):
                all_packets = store_packets
                source_statuses = store_statuses
                selected_input_source = "store"
            else:
                all_packets, source_statuses = collect_raw_packets(
                    workspace=workspace,
                    claude_root=claude_root,
                    codex_history_file=codex_history_file,
                    codex_sessions_root=codex_sessions_root,
                    gap_hours=args.gap_hours,
                )
                selected_input_source = "raw"
        else:
            all_packets, source_statuses = collect_raw_packets(
                workspace=workspace,
                claude_root=claude_root,
                codex_history_file=codex_history_file,
                codex_sessions_root=codex_sessions_root,
                gap_hours=args.gap_hours,
            )

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
            "sources": source_statuses,
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
                "input_source": selected_input_source,
                "input_fidelity": "approximate" if selected_input_source == "store" else "original",
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
        if args.compare_legacy and selected_input_source == "store":
            legacy_packets, _legacy_statuses = collect_raw_packets(
                workspace=workspace,
                claude_root=claude_root,
                codex_history_file=codex_history_file,
                codex_sessions_root=codex_sessions_root,
                gap_hours=args.gap_hours,
            )
            legacy_window = prepare_window_result(legacy_packets, effective_window["days"])
            payload["comparison"] = {
                "legacy_input_source": "raw",
                **build_candidate_comparison(top_candidates, legacy_window["candidates"][: max(0, args.top_n)]),
            }
        if args.dump_intents:
            payload["intent_analysis"] = build_intent_analysis(all_packets)
        if resolved_store_path is not None:
            no_sources = payload.get("summary", {}).get("no_sources_available", False)
            has_candidates = len(top_candidates) > 0
            all_sources_failed = all(
                s.get("status") != "success" for s in source_statuses
            ) if source_statuses else True
            should_persist = has_candidates and not no_sources and not all_sources_failed
            if should_persist:
                try:
                    persist_patterns_from_prepare(payload, store_path=resolved_store_path)
                except Exception as persist_exc:
                    print(f"[warn] pattern persistence failed: {persist_exc}", file=sys.stderr)
        emit(payload)
    except Exception as exc:
        emit(error_response(PREPARE_SOURCE, str(exc)))


if __name__ == "__main__":
    main()
