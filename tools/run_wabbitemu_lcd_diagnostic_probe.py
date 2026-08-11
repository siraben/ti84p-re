#!/usr/bin/env python3
"""Directly execute dormant retail-ROM LCD helpers through Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_lcd_diagnostic_probe,
)
from wabbitemu_lcd_diagnostic_probe import validate_lcd_diagnostic_report

TOOLS = Path(__file__).resolve().parent
DEFAULT_ROM = TOOLS / "rom.bin"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-boot-steps", type=int, default=5_000_000)
    parser.add_argument("--max-probe-steps", type=int, default=250_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.output_dir.exists():
        parser.error(f"refusing to reuse existing output directory {args.output_dir}")
    try:
        source_rom_sha256 = file_sha256(args.rom)
        if source_rom_sha256 != TI84_PLUS_OS_255MP_SHA256:
            raise ValueError("probe requires the exact local OS 2.55MP ROM")
        report = validate_lcd_diagnostic_report(
            run_lcd_diagnostic_probe(
                args.binary,
                args.rom,
                max_boot_steps=args.max_boot_steps,
                max_probe_steps=args.max_probe_steps,
            )
        )
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": file_sha256(args.binary),
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "report": report,
            "launch": (
                "direct entry from an injected RAM harness after retail boot "
                "establishes the protection baseline"
            ),
            "evidence_scope": (
                "actual OS 2.55MP routines at 3F:74C6, 3F:46EF, 3F:472E, "
                "and 3F:74F8 executing in pinned Wabbitemu; not a reachable "
                "retail boot path or physical LCD/ASIC behavior"
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
        f"fill={native['fill_hash']:016x} line={native['line_hash']:016x}; "
        f"writes={native['command_writes']} command/"
        f"{native['data_writes']} data"
    )
    print(
        f"contrast command=0x{native['contrast_out']:02X}, "
        f"Wabbitemu level={native['contrast_level']}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
