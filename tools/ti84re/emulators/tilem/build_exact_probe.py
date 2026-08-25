#!/usr/bin/env python3
"""Build the exact-byte hardware-probe runner from pinned TilEm sources."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ti84re.file_hashes import file_sha256
from ti84re.emulators.tilem.core import TILEM_COMMIT, TILEM_TREE, TilemCoreError, build_probe
from ti84re.paths import PROBES


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.force:
        parser.error(f"refusing to overwrite existing output {args.output}; use --force")
    adapters = [PROBES / "tilem/tilem_probe_support.c", PROBES / "tilem/tilem_exact_probe.c"]
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        command = build_probe(args.source, adapters, args.output, cc=args.cc)
    except (OSError, TilemCoreError) as error:
        parser.error(str(error))
    report = {
        "repository": "debrouxl/tilem",
        "commit": TILEM_COMMIT,
        "git_tree": TILEM_TREE,
        "adapters": [
            {"path": str(path), "sha256": file_sha256(path)} for path in adapters
        ],
        "output": str(args.output),
        "output_sha256": file_sha256(args.output),
        "command": command,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"built exact-probe runner: {args.output}")
        print(f"binary SHA-256: {report['output_sha256']}")


if __name__ == "__main__":
    main()
