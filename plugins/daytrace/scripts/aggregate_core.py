from __future__ import annotations

import json
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from common import default_chrome_root, ensure_datetime, parse_datetime
from source_registry import DEFAULT_USER_SOURCES_DIR, load_registry


DEFAULT_GROUP_WINDOW_MINUTES = 15
DEFAULT_MAX_SPAN_MINUTES = 60
EVIDENCE_LIMIT = 5

# Priority order for salience-based evidence selection.
# Lower value = higher priority when selecting representative evidence.
EVIDENCE_CATEGORY_PRIORITY: dict[str, int] = {
    "git": 0,
    "ai_history": 1,
    "browser": 2,
    "file_activity": 3,
}
REQUIRED_EVENT_FIELDS = {"source", "timestamp", "type", "summary", "details", "confidence"}


def resolve_date_filters(
    date_arg: str | None,
    since: str | None,
    until: str | None,
    *,
    now: datetime | None = None,
) -> tuple[str | None, str | None]:
    if date_arg and (since or until):
        raise ValueError("--date cannot be combined with --since or --until")
    if not date_arg:
        return since, until

    lowered = date_arg.strip().lower()
    today = (now or datetime.now().astimezone()).date()
    if lowered == "today":
        target = today
    elif lowered == "yesterday":
        target = today - timedelta(days=1)
    else:
        target = parse_datetime(date_arg, bound="start").date()
    iso_day = target.isoformat()
    return iso_day, iso_day


def resolve_command_paths(tokens: list[str], *, script_dir: Path) -> list[str]:
    resolved = list(tokens)
    for index, token in enumerate(resolved):
        if token.endswith(".py") or token.endswith(".sh"):
            candidate = script_dir / Path(token).name
            if candidate.exists():
                resolved[index] = str(candidate)
    return resolved


def build_command(
    source: dict[str, Any],
    *,
    workspace: Path,
    since: str | None,
    until: str | None,
    all_sessions: bool,
    script_dir: Path,
) -> list[str]:
    command = resolve_command_paths(shlex.split(source["command"]), script_dir=script_dir)
    command.extend(["--workspace", str(workspace)])
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
        "scope": result["scope"],
        "events_count": len(result.get("events", [])),
    }
    for key in ("reason", "message", "command", "duration_sec"):
        if key in result:
            summary[key] = result[key]
    return summary


def normalize_event(event: dict[str, Any], source_name: str) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    normalized = dict(event)
    normalized["source"] = normalized.get("source") or source_name
    if set(normalized.keys()) & REQUIRED_EVENT_FIELDS != REQUIRED_EVENT_FIELDS:
        missing = REQUIRED_EVENT_FIELDS - set(normalized.keys())
        if missing:
            return None

    timestamp = ensure_datetime(normalized.get("timestamp"))
    if timestamp is None:
        return None
    normalized["timestamp"] = timestamp.isoformat()
    if not isinstance(normalized.get("details"), dict):
        normalized["details"] = {"raw_details": normalized.get("details")}
    return normalized


def error_result(source: dict[str, Any], message: str, command: list[str], duration_sec: float) -> dict[str, Any]:
    return {
        "status": "error",
        "source": source["name"],
        "manifest_source_name": source["name"],
        "scope": source["scope_mode"],
        "message": message,
        "events": [],
        "command": command,
        "duration_sec": round(duration_sec, 3),
    }


def normalize_source_payload(
    source: dict[str, Any],
    payload: dict[str, Any],
    *,
    command: list[str],
    duration_sec: float,
) -> dict[str, Any]:
    status = payload.get("status")
    if status not in {"success", "skipped", "error"}:
        return error_result(source, "Source returned an unknown status", command, duration_sec)

    normalized_events = []
    for raw_event in payload.get("events", []):
        event = normalize_event(raw_event, source["name"])
        if event:
            normalized_events.append(event)

    normalized = {
        "status": status,
        "source": payload.get("source") or source["name"],
        "manifest_source_name": source["name"],
        "scope": source["scope_mode"],
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
    script_dir: Path,
) -> dict[str, Any]:
    command = build_command(
        source,
        workspace=workspace,
        since=since,
        until=until,
        all_sessions=all_sessions,
        script_dir=script_dir,
    )
    started = datetime.now().timestamp()
    try:
        # `source` is expected to come from `source_registry.load_sources()`,
        # which validates that `timeout_sec` exists and is a positive number.
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
        return error_result(source, "Source timed out", command, duration)
    except Exception as exc:
        duration = datetime.now().timestamp() - started
        return error_result(source, str(exc), command, duration)

    duration = datetime.now().timestamp() - started
    stdout = completed.stdout.strip()
    if not stdout:
        return error_result(source, completed.stderr.strip() or "Source returned empty stdout", command, duration)

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return error_result(source, "Source returned invalid JSON", command, duration)

    normalized = normalize_source_payload(source, payload, command=command, duration_sec=duration)
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
    selected_sources = list(sources)
    if requested:
        available_names = {source["name"] for source in selected_sources}
        missing = sorted(requested - available_names)
        if missing:
            raise ValueError(f"Unknown source name(s): {', '.join(missing)}")
        selected_sources = [source for source in selected_sources if source["name"] in requested]

    runnable = []
    skipped = []
    for source in selected_sources:
        if platform_name not in source["platforms"]:
            skipped.append(
                {
                    "status": "skipped",
                    "source": source["name"],
                    "manifest_source_name": source["name"],
                    "scope": source["scope_mode"],
                    "reason": "unsupported_platform",
                    "events": [],
                    "command": shlex.split(source["command"]),
                    "duration_sec": 0.0,
                }
            )
            continue
        runnable.append(source)
    return runnable, skipped


