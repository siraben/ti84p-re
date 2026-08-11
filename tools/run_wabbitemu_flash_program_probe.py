#!/usr/bin/env python3
"""Run guarded Flash byte-program cases through pinned Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_flash_probe import (
    DIRECT_PROGRAM_CASES,
    FlashProgramCase,
    parse_flash_program_case,
    validate_program_report as validate_report,
)
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_flash_program_probe,
)


TOOLS = Path(__file__).resolve().parent
DEFAULT_ROM = TOOLS / "rom.bin"


DEFAULT_CASES = DIRECT_PROGRAM_CASES


def program_case(value: str) -> FlashProgramCase:
    """Parse ``INITIAL:REQUESTED[:TOGGLE]`` with prefixed integer support."""

    try:
        return parse_flash_program_case(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "case must have INITIAL:REQUESTED[:TOGGLE] form"
        ) from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--case",
        type=program_case,
        action="append",
        help="custom INITIAL:REQUESTED[:TOGGLE] case; repeat as needed",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cases = tuple(args.case) if args.case else DEFAULT_CASES
    if len(set(cases)) != len(cases):
        parser.error("each Flash program case may be specified only once")
    if args.output_dir.exists():
        parser.error(f"refusing to reuse existing output directory {args.output_dir}")
    try:
        source_rom_sha256 = file_sha256(args.rom)
        if source_rom_sha256 != TI84_PLUS_OS_255MP_SHA256:
            raise ValueError("probe requires the exact local OS 2.55MP ROM")
        reports = [
            validate_report(
                case,
                run_flash_program_probe(
                    args.binary,
                    args.rom,
                    case.initial,
                    case.requested,
                    initial_toggle=case.initial_toggle,
                ),
            )
            for case in cases
        ]
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": file_sha256(args.binary),
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "cases": reports,
            "launch": (
                "direct initialized-core setup; four command writes and two "
                "target reads use CPU_mem_write and CPU_mem_read"
            ),
            "evidence_scope": (
                "pinned Wabbitemu core behavior checked against its source model; "
                "not a retail-ROM worker run or physical Flash behavior"
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
    for item in reports:
        native = item["native"]
        legality = "illegal 0->1" if item["requested_zero_to_one"] else "legal"
        print(
            f"old {native['initial']:02X} requested {native['requested']:02X}: "
            f"stored {native['stored']:02X}, reads "
            f"{native['first_read']:02X} {native['second_read']:02X} ({legality})"
        )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
