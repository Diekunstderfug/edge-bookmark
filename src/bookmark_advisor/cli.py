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
from bookmark_advisor.models import Plan, PlanAction
from bookmark_advisor.parser import load_snapshot
from bookmark_advisor.planner import build_advise_plan, build_merge_plan
from bookmark_advisor.reporting import write_plan, write_report
from bookmark_advisor.rules import (
    RulesValidationError,
    load_rules,
    validate_rules_file,
    write_fast_rules,
)
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
from bookmark_advisor.utils import atomic_write_json, slugify


def _build_parser() -> argparse.ArgumentParser:
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

    export_fast_rules_parser = subparsers.add_parser("export-fast-rules")
    export_fast_rules_parser.add_argument("--rules")
    export_fast_rules_parser.add_argument("--output")
    export_fast_rules_parser.add_argument("--workspace", default=".")

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
    plan_ai_parser.add_argument("--model", default="gpt-5.4-mini")
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
    run_job_parser.add_argument("--model", default="gpt-5.4-mini")
    run_job_parser.add_argument("--max-actions", type=int, default=40)
    run_job_parser.add_argument("--base-url")
    run_job_parser.add_argument("--allow-write-source", action="store_true")
    run_job_parser.add_argument(
        "--api-style",
        choices=("auto", "responses", "chat_completions", "chat-completions"),
    )

    return parser


def _resolve_workspace(args: argparse.Namespace) -> Path:
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _resolve_destination(out_option: str | None, default: Path) -> Path:
    return Path(out_option).expanduser() if out_option else default


def _load_cli_rules(args: argparse.Namespace, workspace: Path):
    """Load rules for commands with shared error reporting.

    On failure the error is printed to stderr (RulesValidationError lists each
    validation error) and None is returned so the caller can exit with code 1.
    """
    try:
        return load_rules(
            rules_path=Path(args.rules).expanduser() if args.rules else None,
            workspace=workspace,
        )
    except RulesValidationError as exc:
        for error in exc.errors:
            print(error, file=sys.stderr)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
    return None


def _cmd_backup(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args)
    source_path = Path(args.input).expanduser()
    backup_path = create_backup(source_path, workspace / "data" / "backups")
    print(backup_path)
    return 0


def _run_heuristic_plan(args: argparse.Namespace, build_plan) -> int:
    """Shared handler body for the advise and merge commands."""
    workspace = _resolve_workspace(args)
    rules = _load_cli_rules(args, workspace)
    if rules is None:
        return 1
    source_path = Path(args.input).expanduser()
    backup_path = create_backup(source_path, workspace / "data" / "backups")
    snapshot = load_snapshot(source_path)
    timestamp = _timestamp()
    base_name = f"{args.command}_{timestamp}"
    plan_path = workspace / "data" / "plans" / f"{base_name}.json"
    report_path = workspace / "data" / "reports" / f"{base_name}.md"
    plan = build_plan(snapshot, backup_path, report_path, rules)
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


def _cmd_advise(args: argparse.Namespace) -> int:
    return _run_heuristic_plan(args, build_advise_plan)


def _cmd_merge(args: argparse.Namespace) -> int:
    return _run_heuristic_plan(args, build_merge_plan)


def _cmd_apply(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args)
    plan_path = Path(args.plan).expanduser()
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    plan = Plan(
        mode=payload["mode"],
        source_path=payload["source_path"],
        backup_path=payload["backup_path"],
        created_at=payload["created_at"],
        summary=payload["summary"],
        actions=[
            PlanAction.from_payload(action_payload)
            for action_payload in payload["actions"]
        ],
        report_path=payload["report_path"],
        output_path=payload.get("output_path"),
        plan_version=str(payload.get("plan_version", "1")),
        executor=str(payload.get("executor", "edge-extension")),
        source=str(payload.get("source", "bookmark-advisor")),
    )
    output_name = slugify(plan.mode) + "_" + _timestamp() + ".json"
    destination = workspace / "data" / "output" / output_name
    applied_path = apply_plan(plan, destination, write_source=args.write_source)
    print(applied_path)
    return 0


def _cmd_validate_rules(args: argparse.Namespace) -> int:
    rules_path = Path(args.rules).expanduser()
    errors = validate_rules_file(rules_path)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"valid={rules_path.resolve()}")
    return 0


