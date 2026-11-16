#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from common import git_repo_context, sanitize_text, sanitize_url, summarize_text, within_range


class CommonTests(unittest.TestCase):
    def test_sanitize_url_drops_query_and_fragment(self) -> None:
        self.assertEqual(
            sanitize_url("https://example.com/path?a=1&b=2#frag"),
            "https://example.com/path",
        )

    def test_sanitize_text_rewrites_urls_inside_text(self) -> None:
        self.assertEqual(
            sanitize_text("check https://example.com/path?a=1 and https://foo.bar/x#y"),
            "check https://example.com/path and https://foo.bar/x",
        )

    def test_summarize_text_uses_sanitized_urls(self) -> None:
        summarized = summarize_text("visit https://example.com/path?a=1&b=2 for details", limit=200)
        self.assertEqual(summarized, "visit https://example.com/path for details")

    def test_within_range_normalizes_naive_bounds_before_comparison(self) -> None:
        self.assertTrue(
            within_range(
                datetime(2026, 3, 12, 12, 0, 0),
                datetime(2026, 3, 12, 0, 0, 0),
                datetime(2026, 3, 12, 23, 59, 59),
            )
        )

    def test_within_range_includes_value_exactly_at_end_boundary(self) -> None:
        boundary = datetime(2026, 3, 12, 23, 59, 59)

        self.assertTrue(
            within_range(
                boundary,
                datetime(2026, 3, 12, 0, 0, 0),
                boundary,
            )
        )

    def test_git_repo_context_for_root_nested_and_outside(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir).resolve() / "repo"
            nested = repo / "apps" / "web"
            outside = Path(temp_dir).resolve() / "outside"
            nested.mkdir(parents=True)
            outside.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)

            self.assertEqual(git_repo_context(repo, timeout=10), (repo, "."))
            self.assertEqual(git_repo_context(nested, timeout=10), (repo, "apps/web"))
            self.assertIsNone(git_repo_context(outside, timeout=10))


if __name__ == "__main__":
    unittest.main()
