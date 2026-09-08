import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "amazon-review-insights" / "scripts" / "review_cache.py"


def review(number: int) -> dict:
    return {
        "author": f"author-{number}",
        "title": f"title-{number}",
        "content": f"原声 review {number}",
        "date": 1772380800000 + number,
        "star": (number % 5) + 1,
        "authorLabels": ["TOP"],
        "skus": [{"name": "Blue", "value": "L"}],
        "images": [f"https://example.invalid/{number}.jpg"],
        "videos": [],
        "likes": number,
        "image": True,
        "video": False,
        "verified": True,
        "vine": False,
        "free": False,
        "experience": False,
        "futureField": {"kept": number},
    }


def response(page: int, pages: int, total: int, records: list[dict], size: int = 20) -> dict:
    return {
        "code": "OK",
        "message": "成功",
        "data": {
            "guestId": None,
            "pages": pages,
            "page": page,
            "size": size,
            "total": total,
            "took": 0,
            "url": None,
            "order": {"field": "", "desc": True},
            "content": records,
        },
    }


class ReviewCacheCliTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.identity_args = (
            "--workspace",
            str(self.workspace),
            "--marketplace",
            "US",
            "--asin",
            "B0DURABLE01",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_cli(self, command: str, *extra: str, expected: int = 0) -> dict:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), command, *self.identity_args, *extra],
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

    def write_response(self, name: str, payload: dict) -> Path:
        path = self.workspace / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def initialize(self) -> dict:
        return self.run_cli("init")

    def save(self, payload: dict, name: str = "response.json", expected: int = 0) -> dict:
        path = self.write_response(name, payload)
        return self.run_cli("save-page", "--response-file", str(path), expected=expected)

    def test_new_process_resumes_at_next_unsaved_page_with_size_twenty(self):
        self.initialize()
        first = self.run_cli("next-request")
        self.assertEqual(first["action"], "call_mcp")
        self.assertEqual(first["request"], {"marketplace": "US", "asin": "B0DURABLE01", "page": 1, "size": 20})

        saved = self.save(response(1, 3, 45, [review(i) for i in range(1, 21)]))
        self.assertEqual(saved["nextPage"], 2)

        resumed = self.run_cli("next-request")
        self.assertEqual(resumed["request"]["page"], 2)
        self.assertEqual(resumed["request"]["size"], 20)
        self.assertEqual(resumed["savedPages"], [1])

    def test_uncommitted_authorization_blocks_the_same_page_after_restart(self):
        self.initialize()
        first = self.run_cli("next-request")
        self.assertEqual(first["request"]["page"], 1)

        blocked = self.run_cli("next-request", expected=2)
        self.assertEqual(blocked["error"], "REQUEST_PENDING")
        self.assertEqual(blocked["action"], "do_not_call_mcp")
        self.assertEqual(blocked["pendingPage"], 1)
        self.assertNotIn("request", blocked)

    def test_legacy_summary_without_full_reviews_blocks_automatic_recollection(self):
        summary = self.workspace / "review-collection-summary-B0DURABLE01-US.txt"
        summary.write_text("pages=22; total=433; summary only", encoding="utf-8")

        blocked = self.run_cli("init", expected=2)
        self.assertEqual(blocked["error"], "LEGACY_SUMMARY_ONLY")
        self.assertEqual(blocked["action"], "do_not_call_mcp")
        self.assertEqual(Path(blocked["summaryPath"]), summary)
        self.assertFalse((self.workspace / ".amazon-review-insights-cache" / "collections").exists())

        refreshed = self.run_cli("init", "--refresh")
        self.assertEqual(refreshed["action"], "initialized")

    def test_final_documented_page_completes_without_probe_request(self):
        self.initialize()
        self.run_cli("next-request")
        saved = self.save(response(1, 1, 2, [review(1), review(2)]))
        self.assertEqual(saved["status"], "complete")

        blocked = self.run_cli("next-request", expected=2)
        self.assertEqual(blocked["action"], "do_not_call_mcp")
        self.assertEqual(blocked["status"], "complete")
        self.assertNotIn("request", blocked)

    def test_changed_server_page_size_is_rejected_without_advancing(self):
        self.initialize()
        self.run_cli("next-request")
        failure = self.save(
            response(1, 2, 20, [review(i) for i in range(1, 11)], size=10),
            expected=2,
        )
        self.assertEqual(failure["error"], "PAGE_SIZE_MISMATCH")

        state = self.run_cli("status")
        self.assertEqual(state["status"], "collecting")
        self.assertEqual(state["nextPage"], 1)
        self.assertEqual(state["savedPages"], [])

    def test_more_records_than_page_size_is_rejected_without_advancing(self):
        self.initialize()
        self.run_cli("next-request")
        failure = self.save(
            response(1, 2, 21, [review(i) for i in range(1, 22)]),
            expected=2,
        )
        self.assertEqual(failure["error"], "PAGE_RECORD_OVERFLOW")
        self.assertEqual(self.run_cli("status")["nextPage"], 1)

    def test_identical_page_is_idempotent_but_conflicting_page_is_blocked(self):
        self.initialize()
        self.run_cli("next-request")
        payload = response(1, 2, 40, [review(i) for i in range(1, 21)])
        self.save(payload)

        repeated = self.save(payload, "same.json")
        self.assertEqual(repeated["action"], "already_saved")
        self.assertEqual(repeated["rawCount"], 20)

        conflicting = response(1, 2, 40, [review(i) for i in range(101, 121)])
        rejected = self.save(conflicting, "conflict.json", expected=2)
        self.assertEqual(rejected["error"], "PAGE_CONFLICT")
        self.assertEqual(self.run_cli("status")["nextPage"], 2)

    def test_export_round_trips_every_review_field_including_unknown_fields(self):
        self.initialize()
        self.run_cli("next-request")
        original = review(7)
        self.save(response(1, 1, 1, [original]))
        output = self.workspace / "export.json"

        exported = self.run_cli("export-json", "--output", str(output))
        self.assertEqual(exported["reviewCount"], 1)
        bundle = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(bundle["reviews"], [original])
        self.assertEqual(bundle["metadata"]["requestPageSize"], 20)

    def test_visit_limit_with_saved_reviews_is_partial_and_blocks_more_calls(self):
        self.initialize()
        self.run_cli("next-request")
        self.save(response(1, 2, 25, [review(i) for i in range(1, 21)]))
        self.run_cli("next-request")
        error_file = self.write_response(
            "visit-limit.json",
            {"code": "ERROR_VISIT_MAX", "message": "接口访问次数已达上限"},
        )

        recorded = self.run_cli("record-error", "--response-file", str(error_file))
        self.assertEqual(recorded["status"], "partial")
        self.assertEqual(recorded["failure"]["code"], "ERROR_VISIT_MAX")
        self.assertEqual(self.run_cli("next-request", expected=2)["status"], "partial")

    def test_visit_limit_without_reviews_persists_blocked_control_state(self):
        self.initialize()
        self.run_cli("next-request")
        error_file = self.write_response(
            "empty-limit.json",
            {"code": "ERROR_VISIT_MAX", "message": "接口访问次数已达上限"},
        )

        recorded = self.run_cli("record-error", "--response-file", str(error_file))
        self.assertEqual(recorded["status"], "blocked-empty")
        self.assertEqual(recorded["uniqueCount"], 0)
        self.assertEqual(self.run_cli("next-request", expected=2)["status"], "blocked-empty")

    def test_html_must_match_before_cache_deletion_and_receipt_backed_export(self):
        self.initialize()
        self.run_cli("next-request")
        originals = [review(1), review(2)]
        saved = self.save(response(1, 1, 2, originals))
        collection = Path(saved["collectionPath"])

        bad_html = self.workspace / "bad.html"
        bad_html.write_text(
            '<!doctype html><script type="application/json" id="review-data">[]</script>',
            encoding="utf-8",
        )
        mismatch = self.run_cli("finalize-html", "--html", str(bad_html), expected=2)
        self.assertEqual(mismatch["error"], "HTML_DATASET_MISMATCH")
        self.assertTrue(collection.is_dir())

        encoded = json.dumps(originals, ensure_ascii=False).replace("<", "\\u003c")
        good_html = self.workspace / "good.html"
        good_html.write_text(
            f'<!doctype html><script type="application/json" id="review-data">{encoded}</script>',
            encoding="utf-8",
        )
        finalized = self.run_cli("finalize-html", "--html", str(good_html))
        self.assertEqual(finalized["status"], "receipt-backed")
        self.assertFalse(collection.exists())
        self.assertTrue(Path(finalized["receiptPath"]).is_file())

        blocked = self.run_cli("next-request", expected=2)
        self.assertEqual(blocked["status"], "receipt-backed")
        recovered_path = self.workspace / "recovered.json"
        recovered = self.run_cli("export-json", "--output", str(recovered_path))
        self.assertEqual(recovered["source"], "verified-html")
        self.assertEqual(json.loads(recovered_path.read_text(encoding="utf-8"))["reviews"], originals)


if __name__ == "__main__":
    unittest.main()
