#!/usr/bin/env python3
"""Run guarded Fake USB handler edges through pinned Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_usb_edge_probe,
)
from wabbitemu_usb_probe import validate_usb_report


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
        report = validate_usb_report(run_usb_edge_probe(args.binary, args.rom))
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": file_sha256(args.binary),
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "report": report,
            "launch": "direct initialized-core Fake USB port calls",
            "evidence_scope": (
                "pinned Wabbitemu port registration, reset reads, mask-independent and "
                "repeatable line events, active-low summary, latches, and directly "
                "seeded handler contracts; not TI-OS execution, connected endpoint "
                "transactions, electrical behavior, or physical-calculator evidence"
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
        f"ports: 0x54 active={int(native['port54_active'])}, "
        f"accepted={int(native['port54_read_accepted'])}, "
        f"fallback={native['port54_read']:02X}"
    )
    print(
        f"event: line={native['event_line_state']:02X}, "
        f"events={native['event_events']:02X}, summary={native['event_port55']:02X}, "
        f"repeat_irq={int(native['repeated_event_interrupt'])}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
