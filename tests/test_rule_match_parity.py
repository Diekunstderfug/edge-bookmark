import unittest

from bookmark_advisor.ai_planner import _bookmark_row_matches_rule
from bookmark_advisor.models import BookmarkItem
from bookmark_advisor.planner import _bookmark_matches_rule
from bookmark_advisor.rules import (
    BookmarkMatchRule,
    BookmarkRelocationRule,
    matches_rule,
)


def build_rule(
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
        reason="parity test",
    )


def build_bookmark(folder_path: str, title: str, url: str) -> BookmarkItem:
    return BookmarkItem(
        id="1",
        title=title,
        url=url,
        normalized_url=url,
        domain="example.com",
        folder_id="10",
        folder_path=folder_path,
        top_level_folder=None,
        root_key="bookmark_bar",
        path=f"{folder_path}/{title}",
        depth=1,
    )


RULE_CASES = [
    build_rule(),
    build_rule(folder_path="/收藏夹栏/AI"),
    build_rule(title_contains="MCP"),
    build_rule(title_contains="mcp"),
    build_rule(title_equals="ChatGPT"),
    build_rule(url_contains="skillsmp.com"),
    build_rule(url_contains="SKILLSMP.COM"),
    build_rule(folder_path="/收藏夹栏/AI", title_contains="MCP"),
    build_rule(folder_path="/收藏夹栏/AI", url_contains="skillsmp.com"),
    build_rule(title_contains="MCP", title_equals="ChatGPT"),
    build_rule(folder_path="/收藏夹栏/编程", title_contains="量化", url_contains="joinquant"),
]

BOOKMARK_CASES = [
    ("/收藏夹栏/AI", "MCP中文文档 – MCP 中文站（Model Context Protocol 中文）", "https://mcpcn.com/docs/"),
    ("/收藏夹栏/AI", "Agent Skills Marketplace | SkillsMP", "https://skillsmp.com/"),
    ("/收藏夹栏/AI", "ChatGPT", "https://chatgpt.com/"),
    ("/收藏夹栏/编程", "量化投资入门", "https://www.joinquant.com/"),
    ("/收藏夹栏", "loose bookmark", "https://example.com/"),
    ("/其他收藏夹", "Mixed CASE Title MCP", "https://EXAMPLE.com/SkillsMP"),
]


class RuleMatchParityTest(unittest.TestCase):
    def test_planner_and_ai_planner_implementations_agree(self):
        """planner（BookmarkItem）与 ai_planner（dict 行）必须共享同一匹配语义。

        两边各自接收不同输入形态，但语义由 rules.matches_rule 单一实现承载；
        本测试锁定等价输入下三方结果逐例一致，防止任何一侧再度漂移。
        """
        for rule in RULE_CASES:
            for folder_path, title, url in BOOKMARK_CASES:
                item = build_bookmark(folder_path, title, url)
                row = {"folder_path": folder_path, "title": title, "url": url}
                with self.subTest(rule=rule.match, folder_path=folder_path, title=title):
                    self.assertEqual(
                        _bookmark_matches_rule(item, rule),
                        _bookmark_row_matches_rule(row, rule),
                    )
                    self.assertEqual(
                        _bookmark_matches_rule(item, rule),
                        matches_rule(folder_path, title, url, rule),
                    )

    def test_both_sides_true_and_false_branches_are_exercised(self):
        """确保矩阵中同时存在命中与未命中样本（否则一致性断言会空洞通过）。"""
        results = {
            _bookmark_matches_rule(build_bookmark(fp, t, u), r)
            for r in RULE_CASES
            for fp, t, u in BOOKMARK_CASES
        }
        self.assertEqual(results, {True, False})

    def test_ai_planner_row_treats_missing_keys_as_empty_strings(self):
        """ai_planner 包装层保留原有容错：dict 行缺 key 按 "" 处理。"""
        rule = build_rule(folder_path="/收藏夹栏/AI", title_contains="MCP", url_contains="mcpcn.com")
        row = {}
        self.assertFalse(_bookmark_row_matches_rule(row, rule))
        self.assertEqual(
            _bookmark_row_matches_rule(row, rule),
            matches_rule("", "", "", rule),
        )


if __name__ == "__main__":
    unittest.main()
