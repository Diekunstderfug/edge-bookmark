from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bookmark_advisor.utils import atomic_write_json


class RulesValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass
class RulesDefaults:
    protect_root_loose_bookmarks: bool = True
    allow_new_folders_in_advise: bool = True
    generic_new_folder_names: set[str] = field(default_factory=set)
    # fast_rules.json 生成用：保留 YAML 源中 generic_new_folder_names 的原始顺序（原文大小写）。
    generic_new_folder_names_order: list[str] = field(default_factory=list)


@dataclass
class FolderRelocationRule:
    from_path: str
    to_path: str
    reason: str


@dataclass
class BookmarkMatchRule:
    folder_path: str | None = None
    title_contains: str | None = None
    title_equals: str | None = None
    url_contains: str | None = None


@dataclass
class BookmarkRelocationRule:
    match: BookmarkMatchRule
    to_path: str
    reason: str


@dataclass
class RulesConfig:
    defaults: RulesDefaults
    category_hints: dict[str, set[str]]
    folder_relocations: list[FolderRelocationRule]
    bookmark_relocations: list[BookmarkRelocationRule]
    protected_paths: list[str]
    source_path: Path
    # fast_rules.json 生成用：保留每个 category_hints 键在 YAML 源中的值顺序（原文）。
    category_hint_order: dict[str, list[str]] = field(default_factory=dict)


def matches_rule(folder_path: str, title: str, url: str, rule: BookmarkRelocationRule) -> bool:
    """判断书签三元组（folder_path/title/url）是否命中一条书签迁移规则。

    纯函数、只接受基本类型：planner（BookmarkItem）与
    ai_planner（snapshot document dict 行）共用同一匹配语义，
    避免两处各持一份实现后漂移。所有条件需同时满足才算命中。
    """
    match = rule.match
    if match.folder_path and folder_path != match.folder_path:
        return False
    if match.title_contains and match.title_contains.lower() not in title.lower():
        return False
    if match.title_equals and title != match.title_equals:
        return False
    if match.url_contains and match.url_contains.lower() not in url.lower():
        return False
    return True


ALLOWED_TOP_LEVEL_KEYS = {
    "defaults",
    "category_hints",
    "folder_relocations",
    "bookmark_relocations",
    "protected_paths",
}
ALLOWED_DEFAULT_KEYS = {
    "protect_root_loose_bookmarks",
    "allow_new_folders_in_advise",
    "generic_new_folder_names",
}
ALLOWED_MATCH_KEYS = {"folder_path",
                      "title_contains", "title_equals", "url_contains"}


def load_rules(rules_path: Path | None = None, workspace: Path | None = None) -> RulesConfig:
    resolved_path = resolve_rules_path(
        rules_path=rules_path, workspace=workspace)
    data = _load_rules_data(resolved_path)
    errors = validate_rules_data(data)
    if errors:
        raise RulesValidationError(errors)
    return _build_rules_config(data, resolved_path)


def validate_rules_file(rules_path: Path) -> list[str]:
    try:
        data = _load_rules_data(rules_path)
    except Exception as exc:
        return [f"failed to load rules: {exc}"]
    return validate_rules_data(data)


def resolve_rules_path(rules_path: Path | None = None, workspace: Path | None = None) -> Path:
    if rules_path is not None:
        return Path(rules_path).expanduser().resolve()

    workspace_root = (workspace or Path.cwd()).resolve()
    workspace_candidate = workspace_root / "config" / "rules.yaml"
    if workspace_candidate.exists():
        return workspace_candidate

    repo_candidate = Path(__file__).resolve(
    ).parents[2] / "config" / "rules.yaml"
    if repo_candidate.exists():
        return repo_candidate

    raise FileNotFoundError(
        "no rules.yaml found in workspace/config or repo config directory")


