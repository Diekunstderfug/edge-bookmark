[简体中文](README.zh-CN.md)

# Bookmark Advisor

AI-first Microsoft Edge bookmark organizer. The normal workflow is the Edge extension: generate a guarded AI plan, review every proposed action, execute through `chrome.bookmarks`, and undo the latest execution if needed. The Python CLI is available for snapshot export, URL review queues, enriched snapshots, and deeper offline checks.

## Use The Extension

1. Open `edge://extensions`, enable developer mode, and load the `extension/` directory as an unpacked extension.
2. Open the extension popup, switch to **LLM**, and set:
   - **API base URL**: `https://api.openai.com/v1` or another OpenAI-compatible HTTPS endpoint
   - **Endpoint mode**: `auto` for most providers
   - **Model**: `gpt-5.4-mini` by default; fast compatible models work best
   - **API key**: saved as AES-GCM ciphertext in `chrome.storage.local`
3. Return to **Plan**, optionally pick a focus folder, then click **Generate AI Plan**.
4. Review actions one by one. Approve good moves, revise specific rows, or leave uncertain items pending.
5. Click **Execute Reviewed Plan**. Execution happens in Edge via `chrome.bookmarks`, not by editing the bookmarks file.
6. Use **Undo Last Execution** if the latest batch needs to be reversed.
7. Click **Generate New Plan for Remaining** to continue with unreviewed items.

The extension has no build step and no SDK dependency. It uses raw `fetch` against OpenAI-compatible REST APIs and, in `auto` mode, tries `chat_json_object → chat_json_schema → chat_plain_json → completions_plain_json → responses_json_schema`.

## What Is Safe By Design

| Guardrail | Behavior |
|-----------|----------|
| Per-action review | Nothing executes until the individual action is approved or otherwise executable |
| Focus scope | Planning and execution can be restricted to one folder tree |
| Policy engine | Out-of-scope mutations are blocked at execution time |
| Undo log | Parent/title pre-state is recorded so the most recent execution can be reversed |
| Quarantine | Duplicate bookmarks move to `_Quarantine` instead of being permanently deleted |
| Empty-folder cleanup | `delete_empty_folder` re-checks emptiness before removal; undo recreates the folder |
| Locator checks | Bookmark/folder IDs are re-read before mutation |
| Background jobs | Offscreen keepalive pings, `chrome.alarms`, hard cancel, startup recovery, and execution checkpoints |

Large folders are split into 50-bookmark prompt parts with concurrency 3, then merged and deduplicated. Ordinary generation currently caps a non-batched request to 12 high-value actions; revision returns only changed rows and preserves unchanged actions locally.

## CLI Tools

Use the CLI when you need file-based artifacts, URL review sidecars, snapshot diffs, or a stricter offline planning path.

```bash
# Always set PYTHONPATH because this is a src-layout package.
PYTHONPATH=src python3 -m bookmark_advisor <command>
```

### Snapshot And Review

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

### AI Planning

```bash
# Generate a draft plan (OpenAI or compatible provider)
OPENAI_API_KEY=... OPENAI_BASE_URL=https://your-provider.example/v1 \
PYTHONPATH=src python3 -m bookmark_advisor plan-ai \
  --snapshot data/snapshots/enriched_snapshot_YYYYMMDD_HHMMSS.json \
  --rules config/rules.yaml \
  --model gpt-5.4-mini

# Finalize draft → reviewed plan
PYTHONPATH=src python3 -m bookmark_advisor finalize-plan \
  --input data/plans/draft_YYYYMMDD_HHMMSS.json

# Diff two snapshots
PYTHONPATH=src python3 -m bookmark_advisor diff-snapshot \
  --before data/snapshots/before.json --after data/snapshots/after.json
```

The CLI planner uses the official `openai` Python SDK. Set `OPENAI_BASE_URL` for compatible providers. Auto fallback is `responses/json_schema → chat.completions/json_schema → chat.completions/json_object → chat.completions/plain_json`.

### Job Runner

```bash
# Init a reorg job
PYTHONPATH=src python3 -m bookmark_advisor init-job --workspace . --primary-backend extension

# Run the next pending phase
PYTHONPATH=src python3 -m bookmark_advisor run-job --job data/jobs/reorg_*/reorg-job.json
```

The job runner steps through export → review-queue → enrich → ai-plan → finalize sequentially, with a file lock and extension waiting phase.

## Common Checks

```bash
# Full test suite
PYTHONPATH=src python3 -m pytest tests/

# Python CLI tests only
PYTHONPATH=src python3 -m unittest discover -s tests

# Focused extension tests
python -m pytest tests/test_extension_service_worker_state.py \
  tests/test_extension_plan_lint.py \
  tests/test_extension_endpoint_urls.py \
  tests/test_extension_popup_state.py -x -q

# Syntax check a reviewed plan
python3 -m json.tool data/plans/reviewed_plan.json
```

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

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
