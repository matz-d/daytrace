#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

VALID_SCOPE_MODES = {"all-day", "workspace"}
REQUIRED_SOURCE_FIELDS = {
    "name",
    "command",
    "required",
    "timeout_sec",
    "platforms",
    "supports_date_range",
    "supports_all_sessions",
    "scope_mode",
}
MANIFEST_KIND = "daytrace-source-manifest/v1"
SOURCE_IDENTITY_VERSION = "daytrace-source-identity/v1"


def normalize_confidence_categories(source: dict[str, Any]) -> list[str]:
    raw_value = source.get("confidence_category")
    source_name = str(source.get("name", "<unknown-source>"))
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        if not raw_value:
            raise ValueError(f"confidence_category must not be empty for {source_name}")
        return [raw_value]
    if isinstance(raw_value, list):
        if not all(isinstance(item, str) and item for item in raw_value):
            raise ValueError(f"confidence_category must be a string or list of non-empty strings for {source_name}")
        return list(raw_value)
    raise ValueError(f"confidence_category must be a string or list of non-empty strings for {source_name}")


def build_source_identity(source: dict[str, Any]) -> dict[str, str]:
    return {
        "source_id": str(source["name"]),
        "scope_mode": str(source["scope_mode"]),
        "identity_version": str(source.get("identity_version", SOURCE_IDENTITY_VERSION)),
    }


def manifest_fingerprint_payload(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifest_kind": str(source.get("manifest_kind", MANIFEST_KIND)),
        "name": str(source["name"]),
        "command": str(source["command"]),
        "scope_mode": str(source["scope_mode"]),
        "supports_date_range": bool(source["supports_date_range"]),
        "supports_all_sessions": bool(source["supports_all_sessions"]),
        "confidence_categories": normalize_confidence_categories(source),
        "prerequisites": source.get("prerequisites", []),
    }


def compute_manifest_fingerprint(source: dict[str, Any]) -> str:
    payload = manifest_fingerprint_payload(source)
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_bool(value: Any, field_name: str, source_name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean for {source_name}")


def _validate_prerequisites(prerequisites: Any, source_name: str) -> None:
    if prerequisites is None:
        return
    if not isinstance(prerequisites, list):
        raise ValueError(f"prerequisites must be a list for {source_name}")
    for prerequisite in prerequisites:
        if not isinstance(prerequisite, dict):
            raise ValueError(f"each prerequisite must be an object for {source_name}")
        prereq_type = prerequisite.get("type")
        if not isinstance(prereq_type, str) or not prereq_type:
            raise ValueError(f"each prerequisite.type must be a non-empty string for {source_name}")


def validate_source_entry(entry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError("Each source entry must be an object")

    missing = REQUIRED_SOURCE_FIELDS - set(entry.keys())
    if missing:
        raise ValueError(f"Source entry is missing fields: {sorted(missing)}")

    source_name = entry["name"]
    if not isinstance(source_name, str) or not source_name:
        raise ValueError("name must be a non-empty string")
    if not isinstance(entry["command"], str) or not entry["command"]:
        raise ValueError(f"command must be a non-empty string for {source_name}")

    _validate_bool(entry["required"], "required", source_name)
    timeout_sec = entry["timeout_sec"]
    if isinstance(timeout_sec, bool) or not isinstance(timeout_sec, (int, float)) or timeout_sec <= 0:
        raise ValueError(f"timeout_sec must be a positive number for {source_name}")

    platforms = entry["platforms"]
    if not isinstance(platforms, list) or not platforms or not all(isinstance(item, str) and item for item in platforms):
        raise ValueError(f"platforms must be a non-empty list of strings for {source_name}")

    _validate_bool(entry["supports_date_range"], "supports_date_range", source_name)
    _validate_bool(entry["supports_all_sessions"], "supports_all_sessions", source_name)

    if entry["scope_mode"] not in VALID_SCOPE_MODES:
        raise ValueError(f"scope_mode must be one of {sorted(VALID_SCOPE_MODES)} for {source_name}")

    normalize_confidence_categories(entry)
    _validate_prerequisites(entry.get("prerequisites", []), source_name)

    normalized = dict(entry)
    normalized.setdefault("prerequisites", [])
    normalized["manifest_kind"] = str(entry.get("manifest_kind", MANIFEST_KIND))
    normalized["identity_version"] = str(entry.get("identity_version", SOURCE_IDENTITY_VERSION))
    normalized["source_identity"] = build_source_identity(normalized)
    normalized["source_id"] = normalized["source_identity"]["source_id"]
    normalized["manifest_fingerprint"] = compute_manifest_fingerprint(normalized)
    return normalized


def load_sources(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("Source manifest file must contain a JSON object or array")

    sources = []
    seen_source_ids: set[str] = set()
    for entry in data:
        normalized = validate_source_entry(entry)
        source_id = normalized["source_id"]
        if source_id in seen_source_ids:
            raise ValueError(f"Duplicate source name in registry: {source_id}")
        seen_source_ids.add(source_id)
        sources.append(normalized)
    return sources
