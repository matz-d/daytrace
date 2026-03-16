#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

REPO_ROOT = Path(__file__).resolve().parents[4]
PLUGIN_JSON = REPO_ROOT / "plugins" / "daytrace" / ".claude-plugin" / "plugin.json"
SKILLS_ROOT = REPO_ROOT / "plugins" / "daytrace" / "skills"


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


class PluginManifestTests(unittest.TestCase):
    def test_plugin_manifest_registers_all_skills_with_matching_descriptions_and_scripts(self) -> None:
        manifest = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        skills = manifest.get("skills")
        self.assertIsInstance(skills, list)

        by_name = {skill["name"]: skill for skill in skills}
        self.assertEqual(set(by_name), {"daytrace-session", "daily-report", "skill-miner", "post-draft"})

        for skill_name, skill_entry in by_name.items():
            skill_dir = SKILLS_ROOT / skill_name
            frontmatter = load_skill_frontmatter(skill_dir / "SKILL.md")

            self.assertEqual(skill_entry["path"], f"skills/{skill_name}/SKILL.md")
            self.assertEqual(skill_entry["description"], frontmatter["description"])
            self.assertTrue((REPO_ROOT / "plugins" / "daytrace" / skill_entry["path"]).exists())
            for script_path in skill_entry["scripts"]:
                self.assertTrue((REPO_ROOT / "plugins" / "daytrace" / script_path).exists(), script_path)

    def test_daily_report_and_post_draft_descriptions_include_user_trigger_phrases(self) -> None:
        daily = load_skill_frontmatter(SKILLS_ROOT / "daily-report" / "SKILL.md")["description"]
        post = load_skill_frontmatter(SKILLS_ROOT / "post-draft" / "SKILL.md")["description"]

        self.assertIn("日報", daily)
        self.assertTrue("自分用" in daily or "共有用" in daily)
        self.assertTrue(any(phrase in post for phrase in ("記事を書きたい", "ブログにまとめたい", "ふりかえりを書きたい", "学びを共有したい")))


if __name__ == "__main__":
    unittest.main()
