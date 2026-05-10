# Changelog

## 2026-05-10 — Fast models, cached batching, delta revision, MV3 keepalive

### Extension

- **Fast defaults**: default extension model updated to `gpt-5.4-mini`; model hints now recommend `gpt-5.4-mini`, `deepseek-v4-flash`, and `gemini-2.5-flash`
- **Cached part batching**: large folders are split into 50-bookmark prompt parts with concurrency 3; returned activations are merged and deduplicated before compile/finalize
- **Prompt cache alignment**: batched prompts keep shared instructions, rules, and folder catalog before part-specific bookmark rows; official OpenAI calls include `prompt_cache_key`, with 24h retention for supported models
- **Delta-only revision**: revision prompts return only changed activations; unchanged existing plan rows are preserved locally
- **MV3 keepalive hardening**: offscreen LLM calls send 15s keepalive pings, service worker jobs use a `chrome.alarms` watchdog, and execution writes per-action checkpoints for partial recovery
- **Settings persistence**: LLM settings auto-save on blur/pagehide/visibility changes without implicitly saving API keys

### Bug fixes

- **Foreground execution**: `apply-reviewed-plan` runs as a synchronous foreground operation instead of a background job, eliminating stale-state race conditions
- **Undo log accuracy**: only newly created folders are recorded in the undo log; `delete_empty_folder` records post-mutation state
- **Empty title guard**: empty-string title fallback no longer matches wrong bookmarks during locate-before-mutate
- **Focus scope for remove_duplicate**: `remove_duplicate` actions now go through the same focus-path policy check as other action types
- **Offscreen reliability**: creating-promise guard prevents duplicate document creation; hard timeout includes body read time; LLM stage verifies offscreen is alive before dispatching
- **Job lifecycle hardening**: active job storage stores only a summary to reduce `chrome.storage` pressure; job state updates spread the persisted `current` object first to prevent partial writes
- **Path normalization**: `pathWithinScope` uses normalized paths for focus-scope comparisons; `nodeParentPath` and `ensureFolderPath` use the bookmark tree index instead of linear search
- **Action constants**: `EXECUTION_ORDER`, `EXECUTABLE_ACTIONS`, and `EXECUTABLE_STATUSES` extracted to `action_constants.js` shared module
- **Unified logging**: `swLog()` replaces direct `console.log` calls in service worker; `nonNegativeInteger` replaces misleading `positiveInteger`
- **Explicit CSP**: manifest declares `content_security_policy` with script-src restricted to `self`
- **Cancel cleanup**: `cancelActiveJob` always sends `offscreen-cancel` to the offscreen document; orphan offscreen storage results are cleaned on startup

### Tests

- Full suite verified after the consolidation: `149 passed`

## 2026-05-06 — Offscreen LLM recovery, review agreement, empty-folder cleanup

### Extension

- **Offscreen LLM runtime**: long-running AI plan generation and revision now run through `offscreen.html`/`offscreen.js`, with persisted result recovery after service worker wakeups
- **Review agreement**: actions grouped under "needs review" get a quick agree option; agreed `keep_for_review` rows can execute as no-op report entries
- **Empty-folder cleanup**: new `delete_empty_folder` action type removes only folders that are still empty at execution time, and undo recreates the empty folder path
- **Manifest version**: extension version bumped to `0.1.1` so reloads can confirm the new service worker bundle is active

### Python

- Reviewed plan execution, AI action normalization, and reporting now recognize `delete_empty_folder`

### Tests

- Added regression coverage for offscreen lifecycle recovery, agreed review no-op execution, and empty-folder deletion/rejection behavior

## 2026-05-05 — Background job cancellation, heartbeat, stale detection

### Extension

