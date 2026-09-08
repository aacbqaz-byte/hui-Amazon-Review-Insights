#!/usr/bin/env python3
"""Validate an offline Amazon review report before delivery or cache cleanup."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


class ReportValidationError(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class ReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.ids: dict[str, dict[str, str | None]] = {}
        self.tabs: list[dict[str, str | None]] = []
        self.panels: list[dict[str, str | None]] = []
        self.scripts: list[dict[str, Any]] = []
        self.active_script: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value for key, value in attrs}
        element_id = attributes.get("id")
        if element_id:
            if element_id in self.ids:
                raise ReportValidationError("DUPLICATE_ID", f"Duplicate HTML id: {element_id}", elementId=element_id)
            self.ids[element_id] = attributes
        role = (attributes.get("role") or "").lower()
        if role == "tab":
            self.tabs.append(attributes)
        elif role == "tabpanel":
            self.panels.append(attributes)
        if tag.lower() == "script":
            script = {"attrs": attributes, "parts": []}
            self.scripts.append(script)
            self.active_script = script

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            self.active_script = None

    def handle_data(self, data: str) -> None:
        if self.active_script is not None:
            self.active_script["parts"].append(data)


def read_report(path: Path) -> tuple[ReportParser, list[str], list[dict[str, Any]]]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ReportValidationError("HTML_MISSING", f"HTML file is missing or empty: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ReportValidationError("HTML_NOT_UTF8", f"HTML is not valid UTF-8: {exc}") from exc
    parser = ReportParser()
    try:
        parser.feed(text)
        parser.close()
    except ReportValidationError:
        raise
    except Exception as exc:
        raise ReportValidationError("HTML_PARSE_ERROR", f"HTML could not be parsed: {exc}") from exc

    executable: list[str] = []
    json_scripts: list[dict[str, Any]] = []
    for script in parser.scripts:
        attrs = script["attrs"]
        if attrs.get("src"):
            raise ReportValidationError(
                "EXTERNAL_SCRIPT",
                "Standalone reports may not load external scripts",
                source=attrs["src"],
            )
        script_type = (attrs.get("type") or "text/javascript").lower()
        content = "".join(script["parts"])
        if script_type == "application/json":
            json_scripts.append({"attrs": attrs, "content": content})
        else:
            executable.append(content)
    return parser, executable, json_scripts


def validate_navigation(parser: ReportParser, executable: list[str]) -> None:
    panel_ids = {panel.get("id") for panel in parser.panels if panel.get("id")}
    selected_count = 0
    for tab in parser.tabs:
        target = tab.get("aria-controls")
        if not target:
            raise ReportValidationError("NAV_TARGET_MISSING", "Every tab needs aria-controls", target=None)
        if target not in panel_ids:
            raise ReportValidationError(
                "NAV_TARGET_MISSING",
                f"Navigation target does not exist: {target}",
                target=target,
            )
        if not tab.get("data-view"):
            raise ReportValidationError("NAV_VIEW_MISSING", f"Tab targeting {target} needs data-view")
        if (tab.get("aria-selected") or "").lower() == "true":
            selected_count += 1
    if selected_count != 1:
        raise ReportValidationError(
            "NAV_SELECTION_INVALID",
            "Exactly one navigation tab must start selected",
            selectedCount=selected_count,
        )

    combined = "\n".join(executable)
    required_tokens = ("addEventListener", "aria-selected", "hidden")
    missing = [token for token in required_tokens if token not in combined]
    locator_hints = ("data-view", "aria-controls", '[role="tab"]', "[role='tab']", "[role=tab]")
    if not any(token in combined for token in locator_hints):
        missing.append("tab target lookup")
    if missing:
        raise ReportValidationError(
            "NAV_BINDING_MISSING",
            "Executable JavaScript does not contain the required navigation binding",
            missing=missing,
        )


def validate_review_browser(parser: ReportParser, executable: list[str]) -> None:
    required_ids = ("q", "star", "list", "pager")
    missing_ids = [element_id for element_id in required_ids if element_id not in parser.ids]
    if missing_ids:
        raise ReportValidationError(
            "REVIEW_BROWSER_CONTROL_MISSING",
            "Review browser needs search, star filter, review list, and pagination controls",
            missing=missing_ids,
        )
    combined = "\n".join(executable)
    required_bindings = {
        "search": (".oninput", "oninput=", "addEventListener('input'", 'addEventListener("input"'),
        "starFilter": (".onchange", "onchange=", "addEventListener('change'", 'addEventListener("change"'),
        "pagination": (".onclick", "onclick=", "addEventListener('click'", 'addEventListener("click"'),
    }
    missing = [name for name, tokens in required_bindings.items() if not any(token in combined for token in tokens)]
    if "render" not in combined:
        missing.append("render")
    if missing:
        raise ReportValidationError(
            "REVIEW_BROWSER_BINDING_MISSING",
            "Review browser controls are not fully bound",
            missing=missing,
        )


def validate_download(parser: ReportParser, executable: list[str]) -> None:
    download_id = "download-html" if "download-html" in parser.ids else "download" if "download" in parser.ids else None
    if download_id is None:
        raise ReportValidationError("DOWNLOAD_CONTROL_MISSING", "Report needs id=download-html")
    combined = "\n".join(executable)
    missing = [token for token in (download_id, "addEventListener", "Blob") if token not in combined]
    if missing:
        raise ReportValidationError(
            "DOWNLOAD_BINDING_MISSING",
            "Download HTML control is not bound to an offline Blob download",
            missing=missing,
        )


def validate_review_data(json_scripts: list[dict[str, Any]]) -> int:
    matches = [item for item in json_scripts if item["attrs"].get("id") == "review-data"]
    if len(matches) != 1:
        raise ReportValidationError(
            "REVIEW_DATA_MISSING",
            "Report must contain exactly one application/json script with id=review-data",
            count=len(matches),
        )
    try:
        reviews = json.loads(matches[0]["content"])
    except json.JSONDecodeError as exc:
        raise ReportValidationError("REVIEW_DATA_INVALID", f"review-data is invalid JSON: {exc}") from exc
    if not isinstance(reviews, list) or any(not isinstance(item, dict) for item in reviews):
        raise ReportValidationError("REVIEW_DATA_INVALID", "review-data must be an array of review objects")
    return len(reviews)


def validate_javascript(executable: list[str], node: str | None = None) -> None:
    if not executable:
        raise ReportValidationError("JS_MISSING", "Report has no executable inline JavaScript")
    runtime = node or shutil.which("node")
    if not runtime:
        raise ReportValidationError(
            "JS_RUNTIME_MISSING",
            "Node.js or an equivalent JavaScript syntax checker is required before report delivery",
        )
    for index, script in enumerate(executable, start=1):
        completed = subprocess.run(
            [runtime, "--check", "-"],
            input=script,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            details = (completed.stderr or completed.stdout).strip()
            raise ReportValidationError(
                "JS_SYNTAX_ERROR",
                f"Executable script {index} has invalid JavaScript syntax",
                scriptIndex=index,
                details=details,
            )


def validate_report(path: Path, node: str | None = None) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    parser, executable, json_scripts = read_report(resolved)
    validate_javascript(executable, node=node)
    report_mode = "analysis" if parser.tabs else "review-browser"
    if parser.tabs:
        validate_navigation(parser, executable)
    else:
        validate_review_browser(parser, executable)
    validate_download(parser, executable)
    review_count = validate_review_data(json_scripts)
    return {
        "ok": True,
        "status": "valid",
        "reportMode": report_mode,
        "htmlPath": str(resolved),
        "executableScriptCount": len(executable),
        "tabCount": len(parser.tabs),
        "panelCount": len(parser.panels),
        "reviewCount": review_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html")
    parser.add_argument("--node")
    args = parser.parse_args()
    try:
        print(json.dumps(validate_report(Path(args.html), node=args.node), ensure_ascii=False))
        return 0
    except ReportValidationError as exc:
        print(
            json.dumps(
                {"ok": False, "error": exc.code, "message": exc.message, **exc.details},
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
