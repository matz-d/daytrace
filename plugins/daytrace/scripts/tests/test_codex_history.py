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

    def test_load_history_indexes_uses_head_tail_excerpts_for_long_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            history_file = Path(temp_dir) / "history.jsonl"
            rows = [
                json.dumps(
                    {
                        "session_id": "inside",
                        "ts": f"2026-03-09T10:{index:02d}:00+09:00",
                        "text": f"message-{index}",
                    }
                )
                for index in range(10)
            ]
            history_file.write_text("\n".join(rows) + "\n", encoding="utf-8")

            _full_index, filtered_index = load_history_indexes(
                history_file,
                parse_datetime("2026-03-09", bound="start"),
                parse_datetime("2026-03-09", bound="end"),
            )

            excerpts = filtered_index["inside"]["user_excerpts"]
            self.assertEqual(len(excerpts), 8)
            self.assertIn("message-0", excerpts[0])
            self.assertTrue(any("message-9" in excerpt for excerpt in excerpts))


if __name__ == "__main__":
    unittest.main()
