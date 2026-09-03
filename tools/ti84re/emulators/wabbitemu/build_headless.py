#!/usr/bin/env python3
"""Build a hash-guarded Linux runner for the pinned Wabbitemu core."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ti84re.emulators.wabbitemu.headless import (
    WABBITEMU_ARCHIVE_SHA256,
    WABBITEMU_ARCHIVE_URL,
    WABBITEMU_COMMIT,
    WABBITEMU_TREE_SHA256,
    SOURCE_HASHES,
    WabbitemuHeadlessError,
    build_headless,
)
from ti84re.paths import PROBES


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cxx", default="g++")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.output.exists() and not args.force:
        parser.error(f"refusing to overwrite existing output {args.output}; use --force")
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        command = build_headless(
            args.source,
            PROBES / "wabbitemu/wabbitemu_headless.cpp",
            args.output,
            cxx=args.cxx,
        )
    except WabbitemuHeadlessError as error:
        parser.error(str(error))
    report = {
        "repository": "sputt/wabbitemu",
        "commit": WABBITEMU_COMMIT,
        "archive_url": WABBITEMU_ARCHIVE_URL,
        "expected_archive_sha256": WABBITEMU_ARCHIVE_SHA256,
        "source": str(args.source),
        "source_tree_sha256": WABBITEMU_TREE_SHA256,
        "source_hashes": SOURCE_HASHES,
        "output": str(args.output),
        "command": command,
        "portability_shims": [
            "erase MSVC-only __pragma from lcd.c during preprocessing",
            "stub unused debugger-registry and disabled-audio callbacks",
        ],
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"built pinned Wabbitemu {WABBITEMU_COMMIT[:8]} runner: {args.output}")


if __name__ == "__main__":
    main()
