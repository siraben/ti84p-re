#!/usr/bin/env python3
"""Compare keypad matrix reads and ON-edge policy across emulators."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

from keypad_hardware import (
    KEYPAD_EMULATOR_PROFILES,
    on_transition_requests_interrupt,
    read_keypad_matrix,
)


def integer(value: str) -> int:
    return int(value, 0)


def key_position(value: str) -> tuple[int, int]:
    try:
        group_text, bit_text = value.split(",", 1)
        return integer(group_text), integer(bit_text)
    except (ValueError, TypeError) as error:
        raise argparse.ArgumentTypeError("key must be GROUP,BIT") from error


def _emulators(values: list[str] | None) -> list[str]:
    return values or [profile.name for profile in KEYPAD_EMULATOR_PROFILES]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("profiles", help="compare pinned emulator policies")

    matrix = commands.add_parser("matrix", help="model one port-0x01 read")
    matrix.add_argument("--mask", type=integer, required=True)
    matrix.add_argument("--key", action="append", type=key_position, default=[])
    matrix.add_argument("--emulator", action="append")

    on = commands.add_parser("on", help="compare ON transition latching")
    on.add_argument("transitions", nargs="+", choices=("press", "release"))
    on.add_argument("--emulator", action="append")
    on.add_argument("--disabled", action="store_true")
    return parser


def report(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "profiles":
        return {"profiles": [asdict(profile) for profile in KEYPAD_EMULATOR_PROFILES]}
    if args.command == "matrix":
        return {
            "reads": [
                asdict(read_keypad_matrix(emulator, args.mask, args.key))
                for emulator in _emulators(args.emulator)
            ]
        }
    return {
        "transitions": [
            {
                "emulator": emulator,
                "transition": transition,
                "interrupt_requested": on_transition_requests_interrupt(
                    emulator, transition, enabled=not args.disabled
                ),
            }
            for transition in args.transitions
            for emulator in _emulators(args.emulator)
        ]
    }


def print_text(data: dict[str, object]) -> None:
    if "profiles" in data:
        for profile in data["profiles"]:
            print(f"{profile['name']} ({profile['revision']})")
            print(f"  matrix: {profile['matrix_algorithm']}")
            print(
                f"  ON: {profile['on_interrupt_edge']}; "
                f"{profile['on_detection']}"
            )
        return
    if "reads" in data:
        for row in data["reads"]:
            print(
                f"{row['emulator']}: mask=0x{row['group_mask']:02X} "
                f"read=0x{row['active_low_value']:02X} "
                f"closed=0x{row['apparent_closed_bits']:02X}"
            )
            print(f"  {row['algorithm']}")
        return
    for row in data["transitions"]:
        result = "interrupt" if row["interrupt_requested"] else "no interrupt"
        print(f"{row['emulator']} {row['transition']}: {result}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        data = report(args)
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        json.dump(data, sys.stdout, indent=2)
        print()
    else:
        print_text(data)


if __name__ == "__main__":
    main()
