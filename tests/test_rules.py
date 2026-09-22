import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bookmark_advisor.rules import (
    RulesConfig,
    RulesDefaults,
    dump_fast_rules,
    load_rules,
    render_fast_rules,
    validate_rules_file,
    write_fast_rules,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


class RulesTest(unittest.TestCase):
    def test_load_rules_parses_yaml_file(self):
        with TemporaryDirectory() as temp_dir:
            rules_path = Path(temp_dir) / "rules.yaml"
            rules_path.write_text(
                textwrap.dedent(
                    """
                    defaults:
                      protect_root_loose_bookmarks: true
                      allow_new_folders_in_advise: true
                      generic_new_folder_names: [EDU, ORG]

                    category_hints:
                      ai: [chatgpt, openai]

                    folder_relocations:
                      - from: /收藏夹栏/TNBC Datasets
                        to: /收藏夹栏/Database
                        reason: Move TNBC under Database

                    bookmark_relocations:
                      - match:
                          folder_path: /收藏夹栏/AI
                          title_contains: MCP
                        to: /收藏夹栏/AI/mcp
                        reason: Move MCP content

                    protected_paths:
                      - /收藏夹栏
                      - /其他收藏夹
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            rules = load_rules(rules_path)
            self.assertTrue(rules.defaults.protect_root_loose_bookmarks)
            self.assertIn("chatgpt", rules.category_hints["ai"])
            self.assertEqual(rules.folder_relocations[0].to_path, "/收藏夹栏/Database")

    def test_validate_rules_reports_missing_fields(self):
        with TemporaryDirectory() as temp_dir:
            rules_path = Path(temp_dir) / "rules.yaml"
            rules_path.write_text(
                "defaults:\n  protect_root_loose_bookmarks: true\n",
                encoding="utf-8",
            )
            errors = validate_rules_file(rules_path)
            self.assertTrue(errors)
            self.assertTrue(any("missing required top-level key" in error for error in errors))

    def test_validate_rules_command_returns_non_zero_on_invalid_rules(self):
        with TemporaryDirectory() as temp_dir:
            rules_path = Path(temp_dir) / "rules.yaml"
            rules_path.write_text(
                "defaults:\n  protect_root_loose_bookmarks: true\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = str(_REPO_ROOT / "src")
            result = subprocess.run(
                [sys.executable, "-m", "bookmark_advisor", "validate-rules", "--rules", str(rules_path)],
                cwd=_REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing required top-level key", result.stderr)


class FastRulesDumpTest(unittest.TestCase):
    @staticmethod
    def _write_rules(temp_dir, yaml_text: str) -> Path:
        rules_path = Path(temp_dir) / "rules.yaml"
        rules_path.write_text(
            textwrap.dedent(yaml_text).strip() + "\n",
            encoding="utf-8",
        )
        return rules_path

    _MINIMAL_YAML = """
        defaults:
          protect_root_loose_bookmarks: false
          allow_new_folders_in_advise: true
          generic_new_folder_names: [WWW, EDU]

        category_hints:
          ai: [llm, openai]
          编程: [python, git]

        folder_relocations:
          - from: /收藏夹栏/Old
            to: /收藏夹栏/New
            reason: cleanup

        bookmark_relocations:
          - match:
              folder_path: /收藏夹栏/AI
              title_equals: Zotero
            to: /收藏夹栏/Zotero
            reason: zotero links

        protected_paths:
          - /收藏夹栏
        """

    def test_dump_fast_rules_structure(self):
        with TemporaryDirectory() as temp_dir:
            rules = load_rules(self._write_rules(temp_dir, self._MINIMAL_YAML))
            payload = dump_fast_rules(rules)
        self.assertEqual(
            list(payload),
            [
                "defaults",
                "protected_paths",
                "category_hints",
                "folder_relocations",
                "bookmark_relocations",
            ],
        )
        self.assertEqual(
            payload["defaults"],
            {
                "protect_root_loose_bookmarks": False,
                "allow_new_folders_in_advise": True,
                "generic_new_folder_names": ["WWW", "EDU"],
            },
        )
        self.assertEqual(payload["protected_paths"], ["/收藏夹栏"])
        self.assertEqual(list(payload["category_hints"]), ["ai", "编程"])
        self.assertEqual(
            payload["folder_relocations"],
            [
                {
                    "from": "/收藏夹栏/Old",
                    "to": "/收藏夹栏/New",
                    "reason": "cleanup",
                }
            ],
        )
        self.assertEqual(len(payload["bookmark_relocations"]), 1)
        bookmark_rule = payload["bookmark_relocations"][0]
        self.assertEqual(list(bookmark_rule), ["match", "to", "reason"])
        self.assertEqual(
            bookmark_rule["match"],
            {"folder_path": "/收藏夹栏/AI", "title_equals": "Zotero"},
        )
        self.assertEqual(bookmark_rule["to"], "/收藏夹栏/Zotero")

    def test_dump_fast_rules_preserves_source_order(self):
        # RulesConfig 中 set 字段无序；dump 必须按 YAML 源顺序还原为有序数组
        #（extension/fast_rules.json 黄金样例即按源顺序内联）。
        yaml_text = """
            defaults:
              protect_root_loose_bookmarks: true
              allow_new_folders_in_advise: true
              generic_new_folder_names: [ORG, EDU, COM]

            category_hints:
              ai: [prompt, llm, openai]

            folder_relocations: []

            bookmark_relocations: []

            protected_paths: []
            """
        with TemporaryDirectory() as temp_dir:
            rules = load_rules(self._write_rules(temp_dir, yaml_text))
            payload = dump_fast_rules(rules)
        self.assertEqual(
            payload["defaults"]["generic_new_folder_names"],
            ["ORG", "EDU", "COM"],
        )
        self.assertEqual(payload["category_hints"]["ai"], ["prompt", "llm", "openai"])

    def test_dump_fast_rules_without_order_falls_back_to_sorted(self):
        # 手工构造的 RulesConfig 没有顺序信息：回退为排序输出保证确定性。
        rules = RulesConfig(
            defaults=RulesDefaults(generic_new_folder_names={"EDU", "ORG"}),
            category_hints={"ai": {"llm", "openai"}},
            folder_relocations=[],
            bookmark_relocations=[],
            protected_paths=[],
            source_path=Path("rules.yaml"),
        )
        payload = dump_fast_rules(rules)
        self.assertEqual(payload["defaults"]["generic_new_folder_names"], ["EDU", "ORG"])
        self.assertEqual(payload["category_hints"]["ai"], ["llm", "openai"])

    def test_dump_fast_rules_raises_on_order_mismatch(self):
        base = dict(
            category_hints={"ai": {"llm"}},
            folder_relocations=[],
            bookmark_relocations=[],
            protected_paths=[],
            source_path=Path("rules.yaml"),
        )
        bad_generic_order = RulesConfig(
            defaults=RulesDefaults(
                generic_new_folder_names={"EDU"},
                generic_new_folder_names_order=["EDU", "ORG"],
            ),
            **base,
        )
        with self.assertRaises(ValueError):
            dump_fast_rules(bad_generic_order)

        bad_hint_order = RulesConfig(
            defaults=RulesDefaults(
                generic_new_folder_names={"EDU"},
                generic_new_folder_names_order=["EDU"],
            ),
            category_hint_order={"ai": ["llm", "ghost"]},
            **base,
        )
        with self.assertRaises(ValueError):
            dump_fast_rules(bad_hint_order)

    def test_render_fast_rules_matches_extension_format(self):
        # 渲染格式与 extension/fast_rules.json 历史形状逐行对齐：
        # 标量数组内联，match 对象内联，relocation 对象展开，末尾单个换行。
        payload = {
            "defaults": {
                "protect_root_loose_bookmarks": True,
                "allow_new_folders_in_advise": True,
                "generic_new_folder_names": ["EDU"],
            },
            "protected_paths": ["/收藏夹栏"],
            "category_hints": {"ai": ["llm"]},
            "folder_relocations": [
                {"from": "/a", "to": "/b", "reason": "r"},
            ],
            "bookmark_relocations": [
                {
                    "match": {"folder_path": "/a", "title_contains": "x"},
                    "to": "/b",
                    "reason": "r",
                },
            ],
        }
        rendered = render_fast_rules(payload)
        expected = textwrap.dedent(
            """
            {
              "defaults": {
                "protect_root_loose_bookmarks": true,
                "allow_new_folders_in_advise": true,
                "generic_new_folder_names": ["EDU"]
              },
              "protected_paths": ["/收藏夹栏"],
              "category_hints": {
                "ai": ["llm"]
              },
              "folder_relocations": [
                {
                  "from": "/a",
                  "to": "/b",
                  "reason": "r"
                }
              ],
              "bookmark_relocations": [
                {
                  "match": { "folder_path": "/a", "title_contains": "x" },
                  "to": "/b",
                  "reason": "r"
                }
              ]
            }
            """
        ).strip() + "\n"
        self.assertEqual(rendered, expected)
        self.assertEqual(json.loads(rendered), payload)

    def test_render_fast_rules_empty_collections(self):
        payload = {
            "defaults": {
                "protect_root_loose_bookmarks": True,
                "allow_new_folders_in_advise": True,
                "generic_new_folder_names": [],
            },
            "protected_paths": [],
            "category_hints": {},
            "folder_relocations": [],
            "bookmark_relocations": [],
        }
        rendered = render_fast_rules(payload)
        self.assertIn('"generic_new_folder_names": []', rendered)
        self.assertIn('"protected_paths": [],', rendered)
        self.assertIn('"category_hints": {},', rendered)
        self.assertIn('"folder_relocations": [],', rendered)
        self.assertIn('"bookmark_relocations": []', rendered)
        self.assertEqual(json.loads(rendered), payload)

    def test_write_fast_rules_round_trip(self):
        with TemporaryDirectory() as temp_dir:
            rules = load_rules(self._write_rules(temp_dir, self._MINIMAL_YAML))
            expected = dump_fast_rules(rules)
            out_path = Path(temp_dir) / "generated" / "fast_rules.json"
            write_fast_rules(rules, out_path)
            written = out_path.read_text(encoding="utf-8")
        self.assertTrue(written.endswith("}\n"))
        self.assertEqual(json.loads(written), expected)

    def test_export_fast_rules_command_writes_payload(self):
        with TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            rules_path = self._write_rules(temp, self._MINIMAL_YAML)
            out_path = temp / "nested" / "fast_rules.json"
            env = dict(os.environ)
            env["PYTHONPATH"] = str(_REPO_ROOT / "src")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "bookmark_advisor",
                    "export-fast-rules",
                    "--rules",
                    str(rules_path),
                    "--output",
                    str(out_path),
                ],
                cwd=_REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"output={out_path}", result.stdout)
            self.assertIn(f"rules={rules_path.resolve()}", result.stdout)
            expected = dump_fast_rules(load_rules(rules_path))
            written = out_path.read_text(encoding="utf-8")
            self.assertEqual(json.loads(written), expected)
            self.assertTrue(written.endswith("}\n"))


if __name__ == "__main__":
    unittest.main()
