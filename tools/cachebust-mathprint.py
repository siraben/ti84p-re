#!/usr/bin/env python3
"""Attach content versions to the built MathPrint page's local assets."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text)
    if count != 1:
        raise RuntimeError(f"expected one {label} reference, found {count}")
    return updated


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: cachebust-mathprint.py BUILT_MATHPRINT_DIR", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    index_path = root / "index.html"
    app_path = root / "app.js"
    if not index_path.is_file() or not app_path.is_file():
        raise RuntimeError("built MathPrint directory lacks index.html or app.js")

    app = app_path.read_text()
    for filename in (
        "font.json", "layout.json", "draw-order.json", "token-strings.json"
    ):
        version = digest(root / filename)
        app = replace_once(
            app,
            rf"fetch\('{re.escape(filename)}(?:\?v=[0-9a-f]+)?'\)",
            f"fetch('{filename}?v={version}')",
            f"fetch for {filename}",
        )
    app_path.write_text(app)

    index = index_path.read_text()
    for attribute, filename in (
        ("href", "style.css"),
        ("src", "rom-engine.js"),
        ("src", "app.js"),
    ):
        version = digest(root / filename)
        index = replace_once(
            index,
            rf'{attribute}="{re.escape(filename)}(?:\?v=[0-9a-f]+)?"',
            f'{attribute}="{filename}?v={version}"',
            f"{filename} asset",
        )
    index_path.write_text(index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
