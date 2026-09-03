#!/usr/bin/env python3
"""Inspect LCD commands and pinned emulator pointer behavior."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

from ti84re.hardware.lcd_controller import (
    LCD_EMULATOR_PROFILES,
    TOSHIBA_T6K04,
    decode_lcd_command,
    lcd_status,
    read_latch_sequence,
    t6k04_busy_interval_us,
    walk_lcd_transfers,
)


def integer(value: str) -> int:
    return int(value, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "hardware", help="show the source-attributed Toshiba T6K04 specification"
    )
    commands.add_parser("profiles", help="compare pinned emulator profiles")

    busy = commands.add_parser("busy", help="compute T6K04 busy-time bounds")
    busy.add_argument("--oscillator-khz", type=float)

    decode = commands.add_parser("decode", help="decode controller commands")
    decode.add_argument("values", nargs="+", type=integer)

    walk = commands.add_parser("walk", help="walk data-transfer pointers")
    walk.add_argument("--emulator", action="append")
    walk.add_argument("--row", type=integer, default=0)
    walk.add_argument("--column", type=integer, default=14)
    walk.add_argument("--movement", type=integer, default=7)
    walk.add_argument("--count", type=integer, default=4)
    walk.add_argument("--word-length", type=integer, default=8)

    status = commands.add_parser("status", help="compose a status byte")
    status.add_argument("--word-length", type=integer, default=8)
    status.add_argument("--display-on", action="store_true")
    status.add_argument("--movement", type=integer, default=7)
    status.add_argument("--busy", action="store_true")

    latch = commands.add_parser("latch", help="show dummy-read latch values")
    latch.add_argument("values", nargs="+", type=integer)
    latch.add_argument("--initial", type=integer, default=0)
    return parser


def report(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "hardware":
        return {"controller": asdict(TOSHIBA_T6K04)}
    if args.command == "profiles":
        return {"profiles": [asdict(profile) for profile in LCD_EMULATOR_PROFILES]}
    if args.command == "busy":
        frequencies = (
            [args.oscillator_khz]
            if args.oscillator_khz is not None
            else list(TOSHIBA_T6K04.oscillator_choices_khz)
        )
        return {
            "intervals": [
                {
                    "oscillator_khz": frequency,
                    "minimum_us": t6k04_busy_interval_us(frequency)[0],
                    "maximum_us": t6k04_busy_interval_us(frequency)[1],
                }
                for frequency in frequencies
            ]
        }
    if args.command == "decode":
        return {"commands": [asdict(decode_lcd_command(value)) for value in args.values]}
    if args.command == "walk":
        emulators = args.emulator or [profile.name for profile in LCD_EMULATOR_PROFILES]
        return {
            "walks": [
                {
                    "emulator": emulator,
                    "accesses": [
                        asdict(access)
                        for access in walk_lcd_transfers(
                            emulator,
                            row=args.row,
                            column=args.column,
                            movement=args.movement,
                            count=args.count,
                            word_length=args.word_length,
                        )
                    ],
                }
                for emulator in emulators
            ]
        }
    if args.command == "status":
        return {
            "status": lcd_status(
                word_length=args.word_length,
                display_on=args.display_on,
                movement=args.movement,
                busy=args.busy,
            )
        }
    return {
        "observed": list(
            read_latch_sequence(tuple(args.values), initial_latch=args.initial)
        )
    }


def print_text(data: dict[str, object]) -> None:
    if "controller" in data:
        controller = data["controller"]
        print(f"reported controller: {controller['manufacturer']} {controller['part']}")
        print(f"  calculator evidence: {controller['calculator_evidence']}")
        print(f"  limit: {controller['identification_limit']}")
        print(
            f"  data sheet: {controller['columns']}x{controller['rows']} pixels, "
            f"{controller['ram_bits']} bits, "
            f"{controller['eight_bit_pages']} 8-bit pages"
        )
        print(
            f"  interface: {controller['interface']}; "
            f"logic supply={controller['logic_supply_volts'][0]:g}-"
            f"{controller['logic_supply_volts'][1]:g} V; "
            f"package={controller['package']}"
        )
        for timing in controller["bus_timings"]:
            print(
                f"  {timing['supply_volts']:g} V bus: "
                f"cycle>={timing['enable_cycle_min_ns']} ns "
                f"pulse>={timing['enable_pulse_min_ns']} ns "
                f"read-delay<={timing['read_data_delay_max_ns']} ns"
            )
        return
    if "intervals" in data:
        for interval in data["intervals"]:
            print(
                f"fOSC={interval['oscillator_khz']:g} kHz: "
                f"{interval['minimum_us']:.3f}-"
                f"{interval['maximum_us']:.3f} us"
            )
        return
    if "profiles" in data:
        for profile in data["profiles"]:
            print(
                f"{profile['name']} ({profile['revision']}): "
                f"stride={profile['row_stride']} RAM={profile['ram_size']}"
            )
            print(f"  busy: {profile['busy_model']}")
            print(f"  ASIC ready: {profile['asic_ready_model']}")
            print(f"  columns: {profile['out_of_range_columns']}")
        return
    if "commands" in data:
        for command in data["commands"]:
            print(
                f"0x{command['value']:02X}: {command['kind']} "
                f"argument={command['argument']}"
            )
        return
    if "walks" in data:
        for walk in data["walks"]:
            print(walk["emulator"])
            for access in walk["accesses"]:
                flags = []
                if not access["logical_column_in_range"]:
                    flags.append("column-out-of-range")
                if not access["array_index_in_range"]:
                    flags.append("array-out-of-range")
                suffix = f" [{' '.join(flags)}]" if flags else ""
                print(
                    f"  {access['transfer_index']}: "
                    f"requested=({access['requested_row']},{access['requested_column']}) "
                    f"access=({access['accessed_row']},{access['accessed_column']}) "
                    f"index={access['array_index']} "
                    f"next=({access['next_row']},{access['next_column']}){suffix}"
                )
        return
    if "status" in data:
        print(f"0x{data['status']:02X}")
        return
    print(" ".join(f"0x{value:02X}" for value in data["observed"]))


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
