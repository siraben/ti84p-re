#!/usr/bin/env python3
"""Build the direct Flash-command probe from exact pinned TilEm sources."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tilem_core import (
    TILEM_COMMIT,
    TILEM_TREE,
    TilemCoreError,
    build_probe,
    file_sha256,
)

TOOLS = Path(__file__).resolve().parent
ADAPTER_NAMES = ("tilem_probe_support.c", "tilem_flash_probe.c")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.output.exists() and not args.force:
        parser.error(
            f"refusing to overwrite existing output {args.output}; use --force"
        )
    adapters = [TOOLS / name for name in ADAPTER_NAMES]
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        command = build_probe(args.source, adapters, args.output, cc=args.cc)
        report = {
            "repository": "debrouxl/tilem",
            "commit": TILEM_COMMIT,
            "git_tree": TILEM_TREE,
            "source": str(args.source),
            "adapters": [
                {"path": str(path), "sha256": file_sha256(path)} for path in adapters
            ],
            "output": str(args.output),
            "output_sha256": file_sha256(args.output),
            "command": command,
        }
    except (OSError, TilemCoreError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"built pinned TilEm {TILEM_COMMIT[:8]} Flash probe: {args.output}")
        print(f"binary SHA-256: {report['output_sha256']}")


if __name__ == "__main__":
    main()
