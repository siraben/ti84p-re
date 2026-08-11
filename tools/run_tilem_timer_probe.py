#!/usr/bin/env python3
"""Run hash-guarded direct timer and RTC cases through pinned TilEm."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tilem_core import TILEM_COMMIT, TILEM_TREE, TilemCoreError, file_sha256
from tilem_timer import run_timer_probe, validate_timer_report


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
                "timer-probe SHA-256 does not match --expected-binary-sha256"
            )
        report = validate_timer_report(run_timer_probe(args.binary))
        result = {
            "emulator": "TilEm",
            "commit": TILEM_COMMIT,
            "git_tree": TILEM_TREE,
            "binary": str(args.binary),
            "binary_sha256": binary_sha256,
            "report": report,
            "launch": (
                "direct initialized-core timer ports and callbacks with a "
                "probe-controlled time_t source"
            ),
            "evidence_scope": (
                "pinned TilEm timer and RTC behavior; not TI-OS execution, host "
                "wall-clock accuracy, or physical ASIC timing and retention"
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
    print("crystal periods: " + ",".join(map(str, native["crystal_us"])))
    print(
        "expiry statuses: "
        + ",".join(f"{native['expiry'][index]:X}" for index in range(0, 25, 5))
    )
    print(
        "RTC running/frozen/torn: "
        f"{native['rtc'][3]:08X}/{native['rtc'][4]:08X}/{native['rtc'][11]:08X}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
