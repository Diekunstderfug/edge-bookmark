"""Guardrail enforcement over AI-proposed semantic actions.

Extracted from :mod:`bookmark_advisor.ai_planner`. This layer normalizes
AI actions, attaches review evidence, blocks protected-root and
un-reviewed bookmark moves, and injects forced relocation rules from
config/rules.yaml (matching semantics come from
:func:`bookmark_advisor.rules.matches_rule`).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from bookmark_advisor.models import (
    BookmarkLocator,
    FolderLocator,
    SemanticAction,
)
from bookmark_advisor.rules import BookmarkRelocationRule, RulesConfig, matches_rule


def apply_guardrails_to_actions(
    actions: list[SemanticAction],
    snapshot_document: dict[str, Any],
    rules: RulesConfig,
) -> list[SemanticAction]:
    bookmark_index = {
        bookmark["id"]: bookmark
        for bookmark in snapshot_document.get("bookmarks", [])
    }
    guarded: list[SemanticAction] = []
    seen: set[tuple[str, str, str]] = set()

    for action in actions:
        normalized = _normalize_action(action)
        normalized = _attach_action_evidence(normalized, bookmark_index)
        if _is_protected_root_move(normalized, bookmark_index, rules):
            normalized = replace(
                normalized,
                action_type="keep_for_review",
                status="blocked",
                to_path="",
                target_path="",
                details={**normalized.details, "guardrail": "protected-root"},
                reason=f"{normalized.reason} [blocked by protected root rule]",
            )
            normalized = _attach_action_evidence(normalized, bookmark_index)
        if _is_unreviewed_bookmark_move(normalized, bookmark_index):
            normalized = replace(
                normalized,
                action_type="keep_for_review",
                status="blocked",
                to_path="",
                target_path="",
                details={**normalized.details, "guardrail": "missing-review"},
                reason=f"{normalized.reason} [blocked until URL review is completed]",
            )
            normalized = _attach_action_evidence(normalized, bookmark_index)
        key = (
            normalized.action_type,
            normalized.bookmark_locator.id or normalized.folder_locator.id,
            normalized.to_path or normalized.target_path,
        )
        if key in seen:
            continue
        seen.add(key)
        guarded.append(normalized)

    forced_actions = _forced_rule_actions(snapshot_document, rules)
    for action in forced_actions:
        action = _attach_action_evidence(action, bookmark_index)
        key = (
            action.action_type,
            action.bookmark_locator.id or action.folder_locator.id,
            action.to_path or action.target_path,
        )
        if key in seen:
            continue
        seen.add(key)
        guarded.append(action)
    return guarded


def _normalize_action(action: SemanticAction) -> SemanticAction:
    if action.action_type == "move_bookmark" and not action.from_path:
        return replace(action, from_path=action.bookmark_locator.folder_path)
    if action.action_type == "move_folder" and not action.from_path:
        return replace(action, from_path=action.folder_locator.path)
    if action.action_type == "rename_folder" and not action.from_path:
        return replace(action, from_path=action.folder_locator.path)
    if action.action_type == "delete_empty_folder" and not action.from_path:
        return replace(action, from_path=action.folder_locator.path)
    return action


def _attach_action_evidence(
    action: SemanticAction,
    bookmark_index: dict[str, dict[str, Any]],
) -> SemanticAction:
    details = dict(action.details)
    evidence = dict(details.get("evidence") or {})
    bookmark = bookmark_index.get(action.bookmark_locator.id)

    if bookmark:
        evidence.setdefault("review_status", str(bookmark.get("review_status", "missing")))
        evidence.setdefault("review_method", str(bookmark.get("review_method", "")))
        evidence.setdefault(
            "summary",
            str(
                bookmark.get("one_line_summary")
                or bookmark.get("meta_description")
                or bookmark.get("page_title")
                or action.reason
            ),
        )
    else:
        evidence.setdefault("review_status", "derived")
        evidence.setdefault("review_method", "derived")
        evidence.setdefault("summary", action.reason)

    rule_override = details.get("rule_override")
    if not rule_override and details.get("guardrail") in {
        "forced-folder-relocation",
        "forced-bookmark-relocation",
    }:
        rule_override = str(details["guardrail"])
    if rule_override:
        evidence.setdefault("rule_override", str(rule_override))

    details["evidence"] = evidence
    return replace(action, details=details)


def _is_protected_root_move(
    action: SemanticAction,
    bookmark_index: dict[str, dict[str, Any]],
    rules: RulesConfig,
) -> bool:
    if not rules.defaults.protect_root_loose_bookmarks:
        return False
    if action.action_type != "move_bookmark":
        return False
    bookmark = bookmark_index.get(action.bookmark_locator.id)
    if not bookmark:
        return False
    folder_path = bookmark.get("folder_path", "")
    return folder_path in rules.protected_paths


def _is_unreviewed_bookmark_move(
    action: SemanticAction,
    bookmark_index: dict[str, dict[str, Any]],
) -> bool:
    if action.action_type != "move_bookmark":
        return False
    bookmark = bookmark_index.get(action.bookmark_locator.id)
    if not bookmark:
        return True
    return str(bookmark.get("review_status", "missing")) != "reviewed"


def _forced_rule_actions(
    snapshot_document: dict[str, Any],
    rules: RulesConfig,
) -> list[SemanticAction]:
    folder_by_path = {
        folder["path"]: folder for folder in snapshot_document.get("folders", [])
    }
    bookmark_rows = snapshot_document.get("bookmarks", [])
    actions: list[SemanticAction] = []

    for rule in rules.folder_relocations:
        folder = folder_by_path.get(rule.from_path)
        if not folder:
            continue
        actions.append(
            SemanticAction(
                action_id="",
                action_type="move_folder",
                status="approved",
                reason=rule.reason,
                confidence=0.99,
                folder_locator=FolderLocator(
                    id=folder.get("id", ""),
                    name=folder.get("name", ""),
                    path=folder.get("path", ""),
                ),
                from_path=folder.get("path", ""),
                to_path=rule.to_path,
                details={
                    "guardrail": "forced-folder-relocation",
                    "rule_override": "forced-folder-relocation",
                },
            )
        )

    for rule in rules.bookmark_relocations:
        for bookmark in bookmark_rows:
            if not _bookmark_row_matches_rule(bookmark, rule):
                continue
            actions.append(
                SemanticAction(
                    action_id="",
                    action_type="move_bookmark",
                    status="approved",
                    reason=rule.reason,
                    confidence=0.98,
                    bookmark_locator=BookmarkLocator(
                        id=bookmark.get("id", ""),
                        title=bookmark.get("title", ""),
                        url=bookmark.get("url", ""),
                        normalized_url=bookmark.get("normalized_url", ""),
                        folder_path=bookmark.get("folder_path", ""),
                    ),
                    from_path=bookmark.get("folder_path", ""),
                    to_path=rule.to_path,
                    details={
                        "guardrail": "forced-bookmark-relocation",
                        "rule_override": "forced-bookmark-relocation",
                    },
                )
            )
    return actions


def _bookmark_row_matches_rule(bookmark: dict[str, Any], rule: BookmarkRelocationRule) -> bool:
    return matches_rule(
        bookmark.get("folder_path", ""),
        bookmark.get("title", ""),
        bookmark.get("url", ""),
        rule,
    )
