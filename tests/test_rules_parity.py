"""Parity checks: extension/fast_rules.json must equal the payload generated from config/rules.yaml.

config/rules.yaml 是唯一事实来源：本套测试把 extension/fast_rules.json
当作已提交的生成物做校验——加载 YAML → dump_fast_rules 生成 → 与提交文件
断言相等（结构逐字段 + 键顺序 + 字节级复现），并保留既有的与
extension JS 侧一致性检查。
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bookmark_advisor.rules import dump_fast_rules, load_rules, write_fast_rules

REPO_ROOT = Path(__file__).resolve().parents[1]
FAST_RULES_PATH = REPO_ROOT / "extension" / "fast_rules.json"
RULES_YAML_PATH = REPO_ROOT / "config" / "rules.yaml"


class FastRulesParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FAST_RULES_PATH, encoding="utf-8") as f:
            cls.fast_rules = json.load(f)
        cls.rules_config = load_rules(RULES_YAML_PATH)
        cls.generated = dump_fast_rules(cls.rules_config)

    def test_generated_payload_matches_committed_file(self):
        self.assertEqual(self.generated, self.fast_rules)

    def test_generated_top_level_key_order_matches(self):
        self.assertEqual(list(self.generated), list(self.fast_rules))

    def test_generated_defaults_key_order_matches(self):
        self.assertEqual(
            list(self.generated["defaults"]),
            list(self.fast_rules["defaults"]),
        )

    def test_generated_category_hint_key_order_matches(self):
        self.assertEqual(
            list(self.generated["category_hints"]),
            list(self.fast_rules["category_hints"]),
        )

    def test_generated_match_key_order_matches(self):
        self.assertEqual(
            len(self.generated["bookmark_relocations"]),
            len(self.fast_rules["bookmark_relocations"]),
        )
        for generated_rule, committed_rule in zip(
            self.generated["bookmark_relocations"],
            self.fast_rules["bookmark_relocations"],
        ):
            self.assertEqual(
                list(generated_rule["match"]),
                list(committed_rule["match"]),
            )

    def test_write_fast_rules_reproduces_committed_bytes(self):
        with TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "fast_rules.json"
            write_fast_rules(self.rules_config, out_path)
            self.assertEqual(out_path.read_bytes(), FAST_RULES_PATH.read_bytes())

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
