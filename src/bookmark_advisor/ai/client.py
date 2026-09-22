"""OpenAI SDK import, client construction, and request-style adapters.

Extracted from :mod:`bookmark_advisor.ai_planner`. Everything that talks
to OpenAI-compatible endpoints lives here: lazy SDK import, environment
driven client configuration, API-style resolution, and the compatibility
fallback request chain (responses/json_schema -> chat.completions/json_schema
-> chat.completions/json_object -> chat.completions/plain_json).
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

from bookmark_advisor.ai.prompts import (
    _semantic_response_schema,
    _system_prompt,
    _user_prompt,
)
from bookmark_advisor.rules import RulesConfig

SUPPORTED_API_STYLES = {"auto", "responses", "chat_completions"}
COMPATIBILITY_FALLBACK_STATUS_CODES = {400, 404, 405, 415, 422, 501}
NON_RETRYABLE_STATUS_CODES = {401, 403, 429}


class AIPlannerError(RuntimeError):
    pass


def _import_openai_sdk():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AIPlannerError(
            "OpenAI SDK is not installed. Install it with `python3 -m pip install openai` "
            "or install the project dependencies first."
        ) from exc
    return OpenAI


def _build_configured_openai_client(
    base_url: str | None = None,
    import_sdk: Any = None,
) -> Any:
    """Assemble the OpenAI client from environment configuration.

    ``import_sdk`` allows callers to route the SDK loader through their own
    module namespace so historical ``unittest.mock.patch`` targets keep
    working; it defaults to this module's :func:`_import_openai_sdk`.
    """
    if import_sdk is None:
        import_sdk = _import_openai_sdk

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise AIPlannerError("OPENAI_API_KEY is not set")

    try:
        OpenAI = import_sdk()
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
    parsed = urlsplit(normalized)
    if parsed.scheme != "https":
        raise AIPlannerError("OpenAI base URL must use https://")
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
        prompt_must_carry_schema = response_format != "json_schema"
        system_text = _system_prompt(
            max_actions=max_actions,
            require_schema_self_validation=prompt_must_carry_schema,
        )
        user_text = _user_prompt(
            snapshot_document=snapshot_document,
            rules=rules,
            include_schema_in_prompt=prompt_must_carry_schema,
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
            ("chat_completions", "plain_json"),
        ]
    return [
        ("responses", "json_schema"),
        ("chat_completions", "json_schema"),
        ("chat_completions", "json_object"),
        ("chat_completions", "plain_json"),
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
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
    }
    if response_format != "plain_json":
        payload["response_format"] = _chat_completions_format_payload(response_format)
    response = client.chat.completions.create(**payload)
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
