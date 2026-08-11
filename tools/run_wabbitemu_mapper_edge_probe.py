#!/usr/bin/env python3
"""Run guarded memory-mapper edges through pinned Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_mapper_edge_probe,
)
from wabbitemu_mapper_probe import validate_mapper_report


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
        report = validate_mapper_report(run_mapper_edge_probe(args.binary, args.rom))
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": file_sha256(args.binary),
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "report": report,
            "launch": "direct initialized-core mapper port and memory calls",
            "evidence_scope": (
                "pinned Wabbitemu reset mapping, fixed-page opcode handoff, selector "
                "readback, paired-page expression, and independent-versus-paired "
                "overlay routing for reads, low-level writes, and fetched bytes; not "
                "TI-OS execution, physical mapper behavior, or Flash command acceptance"
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
        f"handoff: data={native['fixed_page_after_data_read']:02X}, "
        f"opcode={native['fixed_page_after_opcode']:02X}"
    )
    print(
        f"paired: A/B/C={native['paired_a_page']:02X}/"
        f"{native['paired_b_page']:02X}/{native['paired_c_page']:02X}; "
        f"overlay fetch halt={int(native['independent_fetch_halted'])}→"
        f"{int(native['paired_fetch_halted'])}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
