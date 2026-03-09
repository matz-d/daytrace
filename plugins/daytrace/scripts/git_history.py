#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    apply_limit,
    emit,
    error_response,
    parse_datetime,
    resolve_workspace,
    run_command,
    skipped_response,
    success_response,
    summarize_text,
)


SOURCE_NAME = "git-history"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit git commit history as DayTrace events.")
    parser.add_argument("--workspace", default=".", help="Workspace path to inspect. Defaults to cwd.")
    parser.add_argument("--since", help="Start datetime or date (inclusive).")
    parser.add_argument("--until", help="End datetime or date (inclusive).")
    parser.add_argument("--limit", type=int, help="Maximum number of events to return.")
    return parser


def repo_context(workspace: Path) -> tuple[Path, str] | None:
    repo_check = run_command(["git", "-C", str(workspace), "rev-parse", "--show-toplevel"])
    if repo_check.returncode != 0:
        return None

    repo_root = Path(repo_check.stdout.strip()).resolve()
    relative = "."
    if workspace != repo_root:
        relative = str(workspace.relative_to(repo_root))
    return repo_root, relative


def parse_numstat(record: str, repo_root: Path, workspace: Path) -> dict[str, object] | None:
    lines = [line for line in record.strip().splitlines()]
    if not lines:
        return None

    header = lines[0].split("\x1f")
    if len(header) < 4:
        return None

    commit_hash, authored_at, subject, body = header[:4]
    changed_files = []
    insertions = 0
    deletions = 0

    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        additions_raw, deletions_raw = parts[0], parts[1]
        file_path = "\t".join(parts[2:])

        additions = int(additions_raw) if additions_raw.isdigit() else None
        deletions_count = int(deletions_raw) if deletions_raw.isdigit() else None
        if additions is not None:
            insertions += additions
        if deletions_count is not None:
            deletions += deletions_count

        changed_files.append(
            {
                "path": file_path,
                "additions": additions,
                "deletions": deletions_count,
            }
        )

    return {
        "source": SOURCE_NAME,
        "timestamp": authored_at,
        "type": "commit",
        "summary": summarize_text(subject, 140),
        "details": {
            "commit_hash": commit_hash,
            "workspace": str(workspace),
            "repo_root": str(repo_root),
            "changed_files": changed_files,
            "stats": {
                "files_changed": len(changed_files),
                "insertions": insertions,
                "deletions": deletions,
            },
            "body_summary": summarize_text(body, 240),
        },
        "confidence": "high",
    }


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        workspace = resolve_workspace(args.workspace)
        start = parse_datetime(args.since, bound="start")
        end = parse_datetime(args.until, bound="end")
        context = repo_context(workspace)
        if context is None:
            emit(skipped_response(SOURCE_NAME, "not_git_repo", workspace=str(workspace)))
            return

        repo_root, pathspec = context
        command = [
            "git",
            "-C",
            str(repo_root),
            "log",
            "--numstat",
            "--date=iso-strict",
            "--format=%x1e%H%x1f%aI%x1f%s%x1f%b",
        ]
        if start:
            command.append(f"--after={start.isoformat()}")
        if end:
            command.append(f"--before={end.isoformat()}")
        command.extend(["--", pathspec])

        result = run_command(command)
        if result.returncode != 0:
            emit(error_response(SOURCE_NAME, result.stderr.strip() or "git log failed", workspace=str(workspace)))
            return

        records = [chunk for chunk in result.stdout.split("\x1e") if chunk.strip()]
        events = []
        for record in records:
            event = parse_numstat(record, repo_root, workspace)
            if event:
                events.append(event)

        emit(
            success_response(
                SOURCE_NAME,
                apply_limit(events, args.limit),
                workspace=str(workspace),
                since=args.since,
                until=args.until,
            )
        )
    except Exception as exc:
        emit(error_response(SOURCE_NAME, str(exc)))


if __name__ == "__main__":
    main()
