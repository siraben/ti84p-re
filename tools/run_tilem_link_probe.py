#!/usr/bin/env python3
"""Run hash-guarded raw-link and link-assist cases through pinned TilEm."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tilem_core import TILEM_COMMIT, TILEM_TREE, TilemCoreError, file_sha256
from tilem_link import run_link_probe, validate_link_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-binary-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.output_dir.exists():
        parser.error(f"refusing to reuse existing output directory {args.output_dir}")
    try:
        binary_sha256 = file_sha256(args.binary)
        if binary_sha256 != args.expected_binary_sha256.lower():
            raise TilemCoreError(
                "link-probe SHA-256 does not match --expected-binary-sha256"
            )
        report = validate_link_report(run_link_probe(args.binary))
        result = {
            "emulator": "TilEm",
            "commit": TILEM_COMMIT,
            "git_tree": TILEM_TREE,
            "binary": str(args.binary),
            "binary_sha256": binary_sha256,
            "report": report,
            "launch": "direct initialized-core raw-link and assist port handlers",
            "evidence_scope": (
                "pinned TilEm raw and link-assist state transitions; not TI-OS "
                "execution, virtual-cable lifecycle, electrical levels, physical "
                "edge timing, or connected-calculator behavior"
            ),
        }
        args.output_dir.mkdir(parents=True)
        manifest = args.output_dir / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, TilemCoreError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2))
        return
    native = report["native"]
    print(
        "raw rows: "
        + " / ".join(
            ",".join(f"{value:02X}" for value in native["raw_reads"][start : start + 4])
            for start in range(0, 16, 4)
        )
    )
    print(
        f"assist: send={native['send'][0]:02X}, "
        f"receive={native['receive'][0]:02X}, error={native['error'][0]:02X}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
