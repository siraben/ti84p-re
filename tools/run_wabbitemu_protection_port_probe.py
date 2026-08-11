#!/usr/bin/env python3
"""Run guarded protected-boundary port edges through pinned Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_protection_port_probe,
)
from wabbitemu_protection_port_probe import validate_protection_port_report


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
        report = validate_protection_port_report(
            run_protection_port_probe(args.binary, args.rom)
        )
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": file_sha256(args.binary),
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "report": report,
            "launch": "direct initialized-core protected-boundary port calls",
            "evidence_scope": (
                "pinned Wabbitemu port registration, shared protected-write gate, "
                "Flash-bound low-byte and port-0x24 behavior, and 16-bit RAM-bound "
                "storage; not the retail protected-byte sequence, opcode-fetch "
                "outcomes, or physical ASIC behavior"
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
        "locked writes: "
        + "/".join(str(int(value)) for value in native["locked_write_accepted"])
        + f"; port 24 bound fields={native['port24_flash_lower']:04X}/"
        + f"{native['port24_flash_upper']:04X}"
    )
    print(
        "RAM lower: "
        + "/".join(f"{value:04X}" for value in native["ram_lower_internal"])
        + "; upper: "
        + "/".join(f"{value:04X}" for value in native["ram_upper_internal"])
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
