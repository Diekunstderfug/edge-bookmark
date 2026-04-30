import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bookmark_advisor.ai_planner import (
    _system_prompt,
    _user_prompt,
    apply_guardrails_to_actions,
    finalize_draft_plan,
)
from bookmark_advisor.models import BookmarkLocator, SemanticAction
from bookmark_advisor.parser import load_snapshot
from bookmark_advisor.rules import load_rules
from bookmark_advisor.snapshot_io import (
    build_snapshot_document,
    diff_snapshot_documents,
)


def write_rules_file(base_dir: Path, protect_root: bool = True) -> Path:
    rules_path = base_dir / "rules.yaml"
    rules_path.write_text(
        textwrap.dedent(
            f"""
            defaults:
              protect_root_loose_bookmarks: {"true" if protect_root else "false"}
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
    return rules_path


class SemanticFlowTest(unittest.TestCase):
    def test_snapshot_export_contains_sorted_bookmarks(self):
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "Bookmarks"
            source.write_text(
                """
                {
                  "roots": {
                    "bookmark_bar": {
                      "type": "folder",
                      "name": "收藏夹栏",
                      "children": [
                        {
                          "type": "url",
                          "id": "2",
                          "name": "Zoo",
                          "url": "https://z.example.com"
                        },
                        {
                          "type": "url",
                          "id": "1",
                          "name": "Alpha",
                          "url": "https://a.example.com"
                        }
                      ]
                    }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            document = build_snapshot_document(load_snapshot(source))
            self.assertEqual(document.bookmarks[0].title, "Alpha")
            self.assertEqual(document.bookmarks[1].title, "Zoo")

    def test_guardrails_block_protected_root_moves(self):
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
                          "type": "url",
                          "id": "10",
                          "name": "ChatGPT",
                          "url": "https://chatgpt.com/"
                        }
                      ]
                    }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            snapshot_document = build_snapshot_document(load_snapshot(source)).to_dict()
            rules = load_rules(write_rules_file(temp_path, protect_root=True))
            actions = [
                SemanticAction(
                    action_id="tmp",
                    action_type="move_bookmark",
                    status="proposed",
                    reason="AI guessed this belongs in AI",
                    confidence=0.9,
                    bookmark_locator=BookmarkLocator(
                        id="10",
                        title="ChatGPT",
                        url="https://chatgpt.com/",
                        normalized_url="https://chatgpt.com/",
                        folder_path="/收藏夹栏",
                    ),
                    from_path="/收藏夹栏",
                    to_path="/收藏夹栏/AI",
                )
            ]
            guarded = apply_guardrails_to_actions(actions, snapshot_document, rules)
            self.assertEqual(guarded[0].action_type, "keep_for_review")
            self.assertEqual(guarded[0].status, "blocked")
            self.assertEqual(guarded[0].details["evidence"]["review_status"], "missing")

    def test_guardrails_block_unreviewed_public_moves(self):
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
                          "name": "AI",
                          "children": []
                        },
                        {
                          "type": "url",
                          "id": "10",
                          "name": "ChatGPT",
                          "url": "https://chatgpt.com/"
                        }
                      ]
                    }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            snapshot_document = build_snapshot_document(load_snapshot(source)).to_dict()
            rules = load_rules(write_rules_file(temp_path, protect_root=False))
            actions = [
                SemanticAction(
                    action_id="tmp",
                    action_type="move_bookmark",
                    status="proposed",
                    reason="AI guessed this belongs in AI",
                    confidence=0.9,
                    bookmark_locator=BookmarkLocator(
                        id="10",
                        title="ChatGPT",
                        url="https://chatgpt.com/",
                        normalized_url="https://chatgpt.com/",
                        folder_path="/收藏夹栏",
                    ),
                    from_path="/收藏夹栏",
                    to_path="/收藏夹栏/AI",
                )
            ]
            guarded = apply_guardrails_to_actions(actions, snapshot_document, rules)
            self.assertEqual(guarded[0].action_type, "keep_for_review")
            self.assertEqual(guarded[0].status, "blocked")
            self.assertIn("missing-review", guarded[0].details.get("guardrail", ""))

    def test_ai_prompts_keep_protected_root_loose_bookmarks_in_place(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            rules = load_rules(write_rules_file(temp_path, protect_root=True))
            system_prompt = _system_prompt(max_actions=12)
            user_prompt = _user_prompt(
                {
                    "created_at": "2026-04-22T10:00:00",
                    "folders": [],
                    "bookmarks": [],
                },
                rules,
            )

            self.assertIn("must remain in place by default", system_prompt)
            self.assertIn("protected root loose bookmarks", user_prompt)
            self.assertIn("only emit keep_for_review", user_prompt)

    def test_finalize_draft_plan_auto_approves_high_confidence_actions(self):
        draft_payload = {
            "plan_version": "2",
            "plan_kind": "draft",
            "source": "bookmark-advisor",
            "created_at": "2026-04-21T10:00:00",
            "source_snapshot": "snapshot.json",
            "rules_source": "rules.yaml",
            "model": "gpt-4o-mini",
            "summary": {"overview": "test"},
            "actions": [
                {
                    "action_id": "a-0001",
                    "action_type": "move_bookmark",
                    "status": "proposed",
                    "reason": "clear match",
                    "confidence": 0.92,
                    "bookmark_locator": {
                        "id": "1",
                        "title": "ChatGPT",
                        "url": "https://chatgpt.com/",
                        "normalized_url": "https://chatgpt.com/",
                        "folder_path": "/收藏夹栏"
                    },
                    "folder_locator": {"id": "", "name": "", "path": ""},
                    "from_path": "/收藏夹栏",
                    "to_path": "/收藏夹栏/AI",
                    "target_path": "",
                    "details": {}
                },
                {
                    "action_id": "a-0002",
                    "action_type": "keep_for_review",
                    "status": "proposed",
                    "reason": "ambiguous",
                    "confidence": 0.4,
                    "bookmark_locator": {
                        "id": "2",
                        "title": "Unknown",
                        "url": "https://example.com/",
                        "normalized_url": "https://example.com/",
                        "folder_path": "/收藏夹栏"
                    },
                    "folder_locator": {"id": "", "name": "", "path": ""},
                    "from_path": "/收藏夹栏",
                    "to_path": "",
                    "target_path": "",
                    "details": {}
                }
            ]
        }
        reviewed = finalize_draft_plan(draft_payload, auto_approve_threshold=0.85)
        statuses = [action.status for action in reviewed.actions]
        self.assertEqual(statuses, ["approved", "blocked"])

    def test_snapshot_diff_detects_moves(self):
        before = {
            "created_at": "2026-04-21T10:00:00",
            "bookmarks": [
                {
                    "title": "ChatGPT",
                    "normalized_url": "https://chatgpt.com/",
                    "folder_path": "/收藏夹栏"
                }
            ]
        }
        after = {
            "created_at": "2026-04-21T10:05:00",
            "bookmarks": [
                {
                    "title": "ChatGPT",
                    "normalized_url": "https://chatgpt.com/",
                    "folder_path": "/收藏夹栏/AI"
                }
            ]
        }
        diff = diff_snapshot_documents(before, after)
        self.assertEqual(len(diff["moved_bookmarks"]), 1)
        self.assertEqual(diff["moved_bookmarks"][0]["to_path"], "/收藏夹栏/AI")


if __name__ == "__main__":
    unittest.main()