def _cmd_export_fast_rules(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    rules = _load_cli_rules(args, workspace)
    if rules is None:
        return 1
    destination = _resolve_destination(
        args.output,
        workspace / "data" / "generated" / "fast_rules.json",
    )
    write_fast_rules(rules, destination)
    print(f"output={destination}")
    print(f"rules={rules.source_path}")
    return 0


def _cmd_export_snapshot(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args)
    source_path = Path(args.input).expanduser()
    snapshot = load_snapshot(source_path)
    document = build_snapshot_document(snapshot)
    destination = _resolve_destination(
        args.out,
        workspace / "data" / "snapshots" / f"snapshot_{_timestamp()}.json",
    )
    write_snapshot_document(document, destination)
    print(destination)
    return 0


def _cmd_init_job(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args)
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


def _cmd_build_review_queue(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args)
    snapshot_payload = load_snapshot_document(Path(args.snapshot).expanduser())
    queue_document = build_review_queue_document(snapshot_payload)
    destination = _resolve_destination(
        args.out,
        workspace / "data" / "reviews" / f"review_queue_{_timestamp()}.json",
    )
    write_review_queue_document(queue_document, destination)
    print(destination)
    return 0


def _cmd_enrich_snapshot(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args)
    try:
        snapshot_payload = load_snapshot_document(Path(args.snapshot).expanduser())
        review_payload = load_url_review_document(Path(args.reviews).expanduser())
        enriched_document = build_enriched_snapshot_document(snapshot_payload, review_payload)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    destination = _resolve_destination(
        args.out,
        workspace / "data" / "snapshots" / f"enriched_snapshot_{_timestamp()}.json",
    )
    write_enriched_snapshot_document(enriched_document, destination)
    print(destination)
    return 0


def _cmd_plan_ai(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args)
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
    destination = _resolve_destination(
        args.out,
        workspace / "data" / "plans" / f"draft_{_timestamp()}.json",
    )
    write_semantic_plan(plan, destination)
    print(destination)
    return 0


def _cmd_finalize_plan(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args)
    try:
        draft_payload = load_semantic_plan(Path(args.input).expanduser())
        plan = finalize_draft_plan(
            draft_payload,
            auto_approve_threshold=args.auto_approve_threshold,
        )
    except (AIPlannerError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    destination = _resolve_destination(
        args.out,
        workspace / "data" / "plans" / f"reviewed_{_timestamp()}.json",
    )
    write_semantic_plan(plan, destination)
    print(destination)
    return 0


def _cmd_diff_snapshot(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args)
    before_payload = load_snapshot_document(Path(args.before).expanduser())
    after_payload = load_snapshot_document(Path(args.after).expanduser())
    diff_payload = diff_snapshot_documents(before_payload, after_payload)
    destination = _resolve_destination(
        args.out,
        workspace / "data" / "reports" / f"snapshot_diff_{_timestamp()}.json",
    )
    atomic_write_json(destination, diff_payload)
    print(destination)
    return 0


def _cmd_run_job(args: argparse.Namespace) -> int:
    try:
        result = run_reorg_job(
            Path(args.job).expanduser(),
            model=args.model,
            max_actions=args.max_actions,
            api_style=args.api_style,
            base_url=args.base_url,
            allow_write_source=args.allow_write_source,
        )
    except (AIPlannerError, FileNotFoundError, json.JSONDecodeError, RulesValidationError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


_COMMAND_HANDLERS = {
    "backup": _cmd_backup,
    "advise": _cmd_advise,
    "merge": _cmd_merge,
    "apply": _cmd_apply,
    "validate-rules": _cmd_validate_rules,
    "export-fast-rules": _cmd_export_fast_rules,
    "export-snapshot": _cmd_export_snapshot,
    "init-job": _cmd_init_job,
    "build-review-queue": _cmd_build_review_queue,
    "enrich-snapshot": _cmd_enrich_snapshot,
    "plan-ai": _cmd_plan_ai,
    "finalize-plan": _cmd_finalize_plan,
    "diff-snapshot": _cmd_diff_snapshot,
    "run-job": _cmd_run_job,
}


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    handler = _COMMAND_HANDLERS.get(args.command)
    if handler is None:
        return 1
    return handler(args)
