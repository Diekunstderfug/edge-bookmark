from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bookmark_advisor.models import BookmarkItem, FolderItem
from bookmark_advisor.utils import extract_domain, normalize_url


@dataclass
class BookmarkSnapshot:
    source_path: Path
    raw_data: dict[str, Any]
    folders: dict[str, FolderItem]
    bookmarks: dict[str, BookmarkItem]
    folder_children: dict[str, list[str]]
    root_folder_ids: dict[str, str]
    root_display_names: dict[str, str]
    folder_paths: dict[str, str]

    def get_folder(self, folder_id: str) -> FolderItem:
        return self.folders[folder_id]

    def bookmarks_in_folder(self, folder_id: str) -> list[BookmarkItem]:
        return [bookmark for bookmark in self.bookmarks.values() if bookmark.folder_id == folder_id]

    def find_folder_by_path(self, path: str) -> FolderItem | None:
        folder_id = self.folder_paths.get(path)
        if not folder_id:
            return None
        return self.folders[folder_id]


def load_snapshot(source_path: Path) -> BookmarkSnapshot:
    raw_data = json.loads(source_path.read_text(encoding="utf-8"))
    folders: dict[str, FolderItem] = {}
    bookmarks: dict[str, BookmarkItem] = {}
    folder_children: dict[str, list[str]] = {}
    root_folder_ids: dict[str, str] = {}
    root_display_names: dict[str, str] = {}
    folder_paths: dict[str, str] = {}

    roots = raw_data.get("roots", {})
    for root_key, root_node in roots.items():
        root_name = root_node.get("name") or root_key
        root_id = f"root:{root_key}"
        root_path = f"/{root_name}"
        root_folder = FolderItem(
            id=root_id,
            name=root_name,
            path=root_path,
            root_key=root_key,
            parent_id=None,
            depth=0,
        )
        folders[root_id] = root_folder
        folder_children[root_id] = []
        root_folder_ids[root_key] = root_id
        root_display_names[root_key] = root_name
        folder_paths[root_path] = root_id
        for child in root_node.get("children", []) or []:
            _walk_node(
                node=child,
                root_key=root_key,
                parent_folder=root_folder,
                top_level_folder=None,
                folders=folders,
                bookmarks=bookmarks,
                folder_children=folder_children,
                folder_paths=folder_paths,
            )

    for folder_id, child_ids in folder_children.items():
        folder = folders[folder_id]
        folder.subfolder_count = sum(1 for child_id in child_ids if child_id in folders)
        folder.bookmark_count = sum(1 for child_id in child_ids if child_id in bookmarks)

    return BookmarkSnapshot(
        source_path=source_path,
        raw_data=raw_data,
        folders=folders,
        bookmarks=bookmarks,
        folder_children=folder_children,
        root_folder_ids=root_folder_ids,
        root_display_names=root_display_names,
        folder_paths=folder_paths,
    )


def _walk_node(
    node: dict[str, Any],
    root_key: str,
    parent_folder: FolderItem,
    top_level_folder: str | None,
    folders: dict[str, FolderItem],
    bookmarks: dict[str, BookmarkItem],
    folder_children: dict[str, list[str]],
    folder_paths: dict[str, str],
) -> None:
    node_type = node.get("type")
    node_id = str(node.get("id"))
    node_name = node.get("name") or ""
    if node_type == "folder":
        folder_path = f"{parent_folder.path}/{node_name}" if parent_folder.path != "/" else f"/{node_name}"
        folder = FolderItem(
            id=node_id,
            name=node_name,
            path=folder_path,
            root_key=root_key,
            parent_id=parent_folder.id,
            depth=parent_folder.depth + 1,
        )
        folders[node_id] = folder
        folder_paths[folder_path] = node_id
        folder_children[node_id] = []
        folder_children[parent_folder.id].append(node_id)
        inherited_top = top_level_folder or node_name
        for child in node.get("children", []) or []:
            _walk_node(
                node=child,
                root_key=root_key,
                parent_folder=folder,
                top_level_folder=inherited_top,
                folders=folders,
                bookmarks=bookmarks,
                folder_children=folder_children,
                folder_paths=folder_paths,
            )
        return

    if node_type == "url":
        title = node_name or "(untitled)"
        url = node.get("url") or ""
        bookmark = BookmarkItem(
            id=node_id,
            title=title,
            url=url,
            normalized_url=normalize_url(url),
            domain=extract_domain(url),
            folder_id=parent_folder.id,
            folder_path=parent_folder.path,
            top_level_folder=top_level_folder,
            root_key=root_key,
            path=f"{parent_folder.path}/{title}",
            depth=parent_folder.depth + 1,
        )
        bookmarks[node_id] = bookmark
        folder_children[parent_folder.id].append(node_id)
