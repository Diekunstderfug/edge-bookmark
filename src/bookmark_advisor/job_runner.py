from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from bookmark_advisor.ai_planner import finalize_draft_plan, plan_with_openai, write_semantic_plan
from bookmark_advisor.backup import create_backup
from bookmark_advisor.executor import apply_reviewed_semantic_plan
from bookmark_advisor.models import ReorgExecutionConfig, ReorgJob, ReorgJobState
from bookmark_advisor.parser import load_snapshot
from bookmark_advisor.rules import resolve_rules_path
from bookmark_advisor.snapshot_io import (
    build_enriched_snapshot_document,
    build_review_queue_document,
    build_snapshot_document,
    load_review_queue_document,
    load_snapshot_document,
    load_url_review_document,
    write_enriched_snapshot_document,
    write_review_queue_document,
    write_snapshot_document,
)

PHASES = ("snapshot", "review", "enrich", "plan", "finalize", "apply", "done")
EXECUTION_BACKENDS = {"extension", "write_source"}


def init_reorg_job(
    workspace: Path,
    source_bookmarks_path: Path,
    rules_path: Path | None = None,
    primary_backend: str = "extension",
    fallback_backend: str | None = "write_source",
    allow_write_source: bool = False,
    job_path: Path | None = None,
) -> tuple[ReorgJob, Path]:
    workspace = workspace.resolve()
    source_bookmarks_path = source_bookmarks_path.expanduser().resolve()
    resolved_rules = resolve_rules_path(rules_path=rules_path, workspace=workspace)
    _validate_backend(primary_backend)
    if fallback_backend:
        _validate_backend(fallback_backend)

    if job_path is None:
        job_dir = workspace / "data" / "jobs" / f"reorg_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        manifest_path = job_dir / "reorg-job.json"
    else:
        manifest_path = job_path.expanduser().resolve()
        job_dir = manifest_path.parent

    job = ReorgJob(
        job_version="1",
        workspace=str(workspace),
        source_bookmarks_path=str(source_bookmarks_path),
        rules_path=str(resolved_rules),
        snapshot_path=str(job_dir / "snapshot.json"),
        review_queue_path=str(job_dir / "review-queue.json"),
        url_review_path=str(job_dir / "url-review.json"),
        enriched_snapshot_path=str(job_dir / "enriched-snapshot.json"),
        draft_plan_path=str(job_dir / "draft-plan.json"),
        reviewed_plan_path=str(job_dir / "reviewed-plan.json"),
        execution=ReorgExecutionConfig(
            primary_backend=primary_backend,
            fallback_backend=fallback_backend,
            allow_write_source=allow_write_source,
        ),
        state=ReorgJobState(
            current_phase="snapshot",
            completed_phases=[],
            last_artifact="",
        ),
    )
    write_reorg_job(job, manifest_path)
    return job, manifest_path