def git_repo_available(workspace: Path) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )


def evaluate_prerequisite(prerequisite: dict[str, Any], workspace: Path) -> tuple[bool, str | None]:
    prereq_type = prerequisite.get("type")
    if prereq_type == "git_repo":
        return (git_repo_available(workspace), "not_git_repo")
    if prereq_type == "path_exists":
        path = Path(str(prerequisite["path"])).expanduser()
        return (path.exists(), "not_found")
    if prereq_type == "all_paths_exist":
        paths = [Path(str(path)).expanduser() for path in prerequisite.get("paths", [])]
        return (all(path.exists() for path in paths), "not_found")
    if prereq_type == "glob_exists":
        base = Path(str(prerequisite["base"])).expanduser()
        pattern = str(prerequisite["pattern"])
        return (base.exists() and any(base.glob(pattern)), "not_found")
    if prereq_type == "chrome_history_db":
        chrome_root = default_chrome_root()
        if chrome_root is None:
            return (True, None)
        history_paths = list(chrome_root.glob("Default/History")) + list(chrome_root.glob("Profile */History"))
        return (bool(history_paths), "not_found")
    raise ValueError(f"Unsupported prerequisite type: {prereq_type}")


def source_availability(source: dict[str, Any], workspace: Path, *, script_dir: Path) -> tuple[str, str | None]:
    command = resolve_command_paths(shlex.split(source["command"]), script_dir=script_dir)
    script_token = next((token for token in command if token.endswith(".py") or token.endswith(".sh")), None)
    if script_token and not Path(script_token).exists():
        return "unavailable", "command_missing"

    for prerequisite in source.get("prerequisites", []):
        is_available, reason = evaluate_prerequisite(prerequisite, workspace)
        if not is_available:
            return "unavailable", reason

    return "available", None


def expected_source_names(
    sources: list[dict[str, Any]],
    *,
    platform_name: str,
    workspace: Path,
    script_dir: Path,
) -> set[str]:
    """Return source names expected to produce results.

    Excludes sources that are unsupported on the current platform
    or that fail prerequisite checks, since those would never run.
    """
    runnable, _skipped = select_sources(sources, source_names=None, platform_name=platform_name)
    names: set[str] = set()
    for source in runnable:
        status, _reason = source_availability(source, workspace, script_dir=script_dir)
        if status == "available":
            names.add(source["name"])
    return names


def resolve_sources_file_path(
    sources_file: str | Path | None,
    *,
    default_sources_file: Path,
) -> Path:
    return Path(sources_file).expanduser().resolve() if sources_file else default_sources_file


def load_expected_sources(
    sources_file: Path,
    *,
    platform_name: str,
    workspace: Path,
    script_dir: Path,
    restrict_to_names: set[str] | None = None,
) -> tuple[set[str], dict[str, str]]:
    default_sources_file = (script_dir / "sources.json").resolve()
    resolved_sources_file = sources_file.resolve()
    sources = load_registry(
        resolved_sources_file,
        user_sources_dir=DEFAULT_USER_SOURCES_DIR,
        include_user_sources=resolved_sources_file == default_sources_file,
    )
    names = expected_source_names(
        sources,
        platform_name=platform_name,
        workspace=workspace,
        script_dir=script_dir,
    )
    if restrict_to_names is not None:
        names &= restrict_to_names
    fingerprint_map = {
        source["name"]: source["manifest_fingerprint"]
        for source in sources
        if source["name"] in names
    }
    return names, fingerprint_map


def build_preflight_summary(
    runnable_sources: list[dict[str, Any]],
    skipped_sources: list[dict[str, Any]],
    *,
    workspace: Path,
    script_dir: Path,
) -> str:
    available: list[str] = []
    unavailable: list[str] = []
    skipped: list[str] = []

    for source in runnable_sources:
        status, reason = source_availability(source, workspace, script_dir=script_dir)
        if status == "available":
            available.append(source["name"])
        else:
            unavailable.append(f"{source['name']}({reason})")

    for source in skipped_sources:
        skipped.append(f"{source['source']}({source.get('reason', 'skipped')})")

    parts = [
        f"workspace={workspace}",
        "available=" + (", ".join(sorted(available)) if available else "none"),
    ]
    if unavailable:
        parts.append("unavailable=" + ", ".join(sorted(unavailable)))
    if skipped:
        parts.append("skipped=" + ", ".join(sorted(skipped)))
    return "Source preflight: " + " | ".join(parts)


