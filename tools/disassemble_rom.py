#!/usr/bin/env python3
"""Disassemble an address range from one physical TI ROM page."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rom_image import RomImage
from z80_disassembly import DisassemblyError, disassemble_page


TOOLS = Path(__file__).resolve().parent


def integer(value: str) -> int:
    return int(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("page", type=integer, help="physical Flash page")
    parser.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    parser.add_argument("--start", type=integer, help="first logical address")
    parser.add_argument("--end", type=integer, help="last logical address, inclusive")
    parser.add_argument("--z80dasm", default="z80dasm", help="z80dasm executable")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rom = RomImage.from_path(args.rom)
    if not 0 <= args.page < rom.page_count:
        parser.error(f"page 0x{args.page:X} is outside this ROM")
    origin = 0 if args.page == 0 else 0x4000
    start = origin if args.start is None else args.start
    end = origin + 0x3FFF if args.end is None else args.end
    if not origin <= start <= end <= origin + 0x3FFF:
        parser.error(
            f"range must stay within 0x{origin:04X}-0x{origin + 0x3FFF:04X}"
        )

    try:
        instructions = disassemble_page(rom, args.page, executable=args.z80dasm)
    except DisassemblyError as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
    selected = tuple(
        instruction
        for instruction in instructions
        if start <= instruction.location.address <= end
    )

    if args.json:
        json.dump(
            [
                {
                    "location": str(instruction.location),
                    "bytes": instruction.data.hex(),
                    "instruction": instruction.text,
                }
                for instruction in selected
            ],
            sys.stdout,
            indent=2,
        )
        print()
        return

    for instruction in selected:
        print(
            f"{instruction.location}  {instruction.data.hex().upper():<12} "
            f"{instruction.text}"
        )
    print(f"# {len(selected)} instruction(s)")


if __name__ == "__main__":
    main()
