"""AI planning orchestration.

This module keeps the orchestration entry points (:func:`plan_with_openai`,
:func:`finalize_draft_plan`) and semantic-plan serialization. The mechanical
layers live in the :mod:`bookmark_advisor.ai` subpackage:

- :mod:`bookmark_advisor.ai.client` — OpenAI SDK import, client construction,
  API-style resolution, and the compatibility fallback request chain
- :mod:`bookmark_advisor.ai.prompts` — system/user prompt and response-schema
  builders (prompt wording is locked by tests/test_prompt_parity.py)
- :mod:`bookmark_advisor.ai.guardrails` — guardrail enforcement over
  AI-proposed actions

Compatibility contract: every name that used to live in this module is
re-exported below, including underscore-prefixed private names, so historical
import paths such as ``from bookmark_advisor.ai_planner import _system_prompt``
and the ``unittest.mock.patch`` targets in tests/test_ai_planner_compat.py
(``bookmark_advisor.ai_planner._build_openai_client`` and
``bookmark_advisor.ai_planner._import_openai_sdk``) keep working unchanged.
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from bookmark_advisor.ai.client import (
    AIPlannerError,
    COMPATIBILITY_FALLBACK_STATUS_CODES,
    NON_RETRYABLE_STATUS_CODES,
    SUPPORTED_API_STYLES,
    _build_configured_openai_client,
    _chat_completions_format_payload,
    _coerce_mapping,
    _extract_chat_completion_text,
    _extract_responses_output_text,
    _format_openai_exception,
    _import_openai_sdk,
    _is_compatibility_fallback_error,
    _normalize_openai_base_url,
    _request_attempts,
    _request_semantic_plan,
    _request_with_chat_completions,
    _request_with_responses,
    _resolve_api_style,
    _responses_format_payload,
)
from bookmark_advisor.ai.guardrails import (
    _attach_action_evidence,
    _bookmark_row_matches_rule,
    _forced_rule_actions,
    _is_protected_root_move,
    _is_unreviewed_bookmark_move,
    _normalize_action,
    apply_guardrails_to_actions,
)
from bookmark_advisor.ai.prompts import (
    SUPPORTED_AI_ACTIONS,
    _semantic_response_schema,
    _system_prompt,
    _user_prompt,
)
from bookmark_advisor.models import (
    BookmarkLocator,
    FolderLocator,
    SemanticAction,
    SemanticPlan,
)
from bookmark_advisor.rules import RulesConfig
from bookmark_advisor.utils import atomic_write_json

REVIEWABLE_STATUSES = {"proposed", "approved", "rejected", "edited", "blocked"}
EXECUTABLE_ACTIONS = {"move_bookmark", "move_folder", "create_folder", "rename_folder", "remove_duplicate", "delete_empty_folder"}


def plan_with_openai(
    snapshot_document: dict[str, Any],
    rules: RulesConfig,
    model: str,
    max_actions: int,
    api_style: str | None = None,
    base_url: str | None = None,
) -> SemanticPlan:
    resolved_api_style = _resolve_api_style(api_style or os.getenv("OPENAI_API_STYLE", "auto"))
    client = _build_openai_client(base_url=base_url)
    content_text, api_style_used, response_format_used = _request_semantic_plan(
        client=client,
        snapshot_document=snapshot_document,
        rules=rules,
        model=model,
        max_actions=max_actions,
        api_style=resolved_api_style,
    )

    try:
        result = json.loads(content_text)
    except json.JSONDecodeError as exc:
        raise AIPlannerError(f"failed to parse structured AI output: {exc}") from exc

    actions = [
        _semantic_action_from_ai_payload(item)
        for item in result.get("actions", [])
    ]
    actions = apply_guardrails_to_actions(actions, snapshot_document, rules)

    return SemanticPlan(
        plan_version="2",
        plan_kind="draft",
        source="bookmark-advisor",
        created_at=datetime.now().isoformat(timespec="seconds"),
        source_snapshot=snapshot_document.get("source_path", ""),
        rules_source=str(rules.source_path),
        model=model,
        summary={
            "overview": result.get("summary", {}).get("overview", ""),
            "total_actions": len(actions),
            "ai_action_count": len(result.get("actions", [])),
            "guardrail_adjustments": sum(
                1 for action in actions if action.details.get("guardrail")
            ),
            "api_style_requested": resolved_api_style,
            "api_style_used": api_style_used,
            "response_format_used": response_format_used,
        },
        actions=_reindex_actions(actions),
    )


def finalize_draft_plan(
    draft_payload: dict[str, Any],
    auto_approve_threshold: float = 0.85,
) -> SemanticPlan:
    actions = []
    for item in draft_payload.get("actions", []):
        action = semantic_action_from_dict(item)
        if action.status in {"approved", "edited", "rejected", "blocked"}:
            actions.append(action)
            continue
        if action.action_type == "keep_for_review":
            actions.append(
                replace(
                    action,
                    status="blocked",
                    details={**action.details, "finalize_reason": "review_only"},
                )
            )
            continue
        if action.confidence >= auto_approve_threshold:
            actions.append(
                replace(
                    action,
                    status="approved",
                    details={**action.details, "finalize_reason": "auto-approved"},
                )
            )
        else:
            actions.append(
                replace(
                    action,
                    status="blocked",
                    details={**action.details, "finalize_reason": "below-threshold"},
                )
            )

    summary = dict(draft_payload.get("summary", {}))
    summary.update(
        {
            "approved_actions": sum(1 for action in actions if action.status in {"approved", "edited"}),
            "blocked_actions": sum(1 for action in actions if action.status == "blocked"),
        }
    )
    return SemanticPlan(
        plan_version=str(draft_payload.get("plan_version", "2")),
        plan_kind="reviewed",
        source=str(draft_payload.get("source", "bookmark-advisor")),
        created_at=datetime.now().isoformat(timespec="seconds"),
        source_snapshot=str(draft_payload.get("source_snapshot", "")),
        rules_source=str(draft_payload.get("rules_source", "")),
        model=str(draft_payload.get("model", "")),
        summary=summary,
        actions=_reindex_actions(actions),
    )


def _build_openai_client(base_url: str | None = None) -> Any:
    # Compatibility trampoline: ``_import_openai_sdk`` is resolved through
    # this module's namespace at call time so the historical patch target
    # ``bookmark_advisor.ai_planner._import_openai_sdk`` (locked by
    # tests/test_ai_planner_compat.py) keeps steering SDK import failures.
    return _build_configured_openai_client(base_url=base_url, import_sdk=_import_openai_sdk)


def write_semantic_plan(plan: SemanticPlan, destination: Path) -> None:
    atomic_write_json(destination, plan.to_dict())


def load_semantic_plan(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def semantic_action_from_dict(payload: dict[str, Any]) -> SemanticAction:
    bookmark_locator_payload = payload.get("bookmark_locator") or {}
    folder_locator_payload = payload.get("folder_locator") or {}
    return SemanticAction(
        action_id=str(payload.get("action_id", "")),
        action_type=str(payload.get("action_type", "")),
        status=str(payload.get("status", "proposed")),
        reason=str(payload.get("reason", "")),
        confidence=float(payload.get("confidence", 0)),
        bookmark_locator=BookmarkLocator(
            id=str(bookmark_locator_payload.get("id", "")),
            title=str(bookmark_locator_payload.get("title", "")),
            url=str(bookmark_locator_payload.get("url", "")),
            normalized_url=str(bookmark_locator_payload.get("normalized_url", "")),
            folder_path=str(bookmark_locator_payload.get("folder_path", "")),
        ),
        folder_locator=FolderLocator(
            id=str(folder_locator_payload.get("id", "")),
            name=str(folder_locator_payload.get("name", "")),
            path=str(folder_locator_payload.get("path", "")),
        ),
        from_path=str(payload.get("from_path", "")),
        to_path=str(payload.get("to_path", "")),
        target_path=str(payload.get("target_path", "")),
        to_name=str(payload.get("to_name", "")),
        details=dict(payload.get("details") or {}),
    )


def _semantic_action_from_ai_payload(payload: dict[str, Any]) -> SemanticAction:
    action = semantic_action_from_dict(payload)
    if action.action_type not in SUPPORTED_AI_ACTIONS:
        raise AIPlannerError(f"AI returned unsupported action_type: {action.action_type}")
    if action.status not in REVIEWABLE_STATUSES:
        raise AIPlannerError(f"AI returned unsupported status: {action.status}")
    return action


def _reindex_actions(actions: list[SemanticAction]) -> list[SemanticAction]:
    indexed: list[SemanticAction] = []
    for index, action in enumerate(actions, start=1):
        indexed.append(replace(action, action_id=f"a-{index:04d}"))
    return indexed
