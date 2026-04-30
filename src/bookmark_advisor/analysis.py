from __future__ import annotations

from collections import Counter, defaultdict

from bookmark_advisor.models import AnalysisSummary, FolderProfile
from bookmark_advisor.parser import BookmarkSnapshot
from bookmark_advisor.utils import tokenize


def analyze_snapshot(snapshot: BookmarkSnapshot) -> AnalysisSummary:
    duplicates = find_duplicate_groups(snapshot)
    empty_folder_ids = [
        folder_id
        for folder_id, folder in snapshot.folders.items()
        if folder.depth > 0 and snapshot.folder_children.get(folder_id) == []
    ]
    singleton_folder_ids = [
        folder_id
        for folder_id, folder in snapshot.folders.items()
        if folder.depth > 1 and len(snapshot.folder_children.get(folder_id, [])) == 1
    ]
    clutter_folder_ids = []
    for folder_id, profile in build_folder_profiles(snapshot, max_depth=None).items():
        domain_diversity = len(profile.domain_counts)
        if profile.bookmark_count >= 12 and (domain_diversity >= 8 or len(profile.token_counts) >= 20):
            clutter_folder_ids.append(folder_id)
    root_loose_bookmarks = sum(
        1
        for bookmark in snapshot.bookmarks.values()
        if snapshot.folders[bookmark.folder_id].depth == 0
    )
    return AnalysisSummary(
        total_bookmarks=len(snapshot.bookmarks),
        total_folders=sum(1 for folder in snapshot.folders.values() if folder.depth > 0),
        root_loose_bookmarks=root_loose_bookmarks,
        empty_folder_ids=sorted(empty_folder_ids),
        clutter_folder_ids=sorted(clutter_folder_ids),
        singleton_folder_ids=sorted(singleton_folder_ids),
        duplicate_groups=duplicates,
    )


def find_duplicate_groups(snapshot: BookmarkSnapshot) -> list[list[str]]:
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for bookmark in snapshot.bookmarks.values():
        if bookmark.normalized_url:
            groups[bookmark.normalized_url].append(bookmark.id)
    duplicates = [sorted(ids) for ids in groups.values() if len(ids) > 1]
    duplicates.sort(key=lambda ids: (-len(ids), ids[0]))
    return duplicates


def build_folder_profiles(
    snapshot: BookmarkSnapshot,
    max_depth: int | None = 2,
) -> dict[str, FolderProfile]:
    profiles: dict[str, FolderProfile] = {}
    for folder in snapshot.folders.values():
        if folder.depth == 0:
            continue
        if max_depth is not None and folder.depth > max_depth:
            continue
        bookmark_ids = _descendant_bookmark_ids(snapshot, folder.id)
        if not bookmark_ids:
            continue
        domains = Counter()
        tokens = Counter(tokenize(folder.name))
        for bookmark_id in bookmark_ids:
            bookmark = snapshot.bookmarks[bookmark_id]
            if bookmark.domain:
                domains[bookmark.domain] += 1
            tokens.update(tokenize(bookmark.title))
            tokens.update(tokenize(bookmark.url))
        profiles[folder.id] = FolderProfile(
            folder_id=folder.id,
            path=folder.path,
            name=folder.name,
            depth=folder.depth,
            bookmark_count=len(bookmark_ids),
            domain_counts=dict(domains.most_common(20)),
            token_counts=dict(tokens.most_common(40)),
        )
    return profiles


def _descendant_bookmark_ids(snapshot: BookmarkSnapshot, folder_id: str) -> list[str]:
    results: list[str] = []
    for child_id in snapshot.folder_children.get(folder_id, []):
        if child_id in snapshot.bookmarks:
            results.append(child_id)
        elif child_id in snapshot.folders:
            results.extend(_descendant_bookmark_ids(snapshot, child_id))
    return results

