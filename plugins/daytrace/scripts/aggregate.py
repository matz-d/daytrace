#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from common import ensure_datetime, isoformat, parse_datetime, resolve_workspace

SCRIPT_DIR = Path(__file__).resolve().parent

GROUP_WINDOW_MINUTES = 15
EVIDENCE_LIMIT = 5
AI_HISTORY_SOURCES = {"claude-history", "codex-history"}
REQUIRED_SOURCE_FIELDS = {
    "name",
    "command",
    "required",
    "timeout_sec",
    "platforms",
    "supports_date_range",
    "supports_all_sessions",
}
REQUIRED_EVENT_FIELDS = {"source", "timestamp", "type", "summary", "details", "confidence"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate DayTrace source CLIs into a reusable timeline JSON.")
    parser.add_argument("--workspace", default=".", help="Workspace path. Used as cwd for source CLIs.")
    parser.add_argument("--date", help="Date shorthand. Accepts today, yesterday, or YYYY-MM-DD.")
    parser.add_argument("--since", help="Start datetime or date (inclusive).")
    parser.add_argument("--until", help="End datetime or date (inclusive).")
    parser.add_argument("--all-sessions", action="store_true", help="Pass --all-sessions to sources that support it.")
    parser.add_argument("--sources-file", default=str(SCRIPT_DIR / "sources.json"), help="Path to sources.json.")
    parser.add_argument("--source", action="append", dest="source_names", help="Specific source name(s) to run.")
    parser.add_argument("--max-workers", type=int, help="Maximum concurrent source processes.")
    return parser


def current_platform() -> str:
    if sys.platform.startswith("darwin"):
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def resolve_date_filters(date_arg: str | None, since: str | None, until: str | None) -> tuple[str | None, str | None]:
    if date_arg and (since or until):
        raise ValueError("--date cannot be combined with --since or --until")
    if not date_arg:
        return since, until

    lowered = date_arg.strip().lower()
    today = datetime.now().astimezone().date()
    if lowered == "today":
        target = today
    elif lowered == "yesterday":
        target = today - timedelta(days=1)
    else:
        target = parse_datetime(date_arg, bound="start").date()
    iso_day = target.isoformat()
    return iso_day, iso_day


def load_sources(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("sources.json must be a JSON array")

    sources = []
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError("Each source entry must be an object")
        missing = REQUIRED_SOURCE_FIELDS - set(entry.keys())
        if missing:
            raise ValueError(f"Source entry is missing fields: {sorted(missing)}")
        sources.append(entry)
    return sources


def resolve_command_paths(tokens: list[str]) -> list[str]:
    resolved = list(tokens)
    for i, token in enumerate(resolved):
        if token.endswith(".py") or token.endswith(".sh"):
            candidate = SCRIPT_DIR / Path(token).name
            if candidate.exists():
                resolved[i] = str(candidate)
    return resolved


def build_command(source: dict[str, Any], *, since: str | None, until: str | None, all_sessions: bool) -> list[str]:
    command = resolve_command_paths(shlex.split(source["command"]))
    if source.get("supports_date_range"):
        if since:
            command.extend(["--since", since])
        if until:
            command.extend(["--until", until])
    if all_sessions and source.get("supports_all_sessions"):
        command.append("--all-sessions")
    return command


def summarize_source_result(result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "name": result["source"],
        "status": result["status"],
        "events_count": len(result.get("events", [])),
    }
    for key in ("reason", "message", "command", "duration_sec"):
        if key in result:
            summary[key] = result[key]
    return summary


def normalize_event(event: dict[str, Any], source_name: str) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    event = dict(event)
    event["source"] = event.get("source") or source_name
    if set(event.keys()) & REQUIRED_EVENT_FIELDS != REQUIRED_EVENT_FIELDS:
        missing = REQUIRED_EVENT_FIELDS - set(event.keys())
        if missing:
            return None

    timestamp = ensure_datetime(event.get("timestamp"))
    if timestamp is None:
        return None
    event["timestamp"] = timestamp.isoformat()
    if not isinstance(event.get("details"), dict):
        event["details"] = {"raw_details": event.get("details")}
    return event


def normalize_source_payload(source_name: str, payload: dict[str, Any], *, command: list[str], duration_sec: float) -> dict[str, Any]:
    status = payload.get("status")
    if status not in {"success", "skipped", "error"}:
        return {
            "status": "error",
            "source": source_name,
            "message": "Source returned an unknown status",
            "events": [],
            "command": command,
            "duration_sec": round(duration_sec, 3),
        }

    normalized_events = []
    for raw_event in payload.get("events", []):
        event = normalize_event(raw_event, source_name)
        if event:
            normalized_events.append(event)

    normalized = {
        "status": status,
        "source": payload.get("source") or source_name,
        "events": normalized_events,
        "command": command,
        "duration_sec": round(duration_sec, 3),
    }
    for key in ("reason", "message"):
        if key in payload:
            normalized[key] = payload[key]
    return normalized


def run_source(
    source: dict[str, Any],
    *,
    workspace: Path,
    since: str | None,
    until: str | None,
    all_sessions: bool,
) -> dict[str, Any]:
    command = build_command(source, since=since, until=until, all_sessions=all_sessions)
    started = datetime.now().timestamp()
    try:
        completed = subprocess.run(
            command,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=int(source["timeout_sec"]),
            check=False,
        )
    except subprocess.TimeoutExpired:
        duration = datetime.now().timestamp() - started
        return {
            "status": "error",
            "source": source["name"],
            "message": "Source timed out",
            "events": [],
            "command": command,
            "duration_sec": round(duration, 3),
        }
    except Exception as exc:
        duration = datetime.now().timestamp() - started
        return {
            "status": "error",
            "source": source["name"],
            "message": str(exc),
            "events": [],
            "command": command,
            "duration_sec": round(duration, 3),
        }

    duration = datetime.now().timestamp() - started
    stdout = completed.stdout.strip()
    if not stdout:
        return {
            "status": "error",
            "source": source["name"],
            "message": completed.stderr.strip() or "Source returned empty stdout",
            "events": [],
            "command": command,
            "duration_sec": round(duration, 3),
        }

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "status": "error",
            "source": source["name"],
            "message": "Source returned invalid JSON",
            "events": [],
            "command": command,
            "duration_sec": round(duration, 3),
        }

    normalized = normalize_source_payload(source["name"], payload, command=command, duration_sec=duration)
    if completed.returncode != 0 and normalized["status"] == "success":
        normalized["status"] = "error"
        normalized["message"] = completed.stderr.strip() or "Source exited with a non-zero status"
        normalized["events"] = []
    return normalized


def select_sources(
    sources: list[dict[str, Any]],
    *,
    source_names: list[str] | None,
    platform_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requested = set(source_names or [])
    if requested:
        available_names = {source["name"] for source in sources}
        missing = sorted(requested - available_names)
        if missing:
            raise ValueError(f"Unknown source name(s): {', '.join(missing)}")
        sources = [source for source in sources if source["name"] in requested]

    runnable = []
    skipped = []
    for source in sources:
        if platform_name not in source["platforms"]:
            skipped.append(
                {
                    "status": "skipped",
                    "source": source["name"],
                    "reason": "unsupported_platform",
                    "events": [],
                    "command": shlex.split(source["command"]),
                    "duration_sec": 0.0,
                }
            )
            continue
        runnable.append(source)
    return runnable, skipped


def group_confidence(source_names: set[str]) -> str:
    has_git = "git-history" in source_names
    has_ai = bool(AI_HISTORY_SOURCES & source_names)
    if has_git and has_ai:
        return "high"
    if has_git or has_ai:
        return "medium"
    return "low"


def build_groups(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = []
    current: dict[str, Any] | None = None
    window = timedelta(minutes=GROUP_WINDOW_MINUTES)

    for event in timeline:
        event_time = ensure_datetime(event["timestamp"])
        if current is None:
            current = {"events": [event], "start": event_time, "end": event_time}
            continue

        if event_time - current["end"] <= window:
            current["events"].append(event)
            current["end"] = event_time
            continue

        groups.append(current)
        current = {"events": [event], "start": event_time, "end": event_time}

    if current is not None:
        groups.append(current)

    normalized_groups = []
    for index, group in enumerate(groups, start=1):
        group_id = f"group-{index:03d}"
        events = group["events"]
        source_names = {event["source"] for event in events}
        confidence = group_confidence(source_names)
        evidence = [
            {
                "timestamp": event["timestamp"],
                "source": event["source"],
                "type": event["type"],
                "summary": event["summary"],
            }
            for event in events[:EVIDENCE_LIMIT]
        ]
        for event in events:
            event["group_id"] = group_id

        summary = events[0]["summary"] if len(events) == 1 else f"{len(events)} activities from {', '.join(sorted(source_names))}"
        normalized_groups.append(
            {
                "id": group_id,
                "start_timestamp": group["start"].isoformat(),
                "end_timestamp": group["end"].isoformat(),
                "summary": summary,
                "confidence": confidence,
                "sources": sorted(source_names),
                "source_count": len(source_names),
                "event_count": len(events),
                "evidence": evidence,
                "events": events,
            }
        )

    return normalized_groups


def build_summary(source_results: list[dict[str, Any]], timeline: list[dict[str, Any]], groups: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {"success": 0, "skipped": 0, "error": 0}
    for result in source_results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1

    return {
        "source_status_counts": counts,
        "total_events": len(timeline),
        "total_groups": len(groups),
        "no_sources_available": counts["success"] == 0 and not timeline,
    }


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        workspace = resolve_workspace(args.workspace)
        sources_file = Path(args.sources_file).expanduser().resolve()
        since_arg, until_arg = resolve_date_filters(args.date, args.since, args.until)
        sources = load_sources(sources_file)
        runnable_sources, skipped_sources = select_sources(
            sources,
            source_names=args.source_names,
            platform_name=current_platform(),
        )

        max_workers = args.max_workers or max(1, len(runnable_sources))
        source_results = list(skipped_sources)
        if runnable_sources:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        run_source,
                        source,
                        workspace=workspace,
                        since=since_arg,
                        until=until_arg,
                        all_sessions=args.all_sessions,
                    ): source["name"]
                    for source in runnable_sources
                }
                for future in as_completed(futures):
                    source_results.append(future.result())

        timeline = []
        for result in source_results:
            if result["status"] == "success":
                timeline.extend(result["events"])
        timeline.sort(key=lambda event: event["timestamp"])
        groups = build_groups(timeline)

        output = {
            "status": "success",
            "generated_at": isoformat(datetime.now().astimezone()),
            "workspace": str(workspace),
            "filters": {
                "since": args.since,
                "until": args.until,
                "date": args.date,
                "all_sessions": args.all_sessions,
            },
            "config": {
                "sources_file": str(sources_file),
                "group_window_minutes": GROUP_WINDOW_MINUTES,
                "evidence_limit": EVIDENCE_LIMIT,
            },
            "sources": [summarize_source_result(result) for result in sorted(source_results, key=lambda item: item["source"])],
            "timeline": timeline,
            "groups": groups,
            "summary": build_summary(source_results, timeline, groups),
        }
        json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    except Exception as exc:
        json.dump({"status": "error", "message": str(exc)}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
