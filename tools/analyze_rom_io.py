#!/usr/bin/env python3
"""List statically resolved I/O accesses in selected physical ROM pages."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from rom_image import RomImage
from z80_disassembly import DisassemblyError, disassemble_page
from z80_io import iter_resolved_io_accesses, parse_port_specs


TOOLS = Path(__file__).resolve().parent


def integer(value: str) -> int:
    return int(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "ports",
        nargs="*",
        help="optional ports or inclusive ranges, such as 0x4D or 0x80-0xA2",
    )
    parser.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    parser.add_argument(
        "--page",
        action="append",
        type=integer,
        help="physical page to scan; repeat as needed (default: every page)",
    )
    parser.add_argument("--z80dasm", default="z80dasm", help="z80dasm executable")
    parser.add_argument("--summary", action="store_true", help="print per-port counts")
    parser.add_argument("--before", type=int, default=0, help="preceding context lines")
    parser.add_argument("--after", type=int, default=0, help="following context lines")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--direct-only",
        action="store_true",
        help="exclude port accesses resolved from a literal C register",
    )
    args = parser.parse_args()

    if args.before < 0 or args.after < 0:
        parser.error("--before and --after must be nonnegative")
    try:
        selected_ports = parse_port_specs(args.ports) if args.ports else None
    except ValueError as error:
        parser.error(str(error))

    rom = RomImage.from_path(args.rom)
    pages = args.page if args.page is not None else range(rom.page_count)
    for page in pages:
        if not 0 <= page < rom.page_count:
            parser.error(f"page 0x{page:X} is outside this ROM")

    reports = []
    try:
        for page in pages:
            instructions = disassemble_page(rom, page, executable=args.z80dasm)
            indices = {id(instruction): index for index, instruction in enumerate(instructions)}
            for access in iter_resolved_io_accesses(instructions, selected_ports):
                if args.direct_only and access.source != "immediate":
                    continue
                instruction = access.instruction
                index = indices[id(instruction)]
                start = max(0, index - args.before)
                stop = min(len(instructions), index + args.after + 1)
                reports.append(
                    {
                        "location": str(instruction.location),
                        "bytes": instruction.data.hex(),
                        "direction": access.direction,
                        "port": access.port,
                        "source": access.source,
                        "instruction": instruction.text,
                        "context": [
                            {
                                "location": str(context.location),
                                "bytes": context.data.hex(),
                                "instruction": context.text,
                                "match": context_index == index,
                            }
                            for context_index, context in enumerate(
                                instructions[start:stop], start=start
                            )
                        ],
                    }
                )
    except DisassemblyError as error:
        parser.exit(2, f"{parser.prog}: {error}\n")

    if args.json:
        json.dump(reports, sys.stdout, indent=2)
        print()
        return
    if args.summary:
        counts = Counter((report["port"], report["direction"]) for report in reports)
        for (port, direction), count in sorted(counts.items()):
            print(f"0x{port:02X} {direction.upper():3} {count:4d}")
    else:
        for report in reports:
            if args.before or args.after:
                if report is not reports[0]:
                    print()
                for context in report["context"]:
                    marker = ">" if context["match"] else " "
                    print(
                        f"{marker} {context['location']}  "
                        f"{context['bytes'].upper():<12} {context['instruction']}"
                    )
            else:
                print(
                    f"{report['location']}  {report['bytes'].upper():<8} "
                    f"{report['instruction']} [{report['source']}]"
                )
    print(f"# {len(reports)} statically resolved I/O access candidate(s)")


if __name__ == "__main__":
    main()
