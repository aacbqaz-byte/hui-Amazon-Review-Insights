from pathlib import Path
import unittest


REFERENCE = (
    Path(__file__).resolve().parents[1]
    / "amazon-review-insights"
    / "references"
    / "built-in-analysis-prompt.md"
)
ENTRYPOINT = Path(__file__).resolve().parents[1] / "amazon-review-insights" / "SKILL.md"


class HtmlContractTests(unittest.TestCase):
    def test_cache_reuse_requires_a_canonical_key_and_exact_request_identity(self):
        """A cache for another effective request must never suppress collection."""
        contract = ENTRYPOINT.read_text(encoding="utf-8")

        required_fragments = (
            "stars-<sorted-unique-stars-or-all>_types-<sorted-unique-types-or-all>",
            "normalized filters",
            "exact equality of cached ASIN, marketplace, and normalized filters",
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

    def test_cache_cleanup_waits_for_a_closed_and_verified_requested_output_set(self):
        """A cache remains available until the user closes a fully verified output set."""
        contract = ENTRYPOINT.read_text(encoding="utf-8")

        required_fragments = (
            "requested-output set is open while the user is choosing",
            "close the requested-output set only when the user confirms no further output is needed",
            "requested-output set is closed",
            "every requested artifact exists and has non-zero size",
            "selection remains open",
        )

        missing = [fragment for fragment in required_fragments if fragment not in contract]
        self.assertEqual(missing, [], f"Missing cache-lifecycle safeguards: {missing}")

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

    def test_collection_contract_uses_optional_filters_and_a_two_thousand_review_cap(self):
        contract = ENTRYPOINT.read_text(encoding="utf-8")

        required_fragments = (
            "ask whether the user wants optional review filters",
            "2,000",
            '"size": 10',
            "analyze every unique collected review",
            "Source-reported total",
            "Collected 2,000 reviews; source total unknown",
        )

        missing = [fragment for fragment in required_fragments if fragment not in contract]
        self.assertEqual(missing, [], f"Missing capped-collection requirements: {missing}")
        self.assertNotIn("ceil(N × 0.80)", contract)
        self.assertNotIn("ceil(N × 0.60)", contract)

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
            "Collected 2,000 reviews; source total unknown",
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
