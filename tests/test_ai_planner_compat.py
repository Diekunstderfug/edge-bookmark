from __future__ import annotations

import json
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bookmark_advisor.ai_planner import (
    AIPlannerError,
    _build_openai_client,
    _normalize_openai_base_url,
    plan_with_openai,
)
from bookmark_advisor.rules import load_rules


class FakeSDKError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


class FakeResponsesAPI:
    def __init__(self, error: Exception | None = None, response: dict | None = None):
        self.error = error
        self.response = response or {}
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeChatCompletionsAPI:
    def __init__(self, response: dict | None = None):
        self.response = response or {}
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, responses_api: FakeResponsesAPI, chat_api: FakeChatCompletionsAPI):
        self.responses = responses_api
        self.chat = type("FakeChatNamespace", (), {"completions": chat_api})()


def write_rules_file(base_dir: Path, protect_root: bool = False) -> Path:
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

            folder_relocations: []
            bookmark_relocations: []

            protected_paths:
              - /收藏夹栏
              - /其他收藏夹
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return rules_path


class AIPlannerCompatTest(unittest.TestCase):
    def test_normalize_openai_base_url_strips_endpoint_suffix(self):
        self.assertEqual(
            _normalize_openai_base_url("https://api.openai.com/v1/responses"),
            "https://api.openai.com/v1",
        )
        self.assertEqual(
            _normalize_openai_base_url("https://provider.example/api/v1/chat/completions"),
            "https://provider.example/api/v1",
        )

    def test_plan_with_openai_falls_back_to_chat_completions(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            rules = load_rules(write_rules_file(temp_path, protect_root=False))
            snapshot_document = {
                "created_at": "2026-04-21T12:00:00",
                "source_path": "snapshot.json",
                "folders": [
                    {
                        "id": "f-ai",
                        "name": "AI",
                        "path": "/收藏夹栏/AI",
                        "parent_path": "/收藏夹栏",
                        "root_key": "bookmark_bar",
                        "depth": 1,
                        "bookmark_count": 0,
                        "subfolder_count": 0,
                    }
                ],
                "bookmarks": [
                    {
                        "id": "b-1",
                        "title": "ChatGPT",
                        "url": "https://chatgpt.com/",
                        "normalized_url": "https://chatgpt.com/",
                        "domain": "chatgpt.com",
                        "folder_id": "root",
                        "folder_path": "/收藏夹栏",
                        "top_level_folder": None,
                        "root_key": "bookmark_bar",
                        "path": "/收藏夹栏/ChatGPT",
                        "depth": 0,
                        "review_status": "reviewed",
                        "review_method": "agent_web",
                        "final_url": "https://chatgpt.com/",
                        "page_title": "ChatGPT",
                        "meta_description": "AI assistant",
                        "site_name": "ChatGPT",
                        "h1": "ChatGPT",
                        "content_kind": "product",
                        "one_line_summary": "General AI assistant product.",
                        "review_confidence": 0.96,
                    }
                ],
            }
            draft_payload = {
                "summary": {"overview": "Move ChatGPT into AI"},
                "actions": [
                    {
                        "action_id": "",
                        "action_type": "move_bookmark",
                        "status": "proposed",
                        "reason": "General AI assistant bookmark",
                        "confidence": 0.93,
                        "bookmark_locator": {
                            "id": "b-1",
                            "title": "ChatGPT",
                            "url": "https://chatgpt.com/",
                            "normalized_url": "https://chatgpt.com/",
                            "folder_path": "/收藏夹栏",
                        },
                        "folder_locator": {"id": "", "name": "", "path": ""},
                        "from_path": "/收藏夹栏",
                        "to_path": "/收藏夹栏/AI",
                        "target_path": "",
                        "details": {},
                    }
                ],
            }
            fake_client = FakeClient(
                responses_api=FakeResponsesAPI(
                    error=FakeSDKError(404, "responses endpoint not found"),
                ),
                chat_api=FakeChatCompletionsAPI(
                    response={
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(draft_payload, ensure_ascii=False),
                                }
                            }
                        ]
                    }
                ),
            )

            with patch("bookmark_advisor.ai_planner._build_openai_client", return_value=fake_client):
                plan = plan_with_openai(
                    snapshot_document=snapshot_document,
                    rules=rules,
                    model="test-model",
                    max_actions=8,
                    api_style="auto",
                )

            self.assertEqual(plan.summary["api_style_used"], "chat_completions")
            self.assertEqual(plan.summary["response_format_used"], "json_schema")
            self.assertEqual(plan.actions[0].action_type, "move_bookmark")
            self.assertEqual(plan.actions[0].to_path, "/收藏夹栏/AI")
            self.assertEqual(plan.actions[0].details["evidence"]["review_status"], "reviewed")
            self.assertEqual(plan.actions[0].details["evidence"]["review_method"], "agent_web")
            self.assertEqual(len(fake_client.responses.calls), 1)
            self.assertEqual(len(fake_client.chat.completions.calls), 1)

    def test_build_openai_client_raises_clear_error_when_sdk_missing(self):
        with patch("bookmark_advisor.ai_planner._import_openai_sdk", side_effect=ImportError("missing")):
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False):
                with self.assertRaises(AIPlannerError) as ctx:
                    _build_openai_client()
        self.assertIn("OpenAI SDK is not installed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
