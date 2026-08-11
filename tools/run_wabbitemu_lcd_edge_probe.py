#!/usr/bin/env python3
"""Run guarded LCD-controller and bus-timing edges through Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_lcd_edge_probe,
)
from wabbitemu_lcd_probe import validate_lcd_report


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
        report = validate_lcd_report(run_lcd_edge_probe(args.binary, args.rom))
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": file_sha256(args.binary),
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "report": report,
            "launch": "direct initialized-core LCD and bus-timing port calls",
            "evidence_scope": (
                "pinned Wabbitemu transfer guard, pointer, latch, mapped-port, "
                "ready-interval, delay, memory-wait, and speed-clamp behavior; "
                "not retail-ROM execution, host timing, electrical bus timing, "
                "or physical LCD/ASIC behavior"
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
    print(
        f"LCD guard: early={native['early_status']:02X}, "
        f"boundary={native['boundary_status']:02X}; "
        f"latch={','.join(f'{value:02X}' for value in native['latch_reads'])}"
    )
    print(
        f"columns: 14={native['wrap_column14']:02X}, "
        f"15={native['wrap_column15']:02X}, 0={native['wrap_column0']:02X}; "
        f"ready={native['ready_hold']}T, delay={native['delay_after'] - native['delay_before']}T"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
