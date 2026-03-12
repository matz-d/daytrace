#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

from source_registry import normalize_confidence_categories

SCHEMA_VERSION = 2
DEFAULT_STORE_PATH = Path("~/.daytrace/daytrace.sqlite3").expanduser()


def resolve_store_path(store_path: str | Path | None) -> Path:
    if isinstance(store_path, Path):
        return store_path.expanduser().resolve()
    path = Path(store_path).expanduser() if store_path else DEFAULT_STORE_PATH
    return path.resolve()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def compute_command_fingerprint(command: list[str]) -> str:
    return stable_hash({"command": command})


def compute_source_run_fingerprint(
    source: dict[str, Any],
    *,
    workspace: Path,
    requested_date: str | None,
    since: str | None,
    until: str | None,
    all_sessions: bool,
    command_fingerprint: str,
) -> str:
    return stable_hash(
        {
            "source_identity": source["source_identity"],
            "manifest_fingerprint": source["manifest_fingerprint"],
            "command_fingerprint": command_fingerprint,
            "workspace": str(workspace),
            "requested_date": requested_date,
            "since": since,
            "until": until,
            "all_sessions": all_sessions,
        }
    )


def compute_observation_fingerprint(event: dict[str, Any]) -> str:
    return stable_hash(
        {
            "source": event["source"],
            "timestamp": event["timestamp"],
            "type": event["type"],
            "summary": event["summary"],
            "details": event["details"],
            "confidence": event["confidence"],
        }
    )


_ensured_dirs: set[Path] = set()


