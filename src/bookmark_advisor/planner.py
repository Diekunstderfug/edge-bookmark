from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from bookmark_advisor.analysis import analyze_snapshot, build_folder_profiles
from bookmark_advisor.models import AnalysisSummary, BookmarkItem, Plan, PlanAction
from bookmark_advisor.parser import BookmarkSnapshot
from bookmark_advisor.rules import (
    BookmarkRelocationRule,
    FolderRelocationRule,
    RulesConfig,
)
from bookmark_advisor.utils import top_tokens, tokenize


def build_advise_plan(
    snapshot: BookmarkSnapshot,
    backup_path: Path,
    report_path: Path,
    rules: RulesConfig,
) -> Plan:
    analysis = analyze_snapshot(snapshot)
    actions: list[PlanAction] = []
    actions.extend(_preferred_folder_moves(snapshot, rules))
    actions.extend(_preferred_bookmark_moves(snapshot, rules))
    actions.extend(_duplicate_actions(snapshot, analysis))
    actions.extend(
        _loose_bookmark_actions(
            snapshot,
            allow_new_folders=rules.defaults.allow_new_folders_in_advise,
            rules=rules,
        )
    )
    summary = _base_summary(snapshot, analysis, rules)
    summary["mode_details"] = {
        "new_folder_actions": sum(1 for action in actions if action.action_type == "create_folder"),
        "move_actions": sum(
            1 for action in actions if action.action_type in {"move_bookmark", "move_folder"}
        ),
        "duplicate_actions": sum(1 for action in actions if action.action_type == "remove_duplicate"),
    }
    return Plan(
        mode="advise",
        source_path=str(snapshot.source_path),
        backup_path=str(backup_path),
        created_at=datetime.now().isoformat(timespec="seconds"),
        summary=summary,
        actions=actions,
        report_path=str(report_path),
    )


def build_merge_plan(
    snapshot: BookmarkSnapshot,
    backup_path: Path,
    report_path: Path,
    rules: RulesConfig,
) -> Plan:
    analysis = analyze_snapshot(snapshot)
    actions = _preferred_folder_moves(snapshot, rules)
    actions.extend(_preferred_bookmark_moves(snapshot, rules))
    actions.extend(_loose_bookmark_actions(snapshot, allow_new_folders=False, rules=rules))
    summary = _base_summary(snapshot, analysis, rules)
    summary["mode_details"] = {
        "move_actions": sum(
            1 for action in actions if action.action_type in {"move_bookmark", "move_folder"}
        ),
        "review_actions": sum(
            1 for action in actions if action.action_type == "keep_for_review"
        ),
    }
    return Plan(
        mode="merge",
        source_path=str(snapshot.source_path),
        backup_path=str(backup_path),
        created_at=datetime.now().isoformat(timespec="seconds"),
        summary=summary,
        actions=actions,
        report_path=str(report_path),
    )


def _base_summary(
    snapshot: BookmarkSnapshot,
    analysis: AnalysisSummary,
    rules: RulesConfig,
) -> dict[str, object]:
    return {
        "analysis": analysis.to_dict(),
        "top_level_folders": _top_level_folder_summaries(snapshot),
        "rules_source": str(rules.source_path),
    }


def _top_level_folder_summaries(snapshot: BookmarkSnapshot) -> list[dict[str, object]]:
    profiles = build_folder_profiles(snapshot, max_depth=1)
    rows = []
    for folder_id, profile in sorted(profiles.items(), key=lambda item: item[1].bookmark_count, reverse=True):
        rows.append(
            {
                "folder_id": folder_id,
                "path": profile.path,
                "bookmark_count": profile.bookmark_count,
                "top_domains": list(profile.domain_counts.items())[:5],
            }
        )
    return rows


def _duplicate_actions(snapshot: BookmarkSnapshot, analysis: AnalysisSummary) -> list[PlanAction]:
    actions: list[PlanAction] = []
    for group in analysis.duplicate_groups:
        canonical_id = _choose_canonical(snapshot, group)
        canonical = snapshot.bookmarks[canonical_id]
        for bookmark_id in group:
            if bookmark_id == canonical_id:
                continue
            bookmark = snapshot.bookmarks[bookmark_id]
            actions.append(
                PlanAction(
                    action_type="remove_duplicate",
                    bookmark_id=bookmark.id,
                    from_path=bookmark.folder_path,
                    duplicate_of=canonical.id,
                    reason=f"Normalized URL duplicates {canonical.title}",
                    confidence=0.99,
                )
            )
    return actions


def _preferred_folder_moves(
    snapshot: BookmarkSnapshot,
    rules: RulesConfig,
) -> list[PlanAction]:
    actions: list[PlanAction] = []
    for rule in rules.folder_relocations:
        _append_preferred_folder_move(snapshot, rule, actions)
    return actions


