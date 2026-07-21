# Code Quality Review (2026-05-17)

Scope: naming consistency, duplicated logic, function length, comments/readability, and exception-handling consistency.

## Findings

1. **Naming style is mixed across language boundaries (snake_case vs camelCase), with additional semantic overlap in field names.**
   - Python uses `snake_case` function/field names (e.g., `plan_with_openai`, `source_snapshot`), while extension code uses `camelCase` (`actionDisplayStatus`, `executeReviewedPlan`), which is expected cross-language but still introduces translation overhead for contributors working on both paths.
   - Within plan payloads, both `to_path` and `target_path` coexist and carry different semantics depending on action type, increasing cognitive load.

2. **`service_worker.js` contains several very long multi-responsibility functions.**
   - `applyAction` includes policy validation, argument validation, folder resolution, mutation execution, undo recording, and index maintenance for many action types in a single switch.
   - `executeReviewedPlan` (earlier in file) similarly combines planning, progress reporting, execution ordering, and result aggregation.

3. **Repeated path normalization/index-update patterns in extension execution logic.**
   - Repetitive `expectedX || computedX` + `.replace(/\/+/g, "/")` appears in multiple action branches (rename, delete, move), along with repeated checks for `folderPathIndex` and subsequent index updates.

4. **Comment density is uneven in complex hotspots.**
   - High-complexity execution/cancellation/undo branches in `service_worker.js` are mostly self-documenting via names but have limited rationale comments for edge-case behavior (e.g., why certain undo operations are best-effort, or why cancellation treats missing active job as cancelled).

5. **Exception/error-handling style is inconsistent between Python and JS paths.**
   - Python AI planner wraps parse failures in domain error (`AIPlannerError`) and uses explicit raise points.
   - Extension code mostly throws generic `Error` strings in validators/execution branches and catches in wider control flow, which makes it harder to categorize faults (policy vs input vs API/runtime).

## Suggested Improvements (prioritized)

1. Introduce shared helpers in extension execution:
   - `normalizePath(path)`, `resolveEffectiveFromPath(action, node, idToPath)`, `resolveEffectiveToPath(...)`, and `withUndo(executionId, ...)` to shrink branch size and eliminate duplication.
2. Split `applyAction` into per-action handlers in a dispatch table:
   - e.g., `ACTION_HANDLERS = { create_folder: handleCreateFolder, ... }`.
3. Standardize error taxonomy in JS:
   - Add typed error classes or tagged errors (`code: "POLICY_BLOCKED" | "LOCATOR_NOT_FOUND" | ...`) and central mapping to user-facing messages.
4. Add short “why” comments for non-obvious behavior:
   - cancellation semantics, undo best-effort strategy, and protected-scope policy edge cases.
5. Add a brief contributor note documenting naming/field semantics:
   - especially `to_path` vs `target_path`, plus cross-language naming expectations.
