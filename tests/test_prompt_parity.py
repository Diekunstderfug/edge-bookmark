"""Prompt parity tests: verify Python and JS system prompts share the same 8 core policy points in order.

Runs without Node.js — JS source is read as text and checked for the same phrases.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from bookmark_advisor.ai_planner import _system_prompt

# 8 core policy phrases that MUST appear in both prompts, in this order
CORE_PHRASES = [
    "You are an expert bookmark organizer",
    "Return JSON only",
    "Focus on semantic organization, not cosmetic renaming",
    "Prefer moving bookmarks into semantically appropriate existing folders",
    "Only propose create_folder when a genuinely new category is justified",
    "Use keep_for_review for ambiguous, risky, or low-confidence items",
    "Loose bookmarks directly under protected root paths must stay in place",
    "Only bookmarks with review_status=reviewed may be auto-classified",
]

_EXTENSION_DIR = Path(__file__).resolve().parent.parent / "extension"
_JS_PLANNER_PATH = _EXTENSION_DIR / "ai_planner.js"


def _read_js_system_prompt_source() -> str:
    """Extract the buildSystemPrompt function body from JS source."""
    js_source = _JS_PLANNER_PATH.read_text(encoding="utf-8")
    # Match the return [...] block inside buildSystemPrompt
    match = re.search(
        r"function buildSystemPrompt\(maxActions\)\s*\{[^[]*(\[[\s\S]*?\])\.join",
        js_source,
    )
    if not match:
        raise AssertionError("Could not find buildSystemPrompt return array in JS source")
    return match.group(1)


class TestPromptParity(unittest.TestCase):
    """Both Python and JS system prompts must contain the 8 core policy points in order."""

    def test_python_prompt_has_all_core_phrases_in_order(self):
        prompt = _system_prompt(max_actions=40)
        positions = []
        for phrase in CORE_PHRASES:
            idx = prompt.find(phrase)
            self.assertGreater(
                idx,
                -1,
                f"Python prompt missing core phrase: {phrase!r}\nFull prompt:\n{prompt}",
            )
            positions.append(idx)
        # Verify order: each phrase appears after the previous one
        for i in range(1, len(positions)):
            self.assertGreater(
                positions[i],
                positions[i - 1],
                f"Python prompt: phrase {i!r} at pos {positions[i]} is not after "
                f"phrase {i-1!r} at pos {positions[i-1]}",
            )

    def test_js_prompt_has_all_core_phrases_in_order(self):
        js_array_source = _read_js_system_prompt_source()
        # Flatten array source into a single string (simulate .join(" "))
        # Extract all string literals from the JS array
        string_literals = re.findall(r'"([^"]*)"', js_array_source)
        # Also handle template literals with ${maxActions}
        template_literals = re.findall(r"`([^`]*)`", js_array_source)
        all_parts = string_literals + template_literals
        joined_prompt = " ".join(all_parts)
        positions = []
        for phrase in CORE_PHRASES:
            idx = joined_prompt.find(phrase)
            self.assertGreater(
                idx,
                -1,
                f"JS prompt missing core phrase: {phrase!r}\nJoined prompt:\n{joined_prompt}",
            )
            positions.append(idx)
        for i in range(1, len(positions)):
            self.assertGreater(
                positions[i],
                positions[i - 1],
                f"JS prompt: phrase {i!r} at pos {positions[i]} is not after "
                f"phrase {i-1!r} at pos {positions[i-1]}",
            )

    def test_python_prompt_keeps_schema_self_validation_line(self):
        prompt = _system_prompt(max_actions=40, require_schema_self_validation=True)
        self.assertIn(
            "You must ensure the JSON object matches the provided schema exactly",
            prompt,
        )

    def test_python_prompt_without_schema_self_validation(self):
        prompt = _system_prompt(max_actions=40, require_schema_self_validation=False)
        self.assertNotIn(
            "You must ensure the JSON object matches the provided schema exactly",
            prompt,
        )

    def test_js_prompt_keeps_extension_linting_line(self):
        js_array_source = _read_js_system_prompt_source()
        self.assertIn(
            "The browser extension will lint and post-process your output",
            js_array_source,
        )

    def test_max_actions_parameterized(self):
        prompt = _system_prompt(max_actions=99)
        self.assertIn("Propose at most 99 high-value actions", prompt)

    def test_js_max_actions_template(self):
        js_source = _JS_PLANNER_PATH.read_text(encoding="utf-8")
        self.assertIn("${maxActions}", js_source)

    def test_both_prompts_have_keep_for_review(self):
        """Cross-check: both prompts mention keep_for_review."""
        py_prompt = _system_prompt(max_actions=40)
        self.assertIn("keep_for_review", py_prompt)
        js_array_source = _read_js_system_prompt_source()
        self.assertIn("keep_for_review", js_array_source)

    def test_both_prompts_have_protected_root(self):
        """Cross-check: both prompts mention protected root."""
        py_prompt = _system_prompt(max_actions=40)
        self.assertIn("protected root", py_prompt)
        js_array_source = _read_js_system_prompt_source()
        self.assertIn("protected root", js_array_source)

    def test_both_prompts_have_review_status(self):
        """Cross-check: both prompts mention review_status."""
        py_prompt = _system_prompt(max_actions=40)
        self.assertIn("review_status", py_prompt)
        js_array_source = _read_js_system_prompt_source()
        self.assertIn("review_status", js_array_source)


if __name__ == "__main__":
    unittest.main()