def _append_preferred_folder_move(
    snapshot: BookmarkSnapshot,
    rule: FolderRelocationRule,
    actions: list[PlanAction],
) -> None:
    folder = snapshot.find_folder_by_path(rule.from_path)
    destination_folder = snapshot.find_folder_by_path(rule.to_path)
    if folder is None or destination_folder is None:
        return
    actions.append(
        PlanAction(
            action_type="move_folder",
            folder_id=folder.id,
            from_path=folder.path,
            to_path=destination_folder.path,
            reason=rule.reason,
            confidence=0.97,
            details={"folder_name": folder.name, "mode": "preferred-rule"},
        )
    )


def _preferred_bookmark_moves(
    snapshot: BookmarkSnapshot,
    rules: RulesConfig,
) -> list[PlanAction]:
    actions: list[PlanAction] = []
    for bookmark in snapshot.bookmarks.values():
        for rule in rules.bookmark_relocations:
            if _bookmark_matches_rule(bookmark, rule):
                target_folder = snapshot.find_folder_by_path(rule.to_path)
                if target_folder is None or bookmark.folder_path == target_folder.path:
                    continue
                actions.append(
                    PlanAction(
                        action_type="move_bookmark",
                        bookmark_id=bookmark.id,
                        from_path=bookmark.folder_path,
                        to_path=target_folder.path,
                        reason=rule.reason,
                        confidence=0.96,
                        details={"mode": "preferred-rule"},
                    )
                )
                break
    return actions


def _bookmark_matches_rule(bookmark: BookmarkItem, rule: BookmarkRelocationRule) -> bool:
    match = rule.match
    if match.folder_path and bookmark.folder_path != match.folder_path:
        return False
    if match.title_contains and match.title_contains.lower() not in bookmark.title.lower():
        return False
    if match.title_equals and bookmark.title != match.title_equals:
        return False
    if match.url_contains and match.url_contains.lower() not in bookmark.url.lower():
        return False
    return True


def _choose_canonical(snapshot: BookmarkSnapshot, bookmark_ids: Iterable[str]) -> str:
    def sort_key(bookmark_id: str) -> tuple[int, int, str]:
        bookmark = snapshot.bookmarks[bookmark_id]
        folder = snapshot.folders[bookmark.folder_id]
        return (folder.depth, len(bookmark.title), bookmark.id)

    return min(bookmark_ids, key=sort_key)


def _loose_bookmark_actions(
    snapshot: BookmarkSnapshot,
    allow_new_folders: bool,
    rules: RulesConfig,
) -> list[PlanAction]:
    candidates = [
        bookmark
        for bookmark in snapshot.bookmarks.values()
        if snapshot.folders[bookmark.folder_id].depth == 0
    ]
    actions: list[PlanAction] = []

    if rules.defaults.protect_root_loose_bookmarks:
        for bookmark in sorted(candidates, key=lambda item: item.title.lower()):
            if bookmark.folder_path in rules.protected_paths:
                actions.append(
                    PlanAction(
                        action_type="keep_for_review",
                        bookmark_id=bookmark.id,
                        from_path=bookmark.folder_path,
                        reason="Root loose bookmarks are protected by rules and require manual review",
                        confidence=0.2,
                    )
                )
        return _dedupe_actions(actions)

    profiles = build_folder_profiles(snapshot, max_depth=2)
    created_paths: set[str] = set()
    unplaced: list[BookmarkItem] = []

    for bookmark in sorted(candidates, key=lambda item: item.title.lower()):
        best = _rank_folder(snapshot, bookmark, profiles, rules)
        if best and best["confidence"] >= 0.72:
            actions.append(
                PlanAction(
                    action_type="move_bookmark",
                    bookmark_id=bookmark.id,
                    from_path=bookmark.folder_path,
                    to_path=best["path"],
                    reason=best["reason"],
                    confidence=best["confidence"],
                    details={"mode": "existing-folder"},
                )
            )
        else:
            unplaced.append(bookmark)

    if allow_new_folders and unplaced:
        actions.extend(_group_new_folder_actions(snapshot, unplaced, created_paths, rules))
    else:
        for bookmark in unplaced:
            actions.append(
                PlanAction(
                    action_type="keep_for_review",
                    bookmark_id=bookmark.id,
                    from_path=bookmark.folder_path,
                    reason="No existing folder crossed the confidence threshold",
                    confidence=0.35,
                )
            )
    return _dedupe_actions(actions)


