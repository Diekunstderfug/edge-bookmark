from __future__ import annotations

import json
import ipaddress
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from bookmark_advisor.models import (
    EnrichedSnapshotBookmarkRecord,
    EnrichedSnapshotDocument,
    ReviewQueueDocument,
    ReviewQueueItem,
    SnapshotBookmarkRecord,
    SnapshotDocument,
    SnapshotFolderRecord,
    UrlReviewDocument,
    UrlReviewItem,
)
from bookmark_advisor.parser import BookmarkSnapshot
from bookmark_advisor.utils import atomic_write_json


def build_snapshot_document(
    snapshot: BookmarkSnapshot,
    source: str = "edge-file",
) -> SnapshotDocument:
    folders = [
        SnapshotFolderRecord(
            id=folder.id,
            name=folder.name,
            path=folder.path,
            parent_path=snapshot.folders[folder.parent_id].path if folder.parent_id else None,
            root_key=folder.root_key,
            depth=folder.depth,
            bookmark_count=folder.bookmark_count,
            subfolder_count=folder.subfolder_count,
        )
        for folder in sorted(snapshot.folders.values(), key=lambda item: (item.depth, item.path))
    ]
    bookmarks = [
        SnapshotBookmarkRecord(
            id=bookmark.id,
            title=bookmark.title,
            url=bookmark.url,
            normalized_url=bookmark.normalized_url,
            domain=bookmark.domain,
            folder_id=bookmark.folder_id,
            folder_path=bookmark.folder_path,
            top_level_folder=bookmark.top_level_folder,
            root_key=bookmark.root_key,
            path=bookmark.path,
            depth=bookmark.depth,
        )
        for bookmark in sorted(
            snapshot.bookmarks.values(),
            key=lambda item: (item.folder_path, item.title.lower(), item.normalized_url, item.id),
        )
    ]
    return SnapshotDocument(
        snapshot_version="1",
        source=source,
        source_path=str(snapshot.source_path),
        created_at=datetime.now().isoformat(timespec="seconds"),
        folders=folders,
        bookmarks=bookmarks,
    )


def write_snapshot_document(document: SnapshotDocument, destination: Path) -> None:
    atomic_write_json(destination, document.to_dict())


