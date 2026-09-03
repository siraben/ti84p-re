#!/usr/bin/env python3
"""Find immediate values across every linearly disassembled ROM page."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

from ti84re.rom.image import RomImage
from ti84re.rom.z80_disassembly import (
    DisassemblyError,
    direct_target,
    disassemble_page,
    find_literal_uses,
    nearby_direct_sinks,
)
from ti84re.paths import DEFAULT_ROM


def integer(value: str) -> int:
    return int(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("values", nargs="+", type=integer, help="values such as 0x22")
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument(
        "--sink",
        action="append",
        type=integer,
        default=[],
        help="flag nearby direct CALL/JP targets; repeat as needed",
    )
    parser.add_argument(
        "--distance",
        type=int,
        default=12,
        help="instruction window for --sink proximity (default: 12)",
    )
    parser.add_argument("--z80dasm", default="z80dasm", help="z80dasm executable")
    parser.add_argument(
        "--instruction-regex",
        help="only report rendered instructions matching this regular expression",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.distance < 0:
        parser.error("--distance must be nonnegative")
    try:
        instruction_pattern = (
            re.compile(args.instruction_regex, re.IGNORECASE)
            if args.instruction_regex
            else None
        )
    except re.error as error:
        parser.error(f"invalid --instruction-regex: {error}")
    rom = RomImage.from_path(args.rom)
    reports = []
    try:
        for page in range(rom.page_count):
            instructions = disassemble_page(rom, page, executable=args.z80dasm)
            indices = {id(instruction): index for index, instruction in enumerate(instructions)}
            for use in find_literal_uses(instructions, args.values):
                if instruction_pattern and not instruction_pattern.search(
                    use.instruction.text
                ):
                    continue
                sinks = nearby_direct_sinks(
                    instructions,
                    indices[id(use.instruction)],
                    args.sink,
                    distance=args.distance,
                )
                reports.append(
                    {
                        "location": str(use.instruction.location),
                        "bytes": use.instruction.data.hex(),
                        "instruction": use.instruction.text,
                        "values": list(use.values),
                        "nearby_sinks": [
                            {
                                "location": str(sink.location),
                                "instruction": sink.text,
                                "target": direct_target(sink),
                            }
                            for sink in sinks
                        ],
                    }
                )
    except DisassemblyError as error:
        parser.exit(2, f"{parser.prog}: {error}\n")

    if args.json:
        json.dump(reports, sys.stdout, indent=2)
        print()
        return
    for report in reports:
        values = ",".join(f"0x{value:X}" for value in report["values"])
        sinks = report["nearby_sinks"]
        suffix = ""
        if sinks:
            suffix = " | nearby " + ", ".join(
                f"{sink['location']}->{sink['target']:04X}" for sink in sinks
            )
        print(
            f"{report['location']}  {report['bytes'].upper():<12} "
            f"{report['instruction']:<24} [{values}]{suffix}"
        )
    print(f"# {len(reports)} candidate use(s) across {rom.page_count} physical pages")


if __name__ == "__main__":
    main()
