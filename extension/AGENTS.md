# extension/

Edge MV3 browser extension — plan execution and in-browser AI planning. Vanilla JS, no build step.

## WHERE TO LOOK

| Task | File | Notes |
|------|------|-------|
| Extension UI | `popup.html` + `popup.js` | Two tabs: Plan + LLM Settings. Per-action approve/revise. Auto-saves drafts. |
| Background ops | `service_worker.js` | chrome.bookmarks API, plan execution, undo log, policy engine, quarantine, empty-folder cleanup |
| Background job lifecycle | `service_worker.js` | Offscreen keepalive, alarm watchdog, stale detection, cooperative/hard cancel, startup cleanup, offscreen recovery, execution checkpoints |
| In-browser AI | `ai_planner.js` | HTTPS fetch against OpenAI-compatible APIs (SDK-free), pipe-delimited encoding, cached part batching, delta-only revision |
| Offscreen LLM runtime | `offscreen.html` + `offscreen.js` | Long-running provider fetches that outlive service worker suspension; sends keepalive pings during LLM waits |
| Shared helpers | `storage_helpers.js` | Storage constants, chrome.storage wrappers, `pathWithinScope` |
| Action constants | `action_constants.js` | `EXECUTION_ORDER`, `EXECUTABLE_ACTIONS`, `EXECUTABLE_STATUSES` shared across SW, planner, and lint |
| Plan validation | `plan_lint.js` | JSON syntax + plan-shape linting before execution |
| Extension config | `manifest.json` | MV3, permissions: `bookmarks`, `storage`, `offscreen`, `alarms`, optional host: `https://*/*` |

## ARCHITECTURE

```
popup.html ── loads ── plan_lint.js, popup.js
service_worker.js ── imports ── ai_planner.js, storage_helpers.js (via importScripts)
service_worker.js ── creates ── offscreen.html for long-running LLM calls

Message types (chrome.runtime.sendMessage):
  start-background-job → starts generate/revise/execute jobs with the shared mutation lock
  generate-ai-plan     → compatibility path for HTTPS planning; uses the same mutation lock
  revise-ai-plan       → compatibility path for HTTPS plan revision; uses the same mutation lock
  apply-reviewed-plan  → compatibility path for plan execution; uses the same mutation lock
  undo-last-execution  → reverses the most recent execution from the undo log
  cancel-active-job    → cooperative cancellation (sets timestamp) or hard abort via AbortController
  export-snapshot      → service_worker.js walks bookmark tree
  get-active-job       → returns persisted background job state
  list-folders         → exports current folders for the popup scope picker
```

## CONVENTIONS

- **No bundler**: Files are plain JS loaded directly — no webpack/vite/esbuild
- **No npm/node**: No package.json, no node_modules
- **AI planner is SDK-free**: Uses raw `fetch()` with auto-fallback chain (`chat_json_object → chat_json_schema → chat_plain_json → completions_plain_json → responses_json_schema`)
- **Large-folder planning**: Generation auto-batches >50 bookmarks into 50-bookmark prompt parts with concurrency 3, then merges/deduplicates activations before compile/finalize
- **Delta-only revision**: Revision prompts return only changed activations; unchanged plan rows are preserved locally by `mergeRevisionDraft`
- **Prompt cache layout**: Keep shared instructions/rules/folder catalog before per-part bookmark rows; official OpenAI requests add `prompt_cache_key` and supported models use 24h retention
- **Offscreen LLM calls**: Long provider requests run in `offscreen.js`; keepalive pings reset the service worker idle timer, and results persist to `bookmarkAdvisorOffscreenResult` for recovery after wakeups
- **IIFE module pattern**: `ai_planner.js` and `plan_lint.js` use `(function attach*(globalScope) {...})(self)` — attach to `self` in service worker context
- **Execution order**: `rename_folder → delete_empty_folder → create_folder → move_folder → move_bookmark → remove_duplicate → keep_for_review`
- **Undo log**: Every mutation records pre-state (parentId, title, or recreated folder path) to `bookmarkAdvisorUndoLog` in chrome.storage. `undo-last-execution` reverses the most recent batch. Log auto-trims to 20 execution IDs.
- **Quarantine**: `remove_duplicate` moves bookmarks to `/收藏夹栏/_Quarantine` instead of permanently deleting them. This allows undo and manual review.
- **Empty-folder cleanup**: `delete_empty_folder` only removes a folder after `chrome.bookmarks.getChildren()` confirms it is still empty; undo recreates the empty folder path.
- **Policy engine**: `checkActionPolicy` enforces focus-path scope at execution time. Actions outside the focused folder are blocked with a descriptive reason.
- **Per-action status**: `actionDisplayStatus()` classifies each action as `executable`/`pending`/`blocked`/`review` based on its own status, not the category group. Agreed `keep_for_review` rows are executable no-op report entries.
- **Pipe-delimited encoding**: `encodeSnapshot()`/`encodePlan()` use pipe-separated values instead of JSON to reduce LLM token consumption in prompts.
- **Unified target field**: The AI activation schema uses a single `target` field (destination path, new title, or create path) instead of separate `destination_path`/`create_path`/`new_title`.
- **Undo type constants**: `UNDO_MOVE`, `UNDO_RENAME`, `UNDO_DELETE_FOLDER`, and `UNDO_CREATE_FOLDER` replace stringly-typed undo action types.
- **API key storage**: AES-GCM ciphertext in `chrome.storage.local`, key derived from extension install ID (SHA-256)
- **Popup auto-save**: Form state persisted to `chrome.storage.local` because popups are destroyed on focus loss
- **Background job lifecycle**: Jobs start with `startBackgroundJob()`, offscreen LLM calls send 15s keepalive pings, `chrome.alarms` provides a service-worker watchdog, and jobs can be cancelled cooperatively (`cancellation_requested_at` timestamp) or immediately (`AbortController`). Stale jobs (> 30 min) and startup-stale jobs (> 60s) are auto-failed

## MESSAGE PROTOCOL

| Message | Direction | Payload |
|---------|-----------|---------|
| `start-background-job` | popup → SW | `{job_type, payload}` for `generate-ai-plan`, `revise-ai-plan`, or `apply-reviewed-plan` |
| `generate-ai-plan` | popup/compat → SW | `{options: {apiBaseUrl, apiKey, apiStyle, model, focusPath, maxActions, maxRetries}}` |
| `revise-ai-plan` | popup/compat → SW | `{plan, options}` |
| `apply-reviewed-plan` | popup/compat → SW | `{plan, focusPath}` reviewed SemanticPlan |
| `undo-last-execution` | popup → SW | (none) — reverses most recent execution batch |
| `cancel-active-job` | popup → SW | (none) — cooperative cancellation (sets `cancellation_requested_at`) or hard abort via `AbortController`; clears storage |
| `export-snapshot` | popup → SW | (none) |
| `get-active-job` | popup → SW | (none) |
| `list-folders` | popup → SW | (none) |

## ANTI-PATTERNS

- **DO NOT** add a JS build step or bundler
- **DO NOT** use npm packages — extension is intentionally dependency-free
- **DO NOT** store API keys in plaintext — use AES-GCM via `saveEncryptedSecret()`/`loadEncryptedSecret()`
