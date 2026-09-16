from pathlib import Path
import importlib.util
import json
import re
import subprocess
import tempfile
import unittest


REFERENCE = (
    Path(__file__).resolve().parents[1]
    / "amazon-review-insights"
    / "references"
    / "built-in-analysis-prompt.md"
)
ENTRYPOINT = Path(__file__).resolve().parents[1] / "amazon-review-insights" / "SKILL.md"


class MultiAsinRuntimeTests(unittest.TestCase):
    """Execute the reference's real outline/runtime, not a separately invented report."""

    def test_multi_asin_tabs_and_combined_voice_filter_preserve_source(self):
        # Removing a tab binding, source-index join, filter reset, or pagination
        # must change visible results or selection state and fail this test.
        reference = REFERENCE.read_text(encoding="utf-8")
        outline = re.search(r"```html\n(.*?)\n```", reference, re.S).group(1)
        runtime = "\n".join(re.findall(r"```js\n(.*?)\n```", reference, re.S))
        reviews = [
            {"author": "Ana", "content": f"Travel café {i}", "star": 5, "verified": True,
             "futureField": {"keep": "<original>"}}
            for i in range(21)
        ] + [
            {"author": "Bo", "content": "Travel café weak seam", "star": 2, "verified": False},
            {"author": "Cy", "content": "Travel café strong seam", "star": 5, "verified": True},
        ]
        sources = [{"marketplace": "US", "asin": "B000000001"}] * 21 + [
            {"marketplace": "US", "asin": "B000000002"},
            {"marketplace": "US", "asin": "B000000002"},
        ]
        def safe_json(value):
            return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")

        outline = outline.replace("{{complete_source_reviews_json}}", safe_json(reviews))
        outline = outline.replace("{{complete_source_index_json}}", safe_json(sources))
        outline = outline.replace("{{asin_options}}", '<option value="B000000001">B000000001</option>'
                                  '<option value="B000000002">B000000002</option>')
        # Populate the old outline's open navigation slot with the requested
        # joint views; the validator must reject absent target panels in RED.
        views = ["overview", "shared-intents", "shared-gaps", "asin-differences",
                 "opportunities", "listing-a-plus", "design-brief", "voice", "method", "limitations"]
        navigation = ''.join(
            f'<button role="tab" data-view="{view}" aria-controls="{view}" '
            f'aria-selected="{str(view == "overview").lower()}">{view}</button>'
            for view in views
        )
        outline = outline.replace("{{navigation_tabs}}", navigation)
        outline = outline.replace("{{language_and_download}}", '<button id="download-html">Download HTML</button>')
        outline = re.sub(r"{{[^}]+}}", "", outline)
        html = f"<!doctype html><html><title>Joint VOC</title><body>{outline}<script>{runtime}</script></body></html>"
        validator_path = ENTRYPOINT.parent / "scripts" / "validate_report.py"
        spec = importlib.util.spec_from_file_location("joint_report_validator", validator_path)
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "joint.html"
            path.write_text(html, encoding="utf-8")
            result = validator.validate_report(path)
            self.assertEqual(result["tabCount"], 10, "Joint outline must expose ten working views")
            parser, _, blocks = validator.read_report(path)
        elements = list(parser.ids.values()) + [t for t in parser.tabs if not t.get("id")]
        source_text = {b["attrs"]["id"]: b["content"] for b in blocks}
        # Minimal DOM boundary: execute the shipped code using Node's EventTarget.
        # Parsing, syntax validation, navigation/filter logic, and JSON stay real.
        harness = r'''
const assert = require('node:assert/strict');
class Element extends EventTarget {
  constructor(attrs = {}) { super(); this.attrs = {...attrs}; this.id = attrs.id;
    this.hidden = 'hidden' in attrs; this.value = attrs.value || ''; this.checked = false;
    this.children = []; this.textContent = ''; this.disabled = false; }
  getAttribute(key) { return this.attrs[key]; }
  setAttribute(key, value) { this.attrs[key] = value; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; this.textContent = ''; }
  click() { if (!this.disabled) this.dispatchEvent(new Event('click')); }
}
const elements = INPUT.elements.map(attrs => new Element(attrs));
const byId = id => elements.find(e => e.id === id);
for (const [id, value] of Object.entries(INPUT.sourceText)) byId(id).textContent = value;
const document = {
  getElementById: byId, createElement: () => new Element(),
  querySelectorAll: selector => elements.filter(e =>
    selector.includes('tabpanel') ? e.attrs.role === 'tabpanel' :
    selector.includes('role="tab"') ? e.attrs.role === 'tab' :
    selector.includes('voice-star') ? e.attrs.name === 'voice-star' : false),
  title: 'Joint VOC', documentElement: {outerHTML: ''}
};
const history = {replaceState() {}};
const before = byId('review-data').textContent;
RUNTIME
const text = el => el.textContent + el.children.map(text).join(' ');
for (const id of ['shared-intents', 'shared-gaps', 'asin-differences']) {
  elements.find(e => e.attrs.role === 'tab' && e.attrs['aria-controls'] === id).click();
  assert.deepEqual(elements.filter(e => e.attrs.role === 'tabpanel' && !e.hidden).map(e => e.id), [id]);
  assert.equal(elements.filter(e => e.attrs['aria-selected'] === 'true').length, 1);
}
const list = byId('voice-list');
assert.equal(list.children.length, 20);
byId('voice-next').click();
assert.equal(list.children.length, 3);
const change = (id, value, event = 'change') => {
  byId(id).value = value; byId(id).dispatchEvent(new Event(event));
};
assert.ok(byId('voice-asin').getAttribute('aria-label'));
change('voice-asin', 'B000000002');
assert.equal(list.children.length, 2); // Also proves page reset from page two.
assert.match(text(list), /weak seam/); assert.doesNotMatch(text(list), /Travel café 0/);
change('voice-query', 'cafe travl', 'input'); // Accent + one-edit token search.
assert.equal(list.children.length, 2);
change('voice-verified', 'true');
assert.equal(list.children.length, 1); assert.match(text(list), /strong seam/);
byId('voice-star-2').checked = true;
byId('voice-star-2').dispatchEvent(new Event('change'));
assert.equal(list.children.length, 0);
byId('voice-star-5').checked = true;
byId('voice-star-5').dispatchEvent(new Event('change'));
assert.equal(list.children.length, 1); // Multi-select OR, combined filters AND.
change('voice-verified', '');
assert.equal(list.children.length, 2);
change('voice-asin', '');
assert.equal(list.children.length, 20);
assert.equal(byId('review-data').textContent, before);
assert.deepEqual(JSON.parse(before), INPUT.reviews);
assert.deepEqual(JSON.parse(byId('review-source-index').textContent), INPUT.sources);
'''
        harness = harness.replace("RUNTIME", runtime)
        harness = "const INPUT = " + json.dumps({"elements": elements, "sourceText": source_text,
            "reviews": reviews, "sources": sources}) + ";\n" + harness
        completed = subprocess.run(["node", "-"], input=harness, text=True, encoding="utf-8", capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)


