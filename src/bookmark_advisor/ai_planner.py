from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from bookmark_advisor.models import (
    BookmarkLocator,
    FolderLocator,
    SemanticAction,
    SemanticPlan,
)
from bookmark_advisor.rules import BookmarkRelocationRule, RulesConfig

SUPPORTED_AI_ACTIONS = [
    "move_bookmark",
    "move_folder",
    "create_folder",
    "remove_duplicate",
    "keep_for_review",
]
REVIEWABLE_STATUSES = {"proposed", "approved", "rejected", "edited", "blocked"}
EXECUTABLE_ACTIONS = {"move_bookmark", "move_folder", "create_folder", "remove_duplicate"}
SUPPORTED_API_STYLES = {"auto", "responses", "chat_completions"}
COMPATIBILITY_FALLBACK_STATUS_CODES = {400, 404, 405, 415, 422, 501}
NON_RETRYABLE_STATUS_CODES = {401, 403, 429}


class AIPlannerError(RuntimeError):
    pass


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


def write_semantic_plan(plan: SemanticPlan, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(plan.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


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


def _normalize_action(action: SemanticAction) -> SemanticAction:
    if action.action_type == "move_bookmark" and not action.from_path:
        return replace(action, from_path=action.bookmark_locator.folder_path)
    if action.action_type == "move_folder" and not action.from_path:
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
    match = rule.match
    if match.folder_path and bookmark.get("folder_path", "") != match.folder_path:
        return False
    title = bookmark.get("title", "")
    url = bookmark.get("url", "")
    if match.title_contains and match.title_contains.lower() not in title.lower():
        return False
    if match.title_equals and match.title_equals != title:
        return False
    if match.url_contains and match.url_contains.lower() not in url.lower():
        return False
    return True


def _import_openai_sdk():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AIPlannerError(
            "OpenAI SDK is not installed. Install it with `python3 -m pip install openai` "
            "or install the project dependencies first."
        ) from exc
    return OpenAI


def _build_openai_client(base_url: str | None = None) -> Any:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise AIPlannerError("OPENAI_API_KEY is not set")

    try:
        OpenAI = _import_openai_sdk()
    except ImportError as exc:
        raise AIPlannerError(
            "OpenAI SDK is not installed. Install it with `python3 -m pip install openai` "
            "or install the project dependencies first."
        ) from exc
    client_kwargs: dict[str, Any] = {
        "api_key": api_key,
        "timeout": 120,
    }

    normalized_base_url = _normalize_openai_base_url(base_url or os.getenv("OPENAI_BASE_URL"))
    if normalized_base_url:
        client_kwargs["base_url"] = normalized_base_url

    organization = os.getenv("OPENAI_ORGANIZATION") or os.getenv("OPENAI_ORG_ID")
    project = os.getenv("OPENAI_PROJECT")
    if organization:
        client_kwargs["organization"] = organization
    if project:
        client_kwargs["project"] = project

    return OpenAI(**client_kwargs)


def _resolve_api_style(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized not in SUPPORTED_API_STYLES:
        supported = ", ".join(sorted(SUPPORTED_API_STYLES))
        raise AIPlannerError(f"unsupported OPENAI_API_STYLE '{value}'. Expected one of: {supported}")
    return normalized


def _normalize_openai_base_url(base_url: str | None) -> str | None:
    if not base_url:
        return None

    normalized = base_url.strip().rstrip("/")
    for suffix in ("/responses", "/chat/completions", "/completions"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized


def _request_semantic_plan(
    client: Any,
    snapshot_document: dict[str, Any],
    rules: RulesConfig,
    model: str,
    max_actions: int,
    api_style: str,
) -> tuple[str, str, str]:
    attempts = _request_attempts(api_style)
    fallback_errors: list[str] = []
    last_exc: Exception | None = None

    for request_style, response_format in attempts:
        system_text = _system_prompt(
            max_actions=max_actions,
            require_schema_self_validation=response_format == "json_object",
        )
        user_text = _user_prompt(
            snapshot_document=snapshot_document,
            rules=rules,
            include_schema_in_prompt=response_format == "json_object",
        )
        try:
            if request_style == "responses":
                text = _request_with_responses(
                    client=client,
                    model=model,
                    system_text=system_text,
                    user_text=user_text,
                    response_format=response_format,
                )
            else:
                text = _request_with_chat_completions(
                    client=client,
                    model=model,
                    system_text=system_text,
                    user_text=user_text,
                    response_format=response_format,
                )
            return text, request_style, response_format
        except Exception as exc:  # pragma: no cover - exercised via unit tests with fakes
            if _is_compatibility_fallback_error(exc):
                fallback_errors.append(f"{request_style}/{response_format}: {_format_openai_exception(exc)}")
                last_exc = exc
                continue
            raise AIPlannerError(_format_openai_exception(exc)) from exc

    if last_exc is not None:
        details = " | ".join(fallback_errors)
        raise AIPlannerError(
            "OpenAI-compatible request failed after exhausting compatibility fallbacks: "
            f"{details}"
        ) from last_exc
    raise AIPlannerError("OpenAI-compatible request failed before any request attempt was made")


def _request_attempts(api_style: str) -> list[tuple[str, str]]:
    if api_style == "responses":
        return [
            ("responses", "json_schema"),
            ("responses", "json_object"),
        ]
    if api_style == "chat_completions":
        return [
            ("chat_completions", "json_schema"),
            ("chat_completions", "json_object"),
        ]
    return [
        ("responses", "json_schema"),
        ("chat_completions", "json_schema"),
        ("chat_completions", "json_object"),
    ]


def _request_with_responses(
    client: Any,
    model: str,
    system_text: str,
    user_text: str,
    response_format: str,
) -> str:
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": system_text,
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": user_text,
                    }
                ],
            },
        ],
        text={"format": _responses_format_payload(response_format)},
    )
    return _extract_responses_output_text(response)


