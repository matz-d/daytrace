#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from common import emit, ensure_datetime, error_response
from skill_miner_common import (
    DETAIL_SOURCE,
    DEFAULT_GAP_HOURS,
    build_claude_session_ref,
    build_codex_session_ref,
    claude_message_text,
    codex_command_names,
    codex_message_text,
    compact_snippet,
    load_jsonl,
    parse_session_ref,
)


DEFAULT_CODEX_HISTORY = Path.home() / ".codex" / "history.jsonl"
DEFAULT_CODEX_SESSIONS = Path.home() / ".codex" / "sessions"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve session_refs into detailed skill-miner conversation excerpts.")
    parser.add_argument("--refs", nargs="+", required=True, help="One or more session_refs returned by skill_miner_prepare.py.")
    parser.add_argument("--gap-hours", type=int, default=DEFAULT_GAP_HOURS, help="Claude logical session gap used by prepare.")
    parser.add_argument("--codex-sessions-root", default=str(DEFAULT_CODEX_SESSIONS), help="Codex sessions root.")
    parser.add_argument("--codex-history-file", default=str(DEFAULT_CODEX_HISTORY), help="Codex history.jsonl path.")
    return parser


def claude_visible_text(message: object) -> str:
    if not isinstance(message, dict):
        return compact_snippet(str(message), None, 400)
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif item.get("type") == "tool_use":
                name = item.get("name", "tool")
                parts.append(f"{name} tool call")
        return " ".join(part for part in parts if part)
    return claude_message_text(message)


def codex_visible_text(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") in {"output_text", "text", "input_text"} and isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return " ".join(parts)
    return codex_message_text(payload)


def resolve_claude_detail(file_path: Path, epoch: int, gap_hours: int) -> dict[str, Any]:
    records = load_jsonl(file_path)
    packet_records: list[dict[str, Any]] = []
    last_timestamp = None
    last_sidechain = None

    def current_ref() -> str | None:
        if not packet_records:
            return None
        return build_claude_session_ref(str(file_path), packet_records[0].get("timestamp"))

    def flush_if_match() -> dict[str, Any] | None:
        if not packet_records:
            return None
        ref = current_ref()
        if ref != f"claude:{file_path}:{epoch}":
            return None
        messages: list[dict[str, str]] = []
        tools: Counter[str] = Counter()
        workspace = None
        timestamp = str(packet_records[0].get("timestamp") or "")
        for record in packet_records:
            workspace = record.get("cwd") or workspace
            text = claude_visible_text(record.get("message"))
            if not text:
                continue
            role = "user" if record.get("type") == "user" else "assistant"
            messages.append({"role": role, "text": text})
        return {
            "session_ref": ref,
            "source": "claude-history",
            "workspace": workspace,
            "timestamp": timestamp or None,
            "messages": messages,
            "tool_calls": [{"name": name, "count": count} for name, count in tools.most_common()],
        }

    for record in records:
        record_type = record.get("type")
        if record_type not in {"user", "assistant"}:
            continue
        if record.get("isMeta"):
            continue
        current_timestamp = ensure_datetime(record.get("timestamp"))
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
            detail = flush_if_match()
            if detail:
                return detail
            packet_records = []
        packet_records.append(record)
        last_timestamp = current_timestamp
        last_sidechain = current_sidechain

    detail = flush_if_match()
    if detail:
        return detail
    raise ValueError(f"Claude session_ref not found: claude:{file_path}:{epoch}")


def resolve_codex_detail(session_id: str, epoch: int, sessions_root: Path, history_file: Path) -> dict[str, Any]:
    rollout = None
    for path in sorted(sessions_root.glob("**/rollout-*.jsonl")):
        for record in load_jsonl(path):
            if record.get("type") == "session_meta" and record.get("payload", {}).get("id") == session_id:
                rollout = path
                break
        if rollout is not None:
            break
    if rollout is None:
        raise ValueError(f"Codex rollout not found for session_id={session_id}")

    records = load_jsonl(rollout)
    meta = next((record.get("payload", {}) for record in records if record.get("type") == "session_meta"), {})
    ref = build_codex_session_ref(session_id, meta.get("timestamp"))
    if ref != f"codex:{session_id}:{epoch}":
        raise ValueError(f"Codex session_ref not found: codex:{session_id}:{epoch}")

    history_messages: list[str] = []
    if history_file.exists():
        for record in load_jsonl(history_file):
            if record.get("session_id") == session_id:
                text = str(record.get("text") or "")
                if text:
                    history_messages.append(text)

    messages: list[dict[str, str]] = []
    for text in history_messages:
        messages.append({"role": "user", "text": text})

    tool_counter: Counter[str] = Counter()
    for record in records:
        if record.get("type") == "event_msg" and record.get("payload", {}).get("type") == "user_message":
            text = str(record.get("payload", {}).get("message") or "")
            if text:
                messages.append({"role": "user", "text": text})
        elif record.get("type") == "response_item":
            payload = record.get("payload", {})
            payload_type = payload.get("type")
            if payload_type == "message" and payload.get("role") == "assistant":
                text = codex_visible_text(payload)
                if text:
                    messages.append({"role": "assistant", "text": text})
            elif payload_type == "function_call":
                tool_counter.update(codex_command_names(payload))

    return {
        "session_ref": ref,
        "source": "codex-history",
        "workspace": meta.get("cwd"),
        "timestamp": meta.get("timestamp"),
        "messages": messages,
        "tool_calls": [{"name": name, "count": count} for name, count in tool_counter.most_common()],
    }


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        sessions_root = Path(args.codex_sessions_root).expanduser().resolve()
        history_file = Path(args.codex_history_file).expanduser().resolve()
        details: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []

        for session_ref in args.refs:
            try:
                source_type, identifier, epoch = parse_session_ref(session_ref)
                if source_type == "claude":
                    details.append(resolve_claude_detail(Path(identifier), epoch, args.gap_hours))
                else:
                    details.append(resolve_codex_detail(identifier, epoch, sessions_root, history_file))
            except Exception as exc:
                errors.append({"session_ref": session_ref, "message": str(exc)})

        if details:
            emit({"status": "success", "source": DETAIL_SOURCE, "details": details, "errors": errors})
            return
        emit(error_response(DETAIL_SOURCE, "No session_refs could be resolved", errors=errors))
    except Exception as exc:
        emit(error_response(DETAIL_SOURCE, str(exc)))


if __name__ == "__main__":
    main()
