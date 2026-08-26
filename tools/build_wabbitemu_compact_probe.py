#!/usr/bin/env python3
"""Build the compact-display runner from pinned Wabbitemu sources."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from file_hashes import file_sha256
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WABBITEMU_TREE_SHA256,
    WabbitemuHeadlessError,
    build_headless,
)

TOOLS = Path(__file__).resolve().parent


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
        adapter = TOOLS / "wabbitemu_compact_probe.cpp"
        command = build_headless(args.source, adapter, args.output, cxx=args.cxx)
    except (OSError, WabbitemuHeadlessError) as error:
        parser.error(str(error))
    report = {
        "repository": "sputt/wabbitemu",
        "commit": WABBITEMU_COMMIT,
        "source_tree_sha256": WABBITEMU_TREE_SHA256,
        "adapter": str(adapter),
        "adapter_sha256": file_sha256(adapter),
        "output": str(args.output),
        "output_sha256": file_sha256(args.output),
        "command": command,
    }
    print(json.dumps(report, indent=2) if args.json else report["output_sha256"])


if __name__ == "__main__":
    main()