def write_reorg_job(job: ReorgJob, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(job.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_reorg_job(path: Path) -> ReorgJob:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return reorg_job_from_dict(payload)


def reorg_job_from_dict(payload: dict[str, Any]) -> ReorgJob:
    execution_payload = payload.get("execution") or {}
    state_payload = payload.get("state") or {}
    return ReorgJob(
        job_version=str(payload.get("job_version", "1")),
        workspace=str(payload.get("workspace", "")),
        source_bookmarks_path=str(payload.get("source_bookmarks_path", "")),
        rules_path=str(payload.get("rules_path", "")),
        snapshot_path=str(payload.get("snapshot_path", "")),
        review_queue_path=str(payload.get("review_queue_path", "")),
        url_review_path=str(payload.get("url_review_path", "")),
        enriched_snapshot_path=str(payload.get("enriched_snapshot_path", "")),
        draft_plan_path=str(payload.get("draft_plan_path", "")),
        reviewed_plan_path=str(payload.get("reviewed_plan_path", "")),
        execution=ReorgExecutionConfig(
            primary_backend=str(execution_payload.get("primary_backend", "extension")),
            fallback_backend=(
                str(execution_payload["fallback_backend"])
                if execution_payload.get("fallback_backend") is not None
                else None
            ),
            allow_write_source=bool(execution_payload.get("allow_write_source", False)),
        ),
        state=ReorgJobState(
            current_phase=str(state_payload.get("current_phase", "snapshot")),
            completed_phases=list(state_payload.get("completed_phases", [])),
            last_artifact=str(state_payload.get("last_artifact", "")),
        ),
    )


def run_reorg_job(
    job_path: Path,
    model: str = "gpt-4o-mini",
    max_actions: int = 40,
    api_style: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    manifest_path = job_path.expanduser().resolve()
    job = load_reorg_job(manifest_path)
    latest_message = ""

    while job.state.current_phase != "done":
        if job.state.current_phase == "snapshot":
            snapshot = load_snapshot(Path(job.source_bookmarks_path))
            snapshot_document = build_snapshot_document(snapshot)
            write_snapshot_document(snapshot_document, Path(job.snapshot_path))
            review_queue = build_review_queue_document(snapshot_document.to_dict())
            write_review_queue_document(review_queue, Path(job.review_queue_path))
            job = _advance_job(
                job,
                completed_phase="snapshot",
                next_phase="review",
                last_artifact=job.review_queue_path,
            )
            latest_message = "snapshot exported and review queue generated"
            continue

        if job.state.current_phase == "review":
            if not Path(job.url_review_path).exists():
                write_reorg_job(job, manifest_path)
                return {
                    "job_path": str(manifest_path),
                    "current_phase": job.state.current_phase,
                    "status": "waiting_for_review",
                    "message": "URL review file not found; waiting for bookmark-url-review output.",
                    "last_artifact": job.state.last_artifact,
                }
            load_review_queue_document(Path(job.review_queue_path))
            load_url_review_document(Path(job.url_review_path))
            job = _advance_job(
                job,
                completed_phase="review",
                next_phase="enrich",
                last_artifact=job.url_review_path,
            )
            latest_message = "url review file detected"
            continue

        if job.state.current_phase == "enrich":
            snapshot_payload = load_snapshot_document(Path(job.snapshot_path))
            review_payload = load_url_review_document(Path(job.url_review_path))
            enriched_document = build_enriched_snapshot_document(snapshot_payload, review_payload)
            write_enriched_snapshot_document(enriched_document, Path(job.enriched_snapshot_path))
            job = _advance_job(
                job,
                completed_phase="enrich",
                next_phase="plan",
                last_artifact=job.enriched_snapshot_path,
            )
            latest_message = "enriched snapshot written"
            continue

        if job.state.current_phase == "plan":
            from bookmark_advisor.rules import load_rules

            rules = load_rules(Path(job.rules_path))
            enriched_snapshot = load_snapshot_document(Path(job.enriched_snapshot_path))
            draft_plan = plan_with_openai(
                snapshot_document=enriched_snapshot,
                rules=rules,
                model=model,
                max_actions=max_actions,
                api_style=api_style,
                base_url=base_url,
            )
            write_semantic_plan(draft_plan, Path(job.draft_plan_path))
            job = _advance_job(
                job,
                completed_phase="plan",
                next_phase="finalize",
                last_artifact=job.draft_plan_path,
            )
            latest_message = "draft semantic plan generated"
            continue

        if job.state.current_phase == "finalize":
            draft_payload = json.loads(Path(job.draft_plan_path).read_text(encoding="utf-8"))
            reviewed_plan = finalize_draft_plan(draft_payload)
            write_semantic_plan(reviewed_plan, Path(job.reviewed_plan_path))
            job = _advance_job(
                job,
                completed_phase="finalize",
                next_phase="apply",
                last_artifact=job.reviewed_plan_path,
            )
            latest_message = "reviewed plan generated"
            continue

        if job.state.current_phase == "apply":
            if job.execution.primary_backend == "extension":
                job = _advance_job(
                    job,
                    completed_phase="apply",
                    next_phase="done",
                    last_artifact=job.reviewed_plan_path,
                )
                latest_message = "reviewed plan ready for Edge extension import"
                continue

            if job.execution.primary_backend == "write_source":
                if not job.execution.allow_write_source:
                    raise ValueError("write_source backend requires execution.allow_write_source=true")
                create_backup(
                    Path(job.source_bookmarks_path),
                    Path(job.workspace) / "data" / "backups",
                )
                apply_reviewed_semantic_plan(
                    reviewed_plan_payload=json.loads(
                        Path(job.reviewed_plan_path).read_text(encoding="utf-8")
                    ),
                    source_path=Path(job.source_bookmarks_path),
                    destination=Path(job.source_bookmarks_path),
                    write_source=True,
                )
                job = _advance_job(
                    job,
                    completed_phase="apply",
                    next_phase="done",
                    last_artifact=job.source_bookmarks_path,
                )
                latest_message = "reviewed plan applied to source bookmarks"
                continue

            raise ValueError(f"Unsupported primary backend: {job.execution.primary_backend}")

        raise ValueError(f"Unknown job phase: {job.state.current_phase}")

    write_reorg_job(job, manifest_path)
    return {
        "job_path": str(manifest_path),
        "current_phase": job.state.current_phase,
        "status": "done",
        "message": latest_message or "job completed",
        "last_artifact": job.state.last_artifact,
        "primary_backend": job.execution.primary_backend,
    }


def _advance_job(
    job: ReorgJob,
    completed_phase: str,
    next_phase: str,
    last_artifact: str,
) -> ReorgJob:
    completed_phases = list(job.state.completed_phases)
    if completed_phase not in completed_phases:
        completed_phases.append(completed_phase)
    return replace(
        job,
        state=ReorgJobState(
            current_phase=next_phase,
            completed_phases=completed_phases,
            last_artifact=last_artifact,
        ),
    )


def _validate_backend(backend: str) -> None:
    if backend not in EXECUTION_BACKENDS:
        supported = ", ".join(sorted(EXECUTION_BACKENDS))
        raise ValueError(f"unsupported execution backend '{backend}'. Expected one of: {supported}")
