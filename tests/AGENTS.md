# tests/

Python unittest suite — 6 files, stdlib only (`unittest.TestCase`). No pytest, no conftest, no shared fixtures.

## WHERE TO LOOK

| File | Coverage |
|------|----------|
| `test_utils.py` | `utils.py` — normalize_url, tokenize, slugify |
| `test_rules.py` | `rules.py` — YAML loading, validation + CLI `validate-rules` subprocess |
| `test_planner.py` | `planner.py` — merge/advise plan generation |
| `test_reorg_job.py` | `job_runner.py` — full job workflow with temp files |
| `test_ai_planner_compat.py` | `ai_planner.py` — SDK compatibility, fallback chain, mock clients |
| `test_semantic_flow.py` | End-to-end — snapshot export, guardrails, AI prompts, finalization, diff |

## CONVENTIONS

- **Framework**: `unittest.TestCase` with `unittest.main()` guard — NOT pytest
- **Naming**: Files `test_*.py`, classes `<Feature>Test`, methods `test_<description>`
- **Isolation**: `tempfile.TemporaryDirectory()` per test — no shared temp dirs
- **Fixtures**: Inline helper functions at module level (no conftest.py):
  - `write_rules_file(base_dir, protect_root=True) → Path`
  - `write_bookmarks_file(base_dir) → Path`
  - `fake_draft_plan() → SemanticPlan`
- **Mocking**: Inline fake classes (`FakeClient`, `FakeResponsesAPI`, `FakeChatCompletionsAPI`) — no mocking library
- **Assertions**: `self.assert*` methods only

## COMMANDS

```bash
# Run all tests
PYTHONPATH=src python3 -m unittest discover -s tests

# Run single file
PYTHONPATH=src python3 tests/test_rules.py
```
