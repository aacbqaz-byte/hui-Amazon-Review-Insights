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