def _rank_folder(
    snapshot: BookmarkSnapshot,
    bookmark: BookmarkItem,
    profiles: dict[str, object],
    rules: RulesConfig,
) -> dict[str, object] | None:
    bookmark_tokens = Counter(tokenize(bookmark.title) + tokenize(bookmark.url))
    if bookmark.domain:
        bookmark_tokens.update(tokenize(bookmark.domain))
    best: dict[str, object] | None = None
    for profile in profiles.values():
        domain_score = 0.0
        if bookmark.domain and bookmark.domain in profile.domain_counts:
            domain_score = min(1.0, profile.domain_counts[bookmark.domain] / max(profile.bookmark_count, 1))
        overlap = 0.0
        for token, count in bookmark_tokens.items():
            overlap += min(count, profile.token_counts.get(token, 0))
        token_score = min(1.0, overlap / max(len(bookmark_tokens) or 1, 1))
        folder_hints = _folder_hints(profile.name, rules)
        name_match = 0.25 if any(token in folder_hints for token in bookmark_tokens) else 0.0
        hint_match = 0.22 if any(token in bookmark_tokens for token in folder_hints) else 0.0
        depth_penalty = 0.06 * max(profile.depth - 1, 0)
        score = 0.55 * domain_score + 0.35 * token_score + name_match + hint_match - depth_penalty
        if score <= 0:
            continue
        confidence = min(0.98, 0.45 + score / 1.6)
        reason_parts = []
        if domain_score:
            reason_parts.append(f"domain {bookmark.domain} already appears in {profile.name}")
        if token_score:
            reason_parts.append("title/url tokens overlap with existing items")
        if name_match:
            reason_parts.append("folder name matches bookmark keywords")
        if hint_match:
            reason_parts.append("folder hint keywords match the bookmark topic")
        candidate = {
            "folder_id": profile.folder_id,
            "path": profile.path,
            "confidence": round(confidence, 2),
            "score": score,
            "reason": "; ".join(reason_parts) or "overall similarity to existing category",
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best


def _group_new_folder_actions(
    snapshot: BookmarkSnapshot,
    bookmarks: list[BookmarkItem],
    created_paths: set[str],
    rules: RulesConfig,
) -> list[PlanAction]:
    actions: list[PlanAction] = []
    parent_root = snapshot.root_display_names.get("bookmark_bar", "收藏夹栏")
    parent_path = f"/{parent_root}"

    groups: defaultdict[str, list[BookmarkItem]] = defaultdict(list)
    for bookmark in bookmarks:
        key = _new_folder_key(bookmark)
        groups[key].append(bookmark)

    for key, grouped_bookmarks in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(grouped_bookmarks) < 2:
            for bookmark in grouped_bookmarks:
                actions.append(
                    PlanAction(
                        action_type="keep_for_review",
                        bookmark_id=bookmark.id,
                        from_path=bookmark.folder_path,
                        reason="Need manual review before creating a new category",
                        confidence=0.4,
                    )
                )
            continue
        folder_name = _folder_name_for_group(key, grouped_bookmarks)
        if folder_name.upper() in rules.defaults.generic_new_folder_names:
            for bookmark in grouped_bookmarks:
                actions.append(
                    PlanAction(
                        action_type="keep_for_review",
                        bookmark_id=bookmark.id,
                        from_path=bookmark.folder_path,
                        reason=f"Generic new folder name {folder_name} needs manual review",
                        confidence=0.42,
                    )
                )
            continue
        target_path = f"{parent_path}/{folder_name}"
        if target_path not in created_paths and snapshot.find_folder_by_path(target_path) is None:
            actions.append(
                PlanAction(
                    action_type="create_folder",
                    target_path=target_path,
                    folder_name=folder_name,
                    reason=f"Create a new folder for {folder_name} loose bookmarks",
                    confidence=0.74,
                    details={"parent_path": parent_path},
                )
            )
            created_paths.add(target_path)
        for bookmark in grouped_bookmarks:
            actions.append(
                PlanAction(
                    action_type="move_bookmark",
                    bookmark_id=bookmark.id,
                    from_path=bookmark.folder_path,
                    to_path=target_path,
                    reason=f"Grouped with similar loose bookmarks under {folder_name}",
                    confidence=0.71,
                    details={"mode": "new-folder-group"},
                )
            )
    return actions


def _new_folder_key(bookmark: BookmarkItem) -> str:
    if bookmark.domain:
        domain_parts = bookmark.domain.split(".")
        domain_key = domain_parts[-2] if len(domain_parts) >= 2 else bookmark.domain
        if domain_key:
            return f"domain:{domain_key}"
    tokens = tokenize(bookmark.title)
    if tokens:
        return f"token:{tokens[0]}"
    return f"title:{bookmark.title.lower()}"


def _folder_name_for_group(key: str, bookmarks: list[BookmarkItem]) -> str:
    prefix, _, value = key.partition(":")
    if prefix == "domain":
        return value.upper() if len(value) <= 4 else value.title()
    token_candidates = [token for token, _count in top_tokens([bookmark.title for bookmark in bookmarks], limit=3)]
    if token_candidates:
        head = token_candidates[0]
        return head.upper() if head.isascii() and len(head) <= 4 else head.title()
    return value.title()


def _dedupe_actions(actions: list[PlanAction]) -> list[PlanAction]:
    seen: set[tuple[str, str | None, str | None, str | None, str | None]] = set()
    result: list[PlanAction] = []
    for action in actions:
        key = (
            action.action_type,
            action.bookmark_id,
            action.folder_id,
            action.to_path,
            action.target_path,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(action)
    return result


def _folder_hints(folder_name: str, rules: RulesConfig) -> set[str]:
    hints = set(tokenize(folder_name))
    normalized = "".join(folder_name.lower().split())
    if normalized in rules.category_hints:
        hints.update(rules.category_hints[normalized])
    return hints
