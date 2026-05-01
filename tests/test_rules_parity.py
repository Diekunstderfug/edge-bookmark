"""Parity checks: extension/fast_rules.json must match config/rules.yaml as loaded by rules.py."""

import json
import unittest
from pathlib import Path

from bookmark_advisor.rules import load_rules

REPO_ROOT = Path(__file__).resolve().parents[1]
FAST_RULES_PATH = REPO_ROOT / "extension" / "fast_rules.json"
RULES_YAML_PATH = REPO_ROOT / "config" / "rules.yaml"


class FastRulesParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FAST_RULES_PATH, encoding="utf-8") as f:
            cls.fast_rules = json.load(f)
        cls.rules_config = load_rules(RULES_YAML_PATH)

    def test_protected_paths_match(self):
        expected = list(self.rules_config.protected_paths)
        actual = self.fast_rules["protected_paths"]
        self.assertEqual(actual, expected)

    def test_folder_relocations_match(self):
        expected = [
            {"from": r.from_path, "to": r.to_path, "reason": r.reason}
            for r in self.rules_config.folder_relocations
        ]
        actual = self.fast_rules["folder_relocations"]
        self.assertEqual(actual, expected)

    def test_bookmark_relocations_match(self):
        expected = []
        for r in self.rules_config.bookmark_relocations:
            match = {}
            if r.match.folder_path is not None:
                match["folder_path"] = r.match.folder_path
            if r.match.title_contains is not None:
                match["title_contains"] = r.match.title_contains
            if r.match.title_equals is not None:
                match["title_equals"] = r.match.title_equals
            if r.match.url_contains is not None:
                match["url_contains"] = r.match.url_contains
            expected.append({"match": match, "to": r.to_path, "reason": r.reason})
        actual = self.fast_rules["bookmark_relocations"]
        self.assertEqual(actual, expected)

    def test_defaults_match(self):
        fast_defaults = self.fast_rules["defaults"]
        py_defaults = self.rules_config.defaults
        self.assertEqual(
            fast_defaults["protect_root_loose_bookmarks"],
            py_defaults.protect_root_loose_bookmarks,
        )
        self.assertEqual(
            fast_defaults["allow_new_folders_in_advise"],
            py_defaults.allow_new_folders_in_advise,
        )

    def test_generic_folder_names_match(self):
        fast_names = {n.upper() for n in self.fast_rules["defaults"]["generic_new_folder_names"]}
        py_names = self.rules_config.defaults.generic_new_folder_names
        self.assertEqual(fast_names, py_names)

    def test_category_hints_match(self):
        fast_hints = self.fast_rules["category_hints"]
        py_hints = self.rules_config.category_hints
        self.assertEqual(set(fast_hints.keys()), set(py_hints.keys()))
        for key in fast_hints:
            self.assertEqual(set(fast_hints[key]), py_hints[key], f"category_hints[{key}] mismatch")

    def test_json_is_valid(self):
        with open(FAST_RULES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("defaults", data)
        self.assertIn("protected_paths", data)
        self.assertIn("category_hints", data)
        self.assertIn("folder_relocations", data)
        self.assertIn("bookmark_relocations", data)

    def test_no_inline_protected_paths_in_ai_planner(self):
        ai_planner_path = REPO_ROOT / "extension" / "ai_planner.js"
        content = ai_planner_path.read_text(encoding="utf-8")
        self.assertNotIn("PROTECTED_PATHS = [", content)
        self.assertNotIn("FORCED_FOLDER_RELOCATIONS = [", content)
        self.assertNotIn("FORCED_BOOKMARK_RELOCATIONS = [", content)


if __name__ == "__main__":
    unittest.main()
