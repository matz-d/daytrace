#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from chrome_history import collapse_visits, normalize_url


class ChromeHistoryTests(unittest.TestCase):
    def test_normalize_url_drops_query_string(self) -> None:
        self.assertEqual(
            normalize_url("https://github.com/matz-d/daytrace?tab=readme#top"),
            "https://github.com/matz-d/daytrace",
        )

    def test_collapse_visits_merges_same_normalized_url(self) -> None:
        rows = [
            ("Default", "https://github.com/", "GitHub", 13416800000000000, 2),
            ("Default", "https://github.com/", "GitHub", 13416800010000000, 3),
            ("Profile 1", "https://github.com/", "GitHub", 13416800020000000, 1),
        ]
        collapsed = sorted(collapse_visits(rows), key=lambda item: (str(item["profile"]), str(item["url"])))

        self.assertEqual(len(collapsed), 2)
        self.assertEqual(collapsed[0]["profile"], "Default")
        self.assertEqual(collapsed[0]["visit_count"], 5)
        self.assertEqual(collapsed[1]["profile"], "Profile 1")
        self.assertEqual(collapsed[1]["visit_count"], 1)


if __name__ == "__main__":
    unittest.main()
