# Review Contract

This file defines the minimal sidecar contract for reviewed bookmark URLs.

## Purpose

The review sidecar records what a public bookmark URL is for before semantic planning.

It is intentionally lightweight:

- enough to support reliable classification
- small enough to create in batches
- independent from any specific model provider

## Recommended output file

Write review artifacts under:

- `data/reviews/url_review_YYYYMMDD_HHMMSS.json`

## Top-level shape

```json
{
  "review_version": "1",
  "created_at": "2026-04-22T10:00:00+08:00",
  "source_snapshot": "sha256:4b1d...",
  "items": []
}
```

`source_snapshot` must be copied exactly from the matching `review-queue.json`.
It is a content identity for the snapshot, not a file path. The enrichment step
rejects missing or non-matching values so stale review sidecars cannot be reused
for a different bookmark snapshot.

## Per-item shape

```json
{
  "bookmark_id": "395",
  "url": "https://example.com/docs",
  "normalized_url": "https://example.com/docs",
  "folder_path": "/收藏夹栏",
  "review_status": "reviewed",
  "review_method": "agent_web",
  "final_url": "https://example.com/docs",
  "page_title": "Example Docs",
  "meta_description": "Official product documentation for Example.",
  "site_name": "Example",
  "h1": "Documentation",
  "content_kind": "docs",
  "one_line_summary": "Official documentation for the Example product.",
  "review_confidence": 0.91,
  "notes": ""
}
```

## Allowed `review_status`

- `reviewed`
- `skipped_internal`
- `failed`
- `ambiguous`

## Allowed `review_method`

- `agent_web`
- `provider_search`
- `local_fetch_fallback`
- `manual`

## Allowed `content_kind`

Keep the vocabulary small and stable:

- `docs`
- `tool`
- `product`
- `dashboard`
- `login`
- `dataset`
- `paper`
- `community`
- `shopping`
- `news`
- `reference`
- `unknown`

## Interpretation rules

- `reviewed`: enough information was collected to support semantic planning
- `skipped_internal`: intentionally skipped because the URL is internal, local, IP-based, or browser-internal
- `failed`: review was attempted but usable context could not be collected
- `ambiguous`: information was collected but the site purpose is still unclear

`review_method` describes the source of semantic understanding, not just the transport used to fetch bytes.

## Planning rule

Only items with:

- `review_status = reviewed`

should be eligible for automatic semantic classification.

Items with:

- `skipped_internal`
- `failed`
- `ambiguous`

should remain in place or become `keep_for_review`, unless a strong explicit user rule overrides that behavior.

Items reviewed via `local_fetch_fallback` should still be treated conservatively if:

- the page title is generic
- the metadata is thin
- the one-line summary is weak
- the confidence is low

## Internal or special-case URLs

These normally produce `skipped_internal`:

- direct IP addresses
- private-network IPs
- `localhost`
- `file://`
- `edge://`
- `chrome://`
- `about:`
- `javascript:`
- `data:`

## Notes

- `one_line_summary` is the most important semantic field.
- `content_kind` helps keep planning consistent but should not replace the summary.
- `page_title` alone is not sufficient evidence when it is generic.
- Prefer `agent_web` or `provider_search` when the active agent can perform them.
