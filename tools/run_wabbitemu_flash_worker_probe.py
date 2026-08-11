#!/usr/bin/env python3
"""Run guarded retail-ROM Flash worker cases under pinned Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_flash_probe import (
    WORKER_PROGRAM_CASES,
    FlashProgramCase,
    parse_flash_program_case,
    validate_worker_report,
)
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_flash_worker_probe,
)


TOOLS = Path(__file__).resolve().parent
DEFAULT_ROM = TOOLS / "rom.bin"


def program_case(value: str) -> FlashProgramCase:
    """Adapt the shared case parser to argparse."""

    try:
        return parse_flash_program_case(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def positive_count(value: str) -> int:
    """Parse a positive instruction bound."""

    count = int(value, 0)
    if count <= 0:
        raise argparse.ArgumentTypeError("count must be positive")
    return count


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
    parser.add_argument("--max-boot-steps", type=positive_count, default=5_000_000)
    parser.add_argument("--max-probe-steps", type=positive_count, default=10_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cases = tuple(args.case) if args.case else WORKER_PROGRAM_CASES
    if len(set(cases)) != len(cases):
        parser.error("each Flash worker case may be specified only once")
    if args.output_dir.exists():
        parser.error(f"refusing to reuse existing output directory {args.output_dir}")
    try:
        source_rom_sha256 = file_sha256(args.rom)
        if source_rom_sha256 != TI84_PLUS_OS_255MP_SHA256:
            raise ValueError("probe requires the exact local OS 2.55MP ROM")
        reports = [
            validate_worker_report(
                case,
                run_flash_worker_probe(
                    args.binary,
                    args.rom,
                    case.initial,
                    case.requested,
                    initial_toggle=case.initial_toggle,
                    max_boot_steps=args.max_boot_steps,
                    max_probe_steps=args.max_probe_steps,
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
                "retail boot establishes protection state; the harness directly "
                "unlocks the emulator gate, injects rst 28h / 8087h into RAM "
                "page 1, and executes the original copied block worker"
            ),
            "evidence_scope": (
                "pinned Wabbitemu plus exact retail-ROM bcall and worker behavior; "
                "not an OS/UI caller, protected unlock sequence, or physical Flash"
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
        print(
            f"old {native['initial']:02X} requested {native['requested']:02X}: "
            f"stored {native['stored']:02X}, reads "
            f"{' '.join(f'{value:02X}' for value in native['poll_reads'])}, "
            f"{native['classification']} AF={native['return_af']:04X}"
        )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
