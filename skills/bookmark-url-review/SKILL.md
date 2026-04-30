---
name: bookmark-url-review
description: Use when organizing browser bookmarks and the agent must determine what public URLs are actually for before semantic classification. Before auto-classifying bookmarks, review every non-internal, non-IP, non-local, non-browser-internal URL and record a compact URL review result; unresolved URLs must remain in review-only status.
---

# Bookmark URL Review

Use this skill before generating an AI bookmark reorganization plan.

This skill exists to enforce one hard rule:

- Do not auto-classify public bookmarks unless the agent has first established what the URL is for.

This is a standalone skill.

- It may be called on its own.
- It may also be used as a required sub-step inside a larger bookmark reorganization workflow.
- URL review should stay separate from plan generation so that different agents or providers can own the review step.

## When to use

Use this skill when:

- organizing Edge or Chrome bookmarks
- generating `draft-plan.json` or `reviewed-plan.json`
- deciding whether a bookmark can be auto-moved
- the bookmark title or current folder is too weak to classify reliably

Do not use this skill for:

- pure duplicate detection
- empty-folder cleanup
- browser-internal links or local files

## User instruction priority

The current user's explicit instructions about scope and exclusions come first.

- If the user says not to reorganize a certain area, do not treat URL review as permission to move items there.
- If the user narrows the task to specific folders, review only what is needed for that scope unless they ask for broader coverage.
- If the user explicitly asks to preserve root-level loose bookmarks, keep that protection in force even when a review result is strong.

## Hard rule

Before semantic classification:

- all public, non-IP, non-local URLs must be reviewed
- internal URLs may be skipped
- unresolved public URLs must not be auto-moved
- protected root loose bookmarks must remain in place by default, even after review, unless the user explicitly asked to reorganize the root level

If review fails or remains ambiguous:

- keep the bookmark in place, or
- emit `keep_for_review`

## Preferred execution mode

This skill is agent-first, not scraper-first.

Use the strongest available review capability in this order:

1. A coding agent or model with web search or browsing capability
2. A provider-side search or browsing feature exposed by the active AI provider
3. Local lightweight fetching as a fallback only

If the current agent can inspect the live site through web search or browser review, prefer that over local HTML scraping.

Do not assume local fetching is semantically equivalent to a capable reviewing agent. The purpose of this skill is to establish what a site is for, not merely to download HTML.

## Skip review for these URLs

Treat these as internal or special-case links. Do not require public web review for them:

- direct IP addresses
- private-network IPs such as `10.x.x.x`, `172.16.x.x` to `172.31.x.x`, `192.168.x.x`
- `localhost`
- hostnames that are clearly internal-only or machine-local
- `file://`
- `edge://`
- `chrome://`
- `about:`
- `javascript:`
- `data:`
- login or dashboard URLs that are clearly intranet-only and not publicly inspectable

These links may still be classified later, but not by assuming public website meaning.

## Required workflow

1. Export a snapshot first.

   Use the existing CLI:

   ```bash
   PYTHONPATH=src python3 -m bookmark_advisor export-snapshot
   ```

2. Build the review candidate set.

   Review candidates are bookmarks whose URLs are:

   - public
   - not direct IPs
   - not browser-internal or local protocols

3. Review each candidate URL before auto-classification.

   For each review candidate, determine:

   - final URL after redirects
   - page title
   - meta description when available
   - site or product name when obvious
   - first visible heading when useful
   - one-line summary of what the site is for
   - coarse content kind
   - review confidence
   - review method

4. Write the review result to a sidecar artifact.

   Preferred location:

   - `data/reviews/url_review_YYYYMMDD_HHMMSS.json`

   The expected shape is documented in `references/review-contract.md`.

5. Only after URL review is complete may the agent produce a semantic plan.

6. If a bookmark has no trustworthy review result, do not auto-classify it.

## Review method policy

Record how the review was produced:

- `agent_web`: the reviewing agent used search, browsing, or page inspection
- `provider_search`: the active model/provider supplied live retrieval or search-backed review
- `local_fetch_fallback`: the result came from local lightweight fetching only
- `manual`: a human or explicit manual note supplied the review

When available, prefer `agent_web` or `provider_search`.

If a result only comes from `local_fetch_fallback` and remains weak or generic, do not auto-classify the bookmark.

## Review quality bar

The review must answer the question:

- "What is this site mainly for in one sentence?"

Good outputs:

- "Hosted documentation for the Model Context Protocol ecosystem."
- "Biomedical dataset portal for cancer-related cohort downloads."
- "Cloud provider dashboard and billing console."

Bad outputs:

- "AI-related"
- "Looks like docs"
- "Possibly database"

## Allowed evidence

Prefer semantically strong evidence. If agent browsing is available, use it. If not, fall back to lightweight evidence:

- URL and domain
- HTML title
- meta description
- Open Graph title or description
- first heading
- obvious branding or product label

Only go deeper when the basic metadata is still ambiguous.

## How to use reviewed URLs downstream

After review, use the review result as semantic context for planning:

- existing folder path still matters
- user rules still matter
- hard relocations still override AI suggestions

But reviewed URL meaning should dominate weak titles such as:

- `Home`
- `Docs`
- `Portal`
- `Overview`
- `Dataset`

If the review came from a weak local-only fetch and the result is still generic, treat it as unresolved.

## Safety rules

- Do not assume a site's purpose from title alone when the title is generic.
- Do not auto-create a new category from a single weak signal.
- Do not move unresolved public URLs.
- Do not treat login pages as definitive evidence of the underlying site's topic unless the site identity is clear.
- Do not downgrade an agent-reviewed result to a weaker local-fetch interpretation without explicit evidence.

## Current project flow

Within this repository, the intended sequence is:

1. `export-snapshot`
2. URL review sidecar generation
3. AI planning
4. guardrail filtering
5. reviewed plan generation
6. Edge extension execution

The extension is the executor. URL review belongs on the agent side, before planning.

## References

- Review result shape and minimal fields: `references/review-contract.md`
