from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FolderItem:
    id: str
    name: str
    path: str
    root_key: str
    parent_id: str | None
    depth: int
    bookmark_count: int = 0
    subfolder_count: int = 0


@dataclass
class BookmarkItem:
    id: str
    title: str
    url: str
    normalized_url: str
    domain: str
    folder_id: str
    folder_path: str
    top_level_folder: str | None
    root_key: str
    path: str
    depth: int


@dataclass
class FolderProfile:
    folder_id: str
    path: str
    name: str
    depth: int
    bookmark_count: int
    domain_counts: dict[str, int]
    token_counts: dict[str, int]


@dataclass
class AnalysisSummary:
    total_bookmarks: int
    total_folders: int
    root_loose_bookmarks: int
    empty_folder_ids: list[str]
    clutter_folder_ids: list[str]
    singleton_folder_ids: list[str]
    duplicate_groups: list[list[str]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlanAction:
    action_type: str
    reason: str
    confidence: float
    bookmark_id: str | None = None
    folder_id: str | None = None
    from_path: str | None = None
    to_path: str | None = None
    target_path: str | None = None
    duplicate_of: str | None = None
    folder_name: str | None = None
    to_name: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Plan:
    mode: str
    source_path: str
    backup_path: str
    created_at: str
    summary: dict[str, Any]
    actions: list[PlanAction]
    report_path: str
    output_path: str | None = None
    plan_version: str = "1"
    executor: str = "edge-extension"
    source: str = "bookmark-advisor"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["actions"] = [action.to_dict() for action in self.actions]
        return payload


@dataclass
class RunArtifacts:
    backup_path: Path
    plan_path: Path
    report_path: Path
    output_path: Path | None = None


@dataclass
class SnapshotFolderRecord:
    id: str
    name: str
    path: str
    parent_path: str | None
    root_key: str
    depth: int
    bookmark_count: int
    subfolder_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SnapshotBookmarkRecord:
    id: str
    title: str
    url: str
    normalized_url: str
    domain: str
    folder_id: str
    folder_path: str
    top_level_folder: str | None
    root_key: str
    path: str
    depth: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SnapshotDocument:
    snapshot_version: str
    source: str
    source_path: str
    created_at: str
    folders: list[SnapshotFolderRecord]
    bookmarks: list[SnapshotBookmarkRecord]

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_version": self.snapshot_version,
            "source": self.source,
            "source_path": self.source_path,
            "created_at": self.created_at,
            "folders": [folder.to_dict() for folder in self.folders],
            "bookmarks": [bookmark.to_dict() for bookmark in self.bookmarks],
        }


@dataclass
class ReviewQueueItem:
    bookmark_id: str
    title: str
    url: str
    normalized_url: str
    folder_path: str
    top_level_folder: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewQueueDocument:
    queue_version: str
    created_at: str
    source_snapshot: str
    items: list[ReviewQueueItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_version": self.queue_version,
            "created_at": self.created_at,
            "source_snapshot": self.source_snapshot,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass
class UrlReviewItem:
    bookmark_id: str
    url: str
    normalized_url: str
    folder_path: str
    review_status: str
    review_method: str
    final_url: str = ""
    page_title: str = ""
    meta_description: str = ""
    site_name: str = ""
    h1: str = ""
    content_kind: str = "unknown"
    one_line_summary: str = ""
    review_confidence: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UrlReviewDocument:
    review_version: str
    created_at: str
    source_snapshot: str
    items: list[UrlReviewItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_version": self.review_version,
            "created_at": self.created_at,
            "source_snapshot": self.source_snapshot,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass
class EnrichedSnapshotBookmarkRecord:
    id: str
    title: str
    url: str
    normalized_url: str
    domain: str
    folder_id: str
    folder_path: str
    top_level_folder: str | None
    root_key: str
    path: str
    depth: int
    review_status: str = ""
    review_method: str = ""
    final_url: str = ""
    page_title: str = ""
    meta_description: str = ""
    site_name: str = ""
    h1: str = ""
    content_kind: str = "unknown"
    one_line_summary: str = ""
    review_confidence: float = 0.0
    review_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EnrichedSnapshotDocument:
    snapshot_version: str
    source: str
    source_path: str
    created_at: str
    source_snapshot: str
    review_source: str
    folders: list[SnapshotFolderRecord]
    bookmarks: list[EnrichedSnapshotBookmarkRecord]

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_version": self.snapshot_version,
            "source": self.source,
            "source_path": self.source_path,
            "created_at": self.created_at,
            "source_snapshot": self.source_snapshot,
            "review_source": self.review_source,
            "folders": [folder.to_dict() for folder in self.folders],
            "bookmarks": [bookmark.to_dict() for bookmark in self.bookmarks],
        }


@dataclass
class ReorgExecutionConfig:
    primary_backend: str
    fallback_backend: str | None
    allow_write_source: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReorgJobState:
    current_phase: str
    completed_phases: list[str]
    last_artifact: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReorgJob:
    job_version: str
    workspace: str
    source_bookmarks_path: str
    rules_path: str
    snapshot_path: str
    review_queue_path: str
    url_review_path: str
    enriched_snapshot_path: str
    draft_plan_path: str
    reviewed_plan_path: str
    execution: ReorgExecutionConfig
    state: ReorgJobState

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_version": self.job_version,
            "workspace": self.workspace,
            "source_bookmarks_path": self.source_bookmarks_path,
            "rules_path": self.rules_path,
            "snapshot_path": self.snapshot_path,
            "review_queue_path": self.review_queue_path,
            "url_review_path": self.url_review_path,
            "enriched_snapshot_path": self.enriched_snapshot_path,
            "draft_plan_path": self.draft_plan_path,
            "reviewed_plan_path": self.reviewed_plan_path,
            "execution": self.execution.to_dict(),
            "state": self.state.to_dict(),
        }


@dataclass
class BookmarkLocator:
    id: str = ""
    title: str = ""
    url: str = ""
    normalized_url: str = ""
    folder_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FolderLocator:
    id: str = ""
    name: str = ""
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SemanticAction:
    action_id: str
    action_type: str
    status: str
    reason: str
    confidence: float
    bookmark_locator: BookmarkLocator = field(default_factory=BookmarkLocator)
    folder_locator: FolderLocator = field(default_factory=FolderLocator)
    from_path: str = ""
    to_path: str = ""
    target_path: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bookmark_locator"] = self.bookmark_locator.to_dict()
        payload["folder_locator"] = self.folder_locator.to_dict()
        return payload


@dataclass
class SemanticPlan:
    plan_version: str
    plan_kind: str
    source: str
    created_at: str
    source_snapshot: str
    rules_source: str
    model: str
    summary: dict[str, Any]
    actions: list[SemanticAction]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_version": self.plan_version,
            "plan_kind": self.plan_kind,
            "source": self.source,
            "created_at": self.created_at,
            "source_snapshot": self.source_snapshot,
            "rules_source": self.rules_source,
            "model": self.model,
            "summary": self.summary,
            "actions": [action.to_dict() for action in self.actions],
        }
