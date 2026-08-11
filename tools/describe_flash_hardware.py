#!/usr/bin/env python3
"""Inspect TI-84 Plus Flash geometry and pinned emulator behavior."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

from flash_hardware import (
    EMULATOR_PROFILES,
    FLASH_COMMAND_PROFILES,
    FUJITSU_MBM29LV800TA,
    REPORTED_COMPATIBLE_PARTS,
    TOP_BOOT_SECTORS,
    flash_sector,
    mame_erase_busy_read_range,
    mame_erase_duration_ms,
    mame_erase_status_reads,
    program_byte,
    rom_program_poll_decision,
    wabbitemu_program_error_read,
)


def integer(value: str) -> int:
    return int(value, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "parts", help="separate photographed hardware from compatible families"
    )
    commands.add_parser("profiles", help="compare pinned emulator profiles")
    commands.add_parser("commands", help="compare command-set capabilities")

    geometry = commands.add_parser("geometry", help="resolve erase sectors")
    geometry.add_argument("addresses", nargs="*", type=integer)

    program = commands.add_parser("program", help="compare byte programming")
    program.add_argument("--old", type=integer, default=0x00)
    program.add_argument("--data", type=integer, default=0xFF)

    erase = commands.add_parser("mame-erase", help="inspect MAME erase status")
    erase.add_argument("address", type=integer)
    erase.add_argument("--reads", type=integer, default=4)

    poll = commands.add_parser("poll", help="evaluate the ROM DQ poll path")
    poll.add_argument("--data", type=integer, required=True)
    poll.add_argument("--first", type=integer, required=True)
    poll.add_argument("--dq5", type=integer)
    poll.add_argument("--final", type=integer)
    return parser


def report(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "parts":
        return {
            "photographed_part": asdict(FUJITSU_MBM29LV800TA),
            "reported_compatible_parts": [
                asdict(part) for part in REPORTED_COMPATIBLE_PARTS
            ],
        }
    if args.command == "profiles":
        return {"profiles": [asdict(profile) for profile in EMULATOR_PROFILES]}
    if args.command == "commands":
        return {
            "command_profiles": [
                asdict(profile) for profile in FLASH_COMMAND_PROFILES
            ]
        }
    if args.command == "geometry":
        addresses = args.addresses or [sector.start for sector in TOP_BOOT_SECTORS]
        return {
            "addresses": [
                {"address": address, **asdict(flash_sector(address))}
                for address in addresses
            ]
        }
    if args.command == "program":
        results = [program_byte(profile.name, args.old, args.data)
                   for profile in EMULATOR_PROFILES]
        result = {
            "old": args.old,
            "requested": args.data,
            "results": [asdict(item) for item in results],
        }
        if results[1].requested_zero_to_one:
            result["wabbitemu_error_reads"] = [
                wabbitemu_program_error_read(args.data, dq6=False),
                wabbitemu_program_error_read(args.data, dq6=True),
            ]
        return result
    if args.command == "mame-erase":
        sector = flash_sector(args.address)
        busy_start, busy_end = mame_erase_busy_read_range(args.address)
        return {
            "address": args.address,
            "sector": asdict(sector),
            "duration_ms": mame_erase_duration_ms(args.address),
            "busy_read_range": {"start": busy_start, "end": busy_end},
            "status_reads": list(mame_erase_status_reads(args.reads)),
        }
    return {
        "decision": rom_program_poll_decision(
            args.data,
            args.first,
            dq5_read=args.dq5,
            final_read=args.final,
        )
    }


def print_text(data: dict[str, object]) -> None:
    if "photographed_part" in data:
        part = data["photographed_part"]
        print(f"photographed part: {part['manufacturer']} {part['orderable_part']}")
        print(f"  package marking: {part['photographed_marking']}")
        print(f"  board evidence: {part['board_evidence']}")
        print(
            "  data-sheet autoselect: "
            f"manufacturer=0x{part['manufacturer_code']:02X} "
            f"device=0x{part['device_code_byte_mode']:02X}"
        )
        print(
            "  rated byte program: "
            f"{part['byte_program_typ_us']} us typical, "
            f"{part['byte_program_max_us']} us maximum"
        )
        print(
            "  rated sector erase: "
            f"{part['sector_erase_typ_ms'] / 1000:g} s typical, "
            f"{part['sector_erase_max_ms'] / 1000:g} s maximum"
        )
        compatible = ", ".join(
            f"{item['manufacturer']} {item['family']}"
            for item in data["reported_compatible_parts"]
        )
        print(f"reported compatible families: {compatible}")
        return
    if "profiles" in data:
        for profile in data["profiles"]:
            print(f"{profile['name']} ({profile['revision']})")
            print(f"  program: {profile['program_rule']}; {profile['program_completion']}")
            print(f"  erase: {profile['erase_completion']}")
            print(f"  autoselect: {profile['autoselect']}")
            print(f"  ASIC gate: {profile['asic_write_gate']}")
        return
    if "command_profiles" in data:
        fields = (
            "read_reset",
            "autoselect",
            "byte_program",
            "sector_erase",
            "chip_erase",
            "erase_suspend_resume",
            "fast_program",
            "cfi",
            "sector_protection_report",
        )
        for profile in data["command_profiles"]:
            print(
                f"{profile['name']} "
                f"({profile['source_kind']}, {profile['revision']})"
            )
            for field in fields:
                support = profile[field]
                print(
                    f"  {field.replace('_', ' ')}: {support['status']}; "
                    f"{support['behavior']}"
                )
        return
    if "addresses" in data:
        for item in data["addresses"]:
            print(
                f"0x{item['address']:06X}: sector "
                f"0x{item['start']:06X}-0x{item['start'] + item['size'] - 1:06X} "
                f"({item['size'] // 1024} KiB)"
            )
        return
    if "results" in data:
        print(f"program old=0x{data['old']:02X} requested=0x{data['requested']:02X}")
        for item in data["results"]:
            print(
                f"  {item['emulator']}: stored=0x{item['stored']:02X} "
                f"poll={item['poll_behavior']}"
            )
        if "wabbitemu_error_reads" in data:
            values = " ".join(f"0x{value:02X}" for value in data["wabbitemu_error_reads"])
            print(f"  Wabbitemu error-read values (DQ6=0/1): {values}")
        return
    if "status_reads" in data:
        sector = data["sector"]
        busy = data["busy_read_range"]
        statuses = " ".join(f"0x{value:02X}" for value in data["status_reads"])
        print(
            f"sector 0x{sector['start']:06X}-"
            f"0x{sector['start'] + sector['size'] - 1:06X}, "
            f"timer={data['duration_ms']} ms"
        )
        print(f"busy reads 0x{busy['start']:06X}-0x{busy['end'] - 1:06X}")
        print(f"status: {statuses}")
        return
    print(data["decision"])


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
