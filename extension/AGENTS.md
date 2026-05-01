# extension/

Edge MV3 browser extension — plan execution and in-browser AI planning. Vanilla JS, no build step.

## WHERE TO LOOK

| Task | File | Notes |
|------|------|-------|
| Extension UI | `popup.html` + `popup.js` | Two tabs: Plan + LLM Settings. Auto-saves drafts. |
| Background ops | `service_worker.js` | chrome.bookmarks API, plan execution, snapshot export |
| In-browser AI | `ai_planner.js` | HTTPS fetch against OpenAI-compatible APIs (SDK-free) |
| Plan validation | `plan_lint.js` | JSON syntax + plan-shape linting before execution |
| Extension config | `manifest.json` | MV3, permissions: `bookmarks`, `storage`, host: `https://*/*` |

## ARCHITECTURE

```
popup.html ── loads ── plan_lint.js, popup.js
service_worker.js ── imports ── ai_planner.js (via importScripts)

Message types (chrome.runtime.sendMessage):
  generateAiPlan   → ai_planner.js generates plan via HTTPS
  executePlan      → service_worker.js executes reviewed plan
  exportSnapshot   → service_worker.js walks bookmark tree
```

## CONVENTIONS

- **No bundler**: Files are plain JS loaded directly — no webpack/vite/esbuild
- **No npm/node**: No package.json, no node_modules
- **AI planner is SDK-free**: Uses raw `fetch()` with auto-fallback chain (Responses API → Chat Completions JSON schema → JSON object mode)
- **IIFE module pattern**: `ai_planner.js` and `plan_lint.js` use `(function attach*(globalScope) {...})(self)` — attach to `self` in service worker context
- **Execution order**: `rename_folder → create_folder → move_folder → move_bookmark → remove_duplicate`
- **API key storage**: AES-GCM ciphertext in `chrome.storage.local`, key derived from extension install ID (SHA-256)
- **Popup auto-save**: Form state persisted to `chrome.storage.local` because popups are destroyed on focus loss

## MESSAGE PROTOCOL

| Message | Direction | Payload |
|---------|-----------|---------|
| `generateAiPlan` | popup → SW | `{snapshot, options: {apiBaseUrl, apiKey, apiStyle, model, focusPath, maxActions}}` |
| `executePlan` | popup → SW | `{plan}` (reviewed SemanticPlan) |
| `exportSnapshot` | popup → SW | (none) |

## ANTI-PATTERNS

- **DO NOT** add a JS build step or bundler
- **DO NOT** use npm packages — extension is intentionally dependency-free
- **DO NOT** store API keys in plaintext — use AES-GCM via `saveEncryptedSecret()`/`loadEncryptedSecret()`
