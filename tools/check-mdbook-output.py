#!/usr/bin/env python3
"""Validate generated mdBook output links before deployment."""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urldefrag


EXTERNAL_PREFIXES = (
    "http://",
    "https://",
    "mailto:",
    "tel:",
    "javascript:",
    "data:",
)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value for key, value in attrs if value is not None}
        if "id" in values:
            self.ids.add(values["id"])
        if tag == "a" and "href" in values:
            self.links.append(values["href"])


def html_pages(root: Path) -> dict[Path, PageParser]:
    pages: dict[Path, PageParser] = {}
    for path in root.rglob("*.html"):
        parser = PageParser()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        pages[path.resolve()] = parser
    return pages


def resolve_target(root: Path, page: Path, href: str) -> tuple[Path, str]:
    target, fragment = urldefrag(href)
    if target == "":
        resolved = page
    else:
        resolved = (page.parent / unquote(target)).resolve()
        if resolved.is_dir():
            resolved = resolved / "index.html"
    resolved.relative_to(root)
    return resolved, unquote(fragment)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check-mdbook-output.py OUT_DIR", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    pages = html_pages(root)
    findings: list[str] = []

    for page, parser in sorted(pages.items()):
        for href in parser.links:
            if href.startswith(EXTERNAL_PREFIXES):
                continue
            try:
                target, fragment = resolve_target(root, page, href)
            except ValueError:
                findings.append(
                    f"{page.relative_to(root)}: local href escapes output tree: {href}"
                )
                continue

            if not target.exists():
                findings.append(
                    f"{page.relative_to(root)}: missing local href target: {href}"
                )
                continue

            if fragment:
                target_parser = pages.get(target)
                if target_parser is not None and fragment not in target_parser.ids:
                    findings.append(
                        f"{page.relative_to(root)}: missing fragment target: {href}"
                    )

    if findings:
        print("mdBook output link check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1

    print(f"mdBook output link check passed ({len(pages)} HTML files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
