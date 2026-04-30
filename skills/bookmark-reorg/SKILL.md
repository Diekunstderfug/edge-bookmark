---
name: bookmark-reorg
description: Use when a coding agent needs to take over an end-to-end browser bookmark reorganization workflow in this repository. Read `reorg-job.json`, execute the next phase, call the independent `bookmark-url-review` skill before semantic planning, and produce reviewed plans for either Edge extension execution or direct source writing.
---

# Bookmark Reorg

Use this as the primary skill for end-to-end bookmark reorganization in this repository.

This skill orchestrates the full workflow:

1. `snapshot`
2. `review`
3. `enrich`
4. `plan`
5. `finalize`
6. `apply`

## Entry point

Start from a `reorg-job.json` file.

The job file is the runtime state for the workflow and tells the agent:

- where the source Edge bookmarks file lives
- where the rules file lives
- where snapshot and review artifacts live
- which phase is next
- which execution backend should be used

Preferred CLI:

```bash
PYTHONPATH=src python3 -m bookmark_advisor run-job --job /abs/path/to/reorg-job.json
```

## User instruction priority

The current user's explicit instructions take priority over default heuristics and prior assumptions.

- Follow the user's requested scope first.
- If the user says to leave a region of the bookmark tree alone, do not reorganize it.
- If the user says to prioritize a certain folder or theme, narrow the workflow to that scope before widening it.
- If the user asks for a specific execution path such as direct source writing or extension import, follow that path when it is available and safe.
- Treat defaults such as root-level protection, conservative review gating, and fallback behavior as guardrails that apply unless the user has explicitly overridden them.

When there is tension between an old inferred preference and a new explicit user request, prefer the new explicit request.

## Phase rules

### `snapshot`

- export the current bookmarks snapshot
- generate `review-queue.json`
- advance to `review`

### `review`

- do not locally improvise planning here
- call the independent `bookmark-url-review` skill
- determine what each public URL is actually for before any semantic reorganization plan is allowed
- prefer live semantic review by the active coding agent or by provider/SDK-backed search and retrieval
- only use local lightweight fetching as a fallback when stronger review capability is unavailable
- produce `url-review.json`
- if the review artifact is missing, stop and wait

### `enrich`

- merge snapshot and URL review sidecar
- produce `enriched-snapshot.json`

### `plan`

- run AI planning only on `enriched-snapshot.json`
- do not use bare `snapshot.json` for semantic classification
- keep the generated suggestions aligned with the current user's stated preferences, scope, and exclusions

### `finalize`

- convert the draft plan into `reviewed-plan.json`

### `apply`

- if backend is `extension`, stop with a reviewed plan ready for Edge extension import
- if backend is `write_source`, ensure backup first, then apply the reviewed plan

## Hard dependency

Before semantic planning, the agent must use the independent `bookmark-url-review` skill.

Do not bypass URL review for public URLs.

Public URLs without successful review must not be auto-moved.

Do not generate semantic suggestions from bare titles or folder names when the bookmark points to a public website.

The planner must first know what the site is for by using one of these review paths:

1. agent-led browsing or web review
2. provider or SDK search/retrieval capability
3. local lightweight fetching only as a fallback

If none of those paths produce a trustworthy review result, stop planning for that bookmark and keep it in `keep_for_review`.

Even when a bookmark has been successfully reviewed, do not generate suggestions that violate the user's current explicit instructions about scope, protected areas, or preferred organization style.

Use this directive verbatim when needed:

> Before generating bookmark reorganization suggestions, first review every public URL to determine what the site is actually for. This review may be performed by the coding agent through live browsing, by provider or SDK-backed search, or by local lightweight fetching only as a fallback. Do not generate auto-move suggestions for public URLs that have not received a trustworthy review result.

## Root-level protection

Treat root-level loose bookmarks as protected by default.

- If `protect_root_loose_bookmarks` is true, bookmarks sitting directly under a protected root such as `/收藏夹栏` must not be reorganized automatically.
- Those items may stay in place or enter `keep_for_review`.
- Do not move them into existing folders.
- Do not create new folders to absorb them.
- Only relax this rule when the user has explicitly asked for root-level cleanup.

## Output expectations

The workflow must produce and update these artifacts as needed:

- `snapshot.json`
- `review-queue.json`
- `url-review.json`
- `enriched-snapshot.json`
- `draft-plan.json`
- `reviewed-plan.json`

## Notes

- The Edge extension is an executor, not the planner.
- Direct source writing is supported, but must stay behind explicit job configuration.
- This skill should prefer deterministic repo commands over ad hoc reasoning when artifact generation is needed.
