# Multi-ASIN Amazon Review Insights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable two-to-five-ASIN collection workflow and one provenance-preserving joint HTML analysis report.

**Architecture:** Keep the existing lossless collection and pending-request guard per ASIN. Add a batch orchestrator that delegates to those states, exports unchanged review objects with a parallel ASIN source index, and finalizes one verified HTML into batch-aware per-ASIN receipts.

**Tech Stack:** Python 3 standard library, `unittest`/`pytest`, standalone HTML/CSS/JavaScript, Markdown skill instructions.

**Spec:** `docs/superpowers/specs/2026-09-15-amazon-review-insights-multi-asin-design.md`

## Global Constraints

- SellerSprite MCP requests always use `size: 50`.
- A batch has two through five unique ASINs, one marketplace, and one normalized filter set.
- The default target is 2,000 reviews per ASIN; a custom target is 50–2,000 and divisible by 50.
- Never authorize an MCP call from conversation history; durable local state is authoritative.
- Preserve every review object unchanged and losslessly.
- Joint analysis uses equal-ASIN weighting and retains raw counts and ASIN provenance.
- HTML is fully offline, bilingual, downloadable, full-width, and shows all reviews 20 per page.
- Product content uses only explicitly supplied target-product facts.

---

### Task 1: Durable batch collection and export

**Files:**
- Create: `amazon-review-insights/scripts/batch_review_cache.py`
- Modify: `amazon-review-insights/scripts/review_cache.py`
- Modify: `tests/test_review_cache.py`
- Create: `tests/test_batch_review_cache.py`

**Interfaces:**
- Consumes: existing `CollectionPaths`, `command_init`, `command_next_request`, `command_save_page`, `command_record_error`, and `export_bundle` behavior.
- Produces: CLI commands `init`, `status`, `next-request`, `save-page`, `record-error`, and `export-json`; exported JSON keys `metadata`, `datasets`, `reviews`, and `sourceIndex`.

- [ ] **Step 1: Write failing tests for persisted member target limits**

```python
def test_custom_limit_stops_after_complete_fifty_record_pages(self):
    self.run_cache("init", "--limit", "100")
    self.save_page(1, 50, total=500, pages=10)
    self.save_page(2, 50, total=500, pages=10)
    blocked = self.run_cache("next-request", expect=2)
    self.assertEqual(blocked["status"], "capped")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/test_review_cache.py -k custom_limit -q`
Expected: FAIL because `--limit` is not accepted and no target limit is persisted.

- [ ] **Step 3: Implement the minimal persisted target-limit behavior**

Add `DEFAULT_COLLECTION_LIMIT = 2000`; validate `50 <= limit <= 2000 and limit % 50 == 0`; save `targetLimit` in the manifest; make reconciliation stop at that target; default legacy manifests to 2,000.

- [ ] **Step 4: Run focused and existing cache tests GREEN**

Run: `python -m pytest tests/test_review_cache.py -q`
Expected: all tests pass.

- [ ] **Step 5: Write failing batch orchestration tests**

```python
def test_batch_export_preserves_reviews_and_parallel_source_index(self):
    batch = self.init_batch(["B000000001", "B000000002"])
    self.complete_member(batch, "B000000001", [{"content": "one"}])
    self.complete_member(batch, "B000000002", [{"content": "two"}])
    exported = self.export_batch(batch)
    self.assertEqual(exported["reviews"], [{"content": "one"}, {"content": "two"}])
    self.assertEqual([x["asin"] for x in exported["sourceIndex"]], ["B000000001", "B000000002"])
```

Also cover 1/6 ASIN rejection, duplicate rejection, order-insensitive batch identity, per-ASIN pending-request blocking, partial-member isolation, and completed/receipt-backed member reuse.

- [ ] **Step 6: Run batch tests and verify RED**

Run: `python -m pytest tests/test_batch_review_cache.py -q`
Expected: FAIL because `batch_review_cache.py` does not exist.

- [ ] **Step 7: Implement minimal batch manifest, delegation, and export**

Use an atomic JSON manifest under `.amazon-review-insights-cache/batches/<batch-id>/manifest.json`. Delegate page state changes to `review_cache.py`; flatten datasets in saved display order and append one `{marketplace, asin}` source entry per review.

- [ ] **Step 8: Run Task 1 tests GREEN and commit**

Run: `python -m pytest tests/test_review_cache.py tests/test_batch_review_cache.py -q`
Expected: all tests pass.

Commit: `feat: add durable multi-asin review batches`

---

### Task 2: Batch HTML validation, receipts, and safe cleanup

**Files:**
- Modify: `amazon-review-insights/scripts/validate_report.py`
- Modify: `amazon-review-insights/scripts/review_cache.py`
- Modify: `amazon-review-insights/scripts/batch_review_cache.py`
- Modify: `tests/test_report_validator.py`
- Modify: `tests/test_batch_review_cache.py`

