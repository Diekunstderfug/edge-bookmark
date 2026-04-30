from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from bookmark_advisor import DEFAULT_EDGE_BOOKMARKS
from bookmark_advisor.ai_planner import (
    AIPlannerError,
    finalize_draft_plan,
    load_semantic_plan,
    plan_with_openai,
    write_semantic_plan,
)
from bookmark_advisor.backup import create_backup
from bookmark_advisor.executor import apply_plan
from bookmark_advisor.job_runner import (
    init_reorg_job,
    run_reorg_job,
)
from bookmark_advisor.models import Plan
from bookmark_advisor.parser import load_snapshot
from bookmark_advisor.planner import build_advise_plan, build_merge_plan
from bookmark_advisor.reporting import write_plan, write_report
from bookmark_advisor.rules import RulesValidationError, load_rules, validate_rules_file
from bookmark_advisor.snapshot_io import (
    build_enriched_snapshot_document,
    build_review_queue_document,
    build_snapshot_document,
    diff_snapshot_documents,
    load_review_queue_document,
    load_snapshot_document,
    load_url_review_document,
    write_enriched_snapshot_document,
    write_review_queue_document,
    write_snapshot_document,
)
from bookmark_advisor.utils import slugify


def main() -> int:
    parser = argparse.ArgumentParser(prog="bookmark-advisor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("backup", "advise", "merge"):
        command = subparsers.add_parser(name)
        command.add_argument("--input", default=DEFAULT_EDGE_BOOKMARKS)
        command.add_argument("--workspace", default=".")
        if name in ("advise", "merge"):
            command.add_argument("--rules")
            command.add_argument("--apply", action="store_true")
            command.add_argument("--write-source", action="store_true")

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--plan", required=True)
    apply_parser.add_argument("--workspace", default=".")
    apply_parser.add_argument("--write-source", action="store_true")

    validate_parser = subparsers.add_parser("validate-rules")
    validate_parser.add_argument("--rules", required=True)

    export_snapshot_parser = subparsers.add_parser("export-snapshot")
    export_snapshot_parser.add_argument("--input", default=DEFAULT_EDGE_BOOKMARKS)
    export_snapshot_parser.add_argument("--out")
    export_snapshot_parser.add_argument("--workspace", default=".")

    init_job_parser = subparsers.add_parser("init-job")
    init_job_parser.add_argument("--input", default=DEFAULT_EDGE_BOOKMARKS)
    init_job_parser.add_argument("--rules")
    init_job_parser.add_argument("--workspace", default=".")
    init_job_parser.add_argument("--out")
    init_job_parser.add_argument("--primary-backend", default="extension")
    init_job_parser.add_argument("--fallback-backend", default="write_source")
    init_job_parser.add_argument("--allow-write-source", action="store_true")

    build_review_queue_parser = subparsers.add_parser("build-review-queue")
    build_review_queue_parser.add_argument("--snapshot", required=True)
    build_review_queue_parser.add_argument("--out")
    build_review_queue_parser.add_argument("--workspace", default=".")

    enrich_snapshot_parser = subparsers.add_parser("enrich-snapshot")
    enrich_snapshot_parser.add_argument("--snapshot", required=True)
    enrich_snapshot_parser.add_argument("--reviews", required=True)
    enrich_snapshot_parser.add_argument("--out")
    enrich_snapshot_parser.add_argument("--workspace", default=".")

    plan_ai_parser = subparsers.add_parser("plan-ai")
    plan_ai_parser.add_argument("--snapshot", required=True)
    plan_ai_parser.add_argument("--rules")
    plan_ai_parser.add_argument("--out")
    plan_ai_parser.add_argument("--workspace", default=".")
    plan_ai_parser.add_argument("--model", default="gpt-4o-mini")
    plan_ai_parser.add_argument("--max-actions", type=int, default=40)
    plan_ai_parser.add_argument("--base-url")
    plan_ai_parser.add_argument(
        "--api-style",
        choices=("auto", "responses", "chat_completions", "chat-completions"),
    )

    finalize_parser = subparsers.add_parser("finalize-plan")
    finalize_parser.add_argument("--input", required=True)
    finalize_parser.add_argument("--out")
    finalize_parser.add_argument("--workspace", default=".")
    finalize_parser.add_argument("--auto-approve-threshold", type=float, default=0.85)

    diff_parser = subparsers.add_parser("diff-snapshot")
    diff_parser.add_argument("--before", required=True)
    diff_parser.add_argument("--after", required=True)
    diff_parser.add_argument("--out")
    diff_parser.add_argument("--workspace", default=".")

    run_job_parser = subparsers.add_parser("run-job")
    run_job_parser.add_argument("--job", required=True)
    run_job_parser.add_argument("--model", default="gpt-4o-mini")
    run_job_parser.add_argument("--max-actions", type=int, default=40)
    run_job_parser.add_argument("--base-url")
    run_job_parser.add_argument(
        "--api-style",
        choices=("auto", "responses", "chat_completions", "chat-completions"),
    )

    args = parser.parse_args()

    if args.command == "backup":
        workspace = Path(args.workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        source_path = Path(args.input).expanduser()
        backup_path = create_backup(source_path, workspace / "data" / "backups")
        print(backup_path)
        return 0

    if args.command in {"advise", "merge"}:
        workspace = Path(args.workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            rules = load_rules(
                rules_path=Path(args.rules).expanduser() if args.rules else None,
                workspace=workspace,
            )
        except RulesValidationError as exc:
            for error in exc.errors:
                print(error, file=sys.stderr)
            return 1
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1
        source_path = Path(args.input).expanduser()
        backup_path = create_backup(source_path, workspace / "data" / "backups")
        snapshot = load_snapshot(source_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{args.command}_{timestamp}"
        plan_path = workspace / "data" / "plans" / f"{base_name}.json"
        report_path = workspace / "data" / "reports" / f"{base_name}.md"
        if args.command == "advise":
            plan = build_advise_plan(snapshot, backup_path, report_path, rules)
        else:
            plan = build_merge_plan(snapshot, backup_path, report_path, rules)
        write_plan(plan, plan_path)
        write_report(plan, snapshot, report_path)
        print(f"backup={backup_path}")
        print(f"plan={plan_path}")
        print(f"report={report_path}")
        print(f"rules={rules.source_path}")
        print(f"actions={len(plan.actions)}")
        if args.apply:
            output_path = workspace / "data" / "output" / f"{base_name}_applied.json"
            applied_path = apply_plan(plan, output_path, write_source=args.write_source)
            if args.write_source:
                print("mode=fallback-debug-write-source")
            print(f"applied={applied_path}")
        return 0

    if args.command == "apply":
        workspace = Path(args.workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        plan_path = Path(args.plan).expanduser()
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
        plan = Plan(
            mode=payload["mode"],
            source_path=payload["source_path"],
            backup_path=payload["backup_path"],
            created_at=payload["created_at"],
            summary=payload["summary"],
            actions=[
                _plan_action_from_dict(action_payload)
                for action_payload in payload["actions"]
            ],
            report_path=payload["report_path"],
            output_path=payload.get("output_path"),
            plan_version=str(payload.get("plan_version", "1")),
            executor=str(payload.get("executor", "edge-extension")),
            source=str(payload.get("source", "bookmark-advisor")),
        )
        output_name = slugify(plan.mode) + "_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
        destination = workspace / "data" / "output" / output_name
        applied_path = apply_plan(plan, destination, write_source=args.write_source)
        print(applied_path)
        return 0

    if args.command == "validate-rules":
        rules_path = Path(args.rules).expanduser()
        errors = validate_rules_file(rules_path)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print(f"valid={rules_path.resolve()}")
        return 0

    if args.command == "export-snapshot":
        workspace = Path(args.workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        source_path = Path(args.input).expanduser()
        snapshot = load_snapshot(source_path)
        document = build_snapshot_document(snapshot)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = (
            Path(args.out).expanduser()
            if args.out
            else workspace / "data" / "snapshots" / f"snapshot_{timestamp}.json"
        )
        write_snapshot_document(document, destination)
        print(destination)
        return 0

    if args.command == "init-job":
        workspace = Path(args.workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            _job, destination = init_reorg_job(
                workspace=workspace,
                source_bookmarks_path=Path(args.input).expanduser(),
                rules_path=Path(args.rules).expanduser() if args.rules else None,
                primary_backend=args.primary_backend,
                fallback_backend=args.fallback_backend or None,
                allow_write_source=args.allow_write_source,
                job_path=Path(args.out).expanduser() if args.out else None,
            )
        except (RulesValidationError, FileNotFoundError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(destination)
        return 0

    if args.command == "build-review-queue":
        workspace = Path(args.workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        snapshot_payload = load_snapshot_document(Path(args.snapshot).expanduser())
        queue_document = build_review_queue_document(snapshot_payload)
        destination = (
            Path(args.out).expanduser()
            if args.out
            else workspace / "data" / "reviews" / f"review_queue_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        write_review_queue_document(queue_document, destination)
        print(destination)
        return 0

    if args.command == "enrich-snapshot":
        workspace = Path(args.workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            snapshot_payload = load_snapshot_document(Path(args.snapshot).expanduser())
            review_payload = load_url_review_document(Path(args.reviews).expanduser())
            enriched_document = build_enriched_snapshot_document(snapshot_payload, review_payload)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        destination = (
            Path(args.out).expanduser()
            if args.out
            else workspace / "data" / "snapshots" / f"enriched_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        write_enriched_snapshot_document(enriched_document, destination)
        print(destination)
        return 0

    if args.command == "plan-ai":
        workspace = Path(args.workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            rules = load_rules(
                rules_path=Path(args.rules).expanduser() if args.rules else None,
                workspace=workspace,
            )
            snapshot_payload = load_snapshot_document(Path(args.snapshot).expanduser())
            plan = plan_with_openai(
                snapshot_document=snapshot_payload,
                rules=rules,
                model=args.model,
                max_actions=args.max_actions,
                api_style=args.api_style,
                base_url=args.base_url,
            )
        except (RulesValidationError, AIPlannerError, FileNotFoundError, json.JSONDecodeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        destination = (
            Path(args.out).expanduser()
            if args.out
            else workspace / "data" / "plans" / f"draft_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        write_semantic_plan(plan, destination)
        print(destination)
        return 0

    if args.command == "finalize-plan":
        workspace = Path(args.workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            draft_payload = load_semantic_plan(Path(args.input).expanduser())
            plan = finalize_draft_plan(
                draft_payload,
                auto_approve_threshold=args.auto_approve_threshold,
            )
        except (AIPlannerError, FileNotFoundError, json.JSONDecodeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        destination = (
            Path(args.out).expanduser()
            if args.out
            else workspace / "data" / "plans" / f"reviewed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        write_semantic_plan(plan, destination)
        print(destination)
        return 0

    if args.command == "diff-snapshot":
        workspace = Path(args.workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        before_payload = load_snapshot_document(Path(args.before).expanduser())
        after_payload = load_snapshot_document(Path(args.after).expanduser())
        diff_payload = diff_snapshot_documents(before_payload, after_payload)
        destination = (
            Path(args.out).expanduser()
            if args.out
            else workspace / "data" / "reports" / f"snapshot_diff_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(diff_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(destination)
        return 0

    if args.command == "run-job":
        try:
            result = run_reorg_job(
                Path(args.job).expanduser(),
                model=args.model,
                max_actions=args.max_actions,
                api_style=args.api_style,
                base_url=args.base_url,
            )
        except (AIPlannerError, FileNotFoundError, json.JSONDecodeError, RulesValidationError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    return 1


def _plan_action_from_dict(payload: dict[str, object]):
    from bookmark_advisor.models import PlanAction

    return PlanAction(
        action_type=str(payload["action_type"]),
        reason=str(payload["reason"]),
        confidence=float(payload["confidence"]),
        bookmark_id=_optional_str(payload.get("bookmark_id")),
        folder_id=_optional_str(payload.get("folder_id")),
        from_path=_optional_str(payload.get("from_path")),
        to_path=_optional_str(payload.get("to_path")),
        target_path=_optional_str(payload.get("target_path")),
        duplicate_of=_optional_str(payload.get("duplicate_of")),
        folder_name=_optional_str(payload.get("folder_name")),
        to_name=_optional_str(payload.get("to_name")),
        details=dict(payload.get("details") or {}),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
