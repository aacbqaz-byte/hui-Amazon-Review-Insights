# Amazon Review Insights Skill v3 — Design

## Goal

Upgrade the portable Amazon review-analysis skill with a simpler capped-collection workflow and a fully offline, Google Material 3-inspired HTML dashboard. Preserve all existing analysis and product-content requirements; change only collection interaction, report navigation, report completeness, and report presentation.

## Collection interaction

1. Extract and require `asin` and `marketplace`. Ask only for a missing required value; never infer a marketplace.
2. Once both are present, ask whether the user wants optional review filters. The optional filters are star rating (`starList`) and review type (`typeList`: image, video, VP, Vine). If the user declines or gives no filter, omit both parameters.
3. Start collecting with SellerSprite `review`, `page` beginning at 1 and `size: 10`, the documented maximum.
4. Stop when the endpoint returns an empty/short page or after 2,000 collected records, whichever comes first. Deduplicate by author, timestamp, title, content, and star.
5. Remove the previous 100% / 80% / 60% sampling rules. Analyze every unique collected review, up to the 2,000-review cap.
6. Ask whether to analyze after collection. Offer built-in analysis or an uploaded `.md`/`.txt` custom prompt. Both choices produce HTML by default; do not ask the user to choose an output format.

## Source-count disclosure

The endpoint currently does not document a total-count field. The dashboard must accurately state one of these conditions:

| Condition | Required display |
| --- | --- |
| A documented response total exists | `Source-reported total: N` |
| The endpoint ends before the 2,000 cap | `Collected total: N reviews` |
| The 2,000 cap is reached before an end page | `Collected 2,000 reviews; source total unknown` |

All count statements must identify SellerSprite as the source and must not claim an Amazon-wide verified total.

## Analysis and content preservation

Preserve the original five-step analytical workflow:

1. Denoising and evidence classification.
2. Consumer-intent clustering.
3. Attribute-gap and action analysis.
4. Listing, A+ content, and associated product recommendations when product facts are available.
5. A+ design brief when product facts are available.

The intent analysis may prioritize high-information evidence, but the Voice of Customer view must contain every collected review, including low-information, excluded, Vine, free, and experience reviews. Their source labels and evidence classification must remain visible. No product fact, certification, performance, trademark, ranking, compliance, or sales claim may be invented.

## Dashboard information architecture

Use a Material 3-inspired, evidence-first dashboard with a desktop navigation rail and a narrow-screen horizontal navigation bar. The navigation order is:

1. Overview
2. Intent Maps
3. Opportunities
4. Listing & A+
5. Design Brief
6. Voice of Customer
7. Data & Method
8. Limitations

The Overview leads with three or four ranked findings, sample/source status, and direct-value CSS charts. Use blue for data emphasis, amber for medium risk, red for high risk, and green for positive evidence. Every chart includes labels and values in addition to color.

Provide Chinese and English display modes for UI labels, analysis, charts, recommendations, methods, and limitations. Preserve original review wording. Show a translation appropriate to the active display language; leave marketplace-targeted Listing/A+ copy in its generated target language and label that language rather than rewriting it.

## Voice of Customer

The Voice of Customer page is a report navigation destination, not a representative-excerpt section.

- Render all collected reviews in the report data, including title, content, author, normalized date, star, author labels, review type, verified-purchase status, Vine, free, experience, evidence classification, and intent tags where available.
- Display 20 matching reviews per page.
- Offer star-rating multi-select filters and a local fuzzy text search over original title/content, author, labels, and translations. Matching is case-, whitespace-, punctuation-, and diacritic-insensitive; token matches tolerate a one-character edit for tokens of four or more characters.
- Reset pagination to page one when filters or query change. Display matching count, current page, next/previous controls, and an accessible empty state.
- Keep all review cards in the local HTML data model. Filtering and pagination are client-side only and make no network request.

## Listing, A+, and design brief

The Listing & A+ view remains grounded in supplied product facts, but adds decision-ready content:

- An executive recommendation summarizing positioning, target buyer, top opportunities, proof points, and claims or phrases to avoid.
- Directly adaptable title, bullets, description, A+ module copy, and the evidence/intent that supports each recommendation.
- Clear separation of validated facts, analytical inferences, and optional copy suggestions.

The Design Brief is expanded from a short module list into a persuasion-ready creative brief. Each applicable A+ module contains:

- What to make.
- Why it matters to the buyer and the identified intent.
- Who it is for.
- Page goal and key message.
- Suggested headline, supporting copy, proof points, visual direction, and creative direction.
- Compliance redlines.
- Success criteria, expressed as asset and message-comprehension standards rather than unsupported sales promises.

The dashboard visualizes the brief as module cards connected to buyer intent, evidence strength, and desired buyer takeaway.

## Offline delivery and download

The HTML report must use system fonts, embedded CSS, CSS-only charts, and a small inline JavaScript controller. It must not reference a CDN, external font, image, video, iframe, analytics service, fetch request, or other network resource.

The inline controller handles navigation, language switching, Voice of Customer filtering/search/pagination, and a `Download HTML` / `下载 HTML` button. The button serializes the complete current document into a UTF-8 Blob and downloads a standalone `.html` file with an ASIN/marketplace/timestamp filename. It must preserve every report section and all collected review records.

## Accessibility and responsive behavior

- Use native buttons, a tablist/tab/tabpanel relationship, accurate `aria-selected`, and visible keyboard focus.
- Keep interactive controls at least 44px high and maintain logical keyboard order.
- Use text labels rather than color alone for states and charts.
- Collapse the desktop rail to a horizontally scrollable top navigation below 900px; make Voice controls wrap without horizontal page overflow.
- Respect `prefers-reduced-motion`.
- Print styles hide controls and navigation, reveal all report views, and expand review content.

## Error handling

- Missing required parameter: ask only for the missing value.
- SellerSprite error: state page, collected count, and error; do not create a fabricated report.
- No reviews: produce a concise offline HTML data-status report with collection metadata.
- Missing/unreadable custom prompt: ask for a new attachment or offer built-in analysis.
- No product facts for Steps 4–5: retain the corresponding navigation views and show which minimum facts are missing.

## Files and validation

Modify `amazon-review-insights/SKILL.md` for the interaction, cap, source-count, and download requirements. Replace the dashboard section of `amazon-review-insights/references/built-in-analysis-prompt.md` with the Material 3 and all-review contract. Extend `tests/test_html_contract.py` to assert the changed collection, complete Voice of Customer, pagination, download, and offline invariants. Validate with `quick_validate.py` using UTF-8 mode and run the Python test.
