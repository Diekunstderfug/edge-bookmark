# tests/

Python and extension test suite. Core CLI tests use stdlib `unittest.TestCase`; extension tests are Python pytest files that execute Node.js subprocesses with mock `chrome` globals.

## WHERE TO LOOK

### Python CLI tests (unittest)

| File | Coverage |
|------|----------|
| `test_utils.py` | `utils.py` — normalize_url, tokenize, slugify |
| `test_rules.py` | `rules.py` — YAML loading, validation + CLI `validate-rules` subprocess |
| `test_planner.py` | `planner.py` — merge/advise plan generation |
| `test_reorg_job.py` | `job_runner.py` — full job workflow with temp files |
| `test_ai_planner_compat.py` | `ai_planner.py` — SDK compatibility, fallback chain, mock clients |
| `test_semantic_flow.py` | End-to-end — snapshot export, diffing, guardrails, AI prompts, finalization |
| `test_prompt_parity.py` | Python/JS prompt policy parity |
| `test_prompt_sanitization.py` | Prompt sanitization helpers |
| `test_rules_parity.py` | Python/extension rule behavior parity |
| `test_url_parity.py` | Python/extension URL normalization parity |
| `test_atomic_write.py` | Atomic JSON write helpers |

### Extension tests (pytest + Node.js subprocess)

Entry-level behavior:

| File | Coverage |
|------|----------|
| `test_extension_service_worker_state.py` | Service worker wiring — plan execution, undo log, policy engine, quarantine, locator verification |
| `test_extension_popup_state.py` | Popup — form persistence, settings, i18n |
| `test_extension_plan_lint.py` | Plan lint — action shape validation and executable/no-op classification |
| `test_extension_endpoint_urls.py` | AI planner — endpoint URLs, activation schema, lint/retry behavior, prompt encoding |
| `test_extension_boot_order.py` | Script/import order in `service_worker.js` `importScripts`, `popup.html`, and `offscreen.html` |

Module tests (1:1 with `extension/` modules):

| File | Coverage |
|------|----------|
| `test_extension_shared_contracts.py` | `shared/` — message protocol, plan schema, AI endpoints, path utils, storage |
| `test_extension_background_snapshot.py` | `background/snapshot_export.js` — snapshot walking/export |
| `test_extension_bookmark_tree.py` | `background/bookmark_tree.js` — tree index and path resolution |
| `test_extension_action_handlers.py` | `background/action_handlers.js` — per-action-type mutations |
| `test_extension_execution_policy.py` | `background/execution_policy.js` — focus-path policy checks |
| `test_extension_plan_executor_module.py` | `background/plan_executor.js` — execution flow, checkpoints, cancellation |
| `test_extension_undo_log.py` | `background/undo_log.js` — undo recording and reversal |
| `test_extension_job_store.py` | `background/job_store.js` — persisted job state |
| `test_extension_job_handlers.py` | `background/job_handlers.js` — generate/revise/execute job handlers |
| `test_extension_job_lifecycle.py` | `background/job_lifecycle.js` — watchdog, stale detection, cooperative/hard cancel |
| `test_extension_message_router.py` | `background/message_router.js` — message routing and locking |
| `test_extension_offscreen_client.py` | `background/offscreen_client.js` — offscreen document lifecycle |
| `test_extension_fast_rules.py` | `ai/fast_rules.js` — pre-LLM deterministic rules |
| `test_extension_ai_snapshot_model.py` | `ai/snapshot_model.js` — snapshot-to-prompt model |
| `test_extension_ai_batching.py` | `ai/batching.js` — 50-bookmark part batching |
| `test_extension_ai_prompt_codec.py` | `ai/prompt_codec.js` — pipe-delimited `encodeSnapshot`/`encodePlan` |
| `test_extension_ai_response_codec.py` | `ai/response_codec.js` — LLM response parsing |
| `test_extension_ai_provider_client.py` | `ai/provider_client.js` — HTTPS fetch fallback chain |
| `test_extension_plan_compiler.py` | `ai/plan_compiler.js` — activation merge/dedup, `mergeRevisionDraft` |
| `test_extension_popup_runtime_client.py` | `popup/runtime_client.js` — popup↔SW messaging |
| `test_extension_popup_job_state.py` | `popup/job_state.js` — background job polling/state |
| `test_extension_popup_secrets.py` | `popup/secrets.js` — AES-GCM secret storage |
| `test_extension_popup_settings_store.py` | `popup/settings_store.js` — settings persistence |
| `test_extension_popup_plan_view.py` | `popup/plan_view.js` — `actionDisplayStatus`, per-action rendering |

## CONVENTIONS

- **Framework**: `unittest.TestCase` with `unittest.main()` guard — NOT pytest for Python tests
- **Extension tests**: Use `pytest` to run Python test files that execute Node.js subprocesses with mock `chrome` globals
- **Naming**: Files `test_*.py`, classes `<Feature>Test`, methods `test_<description>`
- **Isolation**: `tempfile.TemporaryDirectory()` per test — no shared temp dirs
- **Fixtures**: Inline helper functions at module level (no conftest.py):
  - `write_rules_file(base_dir, protect_root=True) → Path`
  - `write_bookmarks_file(base_dir) → Path`
  - `fake_draft_plan() → SemanticPlan`
- **Extension test mocking**: Inline `chrome` API mocks in JS strings within Python test methods — `bookmarkCall("get", ...)`, `bookmarkCall("move", ...)`, etc.
- **Module loading in tests**: Extension modules are loaded under Node via the `require` guard in each IIFE — no bundler needed
- **Assertions**: `self.assert*` methods only

## COMMANDS

```bash
# Run Python CLI tests
PYTHONPATH=src python3 -m unittest discover -s tests

# Run all extension tests (requires node)
python -m pytest tests/test_extension_*.py -q

# Focused extension smoke tests
python -m pytest tests/test_extension_service_worker_state.py tests/test_extension_plan_lint.py tests/test_extension_endpoint_urls.py tests/test_extension_popup_state.py -x -q

# Run single file
PYTHONPATH=src python3 tests/test_rules.py
```

## SEE ALSO

- [README.md](../README.md) / [README.zh-CN.md](../README.zh-CN.md) — 项目介绍、使用指南
- [CHANGELOG.md](../CHANGELOG.md) — 版本变更记录
- [AGENTS.md](../AGENTS.md) — 项目级知识库
