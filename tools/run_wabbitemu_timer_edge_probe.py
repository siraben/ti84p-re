#!/usr/bin/env python3
"""Run guarded programmable-timer and RTC edges through pinned Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_timer_edge_probe,
)
from wabbitemu_timer_probe import validate_timer_report


TOOLS = Path(__file__).resolve().parent
DEFAULT_ROM = TOOLS / "rom.bin"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.output_dir.exists():
        parser.error(f"refusing to reuse existing output directory {args.output_dir}")
    try:
        source_rom_sha256 = file_sha256(args.rom)
        if source_rom_sha256 != TI84_PLUS_OS_255MP_SHA256:
            raise ValueError("probe requires the exact local OS 2.55MP ROM")
        report = validate_timer_report(run_timer_edge_probe(args.binary, args.rom))
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": file_sha256(args.binary),
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "report": report,
            "launch": (
                "direct initialized-core timer/RTC ports with explicit emulated "
                "clock advancement"
            ),
            "evidence_scope": (
                "pinned Wabbitemu programmable-timer and RTC behavior checked "
                "against its source model; not retail-ROM execution, wall-clock "
                "timing, low-power electrical behavior, or physical ASIC behavior"
            ),
        }
        args.output_dir.mkdir(parents=True)
        manifest = args.output_dir / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError, WabbitemuHeadlessError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2))
        return
    native = report["native"]
    reads = ",".join(f"{value:02X}" for value in native["crystal_reads"])
    print(
        f"crystal reads: {reads}; CPU catch-up: {native['cpu_count_read']:02X}; "
        f"zero status: {native['zero_status']:02X}"
    )
    print(
        "HALT interrupt: "
        f"{int(native['interrupt_while_halted'])}→"
        f"{int(native['interrupt_after_resume'])}; "
        f"frozen RTC: {native['rtc_frozen']:08X}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
