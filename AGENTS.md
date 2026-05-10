# PROJECT KNOWLEDGE BASE

**Generated:** 2026-05-10
**Commit:** working tree
**Branch:** main

## OVERVIEW

AI-first Microsoft Edge bookmark organizer. Hybrid Python CLI (snapshot export, AI planning, job orchestration) + vanilla JS browser extension (plan execution via `chrome.bookmarks`). Rules in YAML act as guardrails.

## STRUCTURE

```
edge-bookmark/
├── src/bookmark_advisor/   # Python CLI package (setuptools, src-layout)
├── extension/              # Edge MV3 extension (vanilla JS, no build step)
├── config/                 # rules.yaml — guardrails, category hints, relocations
├── skills/                 # Markdown skills for coding agents (bookmark-reorg, bookmark-url-review)
├── tests/                  # unittest/pytest suite for Python CLI and extension behavior
└── data/                   # Runtime: snapshots, plans, jobs (gitignored)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add CLI command | `src/bookmark_advisor/cli.py` | argparse subparsers, dispatch by command name |
| Modify data models | `src/bookmark_advisor/models.py` | All dataclasses: PlanAction, SemanticPlan, SnapshotDocument, ReorgJob, etc. |
| AI planning logic | `src/bookmark_advisor/ai_planner.py` | OpenAI SDK, prompt construction, guardrail application |
| Heuristic planning | `src/bookmark_advisor/planner.py` | Legacy advise/merge modes, folder ranking, loose bookmark placement |
| Plan execution | `src/bookmark_advisor/executor.py` | JSON-tree mutation (move, rename, create, remove) |
| Job orchestration | `src/bookmark_advisor/job_runner.py` | Phase machine: export → review → enrich → plan → finalize |
| Rules engine | `src/bookmark_advisor/rules.py` | YAML parsing (custom, no pyyaml dep), validation, relocation rules |
| Snapshot I/O | `src/bookmark_advisor/snapshot_io.py` | Read/write JSON snapshots, review queues, enriched snapshots, diffing |
| URL utilities | `src/bookmark_advisor/utils.py` | normalize_url, extract_domain, tokenize, slugify |
| Extension popup | `extension/popup.js` + `popup.html` | UI, form persistence, AES-GCM key storage, per-action approve/revise |
| Extension background | `extension/service_worker.js` | chrome.bookmarks API operations, plan execution, undo log, policy engine, quarantine, empty-folder cleanup |
| Extension AI planner | `extension/ai_planner.js` | HTTPS fetch against OpenAI-compatible APIs (SDK-free), pipe-delimited prompt encoding, cached part batching, delta-only revision |
| Extension offscreen runtime | `extension/offscreen.js` + `offscreen.html` | Long-running LLM fetches outside the MV3 service worker lifecycle; sends keepalive pings to the service worker |
| Background job lifecycle | `extension/service_worker.js` | Alarm watchdog, stale detection, cooperative/hard cancel, startup cleanup, offscreen recovery, execution checkpoints |
| Shared helpers | `extension/storage_helpers.js` | Storage constants, chrome.storage wrappers, `pathWithinScope` |
| Action constants | `extension/action_constants.js` | `EXECUTION_ORDER`, `EXECUTABLE_ACTIONS`, `EXECUTABLE_STATUSES` shared across SW, planner, and lint |
| Plan validation | `extension/plan_lint.js` | JSON syntax + plan-shape linting in-browser |
| Guardrail rules | `config/rules.yaml` | Protected paths, category hints, forced relocations |

## CODE MAP

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `cli:main` | Function | `src/bookmark_advisor/cli.py:43` | CLI entry point (argparse dispatch) |
| `plan_with_openai` | Function | `src/bookmark_advisor/ai_planner.py:40` | AI plan generation via OpenAI SDK |
| `finalize_draft_plan` | Function | `src/bookmark_advisor/ai_planner.py:93` | Draft → reviewed plan conversion |
| `apply_guardrails_to_actions` | Function | `src/bookmark_advisor/ai_planner.py:149` | Rule enforcement on AI actions |
| `build_advise_plan` | Function | `src/bookmark_advisor/planner.py:19` | Heuristic advise plan |
| `build_merge_plan` | Function | `src/bookmark_advisor/planner.py:56` | Heuristic merge plan |
| `init_reorg_job` | Function | `src/bookmark_advisor/job_runner.py:34` | Job initialization |
| `run_reorg_job` | Function | `src/bookmark_advisor/job_runner.py:123` | Phase-by-phase job execution |
| `load_rules` | Function | `src/bookmark_advisor/rules.py:69` | YAML rules loading |
| `build_snapshot_document` | Function | `src/bookmark_advisor/snapshot_io.py:25` | Snapshot construction from Edge JSON |
| `analyze_snapshot` | Function | `src/bookmark_advisor/analysis.py:10` | Duplicate/clutter/empty folder detection |
| `executeReviewedPlan` | Function | `extension/service_worker.js:1090` | Extension plan execution with undo recording and policy checks |
| `undoLastExecution` | Function | `extension/service_worker.js:1374` | Reverses the most recent execution from the undo log |
| `checkActionPolicy` | Function | `extension/service_worker.js:1292` | Focus-path enforcement at execution time |
| `actionDisplayStatus` | Function | `extension/popup.js:1127` | Per-action display state (executable/pending/blocked/review) |
| `generateReviewedPlan` | Function | `extension/ai_planner.js:82` | Extension AI plan via HTTPS |

## CONVENTIONS

- **Python path**: `PYTHONPATH=src python3 -m bookmark_advisor <command>` — always set PYTHONPATH
- **No pyyaml dependency**: `rules.py` contains a custom YAML parser — do not add pyyaml
- **No pytest for Python CLI tests**: CLI tests use stdlib `unittest.TestCase` + `unittest.main()`, run via `python3 -m unittest discover -s tests`
- **Extension tests use pytest + node**: `test_extension_*.py` and `test_extension_plan_lint.py` run via pytest but execute Node.js subprocesses with mock `chrome` globals
- **No JS build step**: Extension files in `extension/` are production-ready vanilla JS — no transpilation
- **Two AI planning paths**: CLI uses OpenAI Python SDK; extension uses raw `fetch` (SDK-free by design)
- **Data flow is file-based**: Intermediate artifacts are JSON files (snapshot → review-queue → url-review → enriched-snapshot → draft-plan → reviewed-plan → execution-report)
- **API key encryption**: Extension stores API keys as AES-GCM ciphertext derived from extension install ID (SHA-256)

## ANTI-PATTERNS (THIS PROJECT)

- **DO NOT** use bare `snapshot.json` for semantic classification — always go through URL review first
- **DO NOT** auto-reorganize loose bookmarks under protected roots (`/收藏夹栏`, `/其他收藏夹`, etc.) unless explicitly requested
- **DO NOT** add pyyaml or yaml dependency — project uses custom YAML parser in `rules.py`
- **DO NOT** add a JS build step/bundler — extension is intentionally vanilla JS
- **DO NOT** use `--apply --write-source` as primary workflow — direct file edits get overwritten by Edge sync

## UNIQUE STYLES

- **Bilingual config**: `rules.yaml` contains Chinese folder names (`收藏夹栏`, `编程`, `量化`, `生信和基因组学`) and English code — category hints support both languages
- **Skills as code**: `skills/` directory contains Markdown SKILL.md files that teach coding agents how to orchestrate bookmark reorganization workflows
- **Dual planning**: Heuristic planner (`planner.py`) for deterministic cases, AI planner (`ai_planner.py`) for semantic classification — both produce `SemanticPlan` output
- **Phase machine**: `job_runner.py` implements a linear phase pipeline (export → review_queue → enrich → ai_plan → finalize → execute) with state persistence in `reorg-job.json`
- **Custom YAML parser**: `_parse_simple_yaml()` in `rules.py` — hand-written indentation-aware parser, no external deps

## COMMANDS

```bash
# Run CLI
PYTHONPATH=src python3 -m bookmark_advisor <command>

