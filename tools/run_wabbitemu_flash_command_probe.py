#!/usr/bin/env python3
"""Run a guarded Flash command-family matrix through pinned Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_flash_probe import validate_command_report
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_flash_command_probe,
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
        report = validate_command_report(
            run_flash_command_probe(args.binary, args.rom)
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
                "direct initialized-core setup; command writes and reads use "
                "CPU_mem_write and CPU_mem_read; erase mutations remain in memory"
            ),
            "evidence_scope": (
                "pinned Wabbitemu core command-state behavior checked against "
                "its source model; not retail-ROM or physical Flash behavior"
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
        "autoselect: "
        f"{native['autoselect_maker']:02X}/{native['autoselect_device']:02X}, "
        f"protection {native['autoselect_protection']:02X}"
    )
    print(
        "fast program: "
        f"{native['fast_first_stored']:02X}, {native['fast_second_stored']:02X}; "
        f"exit state {native['fast_exit_step']}"
    )
    print(
        f"sector erase: {native['sector_erased_bytes']} bytes; "
        f"outside changes {native['sector_outside_changed_bytes']}"
    )
    print(
        f"chip erase: {native['chip_non_ff_before']} non-FF bytes to "
        f"{native['chip_non_ff_after']}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
