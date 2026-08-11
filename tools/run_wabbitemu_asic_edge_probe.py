#!/usr/bin/env python3
"""Run guarded ASIC status, identity, protection, and GPIO edges."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_asic_probe import validate_asic_report
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_asic_edge_probe,
)


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
        report = validate_asic_report(run_asic_edge_probe(args.binary, args.rom))
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": file_sha256(args.binary),
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "report": report,
            "launch": "direct initialized-core ASIC-control port calls",
            "evidence_scope": (
                "pinned Wabbitemu status, identity, protection, and GPIO behavior "
                "checked against its source model; not retail-ROM execution, "
                "battery voltage, GPIO electrical behavior, or physical ASIC proof"
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
        f"status: locked={native['port02_locked']:02X}, "
        f"unlocked={native['port02_unlocked']:02X}; "
        f"identity={native['port15_ram_v0']:02X}/{native['port15_ram_v2']:02X}"
    )
    print(
        f"port 0x21: locked accepted={int(native['locked_write_accepted'])}, "
        f"mode-3 internal/read={native['mode3_internal_mode']}/"
        f"{native['mode3_read']:02X}; GPIO latch={native['port3a_second_read']:02X}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
