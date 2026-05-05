# Bookmark Advisor

AI-first Microsoft Edge bookmark organizer — semantic cleanup with guardrails, undo, and per-action approval.

## Feature highlights

- **One-click AI reorganization** — generate a plan from an OpenAI-compatible LLM, review proposed actions, execute inside Edge
- **Undo last execution** — every mutation records pre-state; reverse the entire batch with one click
- **Quarantine, not delete** — duplicate bookmarks go to `_Quarantine` instead of being permanently removed
- **Empty-folder cleanup** — `delete_empty_folder` removes only folders that are still empty at execution time
- **Background job lifecycle** — long-running AI plans and executions run as cancellable background jobs with heartbeat, stale detection, and offscreen recovery
- **Focus scope** — restrict AI planning and execution to a single folder tree; policy engine blocks out-of-scope mutations
- **Per-action approve/revise** — each proposed move, rename, create, delete-empty-folder, or review item has its own approval path
- **Auto-save form state** — popup drafts survive focus loss; reopen and pick up where you left off
- **AES-GCM encrypted API key** — key derived from extension install ID, stored in `chrome.storage.local`
- **CLI path for deep review** — offline URL review sidecars, enriched snapshots, and diffing for high-stakes cleanup

## Quick start — Edge extension

1. Open `edge://extensions`, enable developer mode
2. Load unpacked → select the `extension/` directory
3. Open the extension popup, switch to the **LLM** tab
4. Set your API base URL (must be HTTPS), model, endpoint mode, and API key
5. Return to the **Plan** tab, optionally pick a focus folder, and click **Generate AI Plan**
6. Review each action — approve, revise, or leave as pending
7. Click **Execute Reviewed Plan**
8. After execution, undo if needed, or click **Generate New Plan for Remaining** to continue with unreviewed items

The extension uses raw `fetch` against OpenAI-compatible REST APIs (Responses API → Chat Completions → JSON object fallback). Long LLM calls run through an MV3 offscreen document so the service worker can recover persisted results after wakeups. No SDK dependency.

### Extension safety

| Feature | What it does |
|---------|-------------|
| Undo log | Records parentId + title before each mutation; one-click reversal |
| Quarantine | `remove_duplicate` moves to `_Quarantine` instead of permanent delete |
| Empty-folder delete | `delete_empty_folder` re-checks that the target folder has no children before removal; undo recreates the empty folder path |
| Background jobs | Heartbeat prevents stale detection; hard cancel via AbortController; startup cleanup for interrupted jobs |
| Policy engine | Blocks actions that would escape the focused folder |
| Per-action review | Individual approve/revise per action, not per category group; agreed `keep_for_review` rows execute as no-op report entries |
| Locator verification | Re-checks bookmark/folder IDs exist before every mutation |
| Mutation lock | Service-worker-level lock prevents concurrent plan executions |
| Max retries | Configurable LLM lint-failure retry count (default 1, range 0-3) |

### Extension validation layers

1. JSON syntax check on file import
2. Plan-shape linting (required fields, valid action types, locator data)
3. Focus-path policy enforcement at execution time

## CLI tools (Python)

The CLI is the stricter path — export snapshots, build URL review queues, generate AI plans with the OpenAI Python SDK, diff results.

```bash
# Everything runs from src/
PYTHONPATH=src python3 -m bookmark_advisor <command>
```

### Snapshot & review

```bash
# Export current Edge bookmarks
PYTHONPATH=src python3 -m bookmark_advisor export-snapshot

# Build a review queue for public URLs
PYTHONPATH=src python3 -m bookmark_advisor build-review-queue \
  --snapshot data/snapshots/snapshot_YYYYMMDD_HHMMSS.json

# Merge reviewed URLs back into the snapshot
PYTHONPATH=src python3 -m bookmark_advisor enrich-snapshot \
  --snapshot data/snapshots/snapshot_YYYYMMDD_HHMMSS.json \
  --reviews data/reviews/url_review_YYYYMMDD_HHMMSS.json
```

### AI planning

```bash
# Generate a draft plan (OpenAI or compatible provider)
OPENAI_API_KEY=... OPENAI_BASE_URL=https://your-provider.example/v1 \
PYTHONPATH=src python3 -m bookmark_advisor plan-ai \
  --snapshot data/snapshots/enriched_snapshot_YYYYMMDD_HHMMSS.json \
  --rules config/rules.yaml \
  --model gpt-4o-mini

# Finalize draft → reviewed plan
PYTHONPATH=src python3 -m bookmark_advisor finalize-plan \
  --input data/plans/draft_YYYYMMDD_HHMMSS.json

# Diff two snapshots
PYTHONPATH=src python3 -m bookmark_advisor diff-snapshot \
  --before data/snapshots/before.json --after data/snapshots/after.json
```

### Job runner

```bash
# Init a reorg job
PYTHONPATH=src python3 -m bookmark_advisor init-job --workspace . --primary-backend extension

# Run the next pending phase
PYTHONPATH=src python3 -m bookmark_advisor run-job --job data/jobs/reorg_*/reorg-job.json
```

The job runner steps through export → review-queue → enrich → ai-plan → finalize sequentially, with a file lock and extension waiting phase.

### OpenAI SDK compatibility

The CLI planner uses the official `openai` Python SDK. Set `OPENAI_BASE_URL` for compatible providers. Fallback chain: `responses` → `chat.completions` → `json_object`. Use `--api-style` to force a specific mode.

## Architecture

```
extension/          ← Edge MV3 extension (vanilla JS, no build step)
src/bookmark_advisor/  ← Python CLI (setuptools src-layout)
config/rules.yaml   ← Guardrails: protected paths, forced relocations, category hints
skills/             ← Agent skills for bookmark-reorg and url-review workflows
tests/              ← unittest/pytest test modules for CLI and extension behavior
data/               ← Runtime artifacts: snapshots, plans, jobs (gitignored)
```

**Data flow**: snapshot → review-queue → url-review → enriched-snapshot → draft-plan → reviewed-plan → execution-report. Every intermediate file is readable JSON — editable and reusable.

**Rules** in `config/rules.yaml` are guardrails, not classifiers: protect roots, force known relocations, constrain risky actions, and keep loose bookmarks under protected roots in place by default.

## Running tests

```bash
# Python CLI tests
PYTHONPATH=src python3 -m unittest discover -s tests

# Extension tests (requires node)
python -m pytest tests/test_extension_service_worker_state.py \
  tests/test_extension_plan_lint.py \
  tests/test_extension_endpoint_urls.py \
  tests/test_extension_popup_state.py -x -q
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
