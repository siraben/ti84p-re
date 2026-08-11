#!/usr/bin/env python3
"""Run hash-guarded battery-comparator cases through pinned TilEm."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tilem_battery import run_battery_probe, validate_battery_report
from tilem_core import TILEM_COMMIT, TILEM_TREE, TilemCoreError, file_sha256


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
                "battery-probe SHA-256 does not match --expected-binary-sha256"
            )
        report = validate_battery_report(run_battery_probe(args.binary))
        result = {
            "emulator": "TilEm",
            "commit": TILEM_COMMIT,
            "git_tree": TILEM_TREE,
            "binary": str(args.binary),
            "binary_sha256": binary_sha256,
            "report": report,
            "launch": "direct initialized-core battery comparator sweep",
            "evidence_scope": (
                "pinned TilEm port-0x02 comparator behavior; not TI-OS "
                "execution, measured voltages, or physical ASIC thresholds"
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
    print(
        "reachable levels: "
        + ",".join(map(str, report["source_model"]["reachable_rom_levels"]))
    )
    print(
        "unreachable levels: "
        + ",".join(map(str, report["source_model"]["unreachable_rom_levels"]))
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
