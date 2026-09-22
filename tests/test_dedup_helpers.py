import unittest

from bookmark_advisor.executor import _plan_action_from_semantic_payload
from bookmark_advisor.models import PlanAction
from bookmark_advisor.rules import BookmarkMatchRule, BookmarkRelocationRule, matches_rule
from bookmark_advisor.utils import optional_str


def relocation_rule(
    folder_path=None,
    title_contains=None,
    title_equals=None,
    url_contains=None,
) -> BookmarkRelocationRule:
    return BookmarkRelocationRule(
        match=BookmarkMatchRule(
            folder_path=folder_path,
            title_contains=title_contains,
            title_equals=title_equals,
            url_contains=url_contains,
        ),
        to_path="/收藏夹栏/Target",
        reason="test relocation",
    )


class MatchesRuleTest(unittest.TestCase):
    def test_all_criteria_match(self):
        rule = relocation_rule(
            folder_path="/收藏夹栏/AI",
            title_contains="MCP",
            title_equals="MCP中文文档",
            url_contains="mcpcn.com",
        )
        self.assertTrue(
            matches_rule(
                "/收藏夹栏/AI",
                "MCP中文文档",
                "https://mcpcn.com/docs/",
                rule,
            )
        )

    def test_folder_path_mismatch_returns_false(self):
        rule = relocation_rule(folder_path="/收藏夹栏/AI")
        self.assertFalse(matches_rule("/收藏夹栏/编程", "MCP中文文档", "https://mcpcn.com/", rule))
        self.assertTrue(matches_rule("/收藏夹栏/AI", "anything", "anything", rule))

    def test_title_contains_is_case_insensitive(self):
        rule = relocation_rule(title_contains="MCP")
        self.assertTrue(matches_rule("/x", "model context protocol (mcp) docs", "/x", rule))
        self.assertTrue(matches_rule("/x", "MCP Docs", "/x", rule))
        self.assertFalse(matches_rule("/x", "Model Context Protocol docs", "/x", rule))

    def test_title_equals_is_exact(self):
        rule = relocation_rule(title_equals="ChatGPT")
        self.assertTrue(matches_rule("/x", "ChatGPT", "/x", rule))
        self.assertFalse(matches_rule("/x", "chatgpt", "/x", rule))
        self.assertFalse(matches_rule("/x", "ChatGPT Docs", "/x", rule))

    def test_url_contains_is_case_insensitive(self):
        rule = relocation_rule(url_contains="SkillsMP.com")
        self.assertTrue(matches_rule("/x", "t", "https://skillsmp.com/", rule))
        self.assertFalse(matches_rule("/x", "t", "https://example.com/", rule))

    def test_criteria_combine_with_and_semantics(self):
        rule = relocation_rule(folder_path="/收藏夹栏/AI", url_contains="skillsmp.com")
        self.assertFalse(matches_rule("/收藏夹栏/AI", "t", "https://example.com/", rule))
        self.assertFalse(matches_rule("/收藏夹栏/其他", "t", "https://skillsmp.com/", rule))
        self.assertTrue(matches_rule("/收藏夹栏/AI", "t", "https://skillsmp.com/", rule))

    def test_empty_criteria_match_everything(self):
        rule = relocation_rule()
        self.assertTrue(matches_rule("", "", "", rule))


class OptionalStrTest(unittest.TestCase):
    def test_none_stays_none(self):
        self.assertIsNone(optional_str(None))

    def test_empty_string_collapses_to_none(self):
        self.assertIsNone(optional_str(""))

    def test_whitespace_only_string_is_not_empty(self):
        # 与原两处实现一致：只归一空字符串，不做 strip。
        self.assertEqual(optional_str("   "), "   ")

    def test_non_empty_string_passes_through(self):
        self.assertEqual(optional_str("42"), "42")

    def test_non_string_values_are_coerced(self):
        self.assertEqual(optional_str(0), "0")
        self.assertEqual(optional_str(42), "42")
        self.assertEqual(optional_str(3.5), "3.5")


