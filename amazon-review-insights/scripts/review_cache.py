#!/usr/bin/env python3
"""Durable SellerSprite review collection state.

This helper never calls SellerSprite. It authorizes one request at a time and
persists each successful response before another request can be authorized.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any

from validate_report import ReportValidationError, validate_report


SCHEMA_VERSION = 2
PAGE_SIZE = 20
MAX_RECORDS = 2000
TERMINAL_STATES = {"complete", "capped", "partial", "blocked-empty"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


class CacheError(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class ReviewDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.capture = False
        self.parts: list[str] = []
        self.found = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag.lower() == "script" and attributes.get("id") == "review-data":
            if attributes.get("type") != "application/json":
                raise CacheError("INVALID_HTML_DATA", "review-data must use type=application/json")
            if self.found:
                raise CacheError("INVALID_HTML_DATA", "HTML contains more than one review-data block")
            self.capture = True
            self.found = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self.capture:
            self.capture = False

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.parts.append(data)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CacheError("CACHE_MISSING", f"Required cache file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CacheError("CACHE_CORRUPT", f"Invalid JSON in {path}: {exc}") from exc


def normalize_values(values: list[str] | None, minimum: int, maximum: int, label: str) -> list[int]:
    result: set[int] = set()
    for item in values or []:
        for token in item.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                number = int(token)
            except ValueError as exc:
                raise CacheError("INVALID_FILTER", f"{label} must contain integers") from exc
            if not minimum <= number <= maximum:
                raise CacheError("INVALID_FILTER", f"{label} value {number} is outside {minimum}-{maximum}")
            result.add(number)
    return sorted(result)


def safe_component(value: str, label: str) -> str:
    normalized = value.strip().upper()
    if not normalized or not re.fullmatch(r"[A-Z0-9_-]+", normalized):
        raise CacheError("INVALID_IDENTITY", f"Invalid {label}: {value!r}")
    return normalized


class CollectionPaths:
    def __init__(self, args: argparse.Namespace) -> None:
        self.workspace = Path(args.workspace).expanduser().resolve()
        self.marketplace = safe_component(args.marketplace, "marketplace")
        self.asin = safe_component(args.asin, "asin")
        self.stars = normalize_values(args.stars, 1, 5, "starList")
        self.types = normalize_values(args.types, 1, 4, "typeList")
        stars_key = "-".join(map(str, self.stars)) if self.stars else "all"
        types_key = "-".join(map(str, self.types)) if self.types else "all"
        self.filter_key = f"stars-{stars_key}_types-{types_key}"
        self.identity = f"{self.marketplace}-{self.asin}-{self.filter_key}-size-{PAGE_SIZE}"
        self.root = self.workspace / ".amazon-review-insights-cache"
        self.collection = self.root / "collections" / self.identity
        self.pages = self.collection / "pages"
        self.manifest = self.collection / "manifest.json"
        self.reviews = self.collection / "reviews.jsonl"
        self.receipt = self.root / "receipts" / f"review-receipt-{self.identity}.json"

    def request_identity(self) -> dict[str, Any]:
        return {
            "marketplace": self.marketplace,
            "asin": self.asin,
            "starList": self.stars,
            "typeList": self.types,
            "requestPageSize": PAGE_SIZE,
        }


def new_manifest(paths: CollectionPaths) -> dict[str, Any]:
    now = utc_now()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "identity": paths.identity,
        "request": paths.request_identity(),
        "status": "collecting",
        "savedPages": [],
        "lastCommittedPage": 0,
        "nextPage": 1,
        "sourcePages": None,
        "sourceTotal": None,
        "rawCount": 0,
        "duplicateCount": 0,
        "uniqueCount": 0,
        "datasetSha256": sha256_text("[]"),
        "stopReason": None,
        "failure": None,
        "pendingRequest": None,
        "createdAt": now,
        "updatedAt": now,
    }


def validate_manifest(manifest: dict[str, Any], paths: CollectionPaths) -> None:
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise CacheError(
            "UNSUPPORTED_CACHE_SCHEMA",
            "Cache schema cannot be resumed automatically; explicit refresh is required",
            schemaVersion=manifest.get("schemaVersion"),
        )
    if manifest.get("identity") != paths.identity or manifest.get("request") != paths.request_identity():
        raise CacheError("CACHE_IDENTITY_MISMATCH", "Cache identity does not match this request")


def fingerprint(review: dict[str, Any]) -> str:
    fields = [
        review.get("author"),
        review.get("date"),
        review.get("title"),
        review.get("content"),
        review.get("star"),
    ]
    return sha256_text(canonical_json(fields))


def unique_reviews(raw_reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in raw_reviews:
        key = fingerprint(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def page_path(paths: CollectionPaths, page: int) -> Path:
    return paths.pages / f"page-{page:06d}.json"


def validate_page_file(page_value: dict[str, Any], paths: CollectionPaths, expected_page: int) -> None:
    if page_value.get("schemaVersion") != SCHEMA_VERSION or page_value.get("identity") != paths.identity:
        raise CacheError("CACHE_CORRUPT", f"Page {expected_page} has the wrong schema or identity")
    pagination = page_value.get("pagination")
    reviews = page_value.get("reviews")
    if not isinstance(pagination, dict) or pagination.get("page") != expected_page:
        raise CacheError("CACHE_CORRUPT", f"Page {expected_page} has invalid pagination")
    if pagination.get("size") != PAGE_SIZE:
        raise CacheError("CACHE_CORRUPT", f"Page {expected_page} does not use size {PAGE_SIZE}")
    if not isinstance(reviews, list) or any(not isinstance(item, dict) for item in reviews):
        raise CacheError("CACHE_CORRUPT", f"Page {expected_page} has invalid reviews")


def reconcile(paths: CollectionPaths) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = load_json(paths.manifest)
    if not isinstance(manifest, dict):
        raise CacheError("CACHE_CORRUPT", "Manifest must be a JSON object")
    validate_manifest(manifest, paths)

    files = sorted(paths.pages.glob("page-*.json")) if paths.pages.exists() else []
    raw: list[dict[str, Any]] = []
    saved_pages: list[int] = []
    last_pagination: dict[str, Any] | None = None
    for expected, path in enumerate(files, start=1):
        expected_name = f"page-{expected:06d}.json"
        if path.name != expected_name:
            raise CacheError("PAGE_GAP", f"Expected {expected_name}, found {path.name}; automatic crawling is blocked")
        page_value = load_json(path)
        if not isinstance(page_value, dict):
            raise CacheError("CACHE_CORRUPT", f"{path} must contain a JSON object")
        validate_page_file(page_value, paths, expected)
        saved_pages.append(expected)
        raw.extend(page_value["reviews"])
        last_pagination = page_value["pagination"]

    unique = unique_reviews(raw)
    prior_status = manifest.get("status")
    status = prior_status if prior_status in {"partial", "blocked-empty"} else "collecting"
    stop_reason = manifest.get("stopReason") if status != "collecting" else None
    source_pages = last_pagination.get("pages") if last_pagination else manifest.get("sourcePages")
    source_total = last_pagination.get("total") if last_pagination else manifest.get("sourceTotal")

    if status == "collecting" and last_pagination is not None:
        last_page = saved_pages[-1]
        page_count = len(load_json(page_path(paths, last_page))["reviews"])
        if len(raw) >= MAX_RECORDS:
            status = "capped"
            stop_reason = "cap-2000"
        elif isinstance(source_pages, int) and source_pages > 0 and last_page >= source_pages:
            status = "complete"
            stop_reason = "source-pages"
        elif page_count < PAGE_SIZE:
            status = "complete"
            stop_reason = "empty-page" if page_count == 0 else "short-page"

    jsonl = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in unique)
    if unique:
        atomic_write_text(paths.reviews, jsonl)
    elif paths.reviews.exists():
        paths.reviews.unlink()

    pending_request = manifest.get("pendingRequest")
    if isinstance(pending_request, dict):
        pending_page = pending_request.get("page")
        if not isinstance(pending_page, int) or pending_page <= (saved_pages[-1] if saved_pages else 0):
            pending_request = None
    else:
        pending_request = None
    if status != "collecting":
        pending_request = None

    manifest.update(
        {
            "status": status,
            "savedPages": saved_pages,
            "lastCommittedPage": saved_pages[-1] if saved_pages else 0,
            "nextPage": (saved_pages[-1] + 1) if saved_pages else 1,
            "sourcePages": source_pages,
            "sourceTotal": source_total,
            "rawCount": len(raw),
            "duplicateCount": len(raw) - len(unique),
            "uniqueCount": len(unique),
            "datasetSha256": sha256_text(canonical_json(unique)),
            "stopReason": stop_reason,
            "pendingRequest": pending_request,
            "updatedAt": utc_now(),
        }
    )
    atomic_write_json(paths.manifest, manifest)
    return manifest, unique


def public_state(manifest: dict[str, Any], paths: CollectionPaths, **extra: Any) -> dict[str, Any]:
    value = {
        "ok": True,
        "status": manifest["status"],
        "identity": paths.identity,
        "collectionPath": str(paths.collection),
        "manifestPath": str(paths.manifest),
        "savedPages": manifest["savedPages"],
        "lastCommittedPage": manifest["lastCommittedPage"],
        "nextPage": manifest["nextPage"],
        "rawCount": manifest["rawCount"],
        "duplicateCount": manifest["duplicateCount"],
        "uniqueCount": manifest["uniqueCount"],
        "sourcePages": manifest["sourcePages"],
        "sourceTotal": manifest["sourceTotal"],
        "failure": manifest.get("failure"),
        "pendingPage": (manifest.get("pendingRequest") or {}).get("page"),
    }
    value.update(extra)
    return value


def parse_html_reviews(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        raise CacheError("HTML_MISSING", f"HTML file is missing or empty: {path}")
    parser = ReviewDataParser()
    parser.feed(path.read_text(encoding="utf-8"))
    if not parser.found:
        raise CacheError("INVALID_HTML_DATA", "HTML does not contain the review-data JSON block")
    try:
        reviews = json.loads("".join(parser.parts))
    except json.JSONDecodeError as exc:
        raise CacheError("INVALID_HTML_DATA", f"review-data is not valid JSON: {exc}") from exc
    if not isinstance(reviews, list) or any(not isinstance(item, dict) for item in reviews):
        raise CacheError("INVALID_HTML_DATA", "review-data must be an array of review objects")
    return reviews


def read_valid_receipt(paths: CollectionPaths) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    receipt = load_json(paths.receipt)
    if not isinstance(receipt, dict) or receipt.get("schemaVersion") != SCHEMA_VERSION:
        raise CacheError("RECEIPT_CORRUPT", "Receipt schema is invalid; automatic crawling is blocked")
    if receipt.get("identity") != paths.identity or receipt.get("request") != paths.request_identity():
        raise CacheError("RECEIPT_IDENTITY_MISMATCH", "Receipt identity does not match this request")
    html_path = Path(receipt.get("htmlPath", ""))
    if not html_path.is_file() or sha256_file(html_path) != receipt.get("htmlSha256"):
        raise CacheError("RECEIPT_SOURCE_INVALID", "Receipt-backed HTML is missing or changed; automatic crawling is blocked")
    reviews = parse_html_reviews(html_path)
    if len(reviews) != receipt.get("reviewCount") or sha256_text(canonical_json(reviews)) != receipt.get("datasetSha256"):
        raise CacheError("RECEIPT_SOURCE_INVALID", "Receipt-backed HTML review data does not match its receipt")
    return receipt, reviews


def archive_existing(paths: CollectionPaths) -> None:
    if not paths.collection.exists() and not paths.receipt.exists():
        return
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive = paths.root / "archive" / f"{paths.identity}-{suffix}"
    archive.mkdir(parents=True, exist_ok=False)
    if paths.collection.exists():
        shutil.move(str(paths.collection), str(archive / "collection"))
    if paths.receipt.exists():
        shutil.move(str(paths.receipt), str(archive / "receipt.json"))


def find_legacy_summary(paths: CollectionPaths) -> Path | None:
    for candidate in paths.workspace.rglob("review-collection-summary-*.txt"):
        name = candidate.name.upper()
        if paths.asin in name and paths.marketplace in name:
            return candidate.resolve()
    return None


def command_init(args: argparse.Namespace, paths: CollectionPaths) -> dict[str, Any]:
    if args.refresh:
        archive_existing(paths)
    elif paths.receipt.exists():
        receipt, reviews = read_valid_receipt(paths)
        return {
            "ok": True,
            "action": "use_verified_html",
            "status": "receipt-backed",
            "identity": paths.identity,
            "receiptPath": str(paths.receipt),
            "htmlPath": receipt["htmlPath"],
            "uniqueCount": len(reviews),
        }
    if paths.manifest.exists():
        manifest, _ = reconcile(paths)
        return public_state(manifest, paths, action="resume_existing")
    legacy_summary = None if args.refresh else find_legacy_summary(paths)
    if legacy_summary is not None:
        raise CacheError(
            "LEGACY_SUMMARY_ONLY",
            "发现旧版采集摘要但没有完整评论缓存；为避免重复消耗 MCP 次数，已停止。只有用户明确要求刷新后才能重新抓取。",
            action="do_not_call_mcp",
            status="legacy-summary-only",
            summaryPath=str(legacy_summary),
        )
    paths.pages.mkdir(parents=True, exist_ok=True)
    manifest = new_manifest(paths)
    atomic_write_json(paths.manifest, manifest)
    return public_state(manifest, paths, action="initialized")


def command_status(args: argparse.Namespace, paths: CollectionPaths) -> dict[str, Any]:
    if paths.manifest.exists():
        manifest, _ = reconcile(paths)
        return public_state(manifest, paths, action="status")
    if paths.receipt.exists():
        receipt, reviews = read_valid_receipt(paths)
        return {
            "ok": True,
            "action": "status",
            "status": "receipt-backed",
            "identity": paths.identity,
            "receiptPath": str(paths.receipt),
            "htmlPath": receipt["htmlPath"],
            "uniqueCount": len(reviews),
        }
    raise CacheError("CACHE_ABSENT", "No durable collection state exists; run init before any MCP call")


def command_next_request(args: argparse.Namespace, paths: CollectionPaths) -> dict[str, Any]:
    if paths.receipt.exists():
        receipt, reviews = read_valid_receipt(paths)
        raise CacheError(
            "MCP_CALL_BLOCKED",
            "A verified HTML source already contains the complete local review dataset; do not call MCP",
            action="do_not_call_mcp",
            status="receipt-backed",
            receiptPath=str(paths.receipt),
            htmlPath=receipt["htmlPath"],
            uniqueCount=len(reviews),
        )
    manifest, _ = reconcile(paths)
    if manifest["status"] != "collecting":
        raise CacheError(
            "MCP_CALL_BLOCKED",
            f"Collection status is {manifest['status']}; do not call MCP",
            action="do_not_call_mcp",
            status=manifest["status"],
            nextPage=manifest["nextPage"],
            savedPages=manifest["savedPages"],
            uniqueCount=manifest["uniqueCount"],
        )
    pending = manifest.get("pendingRequest")
    if isinstance(pending, dict):
        raise CacheError(
            "REQUEST_PENDING",
            "This page was already authorized and has not been committed; do not call MCP again automatically",
            action="do_not_call_mcp",
            status="collecting",
            pendingPage=pending.get("page"),
            authorizedAt=pending.get("authorizedAt"),
        )
    request: dict[str, Any] = {
        "marketplace": paths.marketplace,
        "asin": paths.asin,
        "page": manifest["nextPage"],
        "size": PAGE_SIZE,
    }
    if paths.stars:
        request["starList"] = paths.stars
    if paths.types:
        request["typeList"] = paths.types
    manifest["pendingRequest"] = {
        "page": manifest["nextPage"],
        "requestSha256": sha256_text(canonical_json(request)),
        "authorizedAt": utc_now(),
    }
    manifest["updatedAt"] = utc_now()
    atomic_write_json(paths.manifest, manifest)
    return public_state(manifest, paths, action="call_mcp", request=request)


def build_page_value(response: dict[str, Any], paths: CollectionPaths) -> dict[str, Any]:
    if response.get("code") != "OK":
        raise CacheError("MCP_RESPONSE_ERROR", "Successful pages require code=OK; use record-error for failures")
    data = response.get("data")
    if not isinstance(data, dict):
        raise CacheError("INVALID_MCP_RESPONSE", "MCP response data must be an object")
    current_page = data.get("page")
    size = data.get("size")
    records = data.get("content")
    if not isinstance(current_page, int) or current_page < 1:
        raise CacheError("INVALID_MCP_RESPONSE", "data.page must be a positive integer")
    if size != PAGE_SIZE:
        raise CacheError("PAGE_SIZE_MISMATCH", f"Expected data.size={PAGE_SIZE}, received {size}")
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise CacheError("INVALID_MCP_RESPONSE", "data.content must be an array of review objects")
    if len(records) > PAGE_SIZE:
        raise CacheError(
            "PAGE_RECORD_OVERFLOW",
            f"Page contains {len(records)} reviews but declared page size is {PAGE_SIZE}",
        )
    metadata = {key: value for key, value in data.items() if key != "content"}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "identity": paths.identity,
        "source": {"code": response.get("code"), "message": response.get("message")},
        "pagination": {
            "page": current_page,
            "size": size,
            "pages": data.get("pages"),
            "total": data.get("total"),
        },
        "metadata": metadata,
        "reviews": records,
        "savedAt": utc_now(),
    }


def comparable_page(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "savedAt"}


def command_save_page(args: argparse.Namespace, paths: CollectionPaths) -> dict[str, Any]:
    manifest, _ = reconcile(paths)
    response_value = load_json(Path(args.response_file))
    if not isinstance(response_value, dict):
        raise CacheError("INVALID_MCP_RESPONSE", "MCP response must be a JSON object")
    page_value = build_page_value(response_value, paths)
    current_page = page_value["pagination"]["page"]
    destination = page_path(paths, current_page)
    if destination.exists():
        existing = load_json(destination)
        if canonical_json(comparable_page(existing)) == canonical_json(comparable_page(page_value)):
            manifest, _ = reconcile(paths)
            return public_state(manifest, paths, action="already_saved", page=current_page)
        raise CacheError("PAGE_CONFLICT", f"Page {current_page} is already saved with different content")
    if manifest["status"] != "collecting":
        raise CacheError("MCP_CALL_BLOCKED", f"Cannot save a page while status is {manifest['status']}")
    pending = manifest.get("pendingRequest")
    if not isinstance(pending, dict) or pending.get("page") != current_page:
        raise CacheError(
            "UNAUTHORIZED_PAGE",
            f"Page {current_page} has no matching durable request authorization",
        )
    if current_page != manifest["nextPage"]:
        raise CacheError(
            "UNAUTHORIZED_PAGE",
            f"Expected page {manifest['nextPage']}, received page {current_page}; state was not advanced",
        )
    atomic_write_json(destination, page_value)
    manifest, _ = reconcile(paths)
    return public_state(manifest, paths, action="page_saved", page=current_page)


def command_record_error(args: argparse.Namespace, paths: CollectionPaths) -> dict[str, Any]:
    manifest, _ = reconcile(paths)
    if manifest["status"] != "collecting":
        raise CacheError("MCP_CALL_BLOCKED", f"Cannot record a new MCP error while status is {manifest['status']}")
    if not isinstance(manifest.get("pendingRequest"), dict):
        raise CacheError("UNAUTHORIZED_ERROR", "No durable MCP request authorization is pending")
    response_value = load_json(Path(args.response_file))
    if not isinstance(response_value, dict):
        raise CacheError("INVALID_MCP_RESPONSE", "MCP error response must be a JSON object")
    code = response_value.get("code")
    message = response_value.get("message")
    if not isinstance(code, str) or not code or code == "OK":
        raise CacheError("INVALID_MCP_RESPONSE", "record-error requires a non-OK code")
    manifest["status"] = "partial" if manifest["uniqueCount"] else "blocked-empty"
    manifest["failure"] = {"code": code, "message": message}
    manifest["pendingRequest"] = None
    manifest["stopReason"] = "mcp-error"
    manifest["updatedAt"] = utc_now()
    atomic_write_json(paths.manifest, manifest)
    return public_state(manifest, paths, action="error_recorded")


def export_bundle(paths: CollectionPaths) -> tuple[dict[str, Any], str]:
    if paths.manifest.exists():
        manifest, reviews = reconcile(paths)
        if manifest["status"] in {"collecting", "blocked-empty"}:
            raise CacheError("EXPORT_BLOCKED", f"Cannot export collection in status {manifest['status']}")
        metadata = {
            "identity": paths.identity,
            **manifest["request"],
            "status": manifest["status"],
            "sourcePages": manifest["sourcePages"],
            "sourceTotal": manifest["sourceTotal"],
            "rawCount": manifest["rawCount"],
            "duplicateCount": manifest["duplicateCount"],
            "uniqueCount": manifest["uniqueCount"],
            "failure": manifest.get("failure"),
            "datasetSha256": manifest["datasetSha256"],
        }
        return {"metadata": metadata, "reviews": reviews}, "live-cache"
    if paths.receipt.exists():
        receipt, reviews = read_valid_receipt(paths)
        metadata = dict(receipt["metadata"])
        metadata["status"] = "receipt-backed"
        return {"metadata": metadata, "reviews": reviews}, "verified-html"
    raise CacheError("CACHE_ABSENT", "No local reviews are available; automatic crawling is blocked")


def command_export_json(args: argparse.Namespace, paths: CollectionPaths) -> dict[str, Any]:
    bundle, source = export_bundle(paths)
    output = Path(args.output).expanduser().resolve()
    atomic_write_json(output, bundle)
    return {
        "ok": True,
        "action": "exported",
        "source": source,
        "output": str(output),
        "reviewCount": len(bundle["reviews"]),
    }


def command_finalize_html(args: argparse.Namespace, paths: CollectionPaths) -> dict[str, Any]:
    manifest, reviews = reconcile(paths)
    if manifest["status"] not in {"complete", "capped", "partial"}:
        raise CacheError("HTML_FINALIZE_BLOCKED", f"Cannot finalize HTML while status is {manifest['status']}")
    html_path = Path(args.html).expanduser().resolve()
    try:
        validate_report(html_path)
    except ReportValidationError as exc:
        raise CacheError(exc.code, exc.message, **exc.details) from exc
    html_reviews = parse_html_reviews(html_path)
    html_dataset_hash = sha256_text(canonical_json(html_reviews))
    if len(html_reviews) != manifest["uniqueCount"] or html_dataset_hash != manifest["datasetSha256"]:
        raise CacheError(
            "HTML_DATASET_MISMATCH",
            "HTML does not contain the complete cached unique review dataset; cache was preserved",
            expectedCount=manifest["uniqueCount"],
            actualCount=len(html_reviews),
        )
    metadata = {
        "identity": paths.identity,
        **manifest["request"],
        "sourcePages": manifest["sourcePages"],
        "sourceTotal": manifest["sourceTotal"],
        "rawCount": manifest["rawCount"],
        "duplicateCount": manifest["duplicateCount"],
        "uniqueCount": manifest["uniqueCount"],
        "collectionStatus": manifest["status"],
        "failure": manifest.get("failure"),
        "datasetSha256": manifest["datasetSha256"],
    }
    receipt = {
        "schemaVersion": SCHEMA_VERSION,
        "identity": paths.identity,
        "request": paths.request_identity(),
        "status": "receipt-backed",
        "htmlPath": str(html_path),
        "htmlSha256": sha256_file(html_path),
        "datasetSha256": html_dataset_hash,
        "reviewCount": len(reviews),
        "metadata": metadata,
        "createdAt": utc_now(),
    }
    atomic_write_json(paths.receipt, receipt)
    shutil.rmtree(paths.collection)
    return {
        "ok": True,
        "action": "cache_replaced_by_verified_html",
        "status": "receipt-backed",
        "receiptPath": str(paths.receipt),
        "htmlPath": str(html_path),
        "reviewCount": len(reviews),
    }


def add_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--marketplace", required=True)
    parser.add_argument("--asin", required=True)
    parser.add_argument("--stars", action="append")
    parser.add_argument("--types", action="append")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "next-request"):
        command = subparsers.add_parser(name)
        add_identity_arguments(command)

    init = subparsers.add_parser("init")
    add_identity_arguments(init)
    init.add_argument("--refresh", action="store_true")

    save_page = subparsers.add_parser("save-page")
    add_identity_arguments(save_page)
    save_page.add_argument("--response-file", required=True)

    record_error = subparsers.add_parser("record-error")
    add_identity_arguments(record_error)
    record_error.add_argument("--response-file", required=True)

    export_json = subparsers.add_parser("export-json")
    add_identity_arguments(export_json)
    export_json.add_argument("--output", required=True)

    finalize_html = subparsers.add_parser("finalize-html")
    add_identity_arguments(finalize_html)
    finalize_html.add_argument("--html", required=True)
    return parser


COMMANDS = {
    "init": command_init,
    "status": command_status,
    "next-request": command_next_request,
    "save-page": command_save_page,
    "record-error": command_record_error,
    "export-json": command_export_json,
    "finalize-html": command_finalize_html,
}


def main() -> int:
    try:
        args = build_parser().parse_args()
        paths = CollectionPaths(args)
        result = COMMANDS[args.command](args, paths)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except CacheError as exc:
        payload = {"ok": False, "error": exc.code, "message": exc.message, **exc.details}
        print(json.dumps(payload, ensure_ascii=False))
        return 2
    except Exception as exc:  # fail closed: an unexpected problem must never authorize MCP
        print(json.dumps({"ok": False, "error": "UNEXPECTED_ERROR", "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
