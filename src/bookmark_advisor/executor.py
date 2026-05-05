from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bookmark_advisor.models import Plan, PlanAction
from bookmark_advisor.utils import atomic_write_json


def apply_plan(plan: Plan, destination: Path, write_source: bool = False) -> Path:
    source_path = Path(plan.source_path)
    data = json.loads(source_path.read_text(encoding="utf-8"))
    for action in plan.actions:
        _apply_action(data, action)
    target = source_path if write_source else destination
    atomic_write_json(target, data)
    return target


def apply_reviewed_semantic_plan(
    reviewed_plan_payload: dict[str, Any],
    source_path: Path,
    destination: Path,
    write_source: bool = False,
) -> Path:
    data = json.loads(source_path.read_text(encoding="utf-8"))
    for action in reviewed_plan_payload.get("actions", []):
        status = str(action.get("status", ""))
        if status not in {"approved", "edited"}:
            continue
        _apply_action(data, _plan_action_from_semantic_payload(action))
    target = source_path if write_source else destination
    atomic_write_json(target, data)
    return target


def _apply_action(data: dict[str, Any], action: PlanAction) -> None:
    if action.action_type == "keep_for_review":
        return
    if action.action_type == "move_folder":
        if not action.folder_id or not action.to_path:
            raise ValueError("move_folder requires folder_id and to_path")
        node, parent = _find_node_and_parent(data, action.folder_id)
        if not node or not parent:
            raise ValueError(f"Could not resolve folder id: {action.folder_id}")
        if action.from_path and (
            action.to_path == action.from_path or action.to_path.startswith(f"{action.from_path}/")
        ):
            raise ValueError("move_folder destination must not be the source folder or its descendant")
        destination_folder = _ensure_folder_path(data, action.to_path)
        if _contains_node(node, destination_folder):
            raise ValueError("move_folder destination must not be the source folder or its descendant")
        parent["children"] = [child for child in parent.get("children", []) if str(child.get("id")) != action.folder_id]
        destination_folder.setdefault("children", []).append(node)
        return
    if action.action_type == "create_folder":
        _ensure_folder_path(data, action.target_path or "")
        return
    if action.action_type == "move_bookmark":
        if not action.bookmark_id or not action.to_path:
            raise ValueError("move_bookmark requires bookmark_id and to_path")
        node, parent = _find_node_and_parent(data, action.bookmark_id)
        if not node or not parent:
            raise ValueError(f"Could not resolve bookmark id: {action.bookmark_id}")
        destination_folder = _ensure_folder_path(data, action.to_path)
        if any(child.get("id") == node.get("id") for child in destination_folder.get("children", [])):
            return
        parent["children"] = [child for child in parent.get("children", []) if str(child.get("id")) != action.bookmark_id]
        destination_folder.setdefault("children", []).append(node)
        return
    if action.action_type == "remove_duplicate":
        if not action.bookmark_id:
            return
        node, parent = _find_node_and_parent(data, action.bookmark_id)
        if node and parent:
            parent["children"] = [child for child in parent.get("children", []) if str(child.get("id")) != action.bookmark_id]
        return
    if action.action_type == "rename_folder":
        if not action.folder_id or not action.to_name:
            return
        node, _parent = _find_node_and_parent(data, action.folder_id)
        if node:
            node["name"] = action.to_name
        return
    if action.action_type == "delete_empty_folder":
        if not action.folder_id:
            raise ValueError("delete_empty_folder requires folder_id")
        node, parent = _find_node_and_parent(data, action.folder_id)
        if not node or not parent:
            raise ValueError(f"Could not resolve folder id: {action.folder_id}")
        if node.get("type") != "folder":
            raise ValueError("delete_empty_folder target must be a folder")
        if node.get("children"):
            raise ValueError("delete_empty_folder target must be empty")
        parent["children"] = [child for child in parent.get("children", []) if str(child.get("id")) != action.folder_id]
        return


def _find_node_and_parent(data: dict[str, Any], target_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    for root in data.get("roots", {}).values():
        for child in root.get("children", []) or []:
            found, parent = _walk_find(child, root, target_id)
            if found:
                return found, parent
    return None, None


def _walk_find(
    node: dict[str, Any],
    parent: dict[str, Any],
    target_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if str(node.get("id")) == target_id:
        return node, parent
    for child in node.get("children", []) or []:
        found, owner = _walk_find(child, node, target_id)
        if found:
            return found, owner
    return None, None


def _ensure_folder_path(data: dict[str, Any], folder_path: str) -> dict[str, Any]:
    parts = [part for part in folder_path.split("/") if part]
    if not parts:
        raise ValueError("folder_path must not be empty")
    root_node = None
    for root in data.get("roots", {}).values():
        if (root.get("name") or "") == parts[0]:
            root_node = root
            break
    if root_node is None:
        raise ValueError(f"Unknown root folder in path: {folder_path}")
    current = root_node
    for part in parts[1:]:
        next_node = None
        for child in current.get("children", []) or []:
            if child.get("type") == "folder" and (child.get("name") or "") == part:
                next_node = child
                break
        if next_node is None:
            next_node = {
                "type": "folder",
                "id": _next_folder_id(data),
                "name": part,
                "children": [],
                "date_added": "0",
                "date_modified": "0",
            }
            current.setdefault("children", []).append(next_node)
        current = next_node
    return current


def _next_folder_id(data: dict[str, Any]) -> str:
    max_id = 0
    for root in data.get("roots", {}).values():
        for child in root.get("children", []) or []:
            max_id = max(max_id, _walk_max_id(child))
    return str(max_id + 1)


def _walk_max_id(node: dict[str, Any]) -> int:
    try:
        max_id = int(node.get("id", 0))
    except (TypeError, ValueError):
        max_id = 0
    for child in node.get("children", []) or []:
        max_id = max(max_id, _walk_max_id(child))
    return max_id


def _contains_node(ancestor: dict[str, Any], candidate: dict[str, Any]) -> bool:
    if str(ancestor.get("id")) == str(candidate.get("id")):
        return True
    for child in ancestor.get("children", []) or []:
        if _contains_node(child, candidate):
            return True
    return False


def _plan_action_from_semantic_payload(payload: dict[str, Any]) -> PlanAction:
    bookmark_locator = payload.get("bookmark_locator") or {}
    folder_locator = payload.get("folder_locator") or {}
    return PlanAction(
        action_type=str(payload.get("action_type", "")),
        reason=str(payload.get("reason", "")),
        confidence=float(payload.get("confidence", 0)),
        bookmark_id=_optional_str(payload.get("bookmark_id")) or _optional_str(bookmark_locator.get("id")),
        folder_id=_optional_str(payload.get("folder_id")) or _optional_str(folder_locator.get("id")),
        from_path=_optional_str(payload.get("from_path")),
        to_path=_optional_str(payload.get("to_path")),
        target_path=_optional_str(payload.get("target_path")),
        folder_name=_optional_str(payload.get("folder_name")) or _optional_str(folder_locator.get("name")),
        to_name=_optional_str(payload.get("to_name")),
        details=dict(payload.get("details") or {}),
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
