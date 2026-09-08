# Temporary Amazon Review Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist each collected SellerSprite review set locally until every user-requested HTML or Excel artifact has been delivered, so report generation never repeats MCP collection.

**Architecture:** The Skill writes one temporary, filter-keyed JSON checkpoint in `.amazon-review-insights-cache/` after every successful normalized page. All analysis, review-display HTML, and Excel exports consume that cache. A successful verified artifact advances the current task's requested-output set; only when that set is empty is the matching cache deleted. `ERROR_VISIT_MAX` stops collection and routes to either partial-cache output choices or the no-comments warning.

**Tech Stack:** Markdown `SKILL.md` workflow instructions, UTF-8 JSON cache artifacts, standalone HTML, optional `.xlsx` export through an available local spreadsheet runtime, Python `unittest`, Skill Creator validator.

**Spec:** `docs/superpowers/specs/2026-09-08-amazon-review-cache-design.md`

## Global Constraints

- Do not make direct SellerSprite HTTP requests, install an MCP, or store credentials.
- Cache path is `.amazon-review-insights-cache/review-cache-<marketplace>-<asin>-<filter-key>.json` in the active workspace.
- Cache fields include source status, collection metadata, normalized raw records, and deduplicated reviews; no raw credential-bearing MCP envelope is stored.
- Analysis HTML, review-display HTML, and `.xlsx` export read the matching cache and never call SellerSprite again.
- Delete a cache only after every artifact requested in the current task exists and is non-empty; preserve it for pauses, failures, or unrequested future outputs.
- On `ERROR_VISIT_MAX`, stop immediately. Keep a partial non-empty cache; do not write an empty cache.
- Preserve the existing 2,000 cap, evidence rules, full offline HTML contract, and all current report UI requirements.

---

### Task 1: Add cache-workflow contract tests

**Files:**
- Modify: `tests/test_html_contract.py`

**Interfaces:**
- Consumes: `amazon-review-insights/SKILL.md` and `amazon-review-insights/references/built-in-analysis-prompt.md` as the agent-consumed workflow contract.
- Produces: regression coverage for cache creation, reuse, cleanup, partial-data handling, and output choices.

- [ ] **Step 1: Write the failing test**

Add a new `unittest` method that reads `ENTRYPOINT` and requires these cache behavior phrases:

```python
def test_collection_contract_checkpoints_and_reuses_review_cache(self):
    contract = ENTRYPOINT.read_text(encoding="utf-8")
    required_fragments = (
        ".amazon-review-insights-cache",
        "review-cache-<marketplace>-<asin>-<filter-key>.json",
        "after every successful page",
        "reuse the matching cache",
        "never call SellerSprite again",
        "every artifact requested in the current task",
        "ERROR_VISIT_MAX",
        "当前尚未爬取到任何评论，请确定 MCP 是否有使用次数。",
        "review-display HTML",
        ".xlsx",
    )
    missing = [item for item in required_fragments if item not in contract]
    self.assertEqual(missing, [], f"Missing review-cache requirements: {missing}")
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```powershell
python -m unittest tests.test_html_contract.HtmlContractTests.test_collection_contract_checkpoints_and_reuses_review_cache
```

Expected: `FAIL` listing the missing cache-workflow requirements.

- [ ] **Step 3: Commit the failing test**

```powershell
git add -- tests/test_html_contract.py
git commit -m "test: define temporary review cache contract"
```

### Task 2: Define checkpoint, reuse, and cleanup in the Skill entrypoint

**Files:**
- Modify: `amazon-review-insights/SKILL.md`
- Test: `tests/test_html_contract.py`

**Interfaces:**
- Consumes: normalized pages from the configured `sellersprite-mcp` / `review` capability.
- Produces: one cache JSON keyed by marketplace, ASIN, and optional filters; a current-task requested-output ledger; cache reuse instructions for later user requests.

- [ ] **Step 1: Extend the collection workflow after deduplication**

Add a `## Temporary local cache` section directly after `## Collect reviews`. Require agents to:

```markdown
- Serialize UTF-8 JSON to `.amazon-review-insights-cache/review-cache-<marketplace>-<asin>-<filter-key>.json` after every successful page has been normalized, deduplicated, and merged.
- Store schema version, creation time, ASIN, marketplace, exact filters, pages retrieved, raw/duplicate/unique counts, SellerSprite source status, normalized raw records, and unique records.
- Replace the same JSON checkpoint atomically; never persist credentials or a full MCP envelope.
- Before any new collection, reuse the matching cache if it exists and tell the user which file is being reused. Do not call SellerSprite again unless the user explicitly requests refresh, changes ASIN/marketplace/filters, or no matching cache exists.
```

- [ ] **Step 2: Define output-set lifecycle and cleanup**

Add this explicit state transition to the same section:

```markdown
Record every artifact the user requests in the current task. Generate each artifact only from the matching cache. After each artifact is written, verify that its local file exists and has non-zero size. Delete the matching cache only when every artifact requested in the current task has passed that verification. If analysis/export fails, the user pauses, or further outputs remain possible, preserve the cache and report its path.
```

- [ ] **Step 3: Run the focused cache test and make it pass**

Run:

```powershell
python -m unittest tests.test_html_contract.HtmlContractTests.test_collection_contract_checkpoints_and_reuses_review_cache
```

Expected: `OK`.

- [ ] **Step 4: Commit the cache entrypoint workflow**

```powershell
git add -- amazon-review-insights/SKILL.md tests/test_html_contract.py
git commit -m "feat: cache collected Amazon reviews before output"
```

### Task 3: Define partial-data routing and cached output formats

**Files:**
- Modify: `amazon-review-insights/SKILL.md`
- Modify: `amazon-review-insights/references/built-in-analysis-prompt.md`
- Test: `tests/test_html_contract.py`

