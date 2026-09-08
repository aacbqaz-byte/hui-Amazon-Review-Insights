# Durable Amazon Review Collection State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an executable, crash-safe review collection state machine so context compression or process restart can never repeat an already saved SellerSprite page.

**Architecture:** A Python-standard-library CLI owns collection state. Atomic page files are the source of truth, a reconciled manifest authorizes exactly one next MCP request with immutable `size: 20`, and verified offline HTML becomes the durable post-cleanup source through a receipt. Skill prose routes agents through the CLI instead of relying on conversational memory.

**Tech Stack:** Python 3 standard library, JSON/JSONL, SHA-256, `unittest`, Markdown Skill instructions, standalone offline HTML.

**Spec:** `docs/superpowers/specs/2026-09-08-amazon-review-cache-design.md`

## Global Constraints

- The helper is initialized before the first MCP call and consulted before every subsequent MCP call; an atomic pending authorization prevents the same uncommitted page from being released twice.
- A saved page, terminal collection, partial/error state, blocked-empty state, or valid receipt can never authorize an automatic MCP retry.
- A matching legacy summary without full reviews blocks initialization unless the user explicitly requests refresh.
- Pagination size is immutable at `20`; collection stops at 2,000 raw records.
- Raw page files preserve every returned review object; aggregate export preserves every unique review and unknown fields.
- Every file replacement that advances collection state is atomic.
- HTML cache cleanup occurs only after embedded dataset count/hash verification; a durable receipt remains.
- Receipt-backed later outputs read the HTML and do not call SellerSprite.
- No direct HTTP requests, credentials, third-party Python packages, or external HTML resources are introduced.

---

### Task 1: Define executable state-machine behavior

**Files:**
- Create: `tests/test_review_cache.py`
- Create later in Task 2: `amazon-review-insights/scripts/review_cache.py`

**Interfaces:**
- Consumes: CLI commands and JSON SellerSprite fixtures with pagination under `data` and reviews under `data.content`.
- Produces: subprocess-level regression tests for durable paging, immutable size, idempotency, stop states, export, HTML verification, and receipt recovery.

- [ ] **Step 1: Write subprocess test helpers and a first-page fixture**

Create tests that invoke `python amazon-review-insights/scripts/review_cache.py`, use a temporary workspace, and supply a complete response fixture containing every documented review field plus an unknown field. Expected values must be hand-written literals.

- [ ] **Step 2: Add failing recovery and no-repeat tests**

Require `init` then `next-request` to return page 1/size 20; a second process must receive `REQUEST_PENDING` until that response is committed. After `save-page`, a new CLI process must return page 2/size 20. Require repeated identical page saves to be idempotent and conflicting saves to fail.

- [ ] **Step 3: Add failing terminal/error tests**

Require the final documented page to set `complete` and make `next-request` fail without page+1. Require `ERROR_VISIT_MAX` to set `partial` when reviews exist and `blocked-empty` otherwise; both must block new calls.

- [ ] **Step 4: Add failing export/finalization tests**

Require all review fields in `export-json`. Create an offline HTML fixture with `<script type="application/json" id="review-data">`; require mismatched data to preserve cache, matching data to create a receipt and remove the collection, and receipt-backed export to reproduce all reviews.

- [ ] **Step 5: Run and verify RED**

Run `python -m unittest tests.test_review_cache -v` and confirm failure because `review_cache.py` does not exist.

### Task 2: Implement the durable cache helper

**Files:**
- Create: `amazon-review-insights/scripts/review_cache.py`
- Test: `tests/test_review_cache.py`

**Interfaces:**
- CLI identity arguments: `--workspace`, `--marketplace`, `--asin`, repeated/comma-separated `--stars`, and `--types`.
- Commands: `init`, `status`, `next-request`, `save-page --response-file`, `record-error --response-file`, `export-json --output`, and `finalize-html --html`.
- JSON stdout contains `ok`, `action`/`status`, collection paths, counts, and the authorized request when applicable. Blocking conditions return non-zero.

- [ ] **Step 1: Implement identity, atomic JSON writes, and manifest creation**

