# tests/

Python and extension test suite. Core CLI tests use stdlib `unittest.TestCase`; extension tests are Python pytest files that execute Node.js subprocesses with mock `chrome` globals.

## WHERE TO LOOK

| File | Coverage |
|------|----------|
| `test_utils.py` | `utils.py` — normalize_url, tokenize, slugify |
| `test_rules.py` | `rules.py` — YAML loading, validation + CLI `validate-rules` subprocess |
| `test_planner.py` | `planner.py` — merge/advise plan generation |
| `test_reorg_job.py` | `job_runner.py` — full job workflow with temp files |
| `test_ai_planner_compat.py` | `ai_planner.py` — SDK compatibility, fallback chain, mock clients |
| `test_semantic_flow.py` | End-to-end — snapshot export, guardrails, AI prompts, finalization, diff |
| `test_extension_service_worker_state.py` | Extension service worker — plan execution, undo log, policy engine, quarantine, locator verification |
| `test_extension_endpoint_urls.py` | Extension AI planner — endpoint URLs, activation schema, lint/retry behavior, prompt encoding |
| `test_extension_plan_lint.py` | Extension plan lint — action shape validation and executable/no-op classification |
| `test_extension_popup_state.py` | Extension popup — form persistence, settings, i18n |
| `test_prompt_parity.py` | Python/JS prompt policy parity |
| `test_prompt_sanitization.py` | Prompt sanitization helpers |
| `test_rules_parity.py` | Python/extension rule behavior parity |
| `test_url_parity.py` | Python/extension URL normalization parity |
| `test_atomic_write.py` | Atomic JSON write helpers |

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
- **Assertions**: `self.assert*` methods only

## COMMANDS

```bash
# Run Python CLI tests
PYTHONPATH=src python3 -m unittest discover -s tests

# Run extension tests (requires node)
python -m pytest tests/test_extension_service_worker_state.py tests/test_extension_plan_lint.py tests/test_extension_endpoint_urls.py tests/test_extension_popup_state.py -x -q

# Run targeted extension behavior/lint tests
python -m pytest tests/test_extension_plan_lint.py tests/test_extension_service_worker_state.py -q

# Run single file
PYTHONPATH=src python3 tests/test_rules.py
```
