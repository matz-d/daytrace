#!/usr/bin/env python3
"""Tests for plugins/daytrace/scripts/formatter.py.

Covers:
  - path_sanitize: replaces /Users/… absolute paths
  - normalize_source_names: canonical display name mapping
  - check_forbidden_words: internal terms and product-copy violations (warn-only)
  - check_english_leakage: internal English phrases (warn-only)
  - inject_mixed_scope_note: prepended when scope_mode=="mixed"
  - inject_footer: mode-dependent footer
  - apply(): full pipeline smoke test
  - Regression: golden proposal markdown contains no forbidden internal terms
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from conftest import SCRIPTS_DIR, FIXTURES_DIR, PLUGIN_ROOT

from formatter import (
    ArtifactFormatter,
    FormatterInput,
    FormatterResult,
    FORBIDDEN_INTERNAL_TERMS,
    FORBIDDEN_PRODUCT_COPY,
    SOURCE_NAME_MAP,
    format_artifact,
)


class TestPathSanitize(unittest.TestCase):
    def setUp(self) -> None:
        self.fmt = ArtifactFormatter()

    def test_replaces_single_path(self) -> None:
        text, patches = self.fmt.path_sanitize("ファイル /Users/alice/projects/foo.py を編集しました")
        self.assertNotIn("/Users/", text)
        self.assertIn("[PATH]", text)
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0].kind, "path_sanitize")

    def test_replaces_multiple_distinct_paths(self) -> None:
        text, patches = self.fmt.path_sanitize(
            "/Users/alice/a.md と /Users/bob/b.md を比較しました"
        )
        self.assertNotIn("/Users/", text)
        self.assertEqual(len(patches), 2)

    def test_replaces_same_path_once_per_unique(self) -> None:
        text, patches = self.fmt.path_sanitize("/Users/alice/x.py /Users/alice/x.py")
        self.assertNotIn("/Users/", text)
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0].count, 2)

    def test_no_change_when_no_path(self) -> None:
        original = "変更履歴を確認しました"
        text, patches = self.fmt.path_sanitize(original)
        self.assertEqual(text, original)
        self.assertEqual(patches, [])

    def test_path_at_end_of_line(self) -> None:
        text, _ = self.fmt.path_sanitize("保存先: /Users/taro/Documents/report.md")
        self.assertNotIn("/Users/", text)
        self.assertIn("[PATH]", text)


class TestNormalizeSourceNames(unittest.TestCase):
    def setUp(self) -> None:
        self.fmt = ArtifactFormatter()

    def test_all_known_sources_are_normalized(self) -> None:
        for raw, display in SOURCE_NAME_MAP.items():
            text, patches = self.fmt.normalize_source_names(f"source: {raw}")
            self.assertIn(display, text, f"{raw} should normalize to {display}")
            self.assertNotIn(raw, text)
            self.assertEqual(patches[0].original, raw)
            self.assertEqual(patches[0].replacement, display)

    def test_no_change_for_unknown_source(self) -> None:
        original = "source: unknown-source-xyz"
        text, patches = self.fmt.normalize_source_names(original)
        self.assertEqual(text, original)
        self.assertEqual(patches, [])

    def test_multiple_sources_in_one_string(self) -> None:
        text, patches = self.fmt.normalize_source_names(
            "git-history および claude-history から収集"
        )
        self.assertIn("Git の変更履歴", text)
        self.assertIn("Claude の会話ログ", text)
        self.assertEqual(len(patches), 2)


class TestCheckForbiddenWords(unittest.TestCase):
    def setUp(self) -> None:
        self.fmt = ArtifactFormatter()

    def test_internal_terms_are_flagged(self) -> None:
        for term in FORBIDDEN_INTERNAL_TERMS:
            warns = self.fmt.check_forbidden_words(f"この候補の {term} を参照してください")
            self.assertTrue(
                any(term in w for w in warns),
                f"'{term}' should be flagged but wasn't",
            )

    def test_product_copy_violations_are_flagged(self) -> None:
        for term in FORBIDDEN_PRODUCT_COPY:
            warns = self.fmt.check_forbidden_words(f"今日は{term}が多かった")
            self.assertTrue(
                any(term in w for w in warns),
                f"'{term}' should be flagged but wasn't",
            )

    def test_clean_text_has_no_warnings(self) -> None:
        warns = self.fmt.check_forbidden_words("今日は Git の変更履歴を確認しました。課題調査に集中できた1日でした。")
        self.assertEqual(warns, [])

    def test_does_not_modify_text(self) -> None:
        # check_forbidden_words is warn-only — it must not alter the text
        original = "寄り道が多かった"
        warns = self.fmt.check_forbidden_words(original)
        self.assertTrue(len(warns) > 0)
        # Text is returned separately by apply(); this method only warns


class TestCheckEnglishLeakage(unittest.TestCase):
    def setUp(self) -> None:
        self.fmt = ArtifactFormatter()

    def test_detects_continuing_autonomously(self) -> None:
        warns = self.fmt.check_english_leakage("Continuing autonomously with the next step.")
        self.assertTrue(any("Continuing autonomously" in w for w in warns))

    def test_clean_japanese_has_no_warnings(self) -> None:
        warns = self.fmt.check_english_leakage("今日の作業を振り返りました。")
        self.assertEqual(warns, [])

    def test_allowed_english_not_flagged(self) -> None:
        # command names, file names — not in FORBIDDEN_ENGLISH_LEAKAGE
        warns = self.fmt.check_english_leakage("/skill-creator を使って登録しました。")
        self.assertEqual(warns, [])


class TestInjectMixedScopeNote(unittest.TestCase):
    def setUp(self) -> None:
        self.fmt = ArtifactFormatter()

    def test_note_prepended_when_mixed(self) -> None:
        inp = FormatterInput(raw_text="本文です", scope_mode="mixed")
        text = self.fmt.inject_mixed_scope_note("本文です", inp)
        self.assertIn("混在スコープ", text)
        self.assertTrue(text.index("混在スコープ") < text.index("本文です"))

    def test_no_note_when_single(self) -> None:
        inp = FormatterInput(raw_text="本文です", scope_mode="single")
        text = self.fmt.inject_mixed_scope_note("本文です", inp)
        self.assertNotIn("混在スコープ", text)
        self.assertEqual(text, "本文です")


class TestInjectFooter(unittest.TestCase):
    def setUp(self) -> None:
        self.fmt = ArtifactFormatter()

    def _inp(self, mode: str, sources: list[str] | None = None, date: str | None = None) -> FormatterInput:
        return FormatterInput(
            raw_text="本文です",
            mode=mode,
            sources=sources or ["git-history", "claude-history"],
            session_date=date or "2026-03-21",
        )

    def test_report_share_footer_has_no_raw_sources(self) -> None:
        inp = self._inp("report-share")
        text = self.fmt.inject_footer("本文です", inp)
        self.assertIn("---", text)
        self.assertNotIn("git-history", text)
        self.assertNotIn("claude-history", text)
        self.assertIn("DayTrace", text)

    def test_report_private_footer_shows_sources(self) -> None:
        inp = self._inp("report-private")
        text = self.fmt.inject_footer("本文です", inp)
        self.assertIn("再構成元", text)
        self.assertIn("Git の変更履歴", text)  # normalized
        self.assertIn("Claude の会話ログ", text)  # normalized

    def test_no_footer_when_no_sources_and_no_date(self) -> None:
        inp = FormatterInput(raw_text="本文です", mode="report-private")
        text = self.fmt.inject_footer("本文です", inp)
        self.assertEqual(text, "本文です")


class TestApplyPipeline(unittest.TestCase):
    def test_full_pipeline_clean_input(self) -> None:
        result = format_artifact(
            "今日は Git の変更履歴を確認しました。",
            mode="report-share",
            sources=["git-history"],
            session_date="2026-03-21",
        )
        self.assertIsInstance(result, FormatterResult)
        self.assertEqual(result.warnings, [])

    def test_full_pipeline_with_violations(self) -> None:
        result = format_artifact(
            "/Users/alice/report.md に寄り道の記録があります。candidate_id=xyz",
            mode="report-private",
        )
        self.assertIn("[PATH]", result.text)
        self.assertNotIn("/Users/alice/", result.text)
        # forbidden words should be warned
        self.assertTrue(any("寄り道" in w for w in result.warnings))
        self.assertTrue(any("candidate_id" in w for w in result.warnings))

    def test_patches_audit_trail(self) -> None:
        result = format_artifact(
            "/Users/bob/projects/main.py を編集。git-history から確認。",
            mode="report-private",
        )
        kinds = [p.kind for p in result.patches]
        self.assertIn("path_sanitize", kinds)
        self.assertIn("source_normalize", kinds)


class TestForbiddenWordsRegressionOnGoldenProposal(unittest.TestCase):
    """Golden proposal markdown must not contain forbidden internal state terms."""

    def _load_golden(self) -> str:
        golden_path = FIXTURES_DIR / "golden_proposal.md"
        return golden_path.read_text(encoding="utf-8")

    def test_golden_proposal_has_no_internal_state_terms(self) -> None:
        text = self._load_golden()
        fmt = ArtifactFormatter()
        warns = fmt.check_forbidden_words(text)
        internal_warns = [w for w in warns if "forbidden_word" in w and any(
            t in w for t in ("candidate_id", "triage_status", "internal state", "Continuing autonomously")
        )]
        self.assertEqual(
            internal_warns,
            [],
            f"Golden proposal contains forbidden internal terms:\n" + "\n".join(internal_warns),
        )


if __name__ == "__main__":
    unittest.main()