Normalize marketplace/ASIN, sorted unique filters, canonical identity, cache paths, and schema-2 manifest. `init` creates control state before any call and refuses a valid matching receipt unless explicit refresh is requested.

- [ ] **Step 2: Implement reconciliation and guarded next request**

Scan contiguous page files, validate page numbers/size, rebuild raw and deduplicated projections, update counts/hash atomically, and authorize only the manifest's next page with `size: 20` while status is `collecting`. Persist `pendingRequest` before returning it and fail closed on a repeated authorization attempt.

- [ ] **Step 3: Implement page and error persistence**

Validate `code`, `data.page`, `data.size`, and `data.content`; store a sanitized complete page record atomically. Accept an identical existing page idempotently and block a conflicting one. Record exact error code/message and move to `partial` or `blocked-empty` without authorizing another request.

- [ ] **Step 4: Implement export and verified HTML handoff**

Export from live aggregate data or from a receipt-verified HTML JSON block. For `finalize-html`, parse the block, canonicalize/hash reviews, compare to manifest, write the receipt, then delete only the exact collection directory.

- [ ] **Step 5: Run and verify GREEN**

Run `python -m unittest tests.test_review_cache -v`, then `python -m unittest discover -s tests -v`. All tests must pass without warnings.

### Task 3: Route the Skill through the helper

**Files:**
- Modify: `amazon-review-insights/SKILL.md`
- Modify: `amazon-review-insights/references/built-in-analysis-prompt.md`
- Modify: `tests/test_html_contract.py`

**Interfaces:**
- Consumes: helper JSON decisions and local export JSON.
- Produces: an agent workflow that never relies on conversation memory or summary text for collection progress.

- [ ] **Step 1: Write failing Skill integration assertions**

Update contract tests to require the executable helper path, `size: 20`, initialization before the first MCP call, `next-request` before every call/resume, immediate `save-page`, no page+1 probe, HTML `review-data` embedding, receipt-backed recovery, and a hard stop if Python/cache integrity is unavailable.

- [ ] **Step 2: Run the focused tests and verify RED**

Run `python -m unittest tests.test_html_contract -v`; confirm the new assertions fail against the prose-only workflow.

- [ ] **Step 3: Replace prose-only cache instructions with CLI protocol**

Update collection to use page size 20 and the helper sequence. Explicitly state that summaries/progress messages are not durable state, that raw MCP results must be saved before any next request, and that after context compression disk status is authoritative.

- [ ] **Step 4: Update offline HTML data contract**

Require every analysis/review-display HTML to embed all deduplicated reviews in the `review-data` JSON block, safely escaped, so `finalize-html` can verify and later recover them.

- [ ] **Step 5: Run all tests**

Run `python -m unittest discover -s tests -v`; all tests must pass.

### Task 4: Validate, independently forward-test, and install

**Files:**
- Source: `amazon-review-insights/**`
- Install: `C:\Users\jjh09\.codex\skills\amazon-review-insights\**`

**Interfaces:**
- Consumes: validated source Skill.
- Produces: byte-matched local Codex installation and an independent behavioral review.

- [ ] **Step 1: Run Skill Creator validation**

Run the bundled `quick_validate.py` against the source Skill with UTF-8 enabled.

- [ ] **Step 2: Run an independent forward test**

Give a subagent only the updated Skill and a realistic interrupted-collection scenario. It must report which page would be requested after restart and whether a completed/receipt-backed collection could call MCP.

- [ ] **Step 3: Copy the full Skill directory to the installed location**

Copy `SKILL.md`, the reference prompt, and `scripts/review_cache.py`; remove no unrelated files. Verify SHA-256 equality for every copied source file.

- [ ] **Step 4: Validate the installed Skill and rerun tests**

Validate `C:\Users\jjh09\.codex\skills\amazon-review-insights` and run the full local test suite once more.

## Self-review

- Spec coverage: durable paging, immutable size 20, no page+1 probe, exact error states, raw/unique preservation, HTML verification, receipt recovery, and installed synchronization are each assigned to a task.
- Placeholder scan: no placeholder implementation steps or unspecified error handling remain.
- Interface consistency: command names, cache paths, `data.content`, `review-data`, status names, page size, and the 2,000 cap match the spec.