def load_snapshot_document(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_review_queue_document(snapshot_document: dict) -> ReviewQueueDocument:
    items = [
        ReviewQueueItem(
            bookmark_id=str(bookmark.get("id", "")),
            title=str(bookmark.get("title", "")),
            url=str(bookmark.get("url", "")),
            normalized_url=str(bookmark.get("normalized_url", "")),
            folder_path=str(bookmark.get("folder_path", "")),
            top_level_folder=bookmark.get("top_level_folder"),
        )
        for bookmark in snapshot_document.get("bookmarks", [])
        if url_requires_review(str(bookmark.get("url", "")))
    ]
    return ReviewQueueDocument(
        queue_version="1",
        created_at=datetime.now().isoformat(timespec="seconds"),
        source_snapshot=str(snapshot_document.get("source_path", "")),
        items=items,
    )


def write_review_queue_document(document: ReviewQueueDocument, destination: Path) -> None:
    atomic_write_json(destination, document.to_dict())


def load_review_queue_document(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_url_review_document(document: UrlReviewDocument, destination: Path) -> None:
    atomic_write_json(destination, document.to_dict())


def load_url_review_document(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_enriched_snapshot_document(
    snapshot_document: dict,
    review_document: dict,
) -> EnrichedSnapshotDocument:
    review_index = _url_review_index(review_document)
    bookmarks = []
    for bookmark in snapshot_document.get("bookmarks", []):
        bookmark_id = str(bookmark.get("id", ""))
        normalized_url = str(bookmark.get("normalized_url") or bookmark.get("url") or "")
        review_payload = review_index.get((bookmark_id, normalized_url), {})
        default_review_status, default_review_method = _default_review_state(str(bookmark.get("url", "")))
        bookmarks.append(
            EnrichedSnapshotBookmarkRecord(
                id=bookmark_id,
                title=str(bookmark.get("title", "")),
                url=str(bookmark.get("url", "")),
                normalized_url=normalized_url,
                domain=str(bookmark.get("domain", "")),
                folder_id=str(bookmark.get("folder_id", "")),
                folder_path=str(bookmark.get("folder_path", "")),
                top_level_folder=bookmark.get("top_level_folder"),
                root_key=str(bookmark.get("root_key", "")),
                path=str(bookmark.get("path", "")),
                depth=int(bookmark.get("depth", 0)),
                review_status=str(review_payload.get("review_status", default_review_status)),
                review_method=str(review_payload.get("review_method", default_review_method)),
                final_url=str(review_payload.get("final_url", "")),
                page_title=str(review_payload.get("page_title", "")),
                meta_description=str(review_payload.get("meta_description", "")),
                site_name=str(review_payload.get("site_name", "")),
                h1=str(review_payload.get("h1", "")),
                content_kind=str(review_payload.get("content_kind", "unknown")),
                one_line_summary=str(review_payload.get("one_line_summary", "")),
                review_confidence=float(review_payload.get("review_confidence", 0.0)),
                review_notes=str(review_payload.get("notes", "")),
            )
        )
    return EnrichedSnapshotDocument(
        snapshot_version="2",
        source=str(snapshot_document.get("source", "edge-file")),
        source_path=str(snapshot_document.get("source_path", "")),
        created_at=datetime.now().isoformat(timespec="seconds"),
        source_snapshot=str(snapshot_document.get("source_path", "")),
        review_source=str(review_document.get("source_snapshot", "")),
        folders=[
            SnapshotFolderRecord(
                id=str(folder.get("id", "")),
                name=str(folder.get("name", "")),
                path=str(folder.get("path", "")),
                parent_path=folder.get("parent_path"),
                root_key=str(folder.get("root_key", "")),
                depth=int(folder.get("depth", 0)),
                bookmark_count=int(folder.get("bookmark_count", 0)),
                subfolder_count=int(folder.get("subfolder_count", 0)),
            )
            for folder in snapshot_document.get("folders", [])
        ],
        bookmarks=bookmarks,
    )


def write_enriched_snapshot_document(document: EnrichedSnapshotDocument, destination: Path) -> None:
    atomic_write_json(destination, document.to_dict())


def url_requires_review(url: str) -> bool:
    parsed = urlsplit(url.strip())
    scheme = (parsed.scheme or "").lower()
    hostname = (parsed.hostname or "").lower()
    if scheme in {"file", "edge", "chrome", "about", "javascript", "data"}:
        return False
    if not hostname or hostname == "localhost":
        return False
    try:
        ipaddress.ip_address(hostname)
        return False
    except ValueError:
        pass
    if hostname.endswith(".local"):
        return False
    if "." not in hostname:
        return False
    return True


def diff_snapshot_documents(before: dict, after: dict) -> dict:
    before_bookmarks = _bookmark_index(before)
    after_bookmarks = _bookmark_index(after)

    moved = []
    unchanged = 0
    removed = []
    added = []

    for key, before_item in before_bookmarks.items():
        after_item = after_bookmarks.get(key)
        if not after_item:
            removed.append(_bookmark_diff_row(before_item))
            continue
        if before_item["folder_path"] != after_item["folder_path"]:
            moved.append(
                {
                    "title": before_item["title"],
                    "normalized_url": before_item["normalized_url"],
                    "from_path": before_item["folder_path"],
                    "to_path": after_item["folder_path"],
                }
            )
        else:
            unchanged += 1

    for key, after_item in after_bookmarks.items():
        if key not in before_bookmarks:
            added.append(_bookmark_diff_row(after_item))

    return {
        "before_created_at": before.get("created_at", ""),
        "after_created_at": after.get("created_at", ""),
        "moved_bookmarks": moved,
        "removed_bookmarks": removed,
        "added_bookmarks": added,
        "unchanged_bookmarks": unchanged,
    }


def _bookmark_index(document: dict) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for bookmark in document.get("bookmarks", []):
        normalized_url = bookmark.get("normalized_url") or bookmark.get("url") or ""
        key = f"{normalized_url}::{bookmark.get('title','')}"
        index[key] = bookmark
    return index


def _bookmark_diff_row(bookmark: dict) -> dict:
    return {
        "title": bookmark.get("title", ""),
        "normalized_url": bookmark.get("normalized_url", ""),
        "folder_path": bookmark.get("folder_path", ""),
    }


def _url_review_index(review_document: dict) -> dict[tuple[str, str], dict]:
    index: dict[tuple[str, str], dict] = {}
    for item in review_document.get("items", []):
        bookmark_id = str(item.get("bookmark_id", ""))
        normalized_url = str(item.get("normalized_url") or item.get("url") or "")
        if bookmark_id and normalized_url:
            index[(bookmark_id, normalized_url)] = item
    return index


def _default_review_state(url: str) -> tuple[str, str]:
    if url_requires_review(url):
        return "missing", ""
    return "skipped_internal", "system_skip"
