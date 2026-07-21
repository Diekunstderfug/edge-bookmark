# Multi-agent audit summary (2026-05-17)

## Repo freshness check
- Ran `git fetch --all --prune` and verified clean status before audit work.

## 1) Security
- High: API key encryption is reversible local obfuscation because key derivation uses extension id + salt (not user secret).
- High: Arbitrary OpenAI-compatible base URL can exfiltrate API key to attacker-controlled HTTPS endpoint.
- Medium: prompt sanitization is lexical, not semantic isolation against prompt injection.
- Positive: execution focus-path policy and job artifact path boundary checks are present.

## 2) Code quality
- `extension/service_worker.js` has oversized multi-responsibility functions (`executeReviewedPlan`, `applyAction`) with repeated path/index logic.
- Cross-language naming/field semantics can be clearer (`to_path` vs `target_path`).

## 3) Errors / bug risks
- `confidence: null` can trigger `float(None)` crash in semantic action deserialization.
- Extension `maxActions` is hard-capped to 12 despite default 40.
- Unknown `job.type` path in `runBackgroundJob` lacks explicit fail branch.
- `allow_write_source` boolean parsing via `bool(...)` can mis-handle string "false".
- `api_style=responses` lacks fallback chain.

## 4) Race conditions
- Background-job start uses non-atomic read-check-write over storage.
- `runningJobId` is process-memory lock and is lost across SW restarts.
- Undo log append is read-modify-write and can lose updates with concurrent writers.
- Cancellation and offscreen result propagation can race.

## 5) Test flakiness
- Node subprocess timeout thresholds are relatively tight.
- Conditional skips for Node availability reduce coverage consistency across environments.
- Some async lifecycle assertions can be strengthened.

## 6) Maintainability / boundary / docs conformance
- CLI `main()` is a thick dispatcher with business logic branches.
- `job_runner` phase machine and backend execution policy are tightly coupled.
- Terminology mismatch risk: docs mention `execute` phase while code uses `apply` / waiting states.

## Prioritized recommendations
1. Introduce persistent storage lease/CAS primitives for active jobs and undo log.
2. Strengthen credential model (session-only key, passphrase-based unlock, or backend proxy token).
3. Add strict endpoint allowlist and precise optional host permission requests.
4. Split large service worker functions into action handler table + shared helpers.
5. Harden deserialization/validation for nullable and stringly-typed booleans.
6. Normalize phase vocabulary across README/AGENTS/code.
