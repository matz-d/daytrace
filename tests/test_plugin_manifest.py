#!/usr/bin/env python3

from __future__ import annotations

import json
import unittest
from pathlib import Path

from conftest import PLUGIN_ROOT

PLUGIN_JSON = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
SKILLS_ROOT = PLUGIN_ROOT / "skills"


def load_skill_frontmatter(skill_path: Path) -> dict[str, str]:
    lines = skill_path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"Missing frontmatter in {skill_path}")

    payload: dict[str, str] = {}
    index = 1
    while index < len(lines) and lines[index] != "---":
        line = lines[index]
        if line.startswith("name: "):
            payload["name"] = line.split(": ", 1)[1].strip()
        elif line.startswith("description: >"):
            index += 1
            description_lines: list[str] = []
            while index < len(lines):
                continuation = lines[index]
                if continuation == "---" or (continuation and not continuation.startswith("  ")):
                    index -= 1
                    break
                description_lines.append(continuation.strip())
                index += 1
            payload["description"] = " ".join(part for part in description_lines if part)
        index += 1
    return payload


EXPECTED_SKILLS = {"daytrace-session", "daily-report", "skill-miner", "skill-applier", "post-draft"}


class PluginManifestTests(unittest.TestCase):
    def test_plugin_manifest_has_required_fields(self) -> None:
        manifest = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "daytrace")
        self.assertIn("description", manifest)
        self.assertIn("version", manifest)

    def test_all_skills_discoverable_with_valid_frontmatter(self) -> None:
        discovered = {d.name for d in SKILLS_ROOT.iterdir() if d.is_dir() and (d / "SKILL.md").exists()}
        self.assertEqual(discovered, EXPECTED_SKILLS)

        for skill_name in discovered:
            frontmatter = load_skill_frontmatter(SKILLS_ROOT / skill_name / "SKILL.md")
            self.assertEqual(frontmatter["name"], skill_name)
            self.assertTrue(len(frontmatter["description"]) > 0)

    def test_daily_report_and_post_draft_descriptions_include_user_trigger_phrases(self) -> None:
        daily = load_skill_frontmatter(SKILLS_ROOT / "daily-report" / "SKILL.md")["description"]
        post = load_skill_frontmatter(SKILLS_ROOT / "post-draft" / "SKILL.md")["description"]

        self.assertIn("日報", daily)
        self.assertTrue("自分用" in daily or "共有用" in daily)
        self.assertTrue(any(phrase in post for phrase in ("記事を書きたい", "ブログにまとめたい", "ふりかえりを書きたい", "学びを共有したい")))


if __name__ == "__main__":
    unittest.main()
