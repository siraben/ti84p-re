#!/usr/bin/env python3
"""Run hash-guarded direct interrupt cases through pinned TilEm."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tilem_core import TILEM_COMMIT, TILEM_TREE, TilemCoreError, file_sha256
from tilem_interrupt import run_interrupt_probe, validate_interrupt_report


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
                "interrupt-probe SHA-256 does not match --expected-binary-sha256"
            )
        report = validate_interrupt_report(run_interrupt_probe(args.binary))
        result = {
            "emulator": "TilEm",
            "commit": TILEM_COMMIT,
            "git_tree": TILEM_TREE,
            "binary": str(args.binary),
            "binary_sha256": binary_sha256,
            "report": report,
            "launch": "direct initialized-core port, input, timer, link, and reset calls",
            "evidence_scope": (
                "pinned TilEm interrupt-controller behavior; not TI-OS execution, "
                "physical ASIC behavior, electrical signaling, or measured timing"
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
        "reset port03/internal ON/power: "
        f"{native['reset'][0]:02X}/{native['reset'][2]}/{native['reset'][3]}"
    )
    print("ON status: " + ",".join(f"{value:02X}" for value in native["on_status"]))
    print(
        "timer status: " + ",".join(f"{value:02X}" for value in native["timer_status"])
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
