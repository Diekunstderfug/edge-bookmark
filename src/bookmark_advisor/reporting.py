from __future__ import annotations

from pathlib import Path

from bookmark_advisor.models import Plan
from bookmark_advisor.parser import BookmarkSnapshot
from bookmark_advisor.utils import atomic_write_json

EXECUTABLE_ACTION_TYPES = {
    "create_folder",
    "rename_folder",
    "move_folder",
    "move_bookmark",
    "remove_duplicate",
    "delete_empty_folder",
}


def write_plan(plan: Plan, destination: Path) -> None:
    atomic_write_json(destination, plan.to_dict())


def write_report(plan: Plan, snapshot: BookmarkSnapshot, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    executable_actions = [
        action for action in plan.actions if action.action_type in EXECUTABLE_ACTION_TYPES
    ]
    review_only_actions = [
        action for action in plan.actions if action.action_type == "keep_for_review"
    ]
    lines = [
        f"# Bookmark Advisor Report: {plan.mode}",
        "",
        f"- Source: `{plan.source_path}`",
        f"- Backup: `{plan.backup_path}`",
        f"- Created: `{plan.created_at}`",
        f"- Plan version: `{plan.plan_version}`",
        f"- Executor: `{plan.executor}`",
        f"- Plan source: `{plan.source}`",
        f"- Total bookmarks: **{len(snapshot.bookmarks)}**",
        f"- Total folders: **{sum(1 for folder in snapshot.folders.values() if folder.depth > 0)}**",
        "",
        "## Summary",
        "",
    ]
    analysis = plan.summary["analysis"]
    lines.extend(
        [
            f"- Loose root bookmarks: {analysis['root_loose_bookmarks']}",
            f"- Duplicate groups: {len(analysis['duplicate_groups'])}",
            f"- Empty folders: {len(analysis['empty_folder_ids'])}",
            f"- Clutter folders: {len(analysis['clutter_folder_ids'])}",
            f"- Proposed actions: {len(plan.actions)}",
            f"- Executable actions: {len(executable_actions)}",
            f"- Review only actions: {len(review_only_actions)}",
            "",
            "## Top Folders",
            "",
        ]
    )
    for row in plan.summary["top_level_folders"][:10]:
        domains = ", ".join(f"{domain}:{count}" for domain, count in row["top_domains"])
        lines.append(f"- `{row['path']}`: {row['bookmark_count']} bookmarks | {domains}")
    lines.extend(
        [
            "",
            "## Execution Guidance",
            "",
            "- Recommended workflow: generate `plan.json`, import it into the Edge extension, and execute there.",
            "- Direct `--write-source` fallback is kept only for debugging or recovery when extension execution is unavailable.",
            "",
            "## Executable Actions",
            "",
        ]
    )
    for action in executable_actions[:40]:
        path = action.to_path or action.target_path or action.from_path or ""
        bookmark_title = ""
        if action.bookmark_id and action.bookmark_id in snapshot.bookmarks:
            bookmark_title = snapshot.bookmarks[action.bookmark_id].title
        if not bookmark_title and action.folder_id and action.folder_id in snapshot.folders:
            bookmark_title = snapshot.folders[action.folder_id].name
        lines.append(
            f"- `{action.action_type}` | {bookmark_title or action.bookmark_id or action.folder_name or ''} | "
            f"{path} | confidence={action.confidence:.2f} | {action.reason}"
        )
    if len(executable_actions) > 40:
        lines.append(f"- ... and {len(executable_actions) - 40} more executable actions")
    lines.extend(["", "## Review Only Actions", ""])
    for action in review_only_actions[:25]:
        path = action.from_path or action.to_path or ""
        bookmark_title = ""
        if action.bookmark_id and action.bookmark_id in snapshot.bookmarks:
            bookmark_title = snapshot.bookmarks[action.bookmark_id].title
        lines.append(
            f"- `{action.action_type}` | {bookmark_title or action.bookmark_id or ''} | "
            f"{path} | confidence={action.confidence:.2f} | {action.reason}"
        )
    if len(review_only_actions) > 25:
        lines.append(f"- ... and {len(review_only_actions) - 25} more review-only actions")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