class PlanActionFromPayloadTest(unittest.TestCase):
    def test_maps_every_field(self):
        payload = {
            "action_type": "move_bookmark",
            "reason": "preferred rule",
            "confidence": 0.96,
            "bookmark_id": "33",
            "folder_id": "10",
            "from_path": "/收藏夹栏/AI",
            "to_path": "/收藏夹栏/AI/mcp",
            "target_path": "/收藏夹栏/AI/mcp",
            "duplicate_of": "34",
            "folder_name": "mcp",
            "to_name": "MCP",
            "details": {"mode": "preferred-rule"},
        }
        action = PlanAction.from_payload(payload)
        self.assertEqual(action.action_type, "move_bookmark")
        self.assertEqual(action.reason, "preferred rule")
        self.assertEqual(action.confidence, 0.96)
        self.assertEqual(action.bookmark_id, "33")
        self.assertEqual(action.folder_id, "10")
        self.assertEqual(action.from_path, "/收藏夹栏/AI")
        self.assertEqual(action.to_path, "/收藏夹栏/AI/mcp")
        self.assertEqual(action.target_path, "/收藏夹栏/AI/mcp")
        self.assertEqual(action.duplicate_of, "34")
        self.assertEqual(action.folder_name, "mcp")
        self.assertEqual(action.to_name, "MCP")
        self.assertEqual(action.details, {"mode": "preferred-rule"})

    def test_missing_optional_fields_default_to_none(self):
        action = PlanAction.from_payload(
            {"action_type": "keep_for_review", "reason": "r", "confidence": 0.2}
        )
        self.assertIsNone(action.bookmark_id)
        self.assertIsNone(action.folder_id)
        self.assertIsNone(action.from_path)
        self.assertIsNone(action.to_path)
        self.assertIsNone(action.target_path)
        self.assertIsNone(action.duplicate_of)
        self.assertIsNone(action.folder_name)
        self.assertIsNone(action.to_name)
        self.assertEqual(action.details, {})

    def test_empty_optional_strings_collapse_to_none(self):
        action = PlanAction.from_payload(
            {
                "action_type": "move_bookmark",
                "reason": "r",
                "confidence": 1,
                "bookmark_id": "",
                "to_path": "",
            }
        )
        self.assertIsNone(action.bookmark_id)
        self.assertIsNone(action.to_path)

    def test_details_none_falls_back_to_empty_dict(self):
        action = PlanAction.from_payload(
            {"action_type": "move_bookmark", "reason": "r", "confidence": 1, "details": None}
        )
        self.assertEqual(action.details, {})

    def test_confidence_is_coerced_to_float(self):
        action = PlanAction.from_payload(
            {"action_type": "move_bookmark", "reason": "r", "confidence": 1}
        )
        self.assertIsInstance(action.confidence, float)
        self.assertEqual(action.confidence, 1.0)

    def test_round_trips_through_to_dict(self):
        original = PlanAction(
            action_type="remove_duplicate",
            reason="d",
            confidence=0.5,
            bookmark_id="9",
            duplicate_of="8",
            details={"k": "v"},
        )
        restored = PlanAction.from_payload(original.to_dict())
        self.assertEqual(restored, original)


class PlanActionFromSemanticPayloadTest(unittest.TestCase):
    def test_payload_fields_take_precedence_over_locators(self):
        action = _plan_action_from_semantic_payload(
            {
                "action_type": "move_bookmark",
                "reason": "r",
                "confidence": 0.9,
                "bookmark_id": "33",
                "folder_id": "10",
                "folder_name": "AI",
                "bookmark_locator": {"id": "WRONG", "title": "t"},
                "folder_locator": {"id": "WRONG", "name": "WRONG", "path": "/p"},
            }
        )
        self.assertEqual(action.bookmark_id, "33")
        self.assertEqual(action.folder_id, "10")
        self.assertEqual(action.folder_name, "AI")

    def test_missing_ids_fall_back_to_locators(self):
        action = _plan_action_from_semantic_payload(
            {
                "action_type": "rename_folder",
                "reason": "r",
                "confidence": 0.9,
                "to_name": "AI Tools",
                "bookmark_locator": {"id": "33"},
                "folder_locator": {"id": "10", "name": "AI", "path": "/收藏夹栏/AI"},
            }
        )
        self.assertEqual(action.bookmark_id, "33")
        self.assertEqual(action.folder_id, "10")
        self.assertEqual(action.folder_name, "AI")
        self.assertEqual(action.to_name, "AI Tools")

    def test_empty_strings_fall_back_to_locators(self):
        action = _plan_action_from_semantic_payload(
            {
                "action_type": "move_bookmark",
                "reason": "r",
                "confidence": 0.9,
                "bookmark_id": "",
                "folder_id": "",
                "folder_name": "",
                "bookmark_locator": {"id": "33"},
                "folder_locator": {"id": "10", "name": "AI"},
            }
        )
        self.assertEqual(action.bookmark_id, "33")
        self.assertEqual(action.folder_id, "10")
        self.assertEqual(action.folder_name, "AI")

    def test_missing_optional_paths_stay_none(self):
        action = _plan_action_from_semantic_payload(
            {
                "action_type": "delete_empty_folder",
                "reason": "r",
                "confidence": 0.9,
                "folder_locator": {"id": "10", "name": "AI", "path": "/收藏夹栏/AI"},
                "from_path": "/收藏夹栏/AI",
            }
        )
        self.assertIsNone(action.bookmark_id)
        self.assertEqual(action.folder_id, "10")
        self.assertIsNone(action.to_path)
        self.assertIsNone(action.target_path)
        self.assertIsNone(action.to_name)


if __name__ == "__main__":
    unittest.main()
