#!/usr/bin/env python3
"""Run guarded Flash byte-program cases through pinned Wabbitemu."""

from __future__ import annotations

import argparse
from pathlib import Path

from ti84re.emulators.probe_cli import (
    DEFAULT_ROM,
    emit_result,
    require_output_absent,
    wabbitemu_identity,
    write_manifest,
)
from ti84re.emulators.wabbitemu.flash_probe import (
    DIRECT_PROGRAM_CASES,
    FlashProgramCase,
    parse_flash_program_case,
)
from ti84re.emulators.wabbitemu.flash_probe import (
    validate_program_report as validate_report,
)
from ti84re.emulators.wabbitemu.headless import (
    run_flash_program_probe,
)

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
    try:
        require_output_absent(args.output_dir)
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
            **wabbitemu_identity(args.binary, args.rom),
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
        manifest = write_manifest(args.output_dir, result)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))

    summary = []
    for item in reports:
        native = item["native"]
        legality = "illegal 0->1" if item["requested_zero_to_one"] else "legal"
        summary.append(
            f"old {native['initial']:02X} requested {native['requested']:02X}: "
            f"stored {native['stored']:02X}, reads "
            f"{native['first_read']:02X} {native['second_read']:02X} ({legality})"
        )
    emit_result(result, manifest, as_json=args.json, summary=summary)


if __name__ == "__main__":
    main()