- **Service worker heartbeat**: background jobs send periodic heartbeat updates to prevent being marked stale during long-running operations
- **Popup staleness detection**: when the popup opens, it checks whether a running background job has exceeded the 30-minute stale threshold and auto-marks it as failed
- **AbortSignal support**: AI planner (`ai_planner.js`) accepts an `AbortSignal` for cooperative cancellation of LLM requests, with fetch keep-alive to extend MV3 service worker lifetime during awaits
- **Hard cancel**: "Force Stop" button now immediately aborts the active background job via `AbortController`
- **Cooperative cancellation**: cancellation sets a `cancellation_requested_at` timestamp; the job fails gracefully with the cancel reason preserved
- **Startup cleanup**: service worker startup automatically detects and fails background jobs that were interrupted by a restart (jobs stale > 60 seconds)
- **Popup job stage**: running jobs display their current stage (export / LLM / save / finalize) in the popup status

### Tests

- Added regression coverage for heartbeat behavior, stale job detection, cooperative cancellation, hard cancel, and startup cleanup

## 2026-05-03 — Undo, quarantine, policy engine, per-action status, retry control

### Extension

- **Undo log**: every execution records pre-mutation state (parentId, title). "Undo Last Execution" reverses the most recent batch with one click
- **Quarantine delete**: duplicate bookmarks are moved to `_Quarantine` instead of being permanently deleted — safe to undo or manually review
- **Policy engine**: focus-path is enforced at execution time. Actions that would escape the focused folder are blocked with a clear reason
- **Per-action review**: each proposed action shows its own approve button and revise note field, independent of category grouping. Fixes a bug where proposed actions in non-review categories had no approve button
- **Continue button**: after execution, "Generate New Plan for Remaining" appears if the plan still has unreviewed items
- **Max retries**: new input field (default 1, range 0-3) alongside request timeout. Controls how many times the AI planner retries after a lint failure
- **Cancel job**: "Force Stop" button appears during background jobs to trigger cancellation and reset state
- **Unified target field**: AI activation schema now uses a single `target` field instead of separate `destination_path`/`create_path`/`new_title`
- **Pipe-delimited encoding**: snapshot and plan are encoded as pipe-separated values in LLM prompts, reducing token consumption
- **Shared path helper**: `pathWithinScope` extracted to `storage_helpers.js` for reuse across service worker and AI planner
- **Undo type constants**: `UNDO_MOVE`, `UNDO_RENAME`, `UNDO_DELETE_FOLDER` replace stringly-typed action types

### Tests

- New tests for policy engine (blocks/allows focus path), undo log (records before-state, reverses moves), quarantine (moves instead of deletes)
- Updated activation schema in test payloads to match the new `target` field format
- Updated retry behavior tests: explicit `maxRetries` parameter, default changed from 3 to 1

## 2026-05-01 — Service worker mutation lock, locator verification

### Extension

- Service worker mutation lock prevents concurrent plan executions
- Bookmark/folder locator verification before every mutation — catches stale IDs
- Self-descendant guard on move_folder — prevents moving a folder into itself
- Invalid actions now raise errors instead of silently failing

## 2026-04-29 — Focus scope, blocked status, MV3 timeout cap

### Extension

- Focus scope field in popup restricts AI planning to a specific folder tree
- `blocked` action status for low-confidence actions that should not execute
- MV3 service worker lifecycle timeout capped at 300 seconds
- Body read timeout added to HTTP fetch — prevents hanging on slow responses

## 2026-04-27 — Job runner file lock, extension waiting phase

### Python

- Job runner uses a file lock to prevent concurrent job execution
- Extension waiting phase in job runner polls for background job completion
- Artifact path validation before writing execution reports

## 2026-04-25 — HTTPS enforcement, snapshot identity

### Extension

- OpenAI-compatible base URL must be HTTPS — plain HTTP is rejected
- Snapshot content identity hash prevents stale review reuse when bookmarks change

## 2026-04-20 — Dark+amber operations console

### Extension

- Redesigned popup with dark theme and amber accent colors
- Category-based action preview with expand/collapse
- Confidence dots (high/medium/low) on each action
- i18n support for English and Chinese
