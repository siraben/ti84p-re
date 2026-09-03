#!/usr/bin/env python3
"""Resolve one main or boot bcall directly from a TI ROM table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ti84re.rom.bcall_tables import (
    boot_target,
    classify_boot_page,
    find_main_table_page,
    main_target,
    read_boot_names,
    read_equate_names,
    read_main_names,
    target_is_valid,
)
from ti84re.rom.image import RomImage
from ti84re.paths import SYMBOLS, DEFAULT_ROM


def integer(value: str) -> int:
    return int(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("id", type=integer, help="bcall ID, such as 0x810B")
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument(
        "--bytes", type=integer, default=16, help="target bytes to show (default: 16)"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.bytes < 0:
        parser.error("--bytes must be nonnegative")
    rom = RomImage.from_path(args.rom)
    if 0x4000 <= args.id < 0x8000:
        scoring_names = read_main_names(SYMBOLS / "bcalls.txt")
        names = read_equate_names(SYMBOLS / "ti83plus.inc", 0x4000, 0x7FFF)
        names.update(scoring_names)
        table_page, _score = find_main_table_page(rom, scoring_names)
        target = main_target(rom, table_page, args.id, names.get(args.id))
        table_kind = "main"
    elif 0x8000 <= args.id < 0xC000:
        names = read_boot_names(SYMBOLS / "ti83plus.inc")
        table_page = 0x3F
        target = boot_target(rom, args.id, names.get(args.id))
        table_kind = f"boot/{classify_boot_page(rom)}"
    else:
        parser.error("ID must be in 0x4000–0xBFFF")

    if target is None:
        parser.exit(1, f"{parser.prog}: bcall 0x{args.id:04X} is empty\n")
    valid = target_is_valid(rom, target)
    code = rom.bytes_at(target.page, target.address, args.bytes)
    report = {
        "id": target.id,
        "name": target.name,
        "table_kind": table_kind,
        "table_page": table_page,
        "table_bytes": target.table_bytes.hex(),
        "raw_page": target.raw_page,
        "page": target.page,
        "address": target.address,
        "location": str(target.location),
        "valid": valid,
        "bytes": code.hex(),
    }
    if args.json:
        print(json.dumps(report, indent=2))
        return

    name = f" {target.name}" if target.name else " (unnamed)"
    print(f"0x{target.id:04X}{name}")
    print(
        f"table: {table_kind}, page 0x{table_page:02X}, "
        f"entry {target.table_bytes.hex(' ').upper()}"
    )
    print(
        f"target: {target.location}, raw page 0x{target.raw_page:02X}, "
        f"{'valid' if valid else 'INVALID'}"
    )
    print(f"bytes:  {code.hex(' ').upper()}")


if __name__ == "__main__":
    main()
