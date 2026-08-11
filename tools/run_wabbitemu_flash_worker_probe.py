#!/usr/bin/env python3
"""Run guarded retail-ROM Flash worker cases under pinned Wabbitemu."""

from __future__ import annotations

import argparse
from pathlib import Path

from probe_cli import (
    DEFAULT_ROM,
    emit_result,
    positive_int,
    require_output_absent,
    wabbitemu_identity,
    write_manifest,
)
from wabbitemu_flash_probe import (
    WORKER_PROGRAM_CASES,
    FlashProgramCase,
    parse_flash_program_case,
    validate_worker_report,
)
from wabbitemu_headless import (
    run_flash_worker_probe,
)


def program_case(value: str) -> FlashProgramCase:
    """Adapt the shared case parser to argparse."""

    try:
        return parse_flash_program_case(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


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
    parser.add_argument("--max-boot-steps", type=positive_int, default=5_000_000)
    parser.add_argument("--max-probe-steps", type=positive_int, default=10_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cases = tuple(args.case) if args.case else WORKER_PROGRAM_CASES
    if len(set(cases)) != len(cases):
        parser.error("each Flash worker case may be specified only once")
    try:
        require_output_absent(args.output_dir)
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
            **wabbitemu_identity(args.binary, args.rom),
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
        manifest = write_manifest(args.output_dir, result)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))

    summary = []
    for item in reports:
        native = item["native"]
        summary.append(
            f"old {native['initial']:02X} requested {native['requested']:02X}: "
            f"stored {native['stored']:02X}, reads "
            f"{' '.join(f'{value:02X}' for value in native['poll_reads'])}, "
            f"{native['classification']} AF={native['return_af']:04X}"
        )
    emit_result(result, manifest, as_json=args.json, summary=summary)


if __name__ == "__main__":
    main()
