#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from collections import defaultdict
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


SOURCE_NAME = "claude-history"
DEFAULT_ROOT = Path.home() / ".claude" / "projects"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit Claude session summaries as DayTrace events.")
    parser.add_argument("--workspace", default=".", help="Workspace path to filter by. Ignored with --all-sessions.")
    parser.add_argument("--since", help="Start datetime or date (inclusive).")
    parser.add_argument("--until", help="End datetime or date (inclusive).")
    parser.add_argument("--all-sessions", action="store_true", help="Ignore workspace filtering and scan all sessions.")
    parser.add_argument("--limit", type=int, help="Maximum number of events to return.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Claude history root. Defaults to ~/.claude/projects.")
    return parser


def empty_group(path: Path) -> dict[str, object]:
    return {
        "file_path": str(path),
        "session_id": None,
        "cwd": None,
        "is_sidechain": False,
        "timestamps": [],
        "user_excerpts": [],
        "assistant_excerpts": [],
        "message_count": 0,
        "user_count": 0,
        "assistant_count": 0,
    }


def append_excerpt(bucket: list[str], value: str) -> None:
    excerpt = summarize_text(value, 180)
    if excerpt and excerpt not in bucket and len(bucket) < 3:
        bucket.append(excerpt)


def claude_message_text(message: object) -> str:
    if not isinstance(message, dict):
        return extract_text(message)

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        tool_parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
            elif item.get("type") == "tool_use":
                tool_parts.append(f"{item.get('name', 'tool')} tool call")
        if text_parts:
            return " ".join(text_parts)
        if tool_parts:
            return " ".join(tool_parts)
    return extract_text(message)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        root = Path(args.root).expanduser().resolve()
        workspace = None if args.all_sessions else resolve_workspace(args.workspace)
        start = parse_datetime(args.since, bound="start")
        end = parse_datetime(args.until, bound="end")

        if not root.exists():
            emit(skipped_response(SOURCE_NAME, "not_found", root=str(root)))
            return

        session_groups: dict[str, dict[str, object]] = {}
        jsonl_files = sorted(root.glob("**/*.jsonl"))
        if not jsonl_files:
            emit(skipped_response(SOURCE_NAME, "not_found", root=str(root)))
            return

        for path in jsonl_files:
            group_key = str(path)
            group = session_groups.setdefault(group_key, empty_group(path))
            with path.open(encoding="utf-8") as handle:
                for raw_line in handle:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        record = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue

                    record_type = record.get("type")
                    if record_type not in {"user", "assistant"}:
                        continue
                    if record.get("isMeta"):
                        continue

                    timestamp = record.get("timestamp")
                    if not within_range(timestamp, start, end):
                        continue

                    cwd = record.get("cwd")
                    if workspace and not is_within_path(cwd, workspace):
                        continue

                    group["session_id"] = record.get("sessionId") or group["session_id"]
                    group["cwd"] = cwd or group["cwd"]
                    group["is_sidechain"] = bool(record.get("isSidechain")) or bool(group["is_sidechain"])
                    group["timestamps"].append(timestamp)
                    group["message_count"] = int(group["message_count"]) + 1

                    message_text = claude_message_text(record.get("message"))
                    if record_type == "user":
                        group["user_count"] = int(group["user_count"]) + 1
                        append_excerpt(group["user_excerpts"], message_text)
                    else:
                        group["assistant_count"] = int(group["assistant_count"]) + 1
                        append_excerpt(group["assistant_excerpts"], message_text)

        events = []
        for group in session_groups.values():
            timestamps = sorted(group["timestamps"])
            if not timestamps:
                continue

            first_user = group["user_excerpts"][0] if group["user_excerpts"] else "No user prompt captured"
            summary = f"Claude session: {summarize_text(first_user, 96)}"
            details = {
                "cwd": group["cwd"],
                "session_id": group["session_id"],
                "file_path": group["file_path"],
                "is_sidechain": group["is_sidechain"],
                "message_count": group["message_count"],
                "user_message_count": group["user_count"],
                "assistant_message_count": group["assistant_count"],
                "highlights": group["user_excerpts"] + group["assistant_excerpts"],
            }
            if group["assistant_excerpts"]:
                details["assistant_summary"] = group["assistant_excerpts"][-1]

            events.append(
                {
                    "source": SOURCE_NAME,
                    "timestamp": timestamps[-1],
                    "type": "session_summary",
                    "summary": summary,
                    "details": details,
                    "confidence": "medium",
                }
            )

        events.sort(key=lambda event: event["timestamp"], reverse=True)
        emit(
            success_response(
                SOURCE_NAME,
                apply_limit(events, args.limit),
                workspace=str(workspace) if workspace else None,
                since=args.since,
                until=args.until,
                all_sessions=args.all_sessions,
                scanned_files=len(jsonl_files),
            )
        )
    except PermissionError as exc:
        emit(skipped_response(SOURCE_NAME, "permission_denied", root=str(args.root), message=str(exc)))
    except Exception as exc:
        emit(error_response(SOURCE_NAME, str(exc)))


if __name__ == "__main__":
    main()