def collect_source_results(
    runnable_sources: list[dict[str, Any]],
    skipped_sources: list[dict[str, Any]],
    *,
    workspace: Path,
    since: str | None,
    until: str | None,
    all_sessions: bool,
    max_workers: int,
    script_dir: Path,
) -> list[dict[str, Any]]:
    source_results = list(skipped_sources)
    if not runnable_sources:
        return source_results

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                run_source,
                source,
                workspace=workspace,
                since=since,
                until=until,
                all_sessions=all_sessions,
                script_dir=script_dir,
            ): source["name"]
            for source in runnable_sources
        }
        for future in as_completed(futures):
            source_results.append(future.result())
    return source_results


def collect_timeline(source_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for result in source_results:
        if result["status"] == "success":
            timeline.extend(result["events"])
    timeline.sort(key=lambda event: event["timestamp"])
    return timeline


def group_confidence(categories: set[str]) -> str:
    has_git = "git" in categories
    has_ai = "ai_history" in categories
    if has_git and has_ai:
        return "high"
    if has_git or has_ai:
        return "medium"
    return "low"


def build_groups(
    timeline: list[dict[str, Any]],
    *,
    group_window_minutes: int,
    confidence_categories_by_source: dict[str, list[str]],
    evidence_limit: int = EVIDENCE_LIMIT,
    max_span_minutes: int = DEFAULT_MAX_SPAN_MINUTES,
    scope_mode_by_source: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    grouped_ranges = []
    current: dict[str, Any] | None = None
    window = timedelta(minutes=group_window_minutes)
    max_span = timedelta(minutes=max_span_minutes) if max_span_minutes > 0 else None

    for event in timeline:
        event_time = ensure_datetime(event["timestamp"])
        if current is None:
            current = {"events": [event], "start": event_time, "end": event_time}
            continue

        gap_ok = event_time - current["end"] <= window
        span_ok = max_span is None or event_time - current["start"] <= max_span
        if gap_ok and span_ok:
            current["events"].append(event)
            current["end"] = event_time
            continue

        grouped_ranges.append(current)
        current = {"events": [event], "start": event_time, "end": event_time}

    if current is not None:
        grouped_ranges.append(current)

    _scope_lookup = scope_mode_by_source or {}

    normalized_groups = []
    for index, group in enumerate(grouped_ranges, start=1):
        group_id = f"group-{index:03d}"
        events = group["events"]
        source_names = {event["source"] for event in events}
        categories = {
            category
            for source_name in source_names
            for category in confidence_categories_by_source.get(source_name, [])
        }
        confidence = group_confidence(categories)

        # confidence_breakdown: event count per confidence_category
        confidence_breakdown: dict[str, int] = {}
        for event in events:
            for category in confidence_categories_by_source.get(event["source"], []):
                confidence_breakdown[category] = confidence_breakdown.get(category, 0) + 1

        # scope_breakdown: set of scope_modes present in this group
        scope_modes: set[str] = set()
        for source_name in source_names:
            mode = _scope_lookup.get(source_name)
            if mode:
                scope_modes.add(mode)
        scope_breakdown = sorted(scope_modes)
        mixed_scope = len(scope_modes) > 1

        # Salience-based evidence: prioritise git > ai_history > browser > file_activity
        def _evidence_sort_key(ev: dict[str, Any]) -> tuple[int, str]:
            source_cats = confidence_categories_by_source.get(ev["source"], [])
            best = min((EVIDENCE_CATEGORY_PRIORITY.get(c, 99) for c in source_cats), default=99)
            return (best, ev["timestamp"])

        sorted_for_evidence = sorted(events, key=_evidence_sort_key)
        evidence = [
            {
                "timestamp": event["timestamp"],
                "source": event["source"],
                "type": event["type"],
                "summary": event["summary"],
            }
            for event in sorted_for_evidence[:evidence_limit]
        ]

        # Keep `timeline` and `groups[].events` pointing at the same event objects so
        # the AR1a contract can expose `timeline[].group_id` without rebuilding copies.
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
                "confidence_breakdown": confidence_breakdown,
                "sources": sorted(source_names),
                "confidence_categories": sorted(categories),
                "scope_breakdown": scope_breakdown,
                "mixed_scope": mixed_scope,
                "source_count": len(source_names),
                "event_count": len(events),
                "evidence": evidence,
                "evidence_overflow_count": max(0, len(events) - evidence_limit),
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
