#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from conftest import FIXTURES_DIR, SCRIPTS_DIR

from source_registry import (
    MANIFEST_KIND,
    SOURCE_IDENTITY_VERSION,
    RegistryValidationError,
    build_source_identity,
    compute_manifest_fingerprint,
    load_registry,
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
    def test_load_registry_merges_built_in_and_user_dropins(self) -> None:
        fixture_root = FIXTURES_DIR / "source_registry"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            built_in_file = root / "sources.json"
            built_in_file.write_text(json.dumps([make_source_entry("built-in-source")]), encoding="utf-8")
            user_sources_dir = root / "sources.d"
            user_sources_dir.mkdir()
            shutil.copyfile(fixture_root / "user_drop_in.json", user_sources_dir / "user_drop_in.json")

            sources = load_registry(built_in_file, user_sources_dir=user_sources_dir)

            self.assertEqual([source["name"] for source in sources], ["built-in-source", "user-drop-in"])
            user_source = next(source for source in sources if source["name"] == "user-drop-in")
            self.assertEqual(user_source["registry_scope"], "user")
            self.assertEqual(Path(user_source["manifest_path"]).name, "user_drop_in.json")

    def test_load_registry_reports_invalid_user_manifest_machine_readably(self) -> None:
        fixture_root = FIXTURES_DIR / "source_registry"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            built_in_file = root / "sources.json"
            built_in_file.write_text(json.dumps([make_source_entry("built-in-source")]), encoding="utf-8")
            user_sources_dir = root / "sources.d"
            user_sources_dir.mkdir()
            shutil.copyfile(fixture_root / "invalid_manifest.json", user_sources_dir / "invalid_manifest.json")

            with self.assertRaises(RegistryValidationError) as context:
                load_registry(built_in_file, user_sources_dir=user_sources_dir)

            self.assertEqual(len(context.exception.issues), 1)
            issue = context.exception.issues[0]
            self.assertEqual(issue["kind"], "invalid_manifest")
            self.assertEqual(issue["registry_scope"], "user")
            self.assertEqual(Path(issue["path"]).name, "invalid_manifest.json")
            self.assertIn("scope_mode must be one of", issue["message"])

    def test_built_in_sources_json_loads_with_identity_and_fingerprint(self) -> None:
        sources_file = SCRIPTS_DIR / "sources.json"
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
