#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from common import (
    apply_limit,
    emit,
    error_response,
    extract_text,
    is_within_path,
    parse_datetime,
    resolve_workspace,
    skipped_response,
    success_response,
    summarize_text,
    within_range,
)


SOURCE_NAME = "codex-history"
DEFAULT_HISTORY = Path.home() / ".codex" / "history.jsonl"
DEFAULT_SESSIONS = Path.home() / ".codex" / "sessions"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit Codex session summaries as DayTrace events.")
    parser.add_argument("--workspace", default=".", help="Workspace path to filter by. Ignored with --all-sessions.")
    parser.add_argument("--since", help="Start datetime or date (inclusive).")
    parser.add_argument("--until", help="End datetime or date (inclusive).")
    parser.add_argument("--all-sessions", action="store_true", help="Ignore workspace filtering and scan all sessions.")
    parser.add_argument("--limit", type=int, help="Maximum number of events to return.")
    parser.add_argument("--history-file", default=str(DEFAULT_HISTORY), help="Codex history.jsonl path.")
    parser.add_argument("--sessions-root", default=str(DEFAULT_SESSIONS), help="Codex sessions root.")
    return parser


def load_history_index(path: Path, start, end) -> dict[str, dict[str, object]]:
    sessions: dict[str, dict[str, object]] = {}
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            timestamp = record.get("ts")
            if not within_range(timestamp, start, end):
                continue

            session_id = record.get("session_id")
            if not session_id:
                continue

            session = sessions.setdefault(session_id, {"timestamps": [], "user_excerpts": []})
            session["timestamps"].append(timestamp)
            excerpt = summarize_text(record.get("text"), 180)
            if excerpt and excerpt not in session["user_excerpts"] and len(session["user_excerpts"]) < 3:
                session["user_excerpts"].append(excerpt)
    return sessions


