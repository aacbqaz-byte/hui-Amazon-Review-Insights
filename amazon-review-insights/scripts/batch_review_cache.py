#!/usr/bin/env python3
"""Durable multi-ASIN review collection orchestration.

Each batch keeps a stable member order for exports while every member delegates
durable page authorization and persistence to ``review_cache.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import review_cache


BATCH_SCHEMA_VERSION = 1
MIN_BATCH_SIZE = 2
MAX_BATCH_SIZE = 5

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def batch_root(workspace: str) -> Path:
    return Path(workspace).expanduser().resolve() / ".amazon-review-insights-cache" / "batches"


def normalize_batch_request(args: argparse.Namespace) -> tuple[dict[str, Any], list[str]]:
    marketplace = review_cache.safe_component(args.marketplace, "marketplace")
    display_order = [review_cache.safe_component(asin, "asin") for asin in args.asins]
    if not MIN_BATCH_SIZE <= len(display_order) <= MAX_BATCH_SIZE:
        raise review_cache.CacheError(
            "INVALID_BATCH_SIZE",
            f"A batch must contain {MIN_BATCH_SIZE} to {MAX_BATCH_SIZE} ASINs",
        )
    if len(set(display_order)) != len(display_order):
        raise review_cache.CacheError("DUPLICATE_ASIN", "A batch cannot contain the same ASIN more than once")
    stars = review_cache.normalize_values(args.stars, 1, 5, "starList")
    types = review_cache.normalize_values(args.types, 1, 4, "typeList")
    limit = review_cache.validate_collection_limit(args.limit)
    return (
        {
            "marketplace": marketplace,
            "asins": sorted(display_order),
            "starList": stars,
            "typeList": types,
            "targetLimit": limit,
        },
        display_order,
    )


def batch_id_for(request: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(request).encode("utf-8")).hexdigest()
    return f"batch-{digest[:24]}"


def batch_manifest_path(workspace: str, batch_id: str) -> Path:
    normalized = review_cache.safe_component(batch_id, "batch-id")
    return batch_root(workspace) / normalized / "manifest.json"


def load_batch(workspace: str, batch_id: str) -> dict[str, Any]:
    manifest_path = batch_manifest_path(workspace, batch_id)
    manifest = review_cache.load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != BATCH_SCHEMA_VERSION:
        raise review_cache.CacheError("BATCH_CACHE_CORRUPT", "Batch manifest schema is invalid")
    if manifest.get("batchId") != batch_id or not isinstance(manifest.get("request"), dict):
        raise review_cache.CacheError("BATCH_CACHE_CORRUPT", "Batch manifest identity is invalid")
    request = manifest["request"]
    display_order = manifest.get("displayOrder")
    if not isinstance(display_order, list) or display_order != request.get("displayOrder"):
        raise review_cache.CacheError("BATCH_CACHE_CORRUPT", "Batch display order is invalid")
    if sorted(display_order) != request.get("asins"):
        raise review_cache.CacheError("BATCH_CACHE_CORRUPT", "Batch members do not match its canonical request")
    review_cache.validate_collection_limit(request.get("targetLimit"))
    return manifest


def member_arguments(
    workspace: str,
    request: dict[str, Any],
    asin: str,
    command: str,
    **extra: Any,
) -> argparse.Namespace:
    return argparse.Namespace(
        workspace=workspace,
        marketplace=request["marketplace"],
        asin=asin,
        stars=[str(value) for value in request["starList"]],
        types=[str(value) for value in request["typeList"]],
        command=command,
        limit=request["targetLimit"],
        refresh=False,
        **extra,
    )


def member_paths(workspace: str, request: dict[str, Any], asin: str, command: str) -> tuple[argparse.Namespace, review_cache.CollectionPaths]:
    args = member_arguments(workspace, request, asin, command)
    return args, review_cache.resolve_collection_paths(args)


def require_member_target_compatibility(paths: review_cache.CollectionPaths, request: dict[str, Any]) -> None:
    if paths.manifest.exists():
        manifest, _ = review_cache.reconcile(paths)
        review_cache.require_target_limit_compatibility(manifest, request["targetLimit"])


def member_state(workspace: str, request: dict[str, Any], asin: str) -> dict[str, Any]:
    args, paths = member_paths(workspace, request, asin, "status")
    state = review_cache.command_status(args, paths)
    return {"asin": asin, **state}


def batch_state(workspace: str, manifest: dict[str, Any], **extra: Any) -> dict[str, Any]:
    request = manifest["request"]
    members = [member_state(workspace, request, asin) for asin in manifest["displayOrder"]]
    result = {
        "ok": True,
        "batchId": manifest["batchId"],
        "manifestPath": str(batch_manifest_path(workspace, manifest["batchId"])),
        "displayOrder": manifest["displayOrder"],
        "members": members,
    }
    result.update(extra)
    return result


def command_init(args: argparse.Namespace) -> dict[str, Any]:
    request, display_order = normalize_batch_request(args)
    batch_id = batch_id_for(request)
    manifest_path = batch_manifest_path(args.workspace, batch_id)
    if manifest_path.exists():
        manifest = load_batch(args.workspace, batch_id)
    else:
        stored_request = {**request, "displayOrder": display_order}
        manifest = {
            "schemaVersion": BATCH_SCHEMA_VERSION,
            "batchId": batch_id,
            "request": stored_request,
            "displayOrder": display_order,
            "createdAt": review_cache.utc_now(),
        }

    for asin in manifest["displayOrder"]:
        _, paths = member_paths(args.workspace, manifest["request"], asin, "init")
        require_member_target_compatibility(paths, manifest["request"])

    if not manifest_path.exists():
        review_cache.atomic_write_json(manifest_path, manifest)

    for asin in manifest["displayOrder"]:
        member_args = member_arguments(args.workspace, manifest["request"], asin, "init")
        paths = review_cache.resolve_collection_paths(member_args)
        review_cache.command_init(member_args, paths)
    return batch_state(args.workspace, manifest, action="initialized")


def selected_member(args: argparse.Namespace) -> tuple[dict[str, Any], str, argparse.Namespace, review_cache.CollectionPaths]:
    manifest = load_batch(args.workspace, args.batch_id)
    asin = review_cache.safe_component(args.asin, "asin")
    if asin not in manifest["displayOrder"]:
        raise review_cache.CacheError("BATCH_MEMBER_MISSING", f"ASIN {asin} is not in batch {args.batch_id}")
    member_args = member_arguments(args.workspace, manifest["request"], asin, args.command)
    paths = review_cache.resolve_collection_paths(member_args)
    require_member_target_compatibility(paths, manifest["request"])
    return manifest, asin, member_args, paths


def member_result(batch_id: str, asin: str, result: dict[str, Any]) -> dict[str, Any]:
    return {"batchId": batch_id, "asin": asin, **result}


def command_status(args: argparse.Namespace) -> dict[str, Any]:
    manifest = load_batch(args.workspace, args.batch_id)
    return batch_state(args.workspace, manifest, action="status")


def command_next_request(args: argparse.Namespace) -> dict[str, Any]:
    manifest, asin, member_args, paths = selected_member(args)
    return member_result(manifest["batchId"], asin, review_cache.command_next_request(member_args, paths))


def command_save_page(args: argparse.Namespace) -> dict[str, Any]:
    manifest, asin, member_args, paths = selected_member(args)
    member_args.response_file = args.response_file
    return member_result(manifest["batchId"], asin, review_cache.command_save_page(member_args, paths))


def command_record_error(args: argparse.Namespace) -> dict[str, Any]:
    manifest, asin, member_args, paths = selected_member(args)
    member_args.response_file = args.response_file
    return member_result(manifest["batchId"], asin, review_cache.command_record_error(member_args, paths))


def command_export_json(args: argparse.Namespace) -> dict[str, Any]:
    manifest = load_batch(args.workspace, args.batch_id)
    datasets: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    source_index: list[dict[str, str]] = []
    for asin in manifest["displayOrder"]:
        _, paths = member_paths(args.workspace, manifest["request"], asin, "export-json")
        require_member_target_compatibility(paths, manifest["request"])
        bundle, source = review_cache.export_bundle(paths)
        member_reviews = bundle["reviews"]
        datasets.append({"asin": asin, "source": source, **bundle})
        reviews.extend(member_reviews)
        source_index.extend(
            {"marketplace": manifest["request"]["marketplace"], "asin": asin}
            for _ in member_reviews
        )
    bundle = {
        "metadata": {
            "batchId": manifest["batchId"],
            **manifest["request"],
        },
        "datasets": datasets,
        "reviews": reviews,
        "sourceIndex": source_index,
    }
    output = Path(args.output).expanduser().resolve()
    review_cache.atomic_write_json(output, bundle)
    return {
        "ok": True,
        "action": "exported",
        "batchId": manifest["batchId"],
        "output": str(output),
        "reviewCount": len(reviews),
    }


def add_workspace_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", required=True)


def add_member_arguments(parser: argparse.ArgumentParser) -> None:
    add_workspace_argument(parser)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--asin", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    add_workspace_argument(init)
    init.add_argument("--marketplace", required=True)
    init.add_argument("--asins", nargs="+", required=True)
    init.add_argument("--stars", action="append")
    init.add_argument("--types", action="append")
    init.add_argument("--limit", type=int, default=review_cache.DEFAULT_COLLECTION_LIMIT)

    status = subparsers.add_parser("status")
    add_workspace_argument(status)
    status.add_argument("--batch-id", required=True)

    next_request = subparsers.add_parser("next-request")
    add_member_arguments(next_request)

    save_page = subparsers.add_parser("save-page")
    add_member_arguments(save_page)
    save_page.add_argument("--response-file", required=True)

    record_error = subparsers.add_parser("record-error")
    add_member_arguments(record_error)
    record_error.add_argument("--response-file", required=True)

    export_json = subparsers.add_parser("export-json")
    add_workspace_argument(export_json)
    export_json.add_argument("--batch-id", required=True)
    export_json.add_argument("--output", required=True)
    return parser


COMMANDS = {
    "init": command_init,
    "status": command_status,
    "next-request": command_next_request,
    "save-page": command_save_page,
    "record-error": command_record_error,
    "export-json": command_export_json,
}


def main() -> int:
    try:
        args = build_parser().parse_args()
        print(json.dumps(COMMANDS[args.command](args), ensure_ascii=False))
        return 0
    except review_cache.CacheError as exc:
        print(json.dumps({"ok": False, "error": exc.code, "message": exc.message, **exc.details}, ensure_ascii=False))
        return 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": "UNEXPECTED_ERROR", "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