@contextlib.contextmanager
def connect_store(path: Path) -> Generator[sqlite3.Connection, None, None]:
    parent = path.parent
    if parent not in _ensured_dirs:
        parent.mkdir(parents=True, exist_ok=True)
        _ensured_dirs.add(parent)
    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        yield connection
    finally:
        connection.close()


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _create_base_schema(connection: sqlite3.Connection) -> None:
    # All tables are created together to simplify migration.
    # Populate responsibility: store.py owns source_runs/observations;
    # derived_store.py owns activities/patterns.
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS source_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_fingerprint TEXT NOT NULL UNIQUE,
            source_name TEXT NOT NULL,
            source_id TEXT NOT NULL,
            identity_version TEXT NOT NULL,
            manifest_fingerprint TEXT NOT NULL,
            confidence_categories_json TEXT NOT NULL DEFAULT '[]',
            command_fingerprint TEXT NOT NULL,
            status TEXT NOT NULL,
            scope_mode TEXT NOT NULL,
            workspace TEXT NOT NULL,
            requested_date TEXT,
            since_value TEXT,
            until_value TEXT,
            all_sessions INTEGER NOT NULL,
            filters_json TEXT NOT NULL,
            command_json TEXT NOT NULL,
            reason TEXT,
            message TEXT,
            duration_sec REAL NOT NULL,
            events_count INTEGER NOT NULL,
            collected_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_source_runs_source_name
        ON source_runs(source_name, collected_at);

        CREATE INDEX IF NOT EXISTS idx_source_runs_workspace_window
        ON source_runs(workspace, since_value, until_value, all_sessions);

        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_run_id INTEGER NOT NULL,
            event_fingerprint TEXT NOT NULL,
            source_name TEXT NOT NULL,
            scope_mode TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            confidence TEXT NOT NULL,
            details_json TEXT NOT NULL,
            event_json TEXT NOT NULL,
            collected_at TEXT NOT NULL,
            FOREIGN KEY(source_run_id) REFERENCES source_runs(id) ON DELETE CASCADE,
            UNIQUE(source_run_id, event_fingerprint)
        );

        CREATE INDEX IF NOT EXISTS idx_observations_occurred_at
        ON observations(occurred_at);

        CREATE INDEX IF NOT EXISTS idx_observations_source_name
        ON observations(source_name, occurred_at);

        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_fingerprint TEXT NOT NULL,
            derivation_version TEXT NOT NULL,
            input_fingerprint TEXT NOT NULL,
            workspace TEXT,
            since_value TEXT,
            until_value TEXT,
            group_window_minutes INTEGER NOT NULL,
            activity_id TEXT NOT NULL,
            start_timestamp TEXT NOT NULL,
            end_timestamp TEXT NOT NULL,
            summary TEXT NOT NULL,
            confidence TEXT NOT NULL,
            sources_json TEXT NOT NULL,
            confidence_categories_json TEXT NOT NULL,
            source_count INTEGER NOT NULL,
            event_count INTEGER NOT NULL,
            evidence_json TEXT NOT NULL,
            observation_fingerprints_json TEXT NOT NULL,
            activity_json TEXT NOT NULL,
            derived_at TEXT NOT NULL,
            UNIQUE(query_fingerprint, activity_id)
        );

        CREATE INDEX IF NOT EXISTS idx_activities_query
        ON activities(query_fingerprint, start_timestamp);

        CREATE TABLE IF NOT EXISTS patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_fingerprint TEXT NOT NULL,
            pattern_kind TEXT NOT NULL,
            pattern_key TEXT NOT NULL,
            derivation_version TEXT NOT NULL,
            input_fingerprint TEXT NOT NULL,
            workspace TEXT,
            observation_mode TEXT,
            days INTEGER,
            label TEXT NOT NULL,
            score REAL NOT NULL,
            support_json TEXT NOT NULL,
            pattern_json TEXT NOT NULL,
            derived_at TEXT NOT NULL,
            UNIQUE(query_fingerprint, pattern_kind, pattern_key)
        );

        CREATE INDEX IF NOT EXISTS idx_patterns_query
        ON patterns(query_fingerprint, pattern_kind, pattern_key);
        """
    )


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    source_run_columns = _table_columns(connection, "source_runs")
    if "confidence_categories_json" not in source_run_columns:
        connection.execute(
            "ALTER TABLE source_runs ADD COLUMN confidence_categories_json TEXT NOT NULL DEFAULT '[]'"
        )
    _create_base_schema(connection)


def bootstrap_store(path: Path) -> None:
    with connect_store(path) as connection:
        current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version not in {0, 1, SCHEMA_VERSION}:
            raise ValueError(f"Unsupported store schema version: {current_version}")
        if current_version == 1:
            _migrate_v1_to_v2(connection)
        else:
            _create_base_schema(connection)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _upsert_source_run(
    connection: sqlite3.Connection,
    source: dict[str, Any],
    result: dict[str, Any],
    *,
    workspace: Path,
    requested_date: str | None,
    since: str | None,
    until: str | None,
    all_sessions: bool,
    collected_at: str,
) -> int:
    command = result.get("command", [])
    command_fingerprint = compute_command_fingerprint(command)
    run_fingerprint = compute_source_run_fingerprint(
        source,
        workspace=workspace,
        requested_date=requested_date,
        since=since,
        until=until,
        all_sessions=all_sessions,
        command_fingerprint=command_fingerprint,
    )
    filters_json = canonical_json(
        {
            "workspace": str(workspace),
            "date": requested_date,
            "since": since,
            "until": until,
            "all_sessions": all_sessions,
        }
    )
    command_json = canonical_json(command)
    connection.execute(
        """
        INSERT INTO source_runs (
            run_fingerprint,
            source_name,
            source_id,
            identity_version,
            manifest_fingerprint,
            confidence_categories_json,
            command_fingerprint,
            status,
            scope_mode,
            workspace,
            requested_date,
            since_value,
            until_value,
            all_sessions,
            filters_json,
            command_json,
            reason,
            message,
            duration_sec,
            events_count,
            collected_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_fingerprint) DO UPDATE SET
            status = excluded.status,
            reason = excluded.reason,
            message = excluded.message,
            duration_sec = excluded.duration_sec,
            events_count = excluded.events_count,
            confidence_categories_json = excluded.confidence_categories_json,
            command_json = excluded.command_json,
            collected_at = excluded.collected_at
        """,
        (
            run_fingerprint,
            source["name"],
            source["source_id"],
            source["source_identity"]["identity_version"],
            source["manifest_fingerprint"],
            canonical_json(normalize_confidence_categories(source)),
            command_fingerprint,
            result["status"],
            source["scope_mode"],
            str(workspace),
            requested_date,
            since,
            until,
            1 if all_sessions else 0,
            filters_json,
            command_json,
            result.get("reason"),
            result.get("message"),
            float(result.get("duration_sec", 0.0)),
            len(result.get("events", [])),
            collected_at,
        ),
    )
    row = connection.execute(
        "SELECT id FROM source_runs WHERE run_fingerprint = ?",
        (run_fingerprint,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Failed to load persisted source_run for {source['name']}")
    return int(row["id"])


def _replace_observations(
    connection: sqlite3.Connection,
    *,
    source_run_id: int,
    result: dict[str, Any],
    scope_mode: str,
    collected_at: str,
) -> None:
    connection.execute("DELETE FROM observations WHERE source_run_id = ?", (source_run_id,))
    for event in result.get("events", []):
        event_json_str = canonical_json(event)
        details_json_str = canonical_json(event["details"])
        connection.execute(
            """
            INSERT INTO observations (
                source_run_id,
                event_fingerprint,
                source_name,
                scope_mode,
                occurred_at,
                event_type,
                summary,
                confidence,
                details_json,
                event_json,
                collected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_run_id,
                compute_observation_fingerprint(event),
                event["source"],
                scope_mode,
                event["timestamp"],
                event["type"],
                event["summary"],
                event["confidence"],
                details_json_str,
                event_json_str,
                collected_at,
            ),
        )


def persist_source_results(
    source_results: list[dict[str, Any]],
    source_lookup: dict[str, dict[str, Any]],
    *,
    workspace: Path,
    requested_date: str | None,
    since: str | None,
    until: str | None,
    all_sessions: bool,
    store_path: Path,
    collected_at: datetime | None = None,
) -> None:
    bootstrap_store(store_path)
    collected_at_iso = (collected_at or datetime.now().astimezone()).isoformat()
    with connect_store(store_path) as connection:
        for result in source_results:
            source_name = result.get("manifest_source_name", result["source"])
            source = source_lookup.get(source_name)
            if source is None:
                raise ValueError(f"Missing source metadata for persisted result: {source_name}")
            source_run_id = _upsert_source_run(
                connection,
                source,
                result,
                workspace=workspace,
                requested_date=requested_date,
                since=since,
                until=until,
                all_sessions=all_sessions,
                collected_at=collected_at_iso,
            )
            _replace_observations(
                connection,
                source_run_id=source_run_id,
                result=result,
                scope_mode=source["scope_mode"],
                collected_at=collected_at_iso,
            )
        connection.commit()
