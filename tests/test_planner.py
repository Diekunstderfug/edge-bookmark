import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bookmark_advisor.parser import load_snapshot
from bookmark_advisor.planner import build_advise_plan, build_merge_plan
from bookmark_advisor.rules import load_rules


def write_rules_file(base_dir: Path, protect_root: bool = True) -> Path:
    rules_path = base_dir / "rules.yaml"
    rules_path.write_text(
        textwrap.dedent(
            f"""
            defaults:
              protect_root_loose_bookmarks: {"true" if protect_root else "false"}
              allow_new_folders_in_advise: true
              generic_new_folder_names:
                - EDU
                - ORG
                - COM
                - NET
                - CN
                - WWW

            category_hints:
              ai: [ai, openai, chatgpt, deepseek, gemini, claude, llm, prompt, copilot]
              database: [database, dataset, db, portal, archive, catalog]

            folder_relocations:
              - from: /收藏夹栏/TNBC Datasets
                to: /收藏夹栏/Database
                reason: Preferred category mapping places TNBC Datasets under Database

            bookmark_relocations:
              - match:
                  folder_path: /收藏夹栏/AI
                  title_contains: MCP
                to: /收藏夹栏/AI/mcp
                reason: MCP documentation and ecosystem links belong in the dedicated mcp folder
              - match:
                  folder_path: /收藏夹栏/AI
                  url_contains: skillsmp.com
                to: /收藏夹栏/AI/skill
                reason: Skills marketplace links belong in the dedicated skill folder

            protected_paths:
              - /收藏夹栏
              - /其他收藏夹
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return rules_path


class PlannerTest(unittest.TestCase):
    def test_merge_plan_moves_mcp_and_skill_bookmarks_into_new_ai_subfolders(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "Bookmarks"
            source.write_text(
                """
                {
                  "roots": {
                    "bookmark_bar": {
                      "type": "folder",
                      "name": "收藏夹栏",
                      "children": [
                        {
                          "type": "folder",
                          "id": "30",
                          "name": "AI",
                          "children": [
                            {"type": "folder", "id": "31", "name": "mcp", "children": []},
                            {"type": "folder", "id": "32", "name": "skill", "children": []},
                            {
                              "type": "url",
                              "id": "33",
                              "name": "MCP中文文档 – MCP 中文站（Model Context Protocol 中文）",
                              "url": "https://mcpcn.com/docs/"
                            },
                            {
                              "type": "url",
                              "id": "34",
                              "name": "Agent Skills Marketplace - Claude, Codex & ChatGPT Skills | SkillsMP",
                              "url": "https://skillsmp.com/"
                            }
                          ]
                        }
                      ]
                    }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            rules = load_rules(write_rules_file(temp_path))
            snapshot = load_snapshot(source)
            plan = build_merge_plan(snapshot, Path("backup.bak"), Path("report.md"), rules)
            move_targets = {
                action.bookmark_id: action.to_path
                for action in plan.actions
                if action.action_type == "move_bookmark"
            }
            self.assertEqual(move_targets["33"], "/收藏夹栏/AI/mcp")
            self.assertEqual(move_targets["34"], "/收藏夹栏/AI/skill")

    def test_advise_plan_moves_tnbc_datasets_under_database(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "Bookmarks"
            source.write_text(
                """
                {
                  "roots": {
                    "bookmark_bar": {
                      "type": "folder",
                      "name": "收藏夹栏",
                      "children": [
                        {
                          "type": "folder",
                          "id": "20",
                          "name": "Database",
                          "children": []
                        },
                        {
                          "type": "folder",
                          "id": "21",
                          "name": "TNBC Datasets",
                          "children": [
                            {
                              "type": "url",
                              "id": "22",
                              "name": "cBioPortal",
                              "url": "https://www.cbioportal.org/"
                            }
                          ]
                        }
                      ]
                    }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            rules = load_rules(write_rules_file(temp_path))
            snapshot = load_snapshot(source)
            plan = build_advise_plan(snapshot, Path("backup.bak"), Path("report.md"), rules)
            folder_moves = [action for action in plan.actions if action.action_type == "move_folder"]
            self.assertTrue(folder_moves)
            self.assertEqual(folder_moves[0].to_path, "/收藏夹栏/Database")

    def test_merge_plan_moves_loose_bookmarks_into_existing_folder_when_root_protection_disabled(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "Bookmarks"
            source.write_text(
                """
                {
                  "roots": {
                    "bookmark_bar": {
                      "type": "folder",
                      "name": "收藏夹栏",
                      "children": [
                        {
                          "type": "folder",
                          "id": "10",
                          "name": "AI",
                          "children": [
                            {
                              "type": "url",
                              "id": "11",
                              "name": "ChatGPT",
                              "url": "https://chatgpt.com/"
                            }
                          ]
                        },
                        {
                          "type": "url",
                          "id": "12",
                          "name": "OpenAI Docs",
                          "url": "https://platform.openai.com/docs"
                        }
                      ]
                    }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            rules = load_rules(write_rules_file(temp_path, protect_root=False))
            snapshot = load_snapshot(source)
            plan = build_merge_plan(snapshot, Path("backup.bak"), Path("report.md"), rules)
            move_actions = [action for action in plan.actions if action.action_type == "move_bookmark"]
            self.assertTrue(move_actions)
            self.assertEqual(move_actions[0].to_path, "/收藏夹栏/AI")

    def test_merge_plan_keeps_root_bookmarks_for_review_when_protected(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "Bookmarks"
            source.write_text(
                """
                {
                  "roots": {
                    "bookmark_bar": {
                      "type": "folder",
                      "name": "收藏夹栏",
                      "children": [
                        {
                          "type": "folder",
                          "id": "10",
                          "name": "AI",
                          "children": []
                        },
                        {
                          "type": "url",
                          "id": "12",
                          "name": "OpenAI Docs",
                          "url": "https://platform.openai.com/docs"
                        }
                      ]
                    }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            rules = load_rules(write_rules_file(temp_path, protect_root=True))
            snapshot = load_snapshot(source)
            plan = build_merge_plan(snapshot, Path("backup.bak"), Path("report.md"), rules)
            move_actions = [action for action in plan.actions if action.action_type == "move_bookmark"]
            keep_actions = [action for action in plan.actions if action.action_type == "keep_for_review"]
            self.assertFalse(move_actions)
            self.assertEqual(len(keep_actions), 1)
            self.assertIn("protected", keep_actions[0].reason.lower())

    def test_plan_contains_extension_metadata(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "Bookmarks"
            source.write_text(
                """
                {
                  "roots": {
                    "bookmark_bar": {
                      "type": "folder",
                      "name": "收藏夹栏",
                      "children": []
                    }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            rules = load_rules(write_rules_file(temp_path))
            snapshot = load_snapshot(source)
            plan = build_merge_plan(snapshot, Path("backup.bak"), Path("report.md"), rules)
            payload = plan.to_dict()
            self.assertEqual(payload["plan_version"], "1")
            self.assertEqual(payload["executor"], "edge-extension")
            self.assertEqual(payload["source"], "bookmark-advisor")


if __name__ == "__main__":
    unittest.main()