**Interfaces:**
- Consumes: the cache from Task 2 and a SellerSprite result with `code: "ERROR_VISIT_MAX"` when applicable.
- Produces: partial-data disclosure in analysis HTML, review-display HTML, and `.xlsx` export rules.

- [ ] **Step 1: Write the failing partial-artifact test**

Add this new method to `tests/test_html_contract.py`:

```python
def test_partial_cache_contract_preserves_reviews_after_visit_limit(self):
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    reference = REFERENCE.read_text(encoding="utf-8")
    self.assertIn('code: "ERROR_VISIT_MAX"', entrypoint)
    self.assertIn("review-display HTML", entrypoint)
    self.assertIn(".xlsx", entrypoint)
    self.assertIn("all cached unique reviews", entrypoint)
    self.assertIn("ERROR_VISIT_MAX", reference)
    self.assertIn("partial", reference)
```

- [ ] **Step 2: Run the partial-artifact test and verify it fails**

Run:

```powershell
python -m unittest tests.test_html_contract.HtmlContractTests.test_partial_cache_contract_preserves_reviews_after_visit_limit
```

Expected: `FAIL` because neither the visit-limit/output contract nor the partial-source disclosure exists.

- [ ] **Step 3: Add the exact visit-limit branch to `SKILL.md`**

Require this behavior inside collection:

```markdown
If the result has `code: "ERROR_VISIT_MAX"`, stop immediately and do not request another page. If the cache has at least one unique review, mark it partial with the returned code/message and offer: analyze existing comments, download review-display HTML, or download Excel. If no review exists, do not write an empty cache and state exactly: `当前尚未爬取到任何评论，请确定 MCP 是否有使用次数。`
```

- [ ] **Step 4: Add cached artifact definitions**

In `SKILL.md`, add exact contracts for:

```markdown
- Analysis HTML: use the built-in/custom prompt and all cached unique reviews.
- review-display HTML: standalone offline file with every cached unique review, all available metadata, local fuzzy search, star filters, and 20 reviews per page.
- Excel `.xlsx`: one row per cached unique review, documented review fields, normalized date, and collection metadata in a labelled metadata sheet or block. Use an available local spreadsheet runtime; if none is available, say so before attempting export.
```

- [ ] **Step 5: Add partial-source disclosure to the report reference**

In `built-in-analysis-prompt.md`, require every artifact produced from a partial cache to visibly state that SellerSprite MCP collection stopped because of `ERROR_VISIT_MAX`, include collected/unique counts, and never describe the dataset as complete or Amazon-wide.

- [ ] **Step 6: Run all contract tests**

Run:

```powershell
python -m unittest tests.test_html_contract
```

Expected: all tests report `OK`.

- [ ] **Step 7: Commit partial routing and export contracts**

```powershell
git add -- amazon-review-insights/SKILL.md amazon-review-insights/references/built-in-analysis-prompt.md tests/test_html_contract.py
git commit -m "feat: add cached review export and visit-limit recovery"
```

### Task 4: Validate and install the updated Skill

**Files:**
- Modify: `C:\Users\jjh09\.codex\skills\amazon-review-insights\SKILL.md`
- Modify: `C:\Users\jjh09\.codex\skills\amazon-review-insights\references\built-in-analysis-prompt.md`

**Interfaces:**
- Consumes: validated source Skill from Tasks 2–3.
- Produces: byte-for-byte matched local Codex installation.

- [ ] **Step 1: Validate source Skill**

Run:

```powershell
$env:PYTHONUTF8='1'
python 'C:\Users\jjh09\.codex\skills\.system\skill-creator\scripts\quick_validate.py' '.\amazon-review-insights'
Remove-Item Env:PYTHONUTF8
```

Expected: `Skill is valid!`.

- [ ] **Step 2: Copy the two source files to the local Codex Skill**

Run:

```powershell
Copy-Item -LiteralPath '.\amazon-review-insights\SKILL.md' -Destination 'C:\Users\jjh09\.codex\skills\amazon-review-insights\SKILL.md' -Force
Copy-Item -LiteralPath '.\amazon-review-insights\references\built-in-analysis-prompt.md' -Destination 'C:\Users\jjh09\.codex\skills\amazon-review-insights\references\built-in-analysis-prompt.md' -Force
```

- [ ] **Step 3: Verify installed hashes and validate the installed Skill**

Run:

```powershell
Get-FileHash '.\amazon-review-insights\SKILL.md','C:\Users\jjh09\.codex\skills\amazon-review-insights\SKILL.md' -Algorithm SHA256
Get-FileHash '.\amazon-review-insights\references\built-in-analysis-prompt.md','C:\Users\jjh09\.codex\skills\amazon-review-insights\references\built-in-analysis-prompt.md' -Algorithm SHA256
$env:PYTHONUTF8='1'
python 'C:\Users\jjh09\.codex\skills\.system\skill-creator\scripts\quick_validate.py' 'C:\Users\jjh09\.codex\skills\amazon-review-insights'
Remove-Item Env:PYTHONUTF8
```

Expected: matching hashes and `Skill is valid!`.

- [ ] **Step 4: Commit the implementation plan**

```powershell
git add -- docs/superpowers/plans/2026-09-08-amazon-review-cache.md
git commit -m "docs: plan temporary review cache implementation"
```

## Self-review

- Spec coverage: Tasks 1–2 implement checkpointing, reuse, and deferred cleanup; Task 3 covers exact visit-limit behavior and all three outputs; Task 4 validates and installs the Skill.
- Placeholder scan: no placeholder markers or deferred implementation steps are present.
- Type consistency: `review-cache-<marketplace>-<asin>-<filter-key>.json`, `ERROR_VISIT_MAX`, and the requested-output set use the same names throughout.
