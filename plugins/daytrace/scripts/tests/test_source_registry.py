#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from source_registry import (
    MANIFEST_KIND,
    SOURCE_IDENTITY_VERSION,
    build_source_identity,
    compute_manifest_fingerprint,
    load_sources,
)


def make_source_entry(
    name: str,
    *,
    command: str = "python3 scripts/example.py",
    scope_mode: str = "workspace",
    supports_date_range: bool = True,
    supports_all_sessions: bool = False,
    confidence_category: str | list[str] = "git",
    prerequisites: list[dict[str, object]] | None = None,
    required: bool = False,
    timeout_sec: int = 10,
    platforms: list[str] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "command": command,
        "required": required,
        "timeout_sec": timeout_sec,
        "platforms": platforms or ["darwin", "linux"],
        "supports_date_range": supports_date_range,
        "supports_all_sessions": supports_all_sessions,
        "scope_mode": scope_mode,
        "prerequisites": prerequisites or [],
        "confidence_category": confidence_category,
    }


class SourceRegistryTests(unittest.TestCase):
    def test_built_in_sources_json_loads_with_identity_and_fingerprint(self) -> None:
        sources_file = SCRIPT_DIR / "sources.json"
        sources = load_sources(sources_file)

        self.assertGreaterEqual(len(sources), 1)
        for source in sources:
            self.assertEqual(source["source_id"], source["name"])
            self.assertEqual(source["source_identity"]["source_id"], source["name"])
            self.assertEqual(source["source_identity"]["scope_mode"], source["scope_mode"])
            self.assertEqual(source["source_identity"]["identity_version"], SOURCE_IDENTITY_VERSION)
            self.assertEqual(source["manifest_kind"], MANIFEST_KIND)
            self.assertRegex(source["manifest_fingerprint"], r"^[0-9a-f]{64}$")

    def test_manifest_fingerprint_ignores_runtime_only_fields(self) -> None:
        base = make_source_entry(
            "git-history",
            command="python3 scripts/git_history.py",
            confidence_category="git",
            prerequisites=[{"type": "git_repo"}],
        )
        runtime_variant = make_source_entry(
            "git-history",
            command="python3 scripts/git_history.py",
            confidence_category="git",
            prerequisites=[{"type": "git_repo"}],
            required=True,
            timeout_sec=99,
            platforms=["darwin"],
        )

        self.assertEqual(compute_manifest_fingerprint(base), compute_manifest_fingerprint(runtime_variant))

    def test_manifest_fingerprint_changes_when_logical_manifest_changes(self) -> None:
        base = make_source_entry(
            "codex-history",
            command="python3 scripts/codex_history.py",
            scope_mode="all-day",
            supports_all_sessions=True,
            confidence_category="ai_history",
            prerequisites=[{"type": "all_paths_exist", "paths": ["~/.codex/history.jsonl", "~/.codex/sessions"]}],
        )
        changed = make_source_entry(
            "codex-history",
            command="python3 scripts/codex_history_v2.py",
            scope_mode="all-day",
            supports_all_sessions=True,
            confidence_category="ai_history",
            prerequisites=[{"type": "all_paths_exist", "paths": ["~/.codex/history.jsonl", "~/.codex/sessions"]}],
        )

        self.assertEqual(build_source_identity(base), build_source_identity(changed))
        self.assertNotEqual(compute_manifest_fingerprint(base), compute_manifest_fingerprint(changed))

    def test_load_sources_rejects_duplicate_source_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file = Path(temp_dir) / "sources.json"
            sources_file.write_text(
                json.dumps(
                    [
                        make_source_entry("duplicate-source"),
                        make_source_entry("duplicate-source", command="python3 scripts/other.py"),
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Duplicate source name"):
                load_sources(sources_file)

    def test_load_sources_accepts_single_manifest_object_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_file = Path(temp_dir) / "single-source.json"
            sources_file.write_text(json.dumps(make_source_entry("single-source")), encoding="utf-8")

            sources = load_sources(sources_file)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]["name"], "single-source")


if __name__ == "__main__":
    unittest.main()
