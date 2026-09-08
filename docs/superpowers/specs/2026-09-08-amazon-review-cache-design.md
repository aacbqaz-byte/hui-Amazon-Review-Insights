# Amazon Review Insights durable collection state design

## Goal

Make review collection survive context compression, task interruption, and process restart without repeating a SellerSprite MCP page. Persist every returned review before another MCP request is allowed. Once a matching collection is complete, every report or export must use local data and must not call SellerSprite again.

## Root cause addressed

The previous Skill contained prose-only cache instructions. An agent could write a summary text file instead of the full review records, keep the active page only in conversational memory, change `size` after context compression, or regenerate an output by starting collection again. Keyword-based contract tests could not detect any of those failures.

## Durable artifacts

For the canonical identity `<marketplace>-<asin>-<filter-key>`, use:

```text
.amazon-review-insights-cache/
  collections/<identity>/
    manifest.json
    pages/page-000001.json
    pages/page-000002.json
    reviews.jsonl
  receipts/review-receipt-<identity>.json
```

`filter-key` is `stars-<sorted-unique-stars-or-all>_types-<sorted-unique-types-or-all>`. The identity is normalized but still records the original marketplace, ASIN, `starList`, and `typeList` in `manifest.json`. Schema version 2 adds immutable `requestPageSize: 20`; version-1 and size-10 caches cannot be resumed automatically.

Each page file is the source of truth and contains the complete returned review objects plus the page metadata needed for recovery. It does not contain credentials. `reviews.jsonl` is a reconstructed, deduplicated projection for analysis/export; the page files preserve all raw returned reviews, including duplicates and unknown fields.

The manifest records schema version, identity, fixed page size, next page, saved pages, source page/total metadata, raw/duplicate/unique counts, status, stop reason, timestamps, and a hash of the unique dataset. Page files and JSON/JSONL replacements are atomic.

## State machine

The bundled Python helper is the only authority for collection state:

```text
absent --init--> collecting --save-page--> collecting
                              | terminal page / 2,000 cap
                              v
                           complete
collecting --record-error--> partial | blocked-empty
complete/partial --finalize-html--> receipt-backed
```

Before the first MCP request, initialize the matching collection. Before every later MCP request—including after context compression—run the helper's `next-request` command. It reconstructs state from saved page files and returns exactly one permitted request containing the immutable marketplace, ASIN, normalized filters, `next_page`, and `size: 20`.

`next-request` atomically records `pendingRequest` before returning an authorization. It refuses to authorize a call when the state is complete, partial, blocked-empty, receipt-backed, or already has an uncommitted pending request. It never authorizes an already saved or pending page. If compression happens after authorization but before persistence, the next process returns `REQUEST_PENDING` and stops rather than spending another MCP call. `save-page` accepts only the authorized next page, checks that returned `data.page` and `data.size` preserve the pagination contract, atomically saves the page, rebuilds aggregate data, clears the pending request, and only then advances `next_page`.

The server response supplied by the user establishes `size: 20`: `total: 433`, `pages: 22`, and `size: 20`. Request and manifest page size are therefore fixed at 20. If the first or any later response reports a different size, stop with a pagination-contract error; never silently change size within a collection.

A collection becomes complete without probing an extra page when any of these is true:

- the saved page number reaches the documented `data.pages` value;
- the saved page returns fewer than 20 reviews;
- the saved raw record count reaches 2,000.

If source totals/pages are absent, an empty page may be saved as the terminal signal. Never request page `data.pages + 1` merely to confirm the end.

## Context recovery and no-repeat guarantee

Conversation history, progress narration, and summary `.txt` files are never collection state. On every new turn or resumed context, run `status`/`next-request` against the canonical identity before deciding whether MCP may be called.