class HtmlContractTests(unittest.TestCase):
    def test_cache_reuse_requires_a_canonical_key_and_exact_request_identity(self):
        """A cache for another effective request must never suppress collection."""
        contract = ENTRYPOINT.read_text(encoding="utf-8")

        required_fragments = (
            "stars-<sorted-unique-stars-or-all>_types-<sorted-unique-types-or-all>",
            "normalized filters",
            "Exact equality of ASIN, marketplace, normalized filters, schema, and page size",
        )

        missing = [fragment for fragment in required_fragments if fragment not in contract]
        self.assertEqual(missing, [], f"Missing cache-identity safeguards: {missing}")

    def test_partial_artifacts_disclose_the_recorded_failure_without_inventing_visit_limit(self):
        """Direct HTML and Excel exports must preserve any partial-collection cause."""
        contract = ENTRYPOINT.read_text(encoding="utf-8")

        required_fragments = (
            "recorded collection failure code and message",
            "collected and unique counts",
            "only when the recorded failure code is `ERROR_VISIT_MAX`",
            "preserve unknown or other failure codes and messages",
            "analysis HTML, review-display HTML, and Excel",
        )

        missing = [fragment for fragment in required_fragments if fragment not in contract]
        self.assertEqual(missing, [], f"Missing partial-artifact disclosure safeguards: {missing}")

    def test_cache_cleanup_requires_verified_html_and_leaves_a_durable_receipt(self):
        """Deleting live data must leave a verified offline source for later outputs."""
        contract = ENTRYPOINT.read_text(encoding="utf-8")

        required_fragments = (
            "`finalize-html --html <path>`",
            "embedded count and SHA-256",
            "Only a successful verification may delete the live collection directory",
            "durable receipt",
            "later HTML, Excel, or analysis requests",
            "If only Excel is generated, or HTML creation/finalization fails, preserve the live cache",
        )

        missing = [fragment for fragment in required_fragments if fragment not in contract]
        self.assertEqual(missing, [], f"Missing cache-lifecycle safeguards: {missing}")

    def test_html_delivery_requires_runtime_validation_before_cache_cleanup(self):
        """A broken report must be repaired locally without spending another MCP call."""
        contract = ENTRYPOINT.read_text(encoding="utf-8")
        reference = REFERENCE.read_text(encoding="utf-8")

        required_entrypoint = (
            "scripts/validate_report.py",
            "before `finalize-html`",
            "JavaScript syntax",
            "preserve the live cache",
            "never call SellerSprite to repair an HTML",
        )
        required_reference = (
            'id="download-html"',
            "['<!doctype html>', document.documentElement.outerHTML]",
            "getAttribute('aria-controls')",
            "Run `scripts/validate_report.py`",
        )

        self.assertEqual(
            [item for item in required_entrypoint if item not in contract],
            [],
            "Missing report validation gate in SKILL.md",
        )
        self.assertEqual(
            [item for item in required_reference if item not in reference],
            [],
            "Missing safe navigation/download runtime contract",
        )

    def test_excel_export_preserves_existing_evidence_without_new_analysis(self):
        """Export-only work must not alter cached evidence or perform analysis."""
        contract = ENTRYPOINT.read_text(encoding="utf-8")

        required_fragments = (
            "evidence classification and intent/evidence tags when already generated",
            "must not run new analysis merely to fill those fields",
        )

        missing = [fragment for fragment in required_fragments if fragment not in contract]
        self.assertEqual(missing, [], f"Missing Excel evidence-preservation safeguards: {missing}")

    def test_partial_cache_contract_preserves_reviews_after_visit_limit(self):
        entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
        reference = REFERENCE.read_text(encoding="utf-8")
        self.assertIn('code: "ERROR_VISIT_MAX"', entrypoint)
        self.assertIn("review-display HTML", entrypoint)
        self.assertIn(".xlsx", entrypoint)
        self.assertIn("all cached unique reviews", entrypoint)
        self.assertIn("Every artifact produced from a partial cache", entrypoint)
        self.assertIn("recorded collection failure code and message", entrypoint)
        self.assertIn("collected and unique counts", entrypoint)
        self.assertIn("never describe the dataset as complete or Amazon-wide", entrypoint)
        self.assertIn("ERROR_VISIT_MAX", reference)
        self.assertIn("recorded collection failure code and message", reference)
        self.assertIn("partial", reference)

    def test_collection_contract_checkpoints_and_reuses_review_cache(self):
        contract = ENTRYPOINT.read_text(encoding="utf-8")
        required_fragments = (
            ".amazon-review-insights-cache/collections/<identity>/",
            "lossless `pages/page-XXXXXX.json` files",
            "deduplicated `reviews.jsonl`",
            "Generate every artifact from `export-json",
            "never call SellerSprite again",
            "ERROR_VISIT_MAX",
            "当前尚未爬取到任何评论，请确定 MCP 是否有使用次数。",
            "review-display HTML",
            ".xlsx",
        )
        missing = [item for item in required_fragments if item not in contract]
        self.assertEqual(missing, [], f"Missing review-cache requirements: {missing}")

    def test_collection_contract_uses_optional_filters_and_a_two_thousand_review_cap(self):
        contract = ENTRYPOINT.read_text(encoding="utf-8")

        required_fragments = (
            "ask whether the user wants optional review filters",
            "2,000",
            '"size": 20',
            "existing schema-2 size-50 collection or receipt",
            "analyze every unique collected review",
            "Source-reported total",
        )

        missing = [fragment for fragment in required_fragments if fragment not in contract]
        self.assertEqual(missing, [], f"Missing capped-collection requirements: {missing}")
        self.assertNotIn("ceil(N × 0.80)", contract)
        self.assertNotIn("ceil(N × 0.60)", contract)

    def test_every_mcp_page_is_guarded_by_durable_executable_state(self):
        """Context compression must not make conversational memory authoritative."""
        contract = ENTRYPOINT.read_text(encoding="utf-8")

        required_fragments = (
            "scripts/review_cache.py",
            "before the first MCP call",
            "before every MCP call",
            "`next-request`",
            "`save-page`",
            "`pendingRequest`",
            "`REQUEST_PENDING`",
            "Immediately after each MCP response",
            "summary `.txt` files are not collection state",
            "never request `data.pages + 1`",
            "receipt-backed",
            'id="review-data"',
            "If Python is unavailable",
        )

        missing = [fragment for fragment in required_fragments if fragment not in contract]
        self.assertEqual(missing, [], f"Missing executable cache protocol: {missing}")

    def test_raw_mcp_checkpoint_contract_forbids_agent_side_response_rewriting(self):
        contract = ENTRYPOINT.read_text(encoding="utf-8")
        required_fragments = (
            "top-level MCP tool arguments",
            "never nest them under a property named `request`",
            "Do not use Base64 or `btoa`",
            "complete unmodified MCP tool result",
            "keep the temporary response file until the checkpoint succeeds",
        )

        missing = [fragment for fragment in required_fragments if fragment not in contract]
        self.assertEqual(missing, [], f"Missing raw MCP checkpoint safeguards: {missing}")

    def test_joint_findings_require_resolvable_asin_and_voice_evidence(self):
        contract = REFERENCE.read_text(encoding="utf-8")
        required_fragments = (
            "resolvable evidence citations",
            "`VOC #<one-based index>`",
            "same VOC identifier",
            "ASIN source",
            "original-language verbatim excerpt",
        )

        missing = [fragment for fragment in required_fragments if fragment not in contract]
        self.assertEqual(missing, [], f"Missing traceable joint-finding evidence contract: {missing}")

    def test_dashboard_contract_preserves_offline_navigation_and_full_voice_evidence(self):
        contract = REFERENCE.read_text(encoding="utf-8")

        required_fragments = (
            'role="tablist"',
            'data-view="overview"',
            'data-view="voice"',
            'data-lang="zh"',
            'data-lang="en"',
            "all selected analysis-sample reviews",
            "CSS-only charts",
            "no external network resources",
        )

        missing = [fragment for fragment in required_fragments if fragment not in contract]
        self.assertEqual(missing, [], f"Missing dashboard contract requirements: {missing}")

    def test_dashboard_contract_supports_full_voice_paging_filtering_and_download(self):
        contract = REFERENCE.read_text(encoding="utf-8")

        required_fragments = (
            "all collected reviews",
            "20 matching reviews per page",
            "fuzzy text search",
            "star-rating multi-select filters",
            "Download HTML",
            "UTF-8 Blob",
            "Source-reported total",
            "Material 3-inspired",
        )

        missing = [fragment for fragment in required_fragments if fragment not in contract]
        self.assertEqual(missing, [], f"Missing v3 dashboard requirements: {missing}")

    def test_v4_dashboard_contract_has_a_single_coherent_visual_system(self):
        """Catch a regression to the conflicting, card-stacked V3 layout."""
        contract = REFERENCE.read_text(encoding="utf-8")

        required_fragments = (
            "V4 report design system",
            "three deliberate layers: canvas, containers, and content surfaces",
            "one primary data color",
            "Do not use risk colors to encode ordinary data series",
            "Avoid card-inside-card layouts",
            "Skip to report content",
            "left rail, full-width report canvas, and report header",
            "replaces every earlier HTML layout and styling instruction",
        )

        missing = [fragment for fragment in required_fragments if fragment not in contract]
        self.assertEqual(missing, [], f"Missing V4 visual-system requirements: {missing}")
        self.assertNotIn("V3 override — capped collection and Material 3 report", contract)

    def test_dashboard_contract_uses_the_available_desktop_width(self):
        """Catch a fixed report canvas that leaves unused ultrawide space."""
        contract = REFERENCE.read_text(encoding="utf-8")

        required_fragments = (
            "full available width outside the navigation rail",
            "inline-size: 100%",
            "max-inline-size:none",
            "repeat(auto-fit, minmax(280px, 1fr))",
            "Limit long-form paragraphs, not the report canvas",
        )

        missing = [fragment for fragment in required_fragments if fragment not in contract]
        self.assertEqual(missing, [], f"Missing fluid-width requirements: {missing}")
        self.assertNotIn("max-width: 1360px", contract)


if __name__ == "__main__":
    unittest.main()