def validate_rules_data(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["rules file must contain a top-level mapping"]

    unknown_keys = sorted(set(data) - ALLOWED_TOP_LEVEL_KEYS)
    for key in unknown_keys:
        errors.append(f"unknown top-level key: {key}")

    for required_key in sorted(ALLOWED_TOP_LEVEL_KEYS):
        if required_key not in data:
            errors.append(f"missing required top-level key: {required_key}")

    defaults = data.get("defaults")
    if not isinstance(defaults, dict):
        errors.append("defaults must be a mapping")
    else:
        unknown_default_keys = sorted(set(defaults) - ALLOWED_DEFAULT_KEYS)
        for key in unknown_default_keys:
            errors.append(f"unknown defaults key: {key}")
        if not isinstance(defaults.get("protect_root_loose_bookmarks"), bool):
            errors.append(
                "defaults.protect_root_loose_bookmarks must be a boolean")
        if not isinstance(defaults.get("allow_new_folders_in_advise"), bool):
            errors.append(
                "defaults.allow_new_folders_in_advise must be a boolean")
        if not _is_string_list(defaults.get("generic_new_folder_names")):
            errors.append(
                "defaults.generic_new_folder_names must be a list of strings")

    category_hints = data.get("category_hints")
    if not isinstance(category_hints, dict):
        errors.append("category_hints must be a mapping")
    else:
        for key, value in category_hints.items():
            if not isinstance(key, str) or not key.strip():
                errors.append("category_hints keys must be non-empty strings")
            if not _is_string_list(value):
                errors.append(
                    f"category_hints.{key} must be a list of strings")

    protected_paths = data.get("protected_paths")
    if not _is_string_list(protected_paths):
        errors.append("protected_paths must be a list of strings")

    folder_relocations = data.get("folder_relocations")
    if not isinstance(folder_relocations, list):
        errors.append("folder_relocations must be a list")
    else:
        for index, item in enumerate(folder_relocations):
            if not isinstance(item, dict):
                errors.append(f"folder_relocations[{index}] must be a mapping")
                continue
            for key in ("from", "to", "reason"):
                if not isinstance(item.get(key), str) or not item.get(key, "").strip():
                    errors.append(
                        f"folder_relocations[{index}].{key} must be a non-empty string")

    bookmark_relocations = data.get("bookmark_relocations")
    if not isinstance(bookmark_relocations, list):
        errors.append("bookmark_relocations must be a list")
    else:
        for index, item in enumerate(bookmark_relocations):
            if not isinstance(item, dict):
                errors.append(
                    f"bookmark_relocations[{index}] must be a mapping")
                continue
            if not isinstance(item.get("to"), str) or not item.get("to", "").strip():
                errors.append(
                    f"bookmark_relocations[{index}].to must be a non-empty string")
            if not isinstance(item.get("reason"), str) or not item.get("reason", "").strip():
                errors.append(
                    f"bookmark_relocations[{index}].reason must be a non-empty string")
            match = item.get("match")
            if not isinstance(match, dict):
                errors.append(
                    f"bookmark_relocations[{index}].match must be a mapping")
                continue
            unknown_match_keys = sorted(set(match) - ALLOWED_MATCH_KEYS)
            for key in unknown_match_keys:
                errors.append(
                    f"bookmark_relocations[{index}].match has unknown key: {key}")
            if not any(match.get(key) for key in ALLOWED_MATCH_KEYS):
                errors.append(
                    f"bookmark_relocations[{index}].match must define at least one criterion"
                )
            for key, value in match.items():
                if value is not None and (not isinstance(value, str) or not value.strip()):
                    errors.append(
                        f"bookmark_relocations[{index}].match.{key} must be a non-empty string"
                    )

    return errors


def _build_rules_config(data: dict[str, Any], source_path: Path) -> RulesConfig:
    defaults_data = data["defaults"]
    defaults = RulesDefaults(
        protect_root_loose_bookmarks=defaults_data["protect_root_loose_bookmarks"],
        allow_new_folders_in_advise=defaults_data["allow_new_folders_in_advise"],
        generic_new_folder_names={
            name.upper() for name in defaults_data["generic_new_folder_names"]},
        generic_new_folder_names_order=list(
            defaults_data["generic_new_folder_names"]),
    )
    category_hints = {
        _normalize_hint_key(key): {str(item) for item in value}
        for key, value in data["category_hints"].items()
    }
    category_hint_order = {
        _normalize_hint_key(key): _dedupe_preserving_order([str(item) for item in value])
        for key, value in data["category_hints"].items()
    }
    folder_relocations = [
        FolderRelocationRule(
            from_path=item["from"],
            to_path=item["to"],
            reason=item["reason"],
        )
        for item in data["folder_relocations"]
    ]
    bookmark_relocations = [
        BookmarkRelocationRule(
            match=BookmarkMatchRule(
                folder_path=item["match"].get("folder_path"),
                title_contains=item["match"].get("title_contains"),
                title_equals=item["match"].get("title_equals"),
                url_contains=item["match"].get("url_contains"),
            ),
            to_path=item["to"],
            reason=item["reason"],
        )
        for item in data["bookmark_relocations"]
    ]
    return RulesConfig(
        defaults=defaults,
        category_hints=category_hints,
        folder_relocations=folder_relocations,
        bookmark_relocations=bookmark_relocations,
        protected_paths=list(data["protected_paths"]),
        source_path=source_path,
        category_hint_order=category_hint_order,
    )


# ---------------------------------------------------------------------------
# fast_rules.json 单一来源导出：config/rules.yaml 是唯一事实来源，
# extension/fast_rules.json 由本区块生成。生成物必须与已提交的
# extension/fast_rules.json 逐字节一致（tests/test_rules_parity.py
# 以现文件为黄金样例做生成物校验）。

FAST_RULES_TOP_LEVEL_ORDER = (
    "defaults",
    "protected_paths",
    "category_hints",
    "folder_relocations",
    "bookmark_relocations",
)
_MATCH_FIELD_ORDER = ("folder_path", "title_contains",
                      "title_equals", "url_contains")


def dump_fast_rules(rules: RulesConfig) -> dict[str, Any]:
    """从 RulesConfig 生成与 extension/fast_rules.json 结构一致的负载。

    键顺序、嵌套与值类型均与已提交的 extension/fast_rules.json 黄金样例
    逐字段对齐：顶层键固定为 FAST_RULES_TOP_LEVEL_ORDER，set 类字段
    （generic_new_folder_names、category_hints 值）按 YAML 源顺序还原
    为有序数组，match 对象跳过 None 字段。
    """
    return {
        "defaults": {
            "protect_root_loose_bookmarks": rules.defaults.protect_root_loose_bookmarks,
            "allow_new_folders_in_advise": rules.defaults.allow_new_folders_in_advise,
            "generic_new_folder_names": _ordered_generic_new_folder_names(rules.defaults),
        },
        "protected_paths": list(rules.protected_paths),
        "category_hints": {
            key: _ordered_category_hint(key, rules) for key in rules.category_hints
        },
        "folder_relocations": [
            {"from": rule.from_path, "to": rule.to_path, "reason": rule.reason}
            for rule in rules.folder_relocations
        ],
        "bookmark_relocations": [
            {"match": _match_payload(rule.match),
             "to": rule.to_path, "reason": rule.reason}
            for rule in rules.bookmark_relocations
        ],
    }


def render_fast_rules(payload: dict[str, Any]) -> str:
    """将 dump_fast_rules 的负载渲染为与现提交文件逐字节一致的 JSON 文本。

    格式与 extension/fast_rules.json 的历史形状逐行对齐：标量数组内联，
    match 对象内联（``{ "k": "v" }``），relocation 对象展开，2 空格缩进，
    LF 行尾，末尾单个换行。
    """
    defaults = payload["defaults"]
    lines: list[str] = []
    lines.append("{")
    lines.append('  "defaults": {')
    lines.append(
        f'    "protect_root_loose_bookmarks": {_json_value(defaults["protect_root_loose_bookmarks"])},'
    )
    lines.append(
        f'    "allow_new_folders_in_advise": {_json_value(defaults["allow_new_folders_in_advise"])},'
    )
    lines.append(
        f'    "generic_new_folder_names": {_render_inline_list(defaults["generic_new_folder_names"])}'
    )
    lines.append("  },")
    lines.append(
        f'  "protected_paths": {_render_inline_list(payload["protected_paths"])},')
    category_hints = payload["category_hints"]
    if category_hints:
        lines.append('  "category_hints": {')
        hint_keys = list(category_hints)
        for index, key in enumerate(hint_keys):
            suffix = "," if index < len(hint_keys) - 1 else ""
            lines.append(
                f'    {_json_value(key)}: {_render_inline_list(category_hints[key])}{suffix}'
            )
        lines.append("  },")
    else:
        lines.append('  "category_hints": {},')
    folder_rules = payload["folder_relocations"]
    if folder_rules:
        lines.append('  "folder_relocations": [')
        for index, rule in enumerate(folder_rules):
            suffix = "," if index < len(folder_rules) - 1 else ""
            lines.append("    {")
            lines.append(f'      "from": {_json_value(rule["from"])},')
            lines.append(f'      "to": {_json_value(rule["to"])},')
            lines.append(f'      "reason": {_json_value(rule["reason"])}')
            lines.append(f"    }}{suffix}")
        lines.append("  ],")
    else:
        lines.append('  "folder_relocations": [],')
    bookmark_rules = payload["bookmark_relocations"]
    if bookmark_rules:
        lines.append('  "bookmark_relocations": [')
        for index, rule in enumerate(bookmark_rules):
            suffix = "," if index < len(bookmark_rules) - 1 else ""
            lines.append("    {")
            lines.append(
                f'      "match": {_render_inline_dict(rule["match"])},')
            lines.append(f'      "to": {_json_value(rule["to"])},')
            lines.append(f'      "reason": {_json_value(rule["reason"])}')
            lines.append(f"    }}{suffix}")
        lines.append("  ]")
    else:
        lines.append('  "bookmark_relocations": []')
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_fast_rules(rules: RulesConfig, path: Path | str) -> None:
    """原子写出 fast_rules JSON（与 extension/fast_rules.json 历史格式逐字节一致）。"""
    payload = dump_fast_rules(rules)
    atomic_write_json(Path(path), payload, text=render_fast_rules(payload))


def _match_payload(match: BookmarkMatchRule) -> dict[str, str]:
    values = {
        "folder_path": match.folder_path,
        "title_contains": match.title_contains,
        "title_equals": match.title_equals,
        "url_contains": match.url_contains,
    }
    return {field: values[field] for field in _MATCH_FIELD_ORDER if values[field] is not None}


def _ordered_generic_new_folder_names(defaults: RulesDefaults) -> list[str]:
    order = _dedupe_preserving_order(defaults.generic_new_folder_names_order)
    if order:
        if {name.upper() for name in order} != defaults.generic_new_folder_names:
            raise ValueError(
                "generic_new_folder_names_order does not match generic_new_folder_names"
            )
        return order
    return sorted(defaults.generic_new_folder_names)


def _ordered_category_hint(key: str, rules: RulesConfig) -> list[str]:
    values = rules.category_hints.get(key, set())
    order = _dedupe_preserving_order(rules.category_hint_order.get(key, []))
    if order:
        if set(order) != values:
            raise ValueError(
                f"category_hint_order[{key!r}] does not match category_hints[{key!r}]"
            )
        return order
    return sorted(values)


def _dedupe_preserving_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render_inline_list(items: list[str]) -> str:
    if not items:
        return "[]"
    return "[" + ", ".join(_json_value(item) for item in items) + "]"


def _render_inline_dict(entries: dict[str, Any]) -> str:
    if not entries:
        return "{}"
    parts = [f"{_json_value(key)}: {_json_value(value)}" for key,
             value in entries.items()]
    return "{ " + ", ".join(parts) + " }"


def _normalize_hint_key(value: str) -> str:
    return "".join(value.lower().split())


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def _load_rules_data(rules_path: Path) -> dict[str, Any]:
    text = rules_path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return json.loads(text)
    return _parse_simple_yaml(text)


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        stripped = raw_line.lstrip(" ")
        if stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(stripped)
        if "\t" in raw_line[:indent]:
            raise ValueError("tabs are not supported in rules.yaml")
        lines.append((indent, stripped.rstrip()))
    if not lines:
        raise ValueError("rules file is empty")
    value, index = _parse_collection(lines, 0, lines[0][0])
    if index != len(lines):
        raise ValueError("unexpected trailing content in rules file")
    if not isinstance(value, dict):
        raise ValueError("rules file must start with a mapping")
    return value


def _parse_collection(
    lines: list[tuple[int, str]],
    index: int,
    indent: int,
) -> tuple[Any, int]:
    if index >= len(lines):
        raise ValueError("unexpected end of file")
    current_indent, content = lines[index]
    if current_indent != indent:
        raise ValueError(f"expected indent {indent}, got {current_indent}")
    if content.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_dict(lines, index, indent)


def _parse_dict(
    lines: list[tuple[int, str]],
    index: int,
    indent: int,
) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent != indent:
            raise ValueError(f"invalid indentation near: {content}")
        if content.startswith("- "):
            break
        key, raw_value = _split_key_value(content)
        index += 1
        if raw_value == "":
            if index >= len(lines) or lines[index][0] <= current_indent:
                result[key] = {}
            else:
                value, index = _parse_collection(lines, index, lines[index][0])
                result[key] = value
        else:
            result[key] = _parse_scalar(raw_value)
    return result, index


def _parse_list(
    lines: list[tuple[int, str]],
    index: int,
    indent: int,
) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent != indent or not content.startswith("- "):
            break
        item_content = content[2:].strip()
        index += 1
        if item_content == "":
            if index >= len(lines) or lines[index][0] <= current_indent:
                result.append(None)
            else:
                value, index = _parse_collection(lines, index, lines[index][0])
                result.append(value)
            continue
        if _looks_like_mapping(item_content):
            key, raw_value = _split_key_value(item_content)
            item: dict[str, Any] = {}
            if raw_value == "":
                if index >= len(lines) or lines[index][0] <= current_indent:
                    item[key] = {}
                else:
                    value, index = _parse_collection(
                        lines, index, lines[index][0])
                    item[key] = value
            else:
                item[key] = _parse_scalar(raw_value)
            if index < len(lines) and lines[index][0] > current_indent:
                extras, index = _parse_dict(lines, index, current_indent + 2)
                item.update(extras)
            result.append(item)
            continue
        result.append(_parse_scalar(item_content))
    return result, index


def _looks_like_mapping(content: str) -> bool:
    if ":" not in content:
        return False
    key, _sep, _rest = content.partition(":")
    return bool(key.strip())


def _split_key_value(content: str) -> tuple[str, str]:
    key, separator, remainder = content.partition(":")
    if not separator:
        raise ValueError(f"expected key:value pair, got: {content}")
    return key.strip(), remainder.strip()


def _parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in inner.split(",")]
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value
