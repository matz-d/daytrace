#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aggregate_core import load_expected_sources, resolve_sources_file_path
from common import LOCAL_TZ, current_platform, emit, ensure_datetime, error_response, resolve_workspace
from derived_store import (
    SLICE_COMPLETE,
    evaluate_slice_completeness,
    get_observations,
    persist_patterns_from_prepare,
)
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
    build_claude_logical_packets,
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
STORE_HYDRATE_TIMEOUT_SEC = 90
COMPARE_LEGACY_OVERLAP_WARNING_THRESHOLD = 0.5

FIDELITY_ORIGINAL = "original"
FIDELITY_APPROXIMATE = "approximate"
FIDELITY_CANONICAL = "canonical"

# v2 target mix:
# - task_shapes: 0.30 (split between shared-shape overlap and exact specific-shape bonus)
# - snippet / intent: 0.25
# - artifacts: 0.20
# - rules: 0.20
# - tools: 0.05
SIMILARITY_WEIGHT_BUDGET = {
    "task_shapes": 0.22,
    "specific_shape_bonus": 0.08,
    "intent": 0.15,
    "snippet": 0.10,
    "artifacts": 0.20,
    "rules": 0.20,
    "tools": 0.05,
}
SIMILARITY_TASK_SHAPES_WEIGHT = SIMILARITY_WEIGHT_BUDGET["task_shapes"]
SIMILARITY_SPECIFIC_SHAPE_BONUS = SIMILARITY_WEIGHT_BUDGET["specific_shape_bonus"]
SIMILARITY_INTENT_WEIGHT = SIMILARITY_WEIGHT_BUDGET["intent"]
SIMILARITY_SNIPPET_WEIGHT = SIMILARITY_WEIGHT_BUDGET["snippet"]
SIMILARITY_ARTIFACT_WEIGHT = SIMILARITY_WEIGHT_BUDGET["artifacts"]
SIMILARITY_RULE_WEIGHT = SIMILARITY_WEIGHT_BUDGET["rules"]
SIMILARITY_TOOL_WEIGHT = SIMILARITY_WEIGHT_BUDGET["tools"]
SIMILARITY_GENERIC_ONLY_PENALTY = 0.08
SIMILARITY_WEIGHT_TOTAL = sum(SIMILARITY_WEIGHT_BUDGET.values())


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
    parser.add_argument(
        "--reference-date",
        default=None,
        help="Override today's date for the observation window cutoff (YYYY-MM-DD). Intended for testing.",
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


def _tag_fidelity(packet: dict[str, Any], fidelity: str) -> dict[str, Any]:
    packet["_fidelity"] = fidelity
    return packet


def read_claude_packets(root: Path, workspace: Path | None, gap_hours: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not root.exists():
        return [], source_status(CLAUDE_SOURCE, "skipped", reason="not_found", root=str(root))

    packets: list[dict[str, Any]] = []
    try:
        jsonl_files = sorted(root.glob("**/*.jsonl"))
        for path in jsonl_files:
            records = load_jsonl(path)
            logical_packets = build_claude_logical_packets(records, gap_hours)
            matched_packets = [
                lp for lp in logical_packets
                if workspace_matches(lp.get("cwd"), workspace)
            ]
            for packet_index, logical_packet in enumerate(matched_packets):
                packet_start = logical_packet.get("started_at")
                session_ref = build_claude_session_ref(str(path), packet_start)
                packets.append(
                    _tag_fidelity(
                        build_packet(
                            packet_id=f"claude:{path.parent.name}:{path.stem}:{packet_index:03d}",
                            source=CLAUDE_SOURCE,
                            session_ref=session_ref,
                            session_id=logical_packet.get("session_id"),
                            workspace=logical_packet.get("cwd"),
                            timestamp=packet_start,
                            user_messages=list(logical_packet.get("user_messages", [])),
                            assistant_messages=list(logical_packet.get("assistant_messages", [])),
                            tools=list(logical_packet.get("tools", [])),
                        ),
                        FIDELITY_ORIGINAL,
                    )
                )
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
            packet = _tag_fidelity(
                build_packet(
                    packet_id=f"codex:{session_id}",
                    source=CODEX_SOURCE,
                    session_ref=build_codex_session_ref(session_id, start_timestamp),
                    session_id=session_id,
                    workspace=str(cwd) if cwd else None,
                    timestamp=start_timestamp or None,
                    user_messages=user_messages,
                    assistant_messages=assistant_messages,
                    tools=tools,
                ),
                FIDELITY_ORIGINAL,
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
    latest_by_key: dict[tuple[str, ...], dict[str, Any]] = {}

    def observation_key(observation: dict[str, Any]) -> tuple[str, ...]:
        source_name = str(observation.get("source_name") or "")
        event_type = str(observation.get("event_type") or "")
        details = observation.get("details", {})
        if not isinstance(details, dict):
            details = {}
        occurred_at = str(observation.get("occurred_at") or "")
        if source_name == CLAUDE_SOURCE:
            file_path = str(details.get("file_path") or details.get("session_id") or observation.get("event_fingerprint") or "")
            return (source_name, event_type, file_path, occurred_at)
        if source_name == CODEX_SOURCE:
            session_id = str(details.get("session_id") or observation.get("event_fingerprint") or "")
            return (source_name, event_type, session_id, occurred_at)
        return (source_name, event_type, str(observation.get("event_fingerprint") or ""))

    for observation in observations:
        key = observation_key(observation)
        current = latest_by_key.get(key)
        if current is None:
            latest_by_key[key] = observation
            continue
        current_collected = compare_iso_timestamps(current.get("collected_at"))
        candidate_collected = compare_iso_timestamps(observation.get("collected_at"))
        if candidate_collected > current_collected:
            latest_by_key[key] = observation
            continue
        if candidate_collected == current_collected and int(observation.get("observation_id") or 0) > int(current.get("observation_id") or 0):
            latest_by_key[key] = observation
    return sorted(latest_by_key.values(), key=lambda item: int(item.get("observation_id") or 0))


def _append_unique_texts(bucket: list[str], values: list[Any]) -> None:
    for value in values:
        text = str(value or "").strip()
        if text and text not in bucket:
            bucket.append(text)


def _stored_skill_miner_packet(value: Any, *, source_name: str, fallback_workspace: str | None = None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    packet_id = str(value.get("packet_id") or "").strip()
    session_ref = str(value.get("session_ref") or "").strip()
    timestamp = str(value.get("timestamp") or "").strip()
    if not packet_id or not session_ref or not timestamp:
        return None
    packet = dict(value)
    packet["source"] = source_name
    if fallback_workspace and not packet.get("workspace"):
        packet["workspace"] = fallback_workspace
    packet["_fidelity"] = str(packet.get("_fidelity") or FIDELITY_CANONICAL)
    return packet


def _packet_from_claude_observation(observation: dict[str, Any]) -> list[dict[str, Any]]:
    details = observation.get("details", {})
    if not isinstance(details, dict):
        details = {}
    session_id = str(details.get("session_id") or "").strip() or None
    file_path = str(details.get("file_path") or "").strip()
    summary = str(observation.get("summary") or "")
    summary_prefix = "Claude session: "
    first_prompt = summary[len(summary_prefix) :] if summary.startswith(summary_prefix) else summary
    workspace = str(details.get("cwd") or observation.get("workspace") or "")
    logical_packets = details.get("logical_packets")
    if isinstance(logical_packets, list) and logical_packets:
        rebuilt_packets: list[dict[str, Any]] = []
        for packet_index, logical_packet in enumerate(logical_packets):
            if not isinstance(logical_packet, dict):
                continue
            stored_packet = _stored_skill_miner_packet(
                logical_packet.get("skill_miner_packet"),
                source_name=CLAUDE_SOURCE,
                fallback_workspace=workspace or None,
            )
            if stored_packet is not None:
                rebuilt_packets.append(stored_packet)
                continue
            user_messages: list[str] = []
            assistant_messages: list[str] = []
            tools: list[str] = []
            user_highlights = logical_packet.get("user_highlights")
            if isinstance(user_highlights, list):
                _append_unique_texts(user_messages, user_highlights)
            assistant_highlights = logical_packet.get("assistant_highlights")
            if isinstance(assistant_highlights, list):
                _append_unique_texts(assistant_messages, assistant_highlights)
            assistant_summary = str(logical_packet.get("assistant_summary") or "").strip()
            if assistant_summary and assistant_summary not in assistant_messages:
                assistant_messages.append(assistant_summary)
            tool_signals = logical_packet.get("tool_signals")
            if isinstance(tool_signals, list):
                tools.extend(str(item).strip() for item in tool_signals if str(item or "").strip())
            if not user_messages and first_prompt:
                user_messages.append(first_prompt)
            packet_start = str(logical_packet.get("started_at") or observation["occurred_at"])
            rebuilt_packets.append(
                _tag_fidelity(
                    build_packet(
                        packet_id=f"claude-store:{session_id or observation['event_fingerprint']}:{packet_index:03d}",
                        source=CLAUDE_SOURCE,
                        session_ref=build_claude_session_ref(
                            file_path or f"store:{session_id or observation['event_fingerprint']}",
                            packet_start,
                        ),
                        session_id=str(logical_packet.get("session_id") or session_id or "").strip() or None,
                        workspace=str(logical_packet.get("cwd") or workspace or ""),
                        timestamp=packet_start,
                        user_messages=user_messages,
                        assistant_messages=assistant_messages,
                        tools=tools,
                    ),
                    FIDELITY_APPROXIMATE,
                )
            )
        if rebuilt_packets:
            return rebuilt_packets

    user_messages: list[str] = []
    user_highlights = details.get("user_highlights")
    if isinstance(user_highlights, list):
        _append_unique_texts(user_messages, user_highlights)
    elif not user_messages:
        highlights = details.get("highlights")
        if isinstance(highlights, list):
            _append_unique_texts(user_messages, highlights)
    if not user_messages and first_prompt:
        user_messages.append(first_prompt)

    assistant_messages: list[str] = []
    assistant_highlights = details.get("assistant_highlights")
    if isinstance(assistant_highlights, list):
        _append_unique_texts(assistant_messages, assistant_highlights)
    assistant_summary = str(details.get("assistant_summary") or "").strip()
    if assistant_summary and assistant_summary not in assistant_messages:
        assistant_messages.append(assistant_summary)

    session_ref = build_claude_session_ref(
        file_path or f"store:{session_id or observation['event_fingerprint']}",
        str(observation["occurred_at"]),
    )
    return [
        _tag_fidelity(
            build_packet(
                packet_id=f"claude-store:{session_id or observation['event_fingerprint']}",
                source=CLAUDE_SOURCE,
                session_ref=session_ref,
                session_id=session_id,
                workspace=workspace,
                timestamp=str(observation["occurred_at"]),
                user_messages=user_messages,
                assistant_messages=assistant_messages,
                tools=[],
            ),
            FIDELITY_APPROXIMATE,
        )
    ]


def _packet_from_codex_observations(observations: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(observations, key=lambda item: compare_iso_timestamps(item.get("occurred_at")))
    anchor = ordered[-1]
    for observation in ordered:
        details = observation.get("details", {})
        if not isinstance(details, dict):
            continue
        stored_packet = _stored_skill_miner_packet(
            details.get("skill_miner_packet"),
            source_name=CODEX_SOURCE,
            fallback_workspace=str(details.get("cwd") or "").strip() or None,
        )
        if stored_packet is not None:
            return stored_packet

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
                _append_unique_texts(user_messages, user_highlights)
            assistant_highlights = details.get("assistant_highlights")
            if isinstance(assistant_highlights, list):
                _append_unique_texts(assistant_messages, assistant_highlights)
            if not user_messages and not assistant_messages:
                summary = str(observation.get("summary") or "").strip()
                if summary:
                    user_messages.append(summary)
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

    timestamp = earliest_iso_timestamp(timestamps) or str(anchor["occurred_at"])
    session_ref = build_codex_session_ref(session_id or f"store-{anchor['event_fingerprint']}", timestamp)
    return _tag_fidelity(
        build_packet(
            packet_id=f"codex-store:{session_id or anchor['event_fingerprint']}",
            source=CODEX_SOURCE,
            session_ref=session_ref,
            session_id=session_id,
            workspace=workspace,
            timestamp=timestamp,
            user_messages=user_messages,
            assistant_messages=assistant_messages,
            tools=tools,
        ),
        FIDELITY_APPROXIMATE,
    )


def read_store_packets(
    store_path: Path,
    *,
    workspace: Path | None,
    all_sessions: bool,
    max_days: int,
    reference_now: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    effective_now = reference_now or datetime.now(timezone.utc).astimezone()
    since_date, _until_date = _store_slice_bounds(reference_now=effective_now, days=max_days)
    observations = get_observations(
        store_path,
        workspace=workspace,
        since=since_date,
        all_sessions=all_sessions,
        source_names=[CLAUDE_SOURCE, CODEX_SOURCE],
    )
    deduped_observations = _dedupe_observations(observations)
    claude_observations = [observation for observation in deduped_observations if observation["source_name"] == CLAUDE_SOURCE]
    codex_observations = [observation for observation in deduped_observations if observation["source_name"] == CODEX_SOURCE]

    packets: list[dict[str, Any]] = []
    claude_packet_count = 0
    for observation in claude_observations:
        claude_packets = _packet_from_claude_observation(observation)
        packets.extend(claude_packets)
        claude_packet_count += len(claude_packets)
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
            packets_count=claude_packet_count,
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


def _is_store_slice_sufficient(
    packets: list[dict[str, Any]],
    completeness: dict[str, Any] | None,
) -> bool:
    return bool(packets) and completeness is not None and completeness["status"] == SLICE_COMPLETE


def _store_slice_bounds(*, reference_now: datetime, days: int) -> tuple[str, str]:
    local_now = reference_now.astimezone()
    # Add 1-day buffer on both ends to capture data whose local date
    # differs from LOCAL_TZ date due to timezone offsets.
    # The precise filtering is handled by filter_packets_by_days.
    start_date = (local_now - timedelta(days=days + 1)).date().isoformat()
    end_date = (local_now + timedelta(days=1)).date().isoformat()
    return start_date, end_date


def _hydrate_store_slice(
    store_path: Path,
    *,
    workspace: Path,
    all_sessions: bool,
    since: str,
    until: str,
    sources_file: str | None,
) -> None:
    # We intentionally allow overlapping hydrate windows here.
    # `evaluate_slice_completeness()` already reuses broader covering slices before hydration,
    # and `read_store_packets()` collapses overlapping observations across source_run boundaries.
    command = [
        "python3",
        str(SCRIPT_DIR / "aggregate.py"),
        "--workspace",
        str(workspace),
        "--since",
        since,
        "--until",
        until,
        "--store-path",
        str(store_path),
        "--source",
        CLAUDE_SOURCE,
        "--source",
        CODEX_SOURCE,
    ]
    if sources_file:
        command.extend(["--sources-file", str(resolve_sources_file_path(sources_file, default_sources_file=DEFAULT_SOURCES_FILE))])
    if all_sessions:
        command.append("--all-sessions")
    try:
        completed = subprocess.run(
            command,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=STORE_HYDRATE_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"skill-miner store hydration timed out after {STORE_HYDRATE_TIMEOUT_SEC}s") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        message = stderr or stdout or "no aggregate output"
        raise RuntimeError(f"skill-miner store hydration failed: {message}")


def _evaluate_store_slice_completeness(
    store_path: Path,
    *,
    workspace: Path | None,
    expected_sources_workspace: Path,
    all_sessions: bool,
    since: str,
    until: str,
    sources_file: str | None,
) -> dict[str, Any] | None:
    """Return completeness metadata for the current store slice."""
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
        return None
    return evaluate_slice_completeness(
        store_path,
        workspace=workspace,
        since=since,
        until=until,
        all_sessions=all_sessions,
        expected_source_names=expected_names,
        expected_fingerprints=expected_fingerprints or None,
    )


def _should_persist_patterns(
    *,
    selected_input_source: str,
    source_statuses: list[dict[str, Any]],
    top_candidates: list[dict[str, Any]],
    no_sources_available: bool,
    store_slice_completeness: dict[str, Any] | None,
) -> tuple[bool, str | None]:
    if not top_candidates:
        return False, "no_candidates"
    if no_sources_available:
        return False, "no_sources_available"
    unsafe_sources = [str(status.get("name") or "unknown") for status in source_statuses if status.get("status") != "success"]
    if unsafe_sources:
        return False, f"source_status_not_success:{','.join(sorted(unsafe_sources))}"
    if selected_input_source == "store":
        if store_slice_completeness is None:
            return False, "store_slice_unvalidated"
        if store_slice_completeness.get("status") != SLICE_COMPLETE:
            return False, f"store_slice_{store_slice_completeness.get('status', 'unknown')}"
    return True, None


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


def filter_packets_by_days(packets: list[dict[str, Any]], days: int, reference_date: date | None = None) -> tuple[list[dict[str, Any]], str | None]:
    if days <= 0:
        raise ValueError("--days must be a positive integer")
    today = reference_date if reference_date is not None else datetime.now(LOCAL_TZ).date()
    threshold_date = today - timedelta(days=days)
    filtered: list[dict[str, Any]] = []
    for packet in packets:
        timestamp = ensure_datetime(packet.get("timestamp"))
        if timestamp is None:
            continue
        if timestamp.astimezone(LOCAL_TZ).date() >= threshold_date:
            filtered.append(packet)
    return filtered, datetime.combine(threshold_date, datetime.min.time(), tzinfo=LOCAL_TZ).isoformat()


def prepare_window_result(packets: list[dict[str, Any]], days: int, reference_date: date | None = None) -> dict[str, Any]:
    filtered_packets, date_window_start = filter_packets_by_days(packets, days, reference_date)
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
    shared_labels = sorted(selected_set & legacy_set)
    overlap = overlap_score(selected_set, legacy_set)
    jaccard = jaccard_score(selected_set, legacy_set)
    warnings: list[str] = []
    if selected_set and legacy_set and overlap < COMPARE_LEGACY_OVERLAP_WARNING_THRESHOLD:
        warnings.append(
            "store/raw candidate overlap is below threshold "
            f"({overlap:.2f} < {COMPARE_LEGACY_OVERLAP_WARNING_THRESHOLD:.2f})"
        )
    return {
        "selected_candidate_count": len(selected_candidates),
        "legacy_candidate_count": len(legacy_candidates),
        "shared_labels": shared_labels,
        "selected_only_labels": sorted(selected_set - legacy_set),
        "legacy_only_labels": sorted(legacy_set - selected_set),
        "label_overlap_ratio": round(overlap, 3),
        "label_jaccard_ratio": round(jaccard, 3),
        "warnings": warnings,
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
        store_slice_completeness: dict[str, Any] | None = None
        store_hydration: dict[str, Any] | None = None
        if args.input_source in {"store", "auto"}:
            if resolved_store_path is None:
                raise ValueError("--store-path is required when --input-source is store or auto")
            store_window_days = max(max_window_days, args.days)
            store_now = datetime.now(timezone.utc).astimezone()
            store_since, store_until = _store_slice_bounds(reference_now=store_now, days=store_window_days)
            store_packets, store_statuses = read_store_packets(
                resolved_store_path,
                workspace=workspace,
                all_sessions=args.all_sessions,
                max_days=store_window_days,
                reference_now=store_now,
            )
            store_slice_completeness = _evaluate_store_slice_completeness(
                resolved_store_path,
                workspace=workspace,
                expected_sources_workspace=resolved_workspace,
                all_sessions=args.all_sessions,
                since=store_since,
                until=store_until,
                sources_file=args.sources_file,
            )
            store_slice_sufficient = _is_store_slice_sufficient(store_packets, store_slice_completeness)
            before_hydration_status = store_slice_completeness.get("status") if store_slice_completeness else None
            store_hydration = {
                "attempted": False,
                "status": "not_needed" if store_slice_sufficient else "not_attempted",
                "before_status": before_hydration_status,
            }
            if not store_slice_sufficient:
                try:
                    _hydrate_store_slice(
                        resolved_store_path,
                        workspace=resolved_workspace,
                        all_sessions=args.all_sessions,
                        since=store_since,
                        until=store_until,
                        sources_file=args.sources_file,
                    )
                except Exception as hydrate_exc:
                    store_hydration = {
                        "attempted": True,
                        "status": "failed",
                        "before_status": before_hydration_status,
                        "message": str(hydrate_exc),
                    }
                    print(f"[warn] store hydration failed: {hydrate_exc}", file=sys.stderr)
                    if args.input_source == "store":
                        raise
                else:
                    store_packets, store_statuses = read_store_packets(
                        resolved_store_path,
                        workspace=workspace,
                        all_sessions=args.all_sessions,
                        max_days=store_window_days,
                        reference_now=store_now,
                    )
                    store_slice_completeness = _evaluate_store_slice_completeness(
                        resolved_store_path,
                        workspace=workspace,
                        expected_sources_workspace=resolved_workspace,
                        all_sessions=args.all_sessions,
                        since=store_since,
                        until=store_until,
                        sources_file=args.sources_file,
                    )
                    store_slice_sufficient = _is_store_slice_sufficient(store_packets, store_slice_completeness)
                    store_hydration = {
                        "attempted": True,
                        "status": "hydrated",
                        "before_status": before_hydration_status,
                        "after_status": store_slice_completeness.get("status") if store_slice_completeness else None,
                        "sufficient": store_slice_sufficient,
                    }
            if args.input_source == "store":
                all_packets = store_packets
                source_statuses = store_statuses
                selected_input_source = "store"
            elif store_slice_sufficient:
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

        reference_date: date | None = date.fromisoformat(args.reference_date) if args.reference_date else None
        initial_window = prepare_window_result(all_packets, args.days, reference_date)
        effective_window = initial_window
        adaptive_expanded = False
        adaptive_reason = None
        if not args.all_sessions:
            should_expand, adaptive_reason = adaptive_window_decision(initial_window, args.days)
            if should_expand:
                effective_window = prepare_window_result(all_packets, WORKSPACE_ADAPTIVE_EXPANDED_DAYS, reference_date)
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
                "input_fidelity": FIDELITY_APPROXIMATE if selected_input_source == "store" else FIDELITY_ORIGINAL,
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
                **({"store_hydration": store_hydration} if store_hydration else {}),
                **({"input_completeness": store_slice_completeness} if selected_input_source == "store" and store_slice_completeness else {}),
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
            legacy_window = prepare_window_result(legacy_packets, effective_window["days"], reference_date)
            payload["comparison"] = {
                "legacy_input_source": "raw",
                **build_candidate_comparison(top_candidates, legacy_window["candidates"][: max(0, args.top_n)]),
            }
        if args.dump_intents:
            payload["intent_analysis"] = build_intent_analysis(all_packets)
        if resolved_store_path is not None:
            no_sources = payload.get("summary", {}).get("no_sources_available", False)
            should_persist, persist_skip_reason = _should_persist_patterns(
                selected_input_source=selected_input_source,
                source_statuses=source_statuses,
                top_candidates=top_candidates,
                no_sources_available=no_sources,
                store_slice_completeness=store_slice_completeness,
            )
            payload["config"]["pattern_persist"] = {
                "attempted": False,
                "status": "skipped" if not should_persist else "pending",
                **({"reason": persist_skip_reason} if persist_skip_reason else {}),
            }
            if should_persist:
                try:
                    persist_patterns_from_prepare(payload, store_path=resolved_store_path)
                except Exception as persist_exc:
                    payload["config"]["pattern_persist"] = {
                        "attempted": True,
                        "status": "failed",
                        "message": str(persist_exc),
                    }
                    print(f"[warn] pattern persistence failed: {persist_exc}", file=sys.stderr)
                else:
                    payload["config"]["pattern_persist"] = {
                        "attempted": True,
                        "status": "persisted",
                    }
        emit(payload)
    except Exception as exc:
        emit(error_response(PREPARE_SOURCE, str(exc)))


if __name__ == "__main__":
    main()
