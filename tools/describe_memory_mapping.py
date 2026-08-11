#!/usr/bin/env python3
"""Compare TI-83 Plus-family memory-mapper implementation profiles."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

from memory_mapper import (
    EMULATOR_PROFILE_KEYS,
    MAPPER_PROFILES,
    MAPPING_PORTS,
    Ti83PlusMapper,
    mapper_profile,
)


def integer(value: str) -> int:
    return int(value, 0)


def positive_integer(value: str) -> int:
    parsed = integer(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("page count must be positive")
    return parsed


def port_write(value: str) -> tuple[int, int]:
    try:
        port_text, byte_text = value.split("=", 1)
        port, byte = integer(port_text), integer(byte_text)
    except ValueError:
        raise argparse.ArgumentTypeError("write must have the form PORT=VALUE") from None
    if port not in MAPPING_PORTS:
        raise argparse.ArgumentTypeError(f"0x{port:02X} is not a mapper port")
    if not 0 <= byte <= 0xFF:
        raise argparse.ArgumentTypeError("write value must be a byte")
    return port, byte


def logical_address(value: str) -> int:
    address = integer(value)
    if not 0 <= address <= 0xFFFF:
        raise argparse.ArgumentTypeError("logical address must be 16-bit")
    return address


def add_mapping_arguments(parser: argparse.ArgumentParser, *, compare: bool) -> None:
    if compare:
        parser.add_argument(
            "--profiles",
            nargs="+",
            choices=MAPPER_PROFILES,
            default=list(EMULATOR_PROFILE_KEYS),
            help="profiles to compare (default: the three emulators)",
        )
    else:
        parser.add_argument(
            "--profile",
            choices=MAPPER_PROFILES,
            default="tilem",
            help="implementation profile (default: tilem)",
        )
    parser.add_argument(
        "--preset",
        choices=("unknown", "ti84p-reset"),
        default="ti84p-reset",
        help="initial state (default: ti84p-reset)",
    )
    parser.add_argument("--flash-pages", type=positive_integer, default=64)
    parser.add_argument("--ram-pages", type=positive_integer, default=8)
    parser.add_argument(
        "--ram-alias-from",
        type=integer,
        metavar="PAGE",
        help="map this zero-based RAM page and every higher page to one block",
    )
    parser.add_argument(
        "--write",
        action="append",
        type=port_write,
        default=[],
        metavar="PORT=VALUE",
        help="apply a mapper write in order; repeat as needed",
    )
    parser.add_argument(
        "--read",
        action="append",
        type=logical_address,
        default=[],
        metavar="ADDRESS",
        help="model a data read after all writes; repeat as needed",
    )
    parser.add_argument(
        "--fetch",
        action="append",
        type=logical_address,
        default=[],
        metavar="ADDRESS",
        help="model an opcode fetch after reads; repeat as needed",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("profiles", help="describe mapper profiles and coverage")
    mapping = commands.add_parser("map", help="inspect one implementation profile")
    add_mapping_arguments(mapping, compare=False)
    compare = commands.add_parser("compare", help="apply one sequence to profiles")
    add_mapping_arguments(compare, compare=True)
    return parser


def create_mapper(
    args: argparse.Namespace, profile_key: str
) -> tuple[Ti83PlusMapper, list[dict[str, object]]]:
    if args.preset == "ti84p-reset":
        if args.flash_pages != 64 or args.ram_pages != 8:
            raise ValueError("ti84p-reset requires 64 Flash pages and 8 RAM pages")
        mapper = Ti83PlusMapper.ti84p_reset(
            profile_key, ram_alias_from=args.ram_alias_from
        )
    else:
        mapper = Ti83PlusMapper(
            profile=profile_key,
            flash_pages=args.flash_pages,
            ram_pages=args.ram_pages,
            ram_alias_from=args.ram_alias_from,
        )
    for port, value in args.write:
        mapper.write_port(port, value)
    accesses = []
    for address in args.read:
        accesses.append(
            {
                "kind": "read",
                "address": address,
                "mapping": mapper.read_address(address),
                "fixed_page_after": mapper.fixed_page,
                "boot_latch_after": mapper.boot_latch,
            }
        )
    for address in args.fetch:
        accesses.append(
            {
                "kind": "opcode_fetch",
                "address": address,
                "mapping": mapper.read_address(address, opcode_fetch=True),
                "fixed_page_after": mapper.fixed_page,
                "boot_latch_after": mapper.boot_latch,
            }
        )
    return mapper, accesses


def profile_report(profile_key: str) -> dict[str, object]:
    profile = mapper_profile(profile_key)
    row = asdict(profile)
    row["mapped_ports"] = sorted(profile.mapped_ports)
    row["reset_registers"] = {
        f"0x{port:02X}": value for port, value in profile.reset_registers
    }
    return row


def mapper_report(
    mapper: Ti83PlusMapper, accesses: list[dict[str, object]] | None = None
) -> dict[str, object]:
    mode = (
        "unknown"
        if mapper.port4 is None
        else "paired" if mapper.port4 & 1 else "independent"
    )
    windows = []
    for region in range(4):
        start, end = region * 0x4000, region * 0x4000 + 0x3FFF
        kind, page = mapper.mapped_page(region)
        windows.append(
            {"region": region, "start": start, "end": end, "kind": kind, "page": page}
        )
    forced = mapper.forced_ranges()
    registers = []
    for port, value in mapper.register_values().items():
        mapped = port in mapper.profile.mapped_ports
        registers.append(
            {
                "port": port,
                "mapped": mapped,
                "stored": value if mapped else None,
                "readback": mapper.read_port(port) if mapped else None,
            }
        )
    return {
        "profile": mapper.profile.key,
        "implementation": mapper.profile.name,
        "revision": mapper.profile.revision,
        "mode": mode,
        "flash_pages": mapper.flash_pages,
        "ram_pages": mapper.ram_pages,
        "ram_alias_from": mapper.ram_alias_from,
        "initial_pc": mapper.initial_pc,
        "fixed_page": mapper.fixed_page,
        "boot_latch": mapper.boot_latch,
        "mapping_writes": mapper.switches,
        "ignored_writes": [
            {"port": port, "value": value} for port, value in mapper.ignored_writes
        ],
        "registers": registers,
        "windows": windows,
        "forced_ram_ranges": None
        if forced is None
        else [
            {"start": start, "end": end, "page": page}
            for start, end, page in forced
        ],
        "accesses": accesses or [],
    }


def report(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "profiles":
        return {"profiles": [profile_report(key) for key in MAPPER_PROFILES]}
    if args.command == "map":
        mapper, accesses = create_mapper(args, args.profile)
        return {"mappings": [mapper_report(mapper, accesses)]}
    mappings = []
    for profile_key in args.profiles:
        mapper, accesses = create_mapper(args, profile_key)
        mappings.append(mapper_report(mapper, accesses))
    return {
        "mappings": mappings
    }


def page_description(kind: str | None, page: int | None) -> str:
    if kind is None or page is None:
        return "unknown"
    return f"{kind} 0x{page:02X}"


def shown_byte(value: int | None) -> str:
    return "unknown" if value is None else f"0x{value:02X}"


def print_text(data: dict[str, object]) -> None:
    if "profiles" in data:
        for row in data["profiles"]:
            ports = " ".join(f"0x{port:02X}" for port in row["mapped_ports"])
            print(f"{row['key']}: {row['name']} ({row['revision']})")
            print(f"  ports: {ports}")
            print(f"  reset: {row['reset_entry']}")
            print(f"  status: {row['driver_status']}")
            print(f"  limit: {row['known_limit']}")
        return
    for index, result in enumerate(data["mappings"]):
        if index:
            print()
        print(
            f"{result['profile']} ({result['revision']}): mode={result['mode']} "
            f"fixed=0x{result['fixed_page']:02X} boot_latch={result['boot_latch']} "
            f"mapping_writes={result['mapping_writes']}"
        )
        print("  registers (stored/readback):")
        for register in result["registers"]:
            if not register["mapped"]:
                print(f"    0x{register['port']:02X}: unmapped")
            else:
                print(
                    f"    0x{register['port']:02X}: "
                    f"{shown_byte(register['stored'])}/{shown_byte(register['readback'])}"
                )
        print("  windows:")
        for window in result["windows"]:
            print(
                f"    0x{window['start']:04X}-0x{window['end']:04X}  "
                f"{page_description(window['kind'], window['page'])}"
            )
        print("  forced RAM ranges:")
        forced = result["forced_ram_ranges"]
        if forced is None:
            print("    unknown")
        elif not forced:
            print("    none")
        else:
            for item in forced:
                print(
                    f"    0x{item['start']:04X}-0x{item['end']:04X}  "
                    f"ram 0x{item['page']:02X}"
                )
        for ignored in result["ignored_writes"]:
            print(
                f"  ignored write: 0x{ignored['port']:02X}="
                f"{shown_byte(ignored['value'])}"
            )
        for access in result["accesses"]:
            print(
                f"  {access['kind']} 0x{access['address']:04X}: "
                f"{page_description(*access['mapping'])}; "
                f"fixed-after=0x{access['fixed_page_after']:02X}"
            )


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
