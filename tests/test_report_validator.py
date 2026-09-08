import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "amazon-review-insights" / "scripts" / "validate_report.py"


VALID_RUNTIME = textwrap.dedent(
    """
    const tabs = document.querySelectorAll('[role="tab"][data-view]');
    function activateView(view) {
      tabs.forEach((tab) => tab.setAttribute('aria-selected', String(tab.dataset.view === view)));
      document.querySelectorAll('[role="tabpanel"]').forEach((panel) => {
        panel.hidden = panel.id !== view;
      });
    }
    tabs.forEach((tab) => tab.addEventListener('click', () => activateView(tab.dataset.view)));
    document.getElementById('download-html').addEventListener('click', () => {
      const blob = new Blob(['<!doctype html>', document.documentElement.outerHTML], {
        type: 'text/html;charset=utf-8'
      });
      const url = URL.createObjectURL(blob);
      URL.revokeObjectURL(url);
    });
    """
).strip()


ARIA_CONTROLS_RUNTIME = textwrap.dedent(
    """
    const tabs = document.querySelectorAll('[role="tab"]');
    tabs.forEach((tab) => tab.addEventListener('click', () => {
      const view = tab.getAttribute('aria-controls');
      tabs.forEach((item) => item.setAttribute('aria-selected', String(item === tab)));
      document.querySelectorAll('[role="tabpanel"]').forEach((panel) => {
        panel.hidden = panel.id !== view;
      });
    }));
    document.getElementById('download').addEventListener('click', () => {
      const blob = new Blob([document.documentElement.outerHTML], {
        type: 'text/html;charset=utf-8'
      });
      const url = URL.createObjectURL(blob);
      URL.revokeObjectURL(url);
    });
    """
).strip()


def report_html(reviews: list[dict], runtime: str = VALID_RUNTIME, voice_target: str = "voice") -> str:
    payload = json.dumps(reviews, ensure_ascii=False).replace("<", "\\u003c")
    return textwrap.dedent(
        f"""
        <!doctype html>
        <html><body>
          <nav role="tablist">
            <button role="tab" data-view="overview" aria-controls="overview" aria-selected="true">Overview</button>
            <button role="tab" data-view="voice" aria-controls="{voice_target}" aria-selected="false">Voice</button>
          </nav>
          <main>
            <section id="overview" role="tabpanel">Overview</section>
            <section id="voice" role="tabpanel" hidden>Voice</section>
          </main>
          <button type="button" id="download-html">Download HTML</button>
          <script>{runtime}</script>
          <script type="application/json" id="review-data">{payload}</script>
        </body></html>
        """
    ).strip()


def review_browser_html(reviews: list[dict]) -> str:
    payload = json.dumps(reviews, ensure_ascii=False).replace("<", "\\u003c")
    return textwrap.dedent(
        f"""
        <!doctype html>
        <html><body>
          <input type="search" id="q" aria-label="Search reviews">
          <select id="star" aria-label="Filter by star rating"><option value="">All</option></select>
          <main id="list"></main>
          <nav id="pager" aria-label="Review pages"></nav>
          <button type="button" id="download-html">Download HTML</button>
          <script>
            const q = document.getElementById('q');
            const star = document.getElementById('star');
            const list = document.getElementById('list');
            const pager = document.getElementById('pager');
            function render() {{ list.textContent = q.value + star.value; pager.textContent = '1'; }}
            q.addEventListener('input', render);
            star.addEventListener('change', render);
            pager.addEventListener('click', render);
            document.getElementById('download-html').addEventListener('click', () => {{
              const blob = new Blob([document.documentElement.outerHTML], {{ type: 'text/html;charset=utf-8' }});
              const url = URL.createObjectURL(blob);
              URL.revokeObjectURL(url);
            }});
          </script>
          <script type="application/json" id="review-data">{payload}</script>
        </body></html>
        """
    ).strip()


class ReportValidatorCliTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_validator(self, html: str, expected: int = 0) -> dict:
        path = self.workspace / "report.html"
        path.write_text(html, encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), str(path)],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            expected,
            f"stdout={completed.stdout}\nstderr={completed.stderr}",
        )
        self.assertTrue(completed.stdout.strip(), completed.stderr)
        return json.loads(completed.stdout)

    def test_valid_offline_report_passes_script_and_navigation_checks(self):
        result = self.run_validator(report_html([{"content": "works"}]))
        self.assertTrue(result["ok"])
        self.assertEqual(result["executableScriptCount"], 1)
        self.assertEqual(result["tabCount"], 2)
        self.assertEqual(result["panelCount"], 2)
        self.assertEqual(result["reviewCount"], 1)

    def test_aria_controls_navigation_and_legacy_download_id_are_valid(self):
        html = report_html([{"content": "works"}], runtime=ARIA_CONTROLS_RUNTIME)
        html = html.replace('id="download-html"', 'id="download"')
        result = self.run_validator(html)
        self.assertTrue(result["ok"])
        self.assertEqual(result["reportMode"], "analysis")

    def test_review_browser_without_tabs_is_valid_when_controls_are_bound(self):
        result = self.run_validator(review_browser_html([{"content": "works"}]))
        self.assertTrue(result["ok"])
        self.assertEqual(result["reportMode"], "review-browser")

    def test_raw_newline_inside_download_string_fails_javascript_syntax(self):
        broken_runtime = VALID_RUNTIME + "\nconst downloaded = '<!doctype html>\n' + document.documentElement.outerHTML;"
        result = self.run_validator(report_html([], runtime=broken_runtime), expected=2)
        self.assertEqual(result["error"], "JS_SYNTAX_ERROR")
        self.assertIn("SyntaxError", result["details"])

    def test_navigation_target_must_exist(self):
        result = self.run_validator(report_html([], voice_target="missing-panel"), expected=2)
        self.assertEqual(result["error"], "NAV_TARGET_MISSING")
        self.assertEqual(result["target"], "missing-panel")

    def test_navigation_requires_an_executable_click_binding(self):
        runtime = "const tabs = document.querySelectorAll('[role=tab]');"
        result = self.run_validator(report_html([], runtime=runtime), expected=2)
        self.assertEqual(result["error"], "NAV_BINDING_MISSING")


if __name__ == "__main__":
    unittest.main()
