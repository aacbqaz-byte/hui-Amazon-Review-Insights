# Amazon Review Insights v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the portable Amazon review skill to a 2,000-review capped workflow and an offline Material 3-style report with complete, searchable Voice of Customer data.

**Architecture:** `SKILL.md` owns collection interaction and delivery rules. `references/built-in-analysis-prompt.md` owns the report-data contract, Material 3 HTML skeleton, and inline offline controller. A small Python test asserts the contract’s observable workflow and report invariants; the validated source is copied into Codex’s installed skill directory.

**Tech Stack:** Markdown skill instructions, standalone HTML/CSS, inline browser JavaScript, Python `unittest`, SellerSprite MCP `review`, bundled skill validator.

**Spec:** `docs/superpowers/specs/2026-09-07-amazon-review-insights-v3-design.md`

## Global Constraints

- Require `asin` and `marketplace`, then ask once whether optional star or review-type filters are wanted.
- Call SellerSprite `review` at `size: 10`; collect until an end page or 2,000 records, then deduplicate and analyze every unique record.
- Remove 100% / 80% / 60% sampling and never ask the user to select a collection quantity.
- State a documented source total when present, an exact collected total after an end page, or `Collected 2,000 reviews; source total unknown` at the cap.
- Custom prompt analysis outputs standalone HTML by default.
- Keep all collected reviews in Voice of Customer; use 20-card pages, local fuzzy search, and star filtering.
- Use embedded CSS-only charts and a small inline controller only; no external network resource.
- Preserve original Steps 1–5 analytical output, strengthen Listing/A+ and Design Brief, and never invent unsupported claims.

---

### Task 1: Lock the v3 contract with failing tests

**Files:**
- Modify: `tests/test_html_contract.py`
- Test: `tests/test_html_contract.py`

**Interfaces:**
- Consumes: `amazon-review-insights/SKILL.md` and `references/built-in-analysis-prompt.md`.
- Produces: Tests that fail until capped collection, complete voice data, download behavior, and Material 3 navigation are explicit.

- [ ] **Step 1: Add a failing collection-contract test**

Add assertions that `SKILL.md` contains `2,000`, `size: 10`, optional `starList`/`typeList` confirmation, removes `ceil(N × 0.80)` and `ceil(N × 0.60)`, and states that every unique collected review is analyzed.

- [ ] **Step 2: Add a failing dashboard-contract test**

Add assertions that the reference requires all collected reviews, `20 matching reviews per page`, fuzzy search, star filters, `Download HTML`, `Blob`, `Source-reported total`, and `Collected 2,000 reviews; source total unknown`.

- [ ] **Step 3: Run the test to confirm red state**

Run:

```powershell
python '.\tests\test_html_contract.py'
```

Expected: failure listing missing v3 collection and dashboard fragments.

### Task 2: Implement capped collection and content requirements

**Files:**
- Modify: `amazon-review-insights/SKILL.md`
- Modify: `amazon-review-insights/references/built-in-analysis-prompt.md`
- Test: `tests/test_html_contract.py`

**Interfaces:**
- Consumes: Required ASIN/marketplace, optional star/type filters, SellerSprite pages, and optional custom/product prompts.
- Produces: A collection workflow with at most 2,000 records and a report-data contract containing all collected review fields.

- [ ] **Step 1: Replace sampling instructions in `SKILL.md`**

Replace the sampling table with a cap rule: ask for optional filters after required parameters, collect with `size: 10`, stop at end page or 2,000 records, deduplicate, and analyze every unique collected review. Specify the three source-count disclosure conditions from the v3 spec.

- [ ] **Step 2: Update analysis and output defaults**

Require custom-prompt analysis to use the same HTML contract automatically. Preserve high-information evidence selection for insight quality while requiring the complete collected dataset in Voice of Customer.

- [ ] **Step 3: Expand Listing/A+ and Design Brief instructions**

