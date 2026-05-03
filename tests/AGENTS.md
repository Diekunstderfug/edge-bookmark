# tests/

Python unittest suite — 9 files, stdlib only (`unittest.TestCase`). No pytest, no conftest, no shared fixtures.

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
| `test_extension_popup_state.py` | Extension popup — form persistence, settings, i18n |

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
python -m pytest tests/test_extension_service_worker_state.py tests/test_extension_endpoint_urls.py tests/test_extension_popup_state.py -x -q

# Run single file
PYTHONPATH=src python3 tests/test_rules.py
```