def session_meta_from_rollout(path: Path) -> dict[str, object] | None:
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "session_meta":
                continue
            payload = record.get("payload", {})
            if payload.get("id"):
                return payload
    return None


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        history_file = Path(args.history_file).expanduser().resolve()
        sessions_root = Path(args.sessions_root).expanduser().resolve()
        workspace = None if args.all_sessions else resolve_workspace(args.workspace)
        start = parse_datetime(args.since, bound="start")
        end = parse_datetime(args.until, bound="end")

        if not history_file.exists() or not sessions_root.exists():
            emit(skipped_response(SOURCE_NAME, "not_found", history_file=str(history_file), sessions_root=str(sessions_root)))
            return

        full_history_index = load_history_index(history_file, None, None)
        filtered_history_index = load_history_index(history_file, start, end)
        candidate_sessions = set(full_history_index.keys())

        rollout_files = sorted(sessions_root.glob("**/rollout-*.jsonl"))
        if not rollout_files:
            emit(skipped_response(SOURCE_NAME, "not_found", history_file=str(history_file), sessions_root=str(sessions_root)))
            return

        mapped_rollouts: dict[str, Path] = {}
        for rollout in rollout_files:
            meta = session_meta_from_rollout(rollout)
            if not meta:
                continue
            session_id = meta.get("id")
            if not session_id:
                continue
            if candidate_sessions and session_id not in candidate_sessions:
                continue
            mapped_rollouts[session_id] = rollout

        events = []
        for session_id in sorted(candidate_sessions):
            rollout = mapped_rollouts.get(session_id)
            if rollout is None:
                continue

            history_entry = filtered_history_index.get(session_id) or full_history_index.get(
                session_id, {"timestamps": [], "user_excerpts": []}
            )
            tool_counter: Counter[str] = Counter()
            assistant_excerpts: list[str] = []
            meta_details: dict[str, object] | None = None
            commentary_timestamps: list[str] = []
            tool_timestamps: list[str] = []

            with rollout.open(encoding="utf-8") as handle:
                for raw_line in handle:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        record = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue

                    record_type = record.get("type")
                    timestamp = record.get("timestamp")

                    if record_type == "session_meta":
                        payload = record.get("payload", {})
                        session_cwd = payload.get("cwd")
                        if workspace and not is_within_path(session_cwd, workspace):
                            meta_details = None
                            break
                        meta_details = payload
                        continue

                    if record_type == "event_msg" and record.get("payload", {}).get("type") == "user_message":
                        if within_range(timestamp, start, end):
                            commentary_timestamps.append(timestamp)
                        continue

                    if record_type != "response_item":
                        continue

                    payload = record.get("payload", {})
                    payload_type = payload.get("type")
                    if payload_type == "message" and payload.get("role") == "assistant":
                        if within_range(timestamp, start, end):
                            commentary_timestamps.append(timestamp)
                            excerpt = summarize_text(extract_text(payload.get("content")), 180)
                            if excerpt and excerpt not in assistant_excerpts and len(assistant_excerpts) < 3:
                                assistant_excerpts.append(excerpt)
                    elif payload_type == "function_call":
                        if within_range(timestamp, start, end):
                            tool_counter[payload.get("name", "unknown")] += 1
                            tool_timestamps.append(timestamp)

            if meta_details is None:
                continue

            session_timestamp = meta_details.get("timestamp") or (history_entry["timestamps"][0] if history_entry["timestamps"] else None)
            session_summary = f"Codex session in {meta_details.get('cwd', 'unknown workspace')}"
            if within_range(session_timestamp, start, end) or (start is None and end is None):
                events.append(
                    {
                        "source": SOURCE_NAME,
                        "timestamp": session_timestamp,
                        "type": "session_meta",
                        "summary": summarize_text(session_summary, 140),
                        "details": {
                            "session_id": session_id,
                            "cwd": meta_details.get("cwd"),
                            "originator": meta_details.get("originator"),
                            "cli_version": meta_details.get("cli_version"),
                            "model_provider": meta_details.get("model_provider"),
                            "git": meta_details.get("git"),
                        },
                        "confidence": "medium",
                    }
                )

            commentary_anchor = commentary_timestamps[-1] if commentary_timestamps else session_timestamp
            user_excerpt = history_entry["user_excerpts"][0] if history_entry["user_excerpts"] else "No user prompt captured"
            if commentary_anchor and (within_range(commentary_anchor, start, end) or (start is None and end is None)):
                events.append(
                    {
                        "source": SOURCE_NAME,
                        "timestamp": commentary_anchor,
                        "type": "commentary",
                        "summary": f"Codex commentary: {summarize_text(user_excerpt, 96)}",
                        "details": {
                            "session_id": session_id,
                            "cwd": meta_details.get("cwd"),
                            "user_highlights": history_entry["user_excerpts"],
                            "assistant_highlights": assistant_excerpts,
                        },
                        "confidence": "medium",
                    }
                )

            if tool_counter:
                tool_summary = ", ".join(f"{name} x{count}" for name, count in tool_counter.most_common(5))
                events.append(
                    {
                        "source": SOURCE_NAME,
                        "timestamp": tool_timestamps[-1],
                        "type": "tool_call",
                        "summary": f"Codex tool usage: {tool_summary}",
                        "details": {
                            "session_id": session_id,
                            "cwd": meta_details.get("cwd"),
                            "tools": [{"name": name, "count": count} for name, count in tool_counter.most_common()],
                            "total_calls": sum(tool_counter.values()),
                        },
                        "confidence": "high",
                    }
                )

        events.sort(key=lambda event: event["timestamp"] or "", reverse=True)
        emit(
            success_response(
                SOURCE_NAME,
                apply_limit(events, args.limit),
                workspace=str(workspace) if workspace else None,
                since=args.since,
                until=args.until,
                all_sessions=args.all_sessions,
                scanned_rollouts=len(rollout_files),
            )
        )
    except PermissionError as exc:
        emit(
            skipped_response(
                SOURCE_NAME,
                "permission_denied",
                history_file=str(args.history_file),
                sessions_root=str(args.sessions_root),
                message=str(exc),
            )
        )
    except Exception as exc:
        emit(error_response(SOURCE_NAME, str(exc)))


if __name__ == "__main__":
    main()
