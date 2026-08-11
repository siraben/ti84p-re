#!/usr/bin/env python3
"""Find direct CALL/JP references across a paged TI ROM."""

from __future__ import annotations

import argparse
from pathlib import Path

from rom_image import RomImage
from z80_disassembly import (
    DisassemblyError,
    direct_target,
    disassemble_rom,
    find_bcall_sites,
)


TOOLS = Path(__file__).resolve().parent


def integer(value: str) -> int:
    return int(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="+", type=integer, help="targets such as 0x2793")
    parser.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    parser.add_argument("--before", type=int, default=0, help="preceding context lines")
    parser.add_argument("--after", type=int, default=0, help="following context lines")
    parser.add_argument(
        "--bcall",
        action="store_true",
        help="treat targets as bcall IDs following rst 28h instead of CALL/JP addresses",
    )
    parser.add_argument("--z80dasm", default="z80dasm", help="z80dasm executable")
    args = parser.parse_args()

    if args.before < 0 or args.after < 0:
        parser.error("--before and --after must be nonnegative")
    wanted = frozenset(args.targets)
    rom = RomImage.from_path(args.rom)
    match_count = 0
    try:
        for page, instructions in disassemble_rom(rom, executable=args.z80dasm):
            sites = (
                {
                    site.location.address: site
                    for site in find_bcall_sites(rom, page, wanted)
                }
                if args.bcall
                else {}
            )
            for index, instruction in enumerate(instructions):
                if args.bcall:
                    if instruction.location.address not in sites:
                        continue
                elif direct_target(instruction) not in wanted:
                    continue
                match_count += 1
                start = max(0, index - args.before)
                stop = min(len(instructions), index + args.after + 1)
                if args.before or args.after:
                    if match_count > 1:
                        print()
                    for context_index in range(start, stop):
                        context = instructions[context_index]
                        marker = ">" if context_index == index else " "
                        print(
                            f"{marker} {context.location}  "
                            f"{context.data.hex().upper():<12} {context.text}"
                        )
                else:
                    if args.bcall:
                        id_value = sites[instruction.location.address].id
                        print(
                            f"{instruction.location}  EF{id_value & 0xFF:02X}"
                            f"{id_value >> 8:02X}     rst 28h ; bcall 0x{id_value:04X}"
                        )
                    else:
                        print(
                            f"{instruction.location}  "
                            f"{instruction.data.hex().upper():<12} {instruction.text}"
                        )
    except DisassemblyError as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
    kind = "bcall sequence candidate" if args.bcall else "direct reference"
    print(f"# {match_count} {kind}(s) across {rom.page_count} physical pages")


if __name__ == "__main__":
    main()
