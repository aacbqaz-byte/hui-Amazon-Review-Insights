from pathlib import Path
import unittest


REFERENCE = (
    Path(__file__).resolve().parents[1]
    / "amazon-review-insights"
    / "references"
    / "built-in-analysis-prompt.md"
)


class HtmlContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