def _request_with_chat_completions(
    client: Any,
    model: str,
    system_text: str,
    user_text: str,
    response_format: str,
) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        response_format=_chat_completions_format_payload(response_format),
    )
    return _extract_chat_completion_text(response)


def _responses_format_payload(response_format: str) -> dict[str, Any]:
    if response_format == "json_schema":
        return {
            "type": "json_schema",
            "name": "bookmark_draft_plan",
            "strict": True,
            "schema": _semantic_response_schema(),
        }
    return {"type": "json_object"}


def _chat_completions_format_payload(response_format: str) -> dict[str, Any]:
    if response_format == "json_schema":
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "bookmark_draft_plan",
                "strict": True,
                "schema": _semantic_response_schema(),
            },
        }
    return {"type": "json_object"}


def _extract_responses_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)

    payload = _coerce_mapping(response)
    if payload.get("output_text"):
        return str(payload["output_text"])

    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("text"):
                return str(content["text"])
    raise AIPlannerError("OpenAI responses output did not include text")


def _extract_chat_completion_text(response: Any) -> str:
    payload = _coerce_mapping(response)
    choices = payload.get("choices", [])
    if not choices:
        raise AIPlannerError("OpenAI chat completion response did not include choices")

    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                text_parts.append(str(item["text"]))
        if text_parts:
            return "".join(text_parts)
    raise AIPlannerError("OpenAI chat completion response did not include message content")


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped
    return {}


def _is_compatibility_fallback_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in NON_RETRYABLE_STATUS_CODES:
        return False
    if status_code in COMPATIBILITY_FALLBACK_STATUS_CODES:
        return True

    message = str(exc).lower()
    compatibility_markers = (
        "unsupported",
        "not found",
        "unknown parameter",
        "response_format",
        "json_schema",
        "text.format",
        "responses",
        "chat.completions",
        "does not exist",
        "unrecognized request",
    )
    return any(marker in message for marker in compatibility_markers)


def _format_openai_exception(exc: Exception) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code:
        return f"OpenAI-compatible request failed: {status_code} {exc}"
    return f"OpenAI-compatible request failed: {exc}"


def _system_prompt(max_actions: int, require_schema_self_validation: bool = False) -> str:
    prompt = (
        "You are an expert bookmark organizer. "
        "Return JSON only. Focus on semantic organization, not cosmetic renaming. "
        f"Propose at most {max_actions} high-value actions. "
        "Rules are guardrails: obey protected roots, preserve user intent, and prefer moving into existing folders before creating new ones. "
        "Loose bookmarks that sit directly under a protected root path must remain in place by default. "
        "Do not reorganize those root-level loose bookmarks unless the user has explicitly authorized root-level cleanup. "
        "Use keep_for_review for low-confidence or ambiguous items. "
        "Only bookmarks with review_status=reviewed may be auto-classified; unresolved bookmarks must stay in keep_for_review."
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
    compact_snapshot = {
        "created_at": snapshot_document.get("created_at"),
        "folders": snapshot_document.get("folders", []),
        "bookmarks": snapshot_document.get("bookmarks", []),
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
                        "details",
                    ],
                },
            },
        },
        "required": ["summary", "actions"],
    }
