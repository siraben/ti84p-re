#!/usr/bin/env python3
"""Find structural Flash-command candidates in a paged TI ROM."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any, Iterable

from flash_rom_commands import find_flash_unlock_write_candidates
from rom_image import RomImage
from z80_disassembly import DisassemblyError, disassemble_page


TOOLS = Path(__file__).resolve().parent
LIMITATIONS = (
    "linear disassembly is a candidate generator and can decode data as code",
    "only instruction-aligned LD (nn),A writes to 0x5555 or 0x6AAA are selected",
    "nearby LD A,n values establish proximity, not register data flow or reachability",
    "standalone commands written through registers or to other addresses are outside "
    "this scan",
)


def integer(value: str) -> int:
    return int(value, 0)


def candidate_report(candidate) -> dict[str, Any]:
    """Convert one library candidate to a JSON-safe record."""

    instruction = candidate.instruction
    return {
        "location": str(instruction.location),
        "bytes": instruction.data.hex(),
        "instruction": instruction.text,
        "target_address": candidate.target_address,
        "nearby_command_loads": [
            {
                "location": str(load.instruction.location),
                "bytes": load.instruction.data.hex(),
                "instruction": load.instruction.text,
                "distance_instructions": load.distance,
                "value": load.value,
                "meaning": load.meaning,
            }
            for load in candidate.nearby_command_loads
        ],
    }


def scan_rom(
    rom: RomImage,
    *,
    pages: Iterable[int] | None = None,
    before: int = 8,
    after: int = 3,
    executable: str = "z80dasm",
) -> dict[str, Any]:
    """Return a structured structural-candidate report across selected pages."""

    if before < 0 or after < 0:
        raise ValueError("context distances must be nonnegative")
    selected_pages = tuple(range(rom.page_count) if pages is None else pages)
    if any(not 0 <= page < rom.page_count for page in selected_pages):
        raise ValueError(f"page must be between 0 and {rom.page_count - 1}")

    reports = []
    for page in selected_pages:
        instructions = disassemble_page(rom, page, executable=executable)
        reports.extend(
            candidate_report(candidate)
            for candidate in find_flash_unlock_write_candidates(
                instructions, before=before, after=after
            )
        )
    values = Counter(
        load["value"]
        for report in reports
        for load in report["nearby_command_loads"]
    )
    return {
        "rom_pages": rom.page_count,
        "scanned_pages": list(selected_pages),
        "candidate_count": len(reports),
        "nearby_command_value_counts": {
            f"0x{value:02X}": count for value, count in sorted(values.items())
        },
        "limitations": list(LIMITATIONS),
        "candidates": reports,
    }


def print_text(report: dict[str, Any]) -> None:
    print(
        f"{report['candidate_count']} candidate unlock-address store(s) "
        f"across {len(report['scanned_pages'])} page(s)"
    )
    counts = report["nearby_command_value_counts"]
    count_text = (
        ", ".join(f"{value}={count}" for value, count in counts.items())
        if counts
        else "none"
    )
    print("nearby command-valued LD A,n: " + count_text)
    for candidate in report["candidates"]:
        print(
            f"{candidate['location']} {candidate['instruction']} "
            f"target=0x{candidate['target_address']:04X}"
        )
        for load in candidate["nearby_command_loads"]:
            print(
                f"  {load['location']} distance={load['distance_instructions']:+d} "
                f"value=0x{load['value']:02X} {load['meaning']}"
            )
    print("limitations:")
    for limitation in report["limitations"]:
        print(f"  - {limitation}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    parser.add_argument("--page", action="append", type=integer)
    parser.add_argument("--before", type=int, default=8)
    parser.add_argument("--after", type=int, default=3)
    parser.add_argument("--z80dasm", default="z80dasm")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = scan_rom(
            RomImage.from_path(args.rom),
            pages=args.page,
            before=args.before,
            after=args.after,
            executable=args.z80dasm,
        )
    except (OSError, ValueError, DisassemblyError) as error:
        parser.error(str(error))
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print_text(report)


if __name__ == "__main__":
    main()
