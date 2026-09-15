# Multi-ASIN Amazon Review Insights Design

## Objective

Extend Amazon Review Insights from a single-ASIN workflow to one batch of two through five same-category ASINs. Each ASIN remains an independently recoverable collection, while one combined offline HTML reports shared consumer intents, shared product gaps, and ASIN-level differences.

## Inputs and interaction

- Accept one ASIN for backward-compatible single-product work or two through five ASINs for joint analysis.
- Require one explicit marketplace for the batch. Never infer it.
- Ask once for optional `starList` and `typeList`; apply the same filters to every ASIN.
- Ask whether to use the default 2,000-review limit per ASIN. A smaller limit must be 50–2,000 and divisible by 50 because MCP requests always use `size: 50`.
- After collection, ask whether to analyze or export. Analysis asks for built-in versus attached custom prompt. Custom prompts still produce the complete offline HTML.
- Listing, A+, and Design Brief are for one target product. They require the target product’s top three features plus material/composition/specifications; compared-ASIN reviews are not target-product facts.

## Collection architecture

Create a batch manifest under `.amazon-review-insights-cache/batches/<batch-id>/manifest.json`. Its canonical ID is derived from marketplace, sorted unique ASINs, normalized filters, and requested limit, while its display order preserves the user’s order.

Each ASIN continues to use its own existing collection identity and page files. Batch commands delegate page authorization, saving, and errors to the single-ASIN helper. A batch command may operate on one selected ASIN, which permits safe parallel work when a host supports multiple agents; only one writer may handle any given ASIN.

Before every MCP call, including after context compression, read batch status and request authorization from disk. Completed, capped, partial, blocked, pending, or receipt-backed members never receive another automatic call. A failed ASIN does not erase successful members.

## Review limit

New collections default to 2,000 reviews. A user-selected lower target is stored in the member manifest and stops the collection after the exact number of complete 50-record pages. An existing local dataset larger than a newly requested limit is reused in full because no new retrieval is required. A receipt-backed smaller dataset is never silently expanded; expansion requires an explicit refresh decision.

## Combined dataset contract

Batch export contains member metadata, the original per-ASIN review arrays, one flattened review list in deterministic member order, and a parallel same-length source index. The source index records marketplace and ASIN without mutating any source review object.

The HTML embeds:

```html
<script type="application/json" id="review-data">[...unchanged review objects...]</script>
<script type="application/json" id="review-source-index">[{"marketplace":"US","asin":"B000..."}, ...]</script>
```

The validator requires equal lengths and valid source entries. Batch finalization reconstructs each member dataset from the two arrays and compares count and SHA-256 with its local cache or receipt before any cache deletion.

## Joint analysis method

- Classify and summarize reviews in 50-review analysis batches.
- Deduplicate within each ASIN for all metrics.
- Preserve cross-ASIN duplicate copies in Voice of Customer, but group identical cross-ASIN evidence for shared-theme counting.
- Build 5–8 shared intent clusters from usage goal, situation, desired outcome, and conflict—not generic product parameters.
- A shared intent or gap requires evidence from at least `ceil(0.6 × ASIN count)` ASINs. Show raw evidence count, ASIN coverage, per-ASIN rate, and the equal-weight mean of per-ASIN rates.
- The difference view shows each ASIN’s over-indexed intents, strengths, weaknesses, unique gaps, normalized negative-signal rate, star mix, and verbatim evidence.
- Call combined conclusions `Inference`; do not claim access to Amazon algorithm internals.

## HTML information architecture

The full-width, offline, bilingual Material-style report contains these navigation views:

1. Overview
2. Shared Intents / 共同意图
3. Shared Gaps / 共性缺口
4. ASIN Differences / ASIN 差异
5. Opportunities
6. Listing & A+
7. Design Brief
8. Voice of Customer
9. Data & Method
10. Limitations

Voice of Customer contains every review and adds an ASIN filter to existing fuzzy search, star filter, verified-purchase display, and 20-item pagination. Original review text remains visible.

## Finalization and recovery

Validate JavaScript, navigation, download, the complete review array, the source index, and every per-ASIN dataset hash. Only after all checks pass may the helper write a batch receipt plus compatible per-ASIN receipts and remove live member caches. Each receipt points to the verified joint HTML and knows how to select its ASIN’s reviews.

If validation fails, preserve every cache and regenerate only from local JSON. If some ASINs are partial because MCP limits are exhausted, show their exact failure codes and let the user choose whether to continue with existing data.

