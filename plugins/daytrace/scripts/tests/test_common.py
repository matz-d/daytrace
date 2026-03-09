#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import sanitize_text, sanitize_url, summarize_text


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


if __name__ == "__main__":
    unittest.main()
