# src/bookmark_advisor/

Python CLI package for bookmark snapshot export, AI/heuristic planning, job orchestration, and plan execution. setuptools src-layout, single dependency (`openai`).

## WHERE TO LOOK

| Task | File | Key Functions |
|------|------|---------------|
| CLI dispatch | `cli.py` | `main()` — argparse subparsers, one per command |
| Data models | `models.py` | `PlanAction`, `SemanticPlan`, `SnapshotDocument`, `ReorgJob`, `SemanticAction`, all dataclasses |
| AI planning | `ai_planner.py` | `plan_with_openai()`, `finalize_draft_plan()`, `apply_guardrails_to_actions()` |
| Heuristic planning | `planner.py` | `build_advise_plan()`, `build_merge_plan()` — legacy folder ranking |
| Plan execution | `executor.py` | `apply_plan()`, `apply_reviewed_semantic_plan()` — JSON-tree mutation, including empty-folder deletion |
| Job orchestration | `job_runner.py` | `init_reorg_job()`, `run_reorg_job()` — phase machine |
| Rules engine | `rules.py` | `load_rules()`, `validate_rules_data()` — custom YAML parser |
| Snapshot I/O | `snapshot_io.py` | `build_snapshot_document()`, `diff_snapshot_documents()`, enrich/queue builders |
| Analysis | `analysis.py` | `analyze_snapshot()` — duplicates, empty folders, clutter detection |
| URL utilities | `utils.py` | `normalize_url()`, `extract_domain()`, `tokenize()`, `slugify()` |

## ARCHITECTURE: Phase Machine

`job_runner.py` drives a linear pipeline with state persistence:

```
export → review_queue → enrich → ai_plan → finalize → execute
```

Each phase reads input artifact(s), produces output artifact, advances job state in `reorg-job.json`.

## CONVENTIONS

- **Entry point**: `cli:main` registered as `bookmark-advisor` console script in `pyproject.toml`
- **Always `PYTHONPATH=src`**: Package lives in `src/bookmark_advisor/` per setuptools src-layout
- **No pyyaml**: `rules.py` has hand-written YAML parser (`_parse_simple_yaml`). Never add yaml dependency.
- **Dataclasses only**: All models are `@dataclass` in `models.py`. No Pydantic, no attrs.
- **File-based data flow**: All intermediate artifacts are JSON files in `data/` (gitignored)
- **OpenAI fallback chain**: `ai_planner.py` tries responses JSON schema → chat.completions JSON schema → chat.completions json_object → chat.completions plain JSON
- **Semantic action set**: AI/reviewed plans can include `move_bookmark`, `move_folder`, `create_folder`, `rename_folder`, `remove_duplicate`, `delete_empty_folder`, and `keep_for_review`
- **No external deps except `openai`**: Uses only stdlib otherwise (`json`, `dataclasses`, `argparse`, `urlparse`, `tempfile`)

## ANTI-PATTERNS

- **DO NOT** add pyyaml, pydantic, or attrs dependencies
- **DO NOT** use bare `snapshot.json` for AI planning — always go through URL review → enriched snapshot
- **DO NOT** use `--apply --write-source` as primary workflow — direct file edits get overwritten by Edge sync
- **DO NOT** auto-move root-level loose bookmarks when `protect_root_loose_bookmarks: true`

## SEE ALSO

- [README.md](../../README.md) / [README.zh-CN.md](../../README.zh-CN.md) — 项目介绍、使用指南
- [CHANGELOG.md](../../CHANGELOG.md) — 版本变更记录
- [AGENTS.md](../../AGENTS.md) — 项目级知识库
