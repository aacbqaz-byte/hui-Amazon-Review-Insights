import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "amazon-review-insights" / "scripts" / "batch_review_cache.py"
REVIEW_SCRIPT = ROOT / "amazon-review-insights" / "scripts" / "review_cache.py"


def response(page: int, records: list[dict]) -> dict:
    return {
        "code": "OK",
        "message": "success",
        "data": {
            "pages": 1,
            "page": page,
            "size": 50,
            "total": len(records),
            "content": records,
        },
    }


def interactive_report_html(reviews: list[dict]) -> str:
    payload = json.dumps(reviews, ensure_ascii=False).replace("<", "\\u003c")
    return textwrap.dedent(
        f"""
        <!doctype html><html><body>
          <nav role="tablist">
            <button role="tab" data-view="overview" aria-controls="overview" aria-selected="true">Overview</button>
            <button role="tab" data-view="voice" aria-controls="voice" aria-selected="false">Voice</button>
          </nav>
          <section id="overview" role="tabpanel">Overview</section>
          <section id="voice" role="tabpanel" hidden>Voice</section>
          <button id="download-html">Download HTML</button>
          <script>
            const tabs = document.querySelectorAll('[role="tab"][data-view]');
            function activateView(view) {{
              tabs.forEach((tab) => tab.setAttribute('aria-selected', String(tab.dataset.view === view)));
              document.querySelectorAll('[role="tabpanel"]').forEach((panel) => {{ panel.hidden = panel.id !== view; }});
            }}
            tabs.forEach((tab) => tab.addEventListener('click', () => activateView(tab.dataset.view)));
            document.getElementById('download-html').addEventListener('click', () => {{
              const blob = new Blob(['<!doctype html>', document.documentElement.outerHTML], {{type: 'text/html;charset=utf-8'}});
            }});
          </script>
          <script type="application/json" id="review-data">{payload}</script>
        </body></html>
        """
    ).strip()


class BatchReviewCacheCliTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_batch(self, command: str, *extra: str, expected: int = 0) -> dict:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), command, "--workspace", str(self.workspace), *extra],
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

    def init_batch(self, asins: list[str], *, limit: int | None = None) -> dict:
        limit_args = () if limit is None else ("--limit", str(limit))
        return self.run_batch("init", "--marketplace", "US", "--asins", *asins, *limit_args)

    def seed_size_twenty_member(self, asin: str) -> Path:
        identity = f"US-{asin}-stars-all_types-all-size-20"
        collection = self.workspace / ".amazon-review-insights-cache" / "collections" / identity
        page_dir = collection / "pages"
        page_dir.mkdir(parents=True)
        manifest = {
            "schemaVersion": 2,
            "identity": identity,
            "request": {
                "marketplace": "US",
                "asin": asin,
                "starList": [],
                "typeList": [],
                "requestPageSize": 20,
            },
            "status": "collecting",
            "pendingRequest": None,
            "createdAt": "2026-09-08T00:00:00+00:00",
        }
        page = {
            "schemaVersion": 2,
            "identity": identity,
            "pagination": {"page": 1, "size": 20, "pages": 3, "total": 45},
            "reviews": [{"content": f"legacy-{number}"} for number in range(1, 21)],
        }
        (collection / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (page_dir / "page-000001.json").write_text(json.dumps(page), encoding="utf-8")
        return collection

    def member_args(self, batch: dict, asin: str) -> tuple[str, ...]:
        return ("--batch-id", batch["batchId"], "--asin", asin)

    def complete_member(self, batch: dict, asin: str, reviews: list[dict]) -> None:
        self.run_batch("next-request", *self.member_args(batch, asin))
        response_path = self.workspace / f"{asin}.json"
        response_path.write_text(json.dumps(response(1, reviews)), encoding="utf-8")
        saved = self.run_batch(
            "save-page",
            *self.member_args(batch, asin),
            "--response-file",
            str(response_path),
        )
        self.assertEqual(saved["status"], "complete")

    def export_batch(self, batch: dict) -> dict:
        output = self.workspace / "batch-export.json"
        self.run_batch("export-json", "--batch-id", batch["batchId"], "--output", str(output))
        return json.loads(output.read_text(encoding="utf-8"))

    def run_single(self, command: str, asin: str, *extra: str, expected: int = 0) -> dict:
        completed = subprocess.run(
            [sys.executable, str(REVIEW_SCRIPT), command, "--workspace", str(self.workspace),
             "--marketplace", "US", "--asin", asin, *extra],
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def completed_batch(self) -> tuple[dict, dict]:
        batch = self.init_batch(["B000000001", "B000000002"])
        self.complete_member(batch, "B000000001", [{"id": "shared", "content": "one", "asin": "raw-value", "details": {"rating": 5}}])
        self.complete_member(batch, "B000000002", [{"id": "shared", "content": "two"}])
        return batch, self.export_batch(batch)

    def batch_html(self, bundle: dict) -> Path:
        html = self.workspace / "joint.html"
        source = json.dumps(bundle["sourceIndex"], ensure_ascii=False).replace("<", "\\u003c")
        block = f'<script type="application/json" id="review-source-index">{source}</script>'
        html.write_text(interactive_report_html(bundle["reviews"]).replace('</body>', block + '</body>'), encoding="utf-8")
        return html

    def assert_live_caches_preserved(self, batch: dict) -> None:
        for member in batch["members"]:
            self.assertTrue(Path(member["manifestPath"]).is_file())
            self.assertTrue((Path(member["manifestPath"]).parent / "pages" / "page-000001.json").is_file())
        receipts = self.workspace / ".amazon-review-insights-cache" / "receipts"
        self.assertEqual(list(receipts.glob("*.json")), [])

    def test_finalize_batch_writes_member_receipts_then_removes_live_caches(self):
        batch, bundle = self.completed_batch()
        html = self.batch_html(bundle)
        result = self.run_batch("finalize-html", "--batch-id", batch["batchId"], "--html", str(html))
        self.assertEqual(result["status"], "receipt-backed")
        for member, dataset in zip(batch["members"], bundle["datasets"]):
            self.assertFalse(Path(member["manifestPath"]).parent.exists())
            output = self.workspace / f'{member["asin"]}-recovered.json'
            exported = self.run_single("export-json", member["asin"], "--output", str(output))
            self.assertEqual(exported["source"], "verified-html")
            recovered = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(recovered["reviews"], dataset["reviews"])
            blocked = self.run_single("next-request", member["asin"], expected=2)
            self.assertEqual(blocked["error"], "MCP_CALL_BLOCKED")
            self.assertEqual(blocked["uniqueCount"], 1)
        self.assertEqual(self.export_batch(batch)["reviews"], bundle["reviews"])

    def test_finalize_last_member_hash_mismatch_preserves_every_cache(self):
        batch, bundle = self.completed_batch()
        bundle["reviews"][-1]["content"] = "modified"
        result = self.run_batch("finalize-html", "--batch-id", batch["batchId"], "--html", str(self.batch_html(bundle)), expected=2)
        self.assertEqual(result["error"], "HTML_DATASET_MISMATCH")
        self.assert_live_caches_preserved(batch)

    def test_finalize_rejects_unknown_source_without_ignoring_extra_reviews(self):
        batch, bundle = self.completed_batch()
        bundle["reviews"].append({"content": "untracked"})
        bundle["sourceIndex"].append({"marketplace": "CA", "asin": "B000000001"})
        result = self.run_batch("finalize-html", "--batch-id", batch["batchId"], "--html", str(self.batch_html(bundle)), expected=2)
        self.assertEqual(result["error"], "HTML_DATASET_MISMATCH")
        self.assert_live_caches_preserved(batch)

    def test_finalize_requires_source_index(self):
        batch, bundle = self.completed_batch()
        html = self.workspace / "joint.html"
        html.write_text(interactive_report_html(bundle["reviews"]), encoding="utf-8")
        result = self.run_batch("finalize-html", "--batch-id", batch["batchId"], "--html", str(html), expected=2)
        self.assertEqual(result["error"], "REVIEW_SOURCE_INDEX_MISSING")
        self.assert_live_caches_preserved(batch)

    def test_finalize_reuses_an_existing_single_member_receipt(self):
        batch, bundle = self.completed_batch()
        single_html = self.workspace / "single.html"
        single_html.write_text(interactive_report_html(bundle["datasets"][1]["reviews"]), encoding="utf-8")
        self.run_single("finalize-html", "B000000002", "--html", str(single_html))
        html = self.batch_html(bundle)
        result = self.run_batch("finalize-html", "--batch-id", batch["batchId"], "--html", str(html))
        self.assertEqual(result["status"], "receipt-backed")
        # Repeating finalization is safe after all member caches have been removed.
        repeated = self.run_batch("finalize-html", "--batch-id", batch["batchId"], "--html", str(html))
        self.assertEqual(repeated["status"], "receipt-backed")
        self.assertEqual(self.export_batch(batch)["reviews"], bundle["reviews"])

    def test_finalize_rejects_html_inside_member_cache_before_cleanup(self):
        batch, bundle = self.completed_batch()
        html = Path(batch["members"][1]["manifestPath"]).parent / "joint.html"
        html.write_text(self.batch_html(bundle).read_text(encoding="utf-8"), encoding="utf-8")
        result = self.run_batch("finalize-html", "--batch-id", batch["batchId"], "--html", str(html), expected=2)
        self.assertEqual(result["error"], "HTML_PATH_UNSAFE")
        self.assert_live_caches_preserved(batch)
        self.assertTrue(html.is_file())

    def test_batch_export_preserves_reviews_and_parallel_source_index(self):
        batch = self.init_batch(["B000000001", "B000000002"])
        self.complete_member(batch, "B000000001", [{"content": "one"}])
        self.complete_member(batch, "B000000002", [{"content": "two"}])

        exported = self.export_batch(batch)

        self.assertEqual(exported["reviews"], [{"content": "one"}, {"content": "two"}])
        self.assertEqual(
            [item["asin"] for item in exported["sourceIndex"]],
            ["B000000001", "B000000002"],
        )
        self.assertEqual([item["marketplace"] for item in exported["sourceIndex"]], ["US", "US"])
        self.assertEqual(len(exported["datasets"]), 2)

    def test_init_rejects_batches_outside_two_to_five_members(self):
        for asins in (["B000000001"], [f"B00000000{i}" for i in range(1, 7)]):
            with self.subTest(asins=asins):
                rejected = self.run_batch(
                    "init", "--marketplace", "US", "--asins", *asins, expected=2
                )
                self.assertEqual(rejected["error"], "INVALID_BATCH_SIZE")

    def test_init_rejects_duplicate_asins(self):
        rejected = self.run_batch(
            "init",
            "--marketplace",
            "US",
            "--asins",
            "B000000001",
            "b000000001",
            expected=2,
        )
        self.assertEqual(rejected["error"], "DUPLICATE_ASIN")

    def test_batch_identity_is_order_insensitive(self):
        first = self.init_batch(["B000000002", "B000000001"])
        second = self.init_batch(["B000000001", "B000000002"])

        self.assertEqual(first["batchId"], second["batchId"])
        self.assertEqual(first["displayOrder"], ["B000000002", "B000000001"])
        self.assertEqual(second["displayOrder"], ["B000000002", "B000000001"])

    def test_new_batch_member_status_and_request_use_the_actual_fifty_record_page_size(self):
        batch = self.init_batch(["B000000001", "B000000002"], limit=100)
        status = self.run_batch("status", "--batch-id", batch["batchId"])
        request = self.run_batch("next-request", *self.member_args(batch, "B000000001"))

        self.assertEqual(batch["members"][0]["targetLimit"], 100)
        self.assertEqual(status["members"][0]["targetLimit"], 100)
        self.assertEqual(status["members"][0]["requestPageSize"], 50)
        self.assertEqual(request["request"]["size"], 50)

    def test_different_target_limit_batch_fails_before_sharing_a_live_member_cache(self):
        first = self.init_batch(["B000000001", "B000000002"])

        rejected = self.run_batch(
            "init",
            "--marketplace",
            "US",
            "--asins",
            "B000000001",
            "B000000002",
            "--limit",
            "100",
            expected=2,
        )
        original = self.run_batch("status", "--batch-id", first["batchId"])

        self.assertEqual(rejected["error"], "TARGET_LIMIT_CONFLICT")
        self.assertEqual(rejected["requestedTargetLimit"], 100)
        self.assertEqual(rejected["actualTargetLimit"], 2000)
        self.assertIsNone(original["members"][0]["pendingPage"])

    def test_target_conflict_preflight_does_not_create_an_earlier_new_member(self):
        self.init_batch(["B000000002", "B000000003"])

        rejected = self.run_batch(
            "init",
            "--marketplace",
            "US",
            "--asins",
            "B000000001",
            "B000000002",
            "--limit",
            "100",
            expected=2,
        )

        self.assertEqual(rejected["error"], "TARGET_LIMIT_CONFLICT")
        self.assertFalse(
            (
                self.workspace
                / ".amazon-review-insights-cache"
                / "collections"
                / "US-B000000001-stars-all_types-all-size-50"
            ).exists()
        )

    def test_matching_legacy_size_twenty_member_resumes_at_twenty(self):
        self.seed_size_twenty_member("B000000001")
        batch = self.init_batch(["B000000001", "B000000002"])

        status = self.run_batch("status", "--batch-id", batch["batchId"])
        request = self.run_batch("next-request", *self.member_args(batch, "B000000001"))

        self.assertEqual(status["members"][0]["targetLimit"], 2000)
        self.assertEqual(status["members"][0]["requestPageSize"], 20)
        self.assertEqual(request["request"]["size"], 20)
        self.assertEqual(request["request"]["page"], 2)

    def test_incompatible_target_refuses_legacy_size_twenty_member_before_authorization(self):
        legacy = self.seed_size_twenty_member("B000000001")

        rejected = self.run_batch(
            "init",
            "--marketplace",
            "US",
            "--asins",
            "B000000001",
            "B000000002",
            "--limit",
            "100",
            expected=2,
        )
        manifest = json.loads((legacy / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(rejected["error"], "TARGET_LIMIT_CONFLICT")
        self.assertEqual(rejected["actualTargetLimit"], 2000)
        self.assertIsNone(manifest["pendingRequest"])

    def test_pending_authorization_blocks_only_the_same_member(self):
        batch = self.init_batch(["B000000001", "B000000002"])
        self.run_batch("next-request", *self.member_args(batch, "B000000001"))

        blocked = self.run_batch(
            "next-request", *self.member_args(batch, "B000000001"), expected=2
        )
        other = self.run_batch("next-request", *self.member_args(batch, "B000000002"))

        self.assertEqual(blocked["error"], "REQUEST_PENDING")
        self.assertEqual(other["request"]["asin"], "B000000002")

    def test_partial_member_does_not_block_another_member(self):
        batch = self.init_batch(["B000000001", "B000000002"])
        self.run_batch("next-request", *self.member_args(batch, "B000000001"))
        error_path = self.workspace / "limit.json"
        error_path.write_text(json.dumps({"code": "ERROR_VISIT_MAX", "message": "limit"}), encoding="utf-8")
        partial = self.run_batch(
            "record-error",
            *self.member_args(batch, "B000000001"),
            "--response-file",
            str(error_path),
        )
        other = self.run_batch("next-request", *self.member_args(batch, "B000000002"))

        self.assertEqual(partial["status"], "blocked-empty")
        self.assertEqual(other["request"]["asin"], "B000000002")

    def test_completed_and_receipt_backed_members_are_reused(self):
        batch = self.init_batch(["B000000001", "B000000002"])
        self.complete_member(batch, "B000000001", [{"content": "one"}])
        resumed = self.init_batch(["B000000001", "B000000002"])
        complete = self.run_batch(
            "next-request", *self.member_args(resumed, "B000000001"), expected=2
        )
        self.assertEqual(complete["status"], "complete")

        self.complete_member(batch, "B000000002", [{"content": "two"}])
        html = self.workspace / "member.html"
        html.write_text(interactive_report_html([{"content": "two"}]), encoding="utf-8")
        finalized = subprocess.run(
            [
                sys.executable,
                str(REVIEW_SCRIPT),
                "finalize-html",
                "--workspace",
                str(self.workspace),
                "--marketplace",
                "US",
                "--asin",
                "B000000002",
                "--html",
                str(html),
            ],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(finalized.returncode, 0, finalized.stderr)
        reinitialized = self.init_batch(["B000000001", "B000000002"])
        receipt = self.run_batch(
            "next-request", *self.member_args(reinitialized, "B000000002"), expected=2
        )
        self.assertEqual(receipt["status"], "receipt-backed")


if __name__ == "__main__":
    unittest.main()
