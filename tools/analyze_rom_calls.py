#!/usr/bin/env python3
"""Find direct CALL/JP references across a paged TI ROM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Sequence

from rom_image import RomImage, RomLocation
from z80_disassembly import (
    DisassemblyError,
    direct_target,
    disassemble_page,
    disassemble_rom,
    find_bcall_sites,
    find_bjump_sites,
    Z80Instruction,
)


TOOLS = Path(__file__).resolve().parent


def integer(value: str) -> int:
    return int(value, 0)


def paged_target(value: str) -> RomLocation:
    try:
        page_text, address_text = value.split(":", 1)
        page = int(page_text, 16)
        address = int(address_text, 16)
        if not 0 <= page <= 0x3F or not 0 <= address <= 0x7FFF:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError(
            "bjump target must be PAGE:ADDR in hexadecimal, for example 3D:6098"
        ) from None
    return RomLocation(page, address)


def _instruction_report(
    instruction: Z80Instruction, *, match: bool
) -> dict[str, Any]:
    return {
        "location": str(instruction.location),
        "bytes": instruction.data.hex(),
        "instruction": instruction.text,
        "match": match,
    }


def resolved_direct_target(page: int, target: int) -> str:
    """Render the address space implied by a direct ROM CALL or JP."""

    if target < 0x4000:
        return f"00:{target:04X}"
    if target < 0x8000:
        if page == 0:
            return f"banked:{target:04X}"
        return f"{page:02X}:{target:04X}"
    return f"ram:{target:04X}"


def call_reports_for_page(
    rom: RomImage,
    page: int,
    instructions: Sequence[Z80Instruction],
    targets: frozenset[int],
    *,
    bcall: bool,
    before: int,
    after: int,
) -> list[dict[str, Any]]:
    """Build reusable direct-reference or raw-bcall reports for one ROM page.

    The reports deliberately retain surrounding linear disassembly. They are
    candidate-generation records, not claims that every decoded site is
    reachable code.
    """

    bcall_sites = (
        {site.location.address: site for site in find_bcall_sites(rom, page, targets)}
        if bcall
        else {}
    )
    reports = []
    for index, instruction in enumerate(instructions):
        if bcall:
            site = bcall_sites.get(instruction.location.address)
            if site is None:
                continue
            target = site.id
            sequence_bytes = bytes((0xEF, target & 0xFF, target >> 8))
        else:
            target = direct_target(instruction)
            if target not in targets:
                continue
            sequence_bytes = instruction.data
        start = max(0, index - before)
        stop = min(len(instructions), index + after + 1)
        reports.append(
            {
                "location": str(instruction.location),
                "bytes": sequence_bytes.hex(),
                "instruction": "rst 28h" if bcall else instruction.text,
                "kind": "bcall" if bcall else "direct",
                "target": target,
                "resolved_target": (
                    None if bcall else resolved_direct_target(page, target)
                ),
                "context": [
                    _instruction_report(context, match=context_index == index)
                    for context_index, context in enumerate(
                        instructions[start:stop], start=start
                    )
                ],
            }
        )
    return reports


def bjump_reports_for_page(
    rom: RomImage,
    page: int,
    instructions: Sequence[Z80Instruction],
    targets: frozenset[RomLocation],
    *,
    before: int,
    after: int,
) -> list[dict[str, Any]]:
    """Build reusable cross-page descriptor reports for one ROM page."""

    sites = {
        site.location.address: site for site in find_bjump_sites(rom, page, targets)
    }
    reports = []
    for index, instruction in enumerate(instructions):
        site = sites.get(instruction.location.address)
        if site is None:
            continue
        start = max(0, index - before)
        stop = min(len(instructions), index + after + 1)
        reports.append(
            {
                "location": str(instruction.location),
                "bytes": rom.bytes_at(page, instruction.location.address, 6).hex(),
                "instruction": instruction.text,
                "kind": "bjump",
                "target": str(site.target),
                "target_page": site.target.page,
                "target_address": site.target.address,
                "raw_page": site.raw_page,
                "context": [
                    _instruction_report(context, match=context_index == index)
                    for context_index, context in enumerate(
                        instructions[start:stop], start=start
                    )
                ],
            }
        )
    return reports


def analyze_calls(
    rom: RomImage,
    targets: frozenset[int],
    *,
    bcall: bool = False,
    before: int = 0,
    after: int = 0,
    executable: str = "z80dasm",
    pages: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    """Return machine-readable call-reference candidates across a ROM."""

    reports = []
    disassemblies = (
        disassemble_rom(rom, executable=executable)
        if pages is None
        else (
            (page, disassemble_page(rom, page, executable=executable))
            for page in pages
        )
    )
    for page, instructions in disassemblies:
        reports.extend(
            call_reports_for_page(
                rom,
                page,
                instructions,
                targets,
                bcall=bcall,
                before=before,
                after=after,
            )
        )
    return reports


def analyze_bjumps(
    rom: RomImage,
    targets: frozenset[RomLocation],
    *,
    before: int = 0,
    after: int = 0,
    executable: str = "z80dasm",
    pages: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    """Return machine-readable cross-page jump candidates across a ROM."""

    reports = []
    disassemblies = (
        disassemble_rom(rom, executable=executable)
        if pages is None
        else (
            (page, disassemble_page(rom, page, executable=executable))
            for page in pages
        )
    )
    for page, instructions in disassemblies:
        reports.extend(
            bjump_reports_for_page(
                rom,
                page,
                instructions,
                targets,
                before=before,
                after=after,
            )
        )
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "targets",
        nargs="+",
        help="integer call targets, or PAGE:ADDR targets with --bjump",
    )
    parser.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    parser.add_argument("--before", type=int, default=0, help="preceding context lines")
    parser.add_argument("--after", type=int, default=0, help="following context lines")
    parser.add_argument(
        "--bcall",
        action="store_true",
        help="treat targets as bcall IDs following rst 28h instead of CALL/JP addresses",
    )
    parser.add_argument(
        "--bjump",
        action="store_true",
        help="find CALL 2B09h plus inline PAGE:ADDR descriptors",
    )
    parser.add_argument("--z80dasm", default="z80dasm", help="z80dasm executable")
    parser.add_argument(
        "--page",
        action="append",
        type=integer,
        help="physical source page to scan; repeat as needed (default: every page)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.before < 0 or args.after < 0:
        parser.error("--before and --after must be nonnegative")
    if args.bcall and args.bjump:
        parser.error("--bcall and --bjump are mutually exclusive")
    try:
        wanted = frozenset(
            paged_target(target) if args.bjump else integer(target)
            for target in args.targets
        )
    except ValueError as error:
        parser.error(str(error))
    rom = RomImage.from_path(args.rom)
    if args.page is not None:
        for page in args.page:
            if not 0 <= page < rom.page_count:
                parser.error(f"page 0x{page:X} is outside this ROM")
    try:
        if args.bjump:
            reports = analyze_bjumps(
                rom,
                wanted,
                before=args.before,
                after=args.after,
                executable=args.z80dasm,
                pages=args.page,
            )
        else:
            reports = analyze_calls(
                rom,
                wanted,
                bcall=args.bcall,
                before=args.before,
                after=args.after,
                executable=args.z80dasm,
                pages=args.page,
            )
    except DisassemblyError as error:
        parser.exit(2, f"{parser.prog}: {error}\n")

    if args.json:
        json.dump(reports, sys.stdout, indent=2)
        print()
        return
    for report_index, report in enumerate(reports):
        if args.before or args.after:
            if report_index:
                print()
            if report["kind"] == "direct":
                print(
                    f"# {report['location']} direct target "
                    f"{report['resolved_target']}"
                )
            for context in report["context"]:
                marker = ">" if context["match"] else " "
                print(
                    f"{marker} {context['location']}  "
                    f"{context['bytes'].upper():<12} {context['instruction']}"
                )
        elif args.bjump:
            print(
                f"{report['location']}  {report['bytes'].upper():<14} "
                f"call 2B09h ; bjump {report['target']} "
                f"(raw page 0x{report['raw_page']:02X})"
            )
        elif args.bcall:
            print(
                f"{report['location']}  {report['bytes'].upper():<10} "
                f"rst 28h ; bcall 0x{report['target']:04X}"
            )
        else:
            print(
                f"{report['location']}  {report['bytes'].upper():<12} "
                f"{report['instruction']} ; -> {report['resolved_target']}"
            )
    kind = (
        "bjump descriptor candidate"
        if args.bjump
        else "bcall sequence candidate"
        if args.bcall
        else "direct reference"
    )
    scanned_pages = rom.page_count if args.page is None else len(args.page)
    print(f"# {len(reports)} {kind}(s) across {scanned_pages} physical pages")


if __name__ == "__main__":
    main()