- Saved page files are idempotent: the same page with the same content is accepted as already saved; conflicting content for an existing page blocks collection.
- A gap or corrupt page blocks collection and requires repair or explicit user direction.
- A missing/corrupt cache after collection has begun must never trigger an automatic refresh.
- A matching valid receipt points to an HTML file containing the full embedded review dataset and blocks MCP calls permanently unless the user explicitly requests a refresh.
- A matching legacy `review-collection-summary-*.txt` without full cached reviews causes `init` to return `LEGACY_SUMMARY_ONLY` and blocks automatic crawling. The old summary cannot reconstruct comments; only an explicit user refresh may bypass the guard.

## HTML handoff and cache cleanup

Every analysis or review-display HTML embeds all deduplicated reviews in an offline JSON block:

```html
<script type="application/json" id="review-data">[...]</script>
```

Review text must be safely JSON-escaped for HTML. Before dataset comparison, `finalize-html` calls `scripts/validate_report.py` logic to check executable inline JavaScript syntax with Node.js, analysis-tab or review-browser interaction bindings, the offline download binding, and the embedded JSON. It then compares the review count and dataset hash with the manifest. Only after every check succeeds may it write the durable receipt and delete the collection directory. Any validation failure preserves the complete live cache and must be repaired from the local export without calling SellerSprite again.

The receipt remains in `.amazon-review-insights-cache/receipts/` and records collection identity, HTML path, file hash, dataset hash, review count, source status, and completion time. Later HTML, Excel, or analysis requests recover reviews from that verified HTML/receipt rather than SellerSprite. If the HTML is missing or corrupt, stop and ask the user; never silently crawl again.

## MCP result handling

Successful page responses have `code: "OK"` with pagination under `data`. The helper expects the review list at `data.content` and preserves each review object without dropping unknown fields. The known fields include `author`, `title`, `content`, `date`, `star`, `authorLabels`, `skus`, `images`, `videos`, `likes`, `image`, `video`, `verified`, `vine`, `free`, and `experience`.

When the response is `ERROR_VISIT_MAX`, no next request is permitted:

- With saved reviews, persist the exact code/message and mark the collection `partial`; offer analysis, review-display HTML, or Excel from the partial local data.
- With no reviews, persist only control state as `blocked-empty` (not an empty review dataset) and state exactly: `当前尚未爬取到任何评论，请确定 MCP 是否有使用次数。`

Unknown errors use the same stop-first behavior and preserve their exact code/message.

## Script interface

`amazon-review-insights/scripts/review_cache.py` uses the Python standard library only and exposes:

- `init`: create or inspect the canonical collection before the first call; refuse a receipt-backed collection unless `--refresh` is explicitly supplied.
- `status`: reconcile page files and print durable state as JSON.
- `next-request`: print the only MCP request that may be issued, or return a blocking non-zero exit.
- `save-page --response-file`: persist a successful full response before another call.
- `record-error --response-file`: persist a stopped/partial state.
- `export-json --output`: materialize all deduplicated reviews and metadata from the collection or receipt-backed HTML without MCP.
- `finalize-html --html`: verify the embedded full review dataset, write a receipt, and remove only the matching collection directory.

`amazon-review-insights/scripts/validate_report.py` validates a standalone report independently before delivery. It rejects JavaScript syntax errors, missing or unbound navigation/review-browser controls, external scripts, missing offline download behavior, and invalid/missing `review-data`.

If Python is unavailable, the Skill must stop before the first MCP request. It may not collect reviews without the durable helper.

## Required behavioral tests

Tests execute the real helper in separate processes and prove:

1. page 1 is durable and a fresh process authorizes page 2, never page 1;
2. a second process cannot reauthorize an uncommitted pending page;
3. `size` stays 20 and a conflicting returned size is rejected without advancing state;
4. saving a page twice is idempotent while conflicting duplicate content is blocked;
5. the last documented page completes without authorizing an extra probe page;
6. all input review fields survive raw-page persistence and JSON export;
7. complete, partial, blocked-empty, and receipt-backed states refuse MCP authorization;
8. `ERROR_VISIT_MAX` preserves non-empty partial data and blocks empty retries;
9. HTML finalization requires a matching embedded review count/hash before cache deletion;
10. receipt-backed export reads the verified HTML after raw cache deletion;
11. existing standalone report contract and Skill validation remain green.
