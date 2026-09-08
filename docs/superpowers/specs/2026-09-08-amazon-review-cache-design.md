# Amazon Review Insights temporary review cache design

## Goal

Prevent repeat SellerSprite MCP calls after a review collection has completed or partially completed. A local cache becomes the single input for all follow-on analysis and export work. It is deleted only after the user has obtained every requested artifact for the current task.

## Scope

This design changes the Skill workflow only. It does not add credentials, direct SellerSprite HTTP requests, a database, or long-term review retention.

## Cache artifact

After collection, write one UTF-8 JSON cache in the active workspace:

```text
.amazon-review-insights-cache/
  review-cache-<marketplace>-<asin>-<filter-key>.json
```

`filter-key` deterministically represents the selected `starList` and `typeList`, so a filtered collection cannot be confused with an unfiltered one. The cache contains:

- Cache schema version and creation timestamp.
- `marketplace`, `asin`, `starList`, `typeList`, pages retrieved, raw count, duplicate count, and unique count.
- SellerSprite source status: documented source total when available, completed collection, or partial collection status.
- Every normalized raw record and every unique normalized review, retaining the documented response fields.
- The failure code and message when collection stopped because of a known MCP error.

Write the cache only after each successful page is normalized and merged, replacing it atomically so a task interruption still leaves the newest complete state. Never store credentials or full raw MCP envelopes.

## Workflow

```text
SellerSprite MCP → normalize, deduplicate, and checkpoint JSON cache
                                      ↓
                    user chooses one or more cached-data outputs
                       ├─ built-in or custom analysis → complete analysis HTML
                       ├─ review-display HTML → paged/filterable full review file
                       └─ Excel (.xlsx) → all unique reviews and metadata
                                      ↓
                verify every requested artifact exists and is non-empty
                                      ↓
                         delete only the matching cache JSON
```

Every output reads the matching cache, never calls SellerSprite again. If a matching cache exists before a new collection request, offer to use it. A new fetch is allowed only when the user explicitly asks to refresh, changes marketplace/ASIN/filters, or the cache is absent.

The cache remains available while the user chooses additional outputs. It is deleted only after all outputs requested in the current task have been written and verified as non-empty. If output generation fails, the user pauses, or the task stops, preserve the cache for retry. The cache file name and status are reported to the user while it exists.

## MCP visit-limit handling

When the MCP result is exactly:

```json
{
  "code": "ERROR_VISIT_MAX",
  "message": "接口访问次数已达上限"
}
```

stop collection immediately and make no further page requests.

- If at least one unique review is already cached, write/keep a partial cache with the code and message. Tell the user that the MCP visit limit is exhausted and offer: analyze the existing comments, download review-display HTML, or download Excel. Every resulting artifact must identify the data as partial and name the MCP visit-limit cause.
- If no review has been collected, do not create an empty review cache. Tell the user: `当前尚未爬取到任何评论，请确定 MCP 是否有使用次数。`

Never claim that a partial cache is complete or Amazon-wide.

## Output requirements

The analysis HTML retains the existing offline dashboard and full Voice of Customer contract. The review-display HTML is a standalone offline file containing all cached unique reviews, with local fuzzy search, star filters, 20 reviews per page, and all available metadata. The Excel export contains one row per unique review, the documented review fields, normalized date, evidence classification/tags when generated, and collection metadata in a separate sheet or clearly labelled metadata block.

## Error handling and tests

Tests will prove that the Skill requires:

1. checkpointing all completed pages to the cache;
2. cache reuse for every output with no MCP call;
3. cleanup only after every requested artifact verifies successfully;
4. cache preservation on failure or paused work; and
5. the exact `ERROR_VISIT_MAX` branches for non-empty and empty collections.

Skill validation and the existing report-contract test suite must remain green.