**Interfaces:**
- Consumes: Task 1 `reviews` plus `sourceIndex` export contract.
- Produces: optional `review-source-index` validation; `finalize-html` batch command; batch-aware receipts recoverable by single-ASIN `export-json`.

- [ ] **Step 1: Write failing validator tests**

```python
def test_rejects_batch_source_index_length_mismatch(self):
    html = self.valid_report(reviews=[{"content": "a"}], source_index=[])
    result = self.run_validator(html)
    self.assertEqual(result["error"], "REVIEW_SOURCE_INDEX_MISMATCH")
```

Also test invalid source objects and successful validation of matching entries.

- [ ] **Step 2: Run focused validator tests and verify RED**

Run: `python -m pytest tests/test_report_validator.py -k source_index -q`
Expected: FAIL because the source-index block is ignored.

- [ ] **Step 3: Implement source-index parsing and validation**

Parse `script#review-source-index` when present, require an array equal in length to `review-data`, and require non-empty string `marketplace` and `asin` fields for each item. Keep single-ASIN reports valid when the block is absent.

- [ ] **Step 4: Write failing finalization and receipt-recovery tests**

```python
def test_finalize_batch_writes_member_receipts_then_removes_live_caches(self):
    result = self.finalize_valid_batch_html()
    self.assertEqual(result["status"], "receipt-backed")
    self.assertFalse(self.member_collection_path("B000000001").exists())
    recovered = self.export_single_member("B000000001")
    self.assertEqual(recovered["reviews"], self.member_one_reviews)
```

Also prove that one mismatched member hash preserves every cache and writes no usable final receipt.

- [ ] **Step 5: Run batch finalization tests and verify RED**

Run: `python -m pytest tests/test_batch_review_cache.py -k finalize -q`
Expected: FAIL because `finalize-html` and batch-aware receipt selection are absent.

- [ ] **Step 6: Implement validate-all-then-finalize behavior**

Reconstruct per-ASIN arrays with `zip(review-data, review-source-index)`, verify every member count/hash first, write batch-aware receipts atomically, and only then remove live collection directories. Extend receipt reading to select the receipt ASIN from a combined HTML.

- [ ] **Step 7: Run Task 2 tests GREEN and commit**

Run: `python -m pytest tests/test_report_validator.py tests/test_review_cache.py tests/test_batch_review_cache.py -q`
Expected: all tests pass.

Commit: `feat: verify joint reports without repeat crawling`

---

### Task 3: Joint VOC analysis contract and portable Skill workflow

**Files:**
- Modify: `amazon-review-insights/references/built-in-analysis-prompt.md`
- Modify: `amazon-review-insights/SKILL.md`
- Modify: `README.md`
- Modify: `tests/test_html_contract.py`

**Interfaces:**
- Consumes: Task 1 batch commands and Task 2 HTML/receipt contract.
- Produces: portable interaction workflow and ten-view joint report specification with all-review ASIN filtering.

- [ ] **Step 1: Write failing behavior-contract tests**

Create a representative batch HTML fixture and assert through the validator/runtime harness that it exposes working tabs for `shared-intents`, `shared-gaps`, and `asin-differences`, plus an ASIN selector that filters the visible Voice of Customer results without altering `review-data`.

- [ ] **Step 2: Run the focused contract tests and verify RED**

Run: `python -m pytest tests/test_html_contract.py -k multi_asin -q`
Expected: FAIL because the existing contract has no joint-analysis views or ASIN filter.

- [ ] **Step 3: Update the built-in prompt**

Define `ceil(0.6 × ASIN count)` coverage for shared findings, equal-ASIN rate averaging, raw-count disclosure, cross-ASIN duplicate evidence families, the ASIN difference matrix, target-product fact boundaries, and the ten-view navigation/ASIN-filter runtime.

- [ ] **Step 4: Update SKILL.md and README**

Document one-ASIN backward compatibility, the two-to-five-ASIN flow, one common marketplace/filter set, the default/custom page-aligned cap, durable batch recovery after context compression, partial-member decisions, batch export/finalization, execution estimates, and optional parallel collection with exactly one writer per ASIN.

- [ ] **Step 5: Run the complete suite GREEN and validate the skill**

Run: `python -m pytest -q`
Expected: all tests pass.

Run: `python C:/Users/jjh09/.codex/skills/.system/skill-creator/scripts/quick_validate.py amazon-review-insights`
Expected: `Skill is valid!`

- [ ] **Step 6: Install and verify local parity**

Replace only `C:/Users/jjh09/.codex/skills/amazon-review-insights` with the verified source directory, then compare recursive SHA-256 manifests for exact parity.

- [ ] **Step 7: Commit**

Commit: `feat: analyze multiple asins in one voc report`

