#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from codex_history import load_history_indexes
from common import parse_datetime


class CodexHistoryTests(unittest.TestCase):
    def test_load_history_indexes_returns_full_and_filtered_views(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            history_file = Path(temp_dir) / "history.jsonl"
            history_file.write_text(
                "\n".join(
                    [
                        '{"session_id":"inside","ts":"2026-03-09T10:00:00+09:00","text":"review this PR"}',
                        '{"session_id":"outside","ts":"2026-03-07T10:00:00+09:00","text":"old session"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            full_index, filtered_index = load_history_indexes(
                history_file,
                parse_datetime("2026-03-09", bound="start"),
                parse_datetime("2026-03-09", bound="end"),
            )

            self.assertEqual(set(full_index.keys()), {"inside", "outside"})
            self.assertEqual(set(filtered_index.keys()), {"inside"})
            self.assertEqual(filtered_index["inside"]["user_excerpts"], ["review this PR"])


if __name__ == "__main__":
    unittest.main()