Require positioning conclusion, target buyer, top opportunities, proof points, claims to avoid, directly adaptable copy, and evidence mapping in Listing/A+. Require each Design Brief module to state what, why, who, goal, key message, copy, visual direction, compliance redlines, and asset/message-comprehension success criteria.

- [ ] **Step 4: Run the test to confirm green state**

Run:

```powershell
python '.\tests\test_html_contract.py'
```

Expected: `OK`.

### Task 3: Implement the offline Material 3 report controller

**Files:**
- Modify: `amazon-review-insights/references/built-in-analysis-prompt.md`
- Test: `tests/test_html_contract.py`

**Interfaces:**
- Consumes: All collected review records plus analytical and product-content results from Task 2.
- Produces: One self-contained HTML document with desktop rail/mobile navigation, bilingual display, download, and paginated Voice of Customer tools.

- [ ] **Step 1: Replace the dashboard skeleton and visual rules**

Require Material 3-inspired color tokens, responsive desktop rail/mobile top navigation, keyboard-accessible tabs, direct-label CSS bars/donut, and the eight specified report views. Keep all Steps 1–5 content in its assigned view.

- [ ] **Step 2: Define complete Voice of Customer data and controls**

Require every collected review’s escaped fields, evidence classification, and intent tags. Define 20 results per page, star checkboxes, a fuzzy-match input that tolerates one edit in tokens of four or more characters, matching-count display, paging controls, and an empty result state.

- [ ] **Step 3: Define local download behavior**

Require an accessible `Download HTML` button whose inline controller serializes `document.documentElement.outerHTML` as a UTF-8 Blob, creates a temporary local object URL, downloads an ASIN/marketplace/timestamp filename, then revokes the URL. Prohibit external resources and network requests.

- [ ] **Step 4: Run all validation**

Run:

```powershell
python '.\tests\test_html_contract.py'
$env:PYTHONUTF8 = '1'
python 'C:\Users\jjh09\.codex\skills\.system\skill-creator\scripts\quick_validate.py' '.\amazon-review-insights'
Remove-Item Env:PYTHONUTF8
```

Expected: Python test reports `OK` and validator reports `Skill is valid!`.

- [ ] **Step 5: Commit source changes**

```powershell
git add -- 'amazon-review-insights/SKILL.md' 'amazon-review-insights/references/built-in-analysis-prompt.md' 'tests/test_html_contract.py'
git commit -m 'feat: add capped collection and offline report controls'
```

### Task 4: Synchronize the installed Codex skill

**Files:**
- Modify: `C:\Users\jjh09\.codex\skills\amazon-review-insights\SKILL.md`
- Modify: `C:\Users\jjh09\.codex\skills\amazon-review-insights\references\built-in-analysis-prompt.md`
- Test: installed skill with `quick_validate.py`

**Interfaces:**
- Consumes: The validated source files from Tasks 2–3.
- Produces: The exact v3 source in Codex’s active local skill directory.

- [ ] **Step 1: Copy the two validated files to the installed directory**

Run:

```powershell
Copy-Item -LiteralPath '.\amazon-review-insights\SKILL.md' -Destination 'C:\Users\jjh09\.codex\skills\amazon-review-insights\SKILL.md'
Copy-Item -LiteralPath '.\amazon-review-insights\references\built-in-analysis-prompt.md' -Destination 'C:\Users\jjh09\.codex\skills\amazon-review-insights\references\built-in-analysis-prompt.md'
```

- [ ] **Step 2: Verify installed source identity and validity**

Run:

```powershell
Get-FileHash '.\amazon-review-insights\SKILL.md','C:\Users\jjh09\.codex\skills\amazon-review-insights\SKILL.md' -Algorithm SHA256
$env:PYTHONUTF8 = '1'
python 'C:\Users\jjh09\.codex\skills\.system\skill-creator\scripts\quick_validate.py' 'C:\Users\jjh09\.codex\skills\amazon-review-insights'
Remove-Item Env:PYTHONUTF8
```

Expected: the two Skill hashes match and the validator reports `Skill is valid!`.
