#!/usr/bin/env python3

from __future__ import annotations

import unittest

import conftest  # noqa: F401  (adds scripts/ to sys.path)
from request_text import clean_request_text, is_injected_turn


class RequestTextTests(unittest.TestCase):
    def test_injected_turns_become_empty(self) -> None:
        for text in (
            "This session is being continued from a previous conversation that ran out of context.",
            "<local-command-stdout>done</local-command-stdout>",
            "# AGENTS.md instructions for /repo\n<INSTRUCTIONS>x</INSTRUCTIONS>",
            "<environment_context><cwd>/repo</cwd></environment_context>",
            "<system-reminder>only a reminder</system-reminder>",
        ):
            with self.subTest(text=text[:30]):
                self.assertEqual(clean_request_text(text), "")

    def test_user_words_survive_around_injected_blocks(self) -> None:
        self.assertEqual(clean_request_text("<system-reminder>x</system-reminder>\nなんか違うな"), "なんか違うな")

    def test_slash_command_becomes_name_and_args(self) -> None:
        text = "<command-name>/fx-l3</command-name><command-message>fx-l3</command-message><command-args>USDJPY</command-args>"
        self.assertEqual(clean_request_text(text), "/fx-l3 USDJPY")

    def test_pasted_content_is_kept(self) -> None:
        text = '<pasted_content id="a1">見積の文面</pasted_content> これを直して'
        self.assertIn("見積の文面", clean_request_text(text))

    def test_long_text_is_truncated(self) -> None:
        self.assertEqual(len(clean_request_text("あ" * 5000, limit=100)), 101)

    def test_is_injected_turn_ignores_leading_space(self) -> None:
        self.assertTrue(is_injected_turn("  <task-notification>x</task-notification>"))


if __name__ == "__main__":
    unittest.main()
