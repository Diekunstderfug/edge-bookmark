"""Prompt and response-schema builders for the AI planner.

Extracted from :mod:`bookmark_advisor.ai_planner`. The wording of
``_system_prompt`` is locked by tests/test_prompt_parity.py (core policy
phrases, in order) and mirrored by extension/ai/prompt_codec.js — keep it
byte-for-byte unless the parity tests are updated on both sides.
"""
from __future__ import annotations

import json
from typing import Any

from bookmark_advisor.rules import RulesConfig
from bookmark_advisor.utils import sanitize_for_prompt

SUPPORTED_AI_ACTIONS = [
    "move_bookmark",
    "move_folder",
    "create_folder",
    "rename_folder",
    "remove_duplicate",
    "delete_empty_folder",
    "keep_for_review",
]


def _system_prompt(max_actions: int, require_schema_self_validation: bool = False) -> str:
    prompt = (
        "You are an expert bookmark organizer. "
        "Return JSON only. "
        "Focus on semantic organization, not cosmetic renaming. "
        "Prefer moving bookmarks into semantically appropriate existing folders. "
        "Only propose create_folder when a genuinely new category is justified. "
        f"Propose at most {max_actions} high-value actions. "
        "Use keep_for_review for ambiguous, risky, or low-confidence items. "
        "Loose bookmarks directly under protected root paths must stay in place. "
        "Only bookmarks with review_status=reviewed may be auto-classified; "
        "unresolved bookmarks must stay in keep_for_review."
    )
    if require_schema_self_validation:
        prompt += " You must ensure the JSON object matches the provided schema exactly."
    return prompt


def _user_prompt(
    snapshot_document: dict[str, Any],
    rules: RulesConfig,
    include_schema_in_prompt: bool = False,
) -> str:
    rules_summary = {
        "protect_root_loose_bookmarks": rules.defaults.protect_root_loose_bookmarks,
        "protected_paths": rules.protected_paths,
        "forced_folder_relocations": [
            {"from": rule.from_path, "to": rule.to_path, "reason": rule.reason}
            for rule in rules.folder_relocations
        ],
        "forced_bookmark_relocations": [
            {
                "match": {
                    "folder_path": rule.match.folder_path or "",
                    "title_contains": rule.match.title_contains or "",
                    "title_equals": rule.match.title_equals or "",
                    "url_contains": rule.match.url_contains or "",
                },
                "to": rule.to_path,
                "reason": rule.reason,
            }
            for rule in rules.bookmark_relocations
        ],
    }
    sanitized_bookmarks = [
        {
            **bm,
            "title": sanitize_for_prompt(str(bm.get("title", ""))),
            "url": sanitize_for_prompt(str(bm.get("url", ""))),
        }
        for bm in snapshot_document.get("bookmarks", [])
    ]
    compact_snapshot = {
        "created_at": snapshot_document.get("created_at"),
        "folders": snapshot_document.get("folders", []),
        "bookmarks": sanitized_bookmarks,
    }
    prompt = (
        "Given this bookmark snapshot and these guardrails, propose a draft semantic reorganization plan.\n"
        "The snapshot may already include URL review fields for each bookmark.\n"
        "Only review_status=reviewed bookmarks may be auto-moved unless a strong explicit rule overrides that behavior.\n"
        "If protect_root_loose_bookmarks is true, bookmarks that currently live directly under a protected root path must stay where they are.\n"
        "For those protected root loose bookmarks, only emit keep_for_review unless the user has explicitly requested root-level cleanup.\n"
        "Do not invent bookmarks or folders that are not implied by the snapshot.\n"
        "Prefer moving bookmarks into semantically appropriate existing folders.\n"
        "Only propose create_folder when a genuinely new category is justified.\n"
        "Return only the structured plan.\n\n"
        f"Rules:\n{json.dumps(rules_summary, ensure_ascii=False, indent=2)}\n\n"
        f"Snapshot:\n{json.dumps(compact_snapshot, ensure_ascii=False, indent=2)}"
    )
    if include_schema_in_prompt:
        prompt += (
            "\n\nExpected JSON schema:\n"
            f"{json.dumps(_semantic_response_schema(), ensure_ascii=False, indent=2)}"
        )
    return prompt


def _semantic_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "overview": {"type": "string"},
                },
                "required": ["overview"],
            },
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "action_id": {"type": "string"},
                        "action_type": {"type": "string", "enum": SUPPORTED_AI_ACTIONS},
                        "status": {
                            "type": "string",
                            "enum": ["proposed", "approved", "rejected", "edited", "blocked"],
                        },
                        "reason": {"type": "string"},
                        "confidence": {"type": "number"},
                        "bookmark_locator": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string"},
                                "title": {"type": "string"},
                                "url": {"type": "string"},
                                "normalized_url": {"type": "string"},
                                "folder_path": {"type": "string"},
                            },
                            "required": ["id", "title", "url", "normalized_url", "folder_path"],
                        },
                        "folder_locator": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string"},
                                "name": {"type": "string"},
                                "path": {"type": "string"},
                            },
                            "required": ["id", "name", "path"],
                        },
                        "from_path": {"type": "string"},
                        "to_path": {"type": "string"},
                        "target_path": {"type": "string"},
                        "to_name": {"type": "string"},
                        "details": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "evidence": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "review_status": {"type": "string"},
                                        "review_method": {"type": "string"},
                                        "summary": {"type": "string"},
                                        "rule_override": {"type": "string"},
                                    },
                                    "required": ["review_status", "review_method", "summary"],
                                },
                                "guardrail": {"type": "string"},
                                "rule_override": {"type": "string"},
                            },
                            "required": ["evidence"],
                        },
                    },
                    "required": [
                        "action_id",
                        "action_type",
                        "status",
                        "reason",
                        "confidence",
                        "bookmark_locator",
                        "folder_locator",
                        "from_path",
                        "to_path",
                        "target_path",
                        "to_name",
                        "details",
                    ],
                },
            },
        },
        "required": ["summary", "actions"],
    }
