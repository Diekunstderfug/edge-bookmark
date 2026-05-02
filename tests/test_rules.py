import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bookmark_advisor.rules import load_rules, validate_rules_file

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
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing required top-level key", result.stderr)


if __name__ == "__main__":
    unittest.main()