# Common commands
PYTHONPATH=src python3 -m bookmark_advisor export-snapshot
PYTHONPATH=src python3 -m bookmark_advisor validate-rules --rules config/rules.yaml
PYTHONPATH=src python3 -m bookmark_advisor init-job --workspace . --primary-backend extension
PYTHONPATH=src python3 -m bookmark_advisor run-job --job data/jobs/<job>/reorg-job.json

# Run Python CLI tests
PYTHONPATH=src python3 -m unittest discover -s tests

# Run extension tests (requires node)
python -m pytest tests/test_extension_service_worker_state.py tests/test_extension_plan_lint.py tests/test_extension_endpoint_urls.py tests/test_extension_popup_state.py -x -q

# Syntax check a plan
python3 -m json.tool data/plans/reviewed_plan.json
```

## NOTES

- `data/` is gitignored — runtime artifacts only, never committed
- Default Edge bookmarks path uses the current macOS user profile: `~/Library/Application Support/Microsoft Edge/Default/Bookmarks`
- Extension API key storage is convenience encryption, not security against browser profile access
- `ai_planner.py` supports OpenAI-compatible providers via `OPENAI_BASE_URL` with auto-fallback (responses/json_schema → chat.completions/json_schema → chat.completions/json_object → chat.completions/plain_json)
- Extension `ai_planner.js` auto mode uses `chat_json_object → chat_json_schema → chat_plain_json → completions_plain_json → responses_json_schema`
- Extension default model is `gpt-5.4-mini`; UI recommends fast models such as `gpt-5.4-mini`, `deepseek-v4-flash`, and `gemini-2.5-flash`
- Extension generation auto-batches folders with more than 50 bookmarks into 50-bookmark cached prompt parts (concurrency 3), then merges and deduplicates activations
- Extension revision is delta-only: the LLM returns only changed actions, and unchanged existing plan rows are preserved locally
- Official OpenAI calls include `prompt_cache_key` and supported GPT-5.x/GPT-4.1 requests use `prompt_cache_retention=24h`; DeepSeek relies on automatic KV prefix cache
- Popup auto-saves form drafts because extension popups are destroyed on focus loss
- Extension undo log allows reversing the most recent execution batch
- Duplicate bookmarks are quarantined to `_Quarantine` instead of permanently deleted
- Empty folders can be removed through `delete_empty_folder`; execution re-checks emptiness and undo recreates the empty folder path
- Agreed `keep_for_review` actions can execute as no-op report entries so review-only decisions can be tracked
- Focus-path policy engine blocks out-of-scope actions at execution time
- Max retries (default 1, range 0-3) controls LLM lint-failure retry count
- Background jobs use offscreen keepalive pings plus a `chrome.alarms` watchdog; stale threshold is 30 minutes, startup stale threshold is 60 seconds
- Cooperative cancellation sets `cancellation_requested_at`; hard cancel uses `AbortController` to immediately interrupt the job
- No CI/CD pipeline — run local syntax checks and `PYTHONPATH=src python3 -m pytest tests/` before shipping

## SEE ALSO

- [README.md](README.md) / [README.zh-CN.md](README.zh-CN.md) — 项目介绍、使用指南、架构概览
- [CHANGELOG.md](CHANGELOG.md) — 版本变更记录
