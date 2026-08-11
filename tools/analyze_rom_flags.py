#!/usr/bin/env python3
"""Find exact indexed bit operations and immediate writes across a TI ROM."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

from indexed_flags import (
    scan_indexed_bit_references,
    scan_indexed_immediate_writes,
)
from rom_image import RomImage


TOOLS = Path(__file__).resolve().parent


def integer(value: str) -> int:
    return int(value, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    parser.add_argument("--offset", type=integer, help="IX/IY displacement")
    parser.add_argument("--bit", type=integer, help="bit number 0 through 7")
    parser.add_argument("--index", choices=("ix", "iy"))
    parser.add_argument("--page", action="append", type=integer)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--expect-sha256",
        help="reject a ROM whose lowercase SHA-256 does not match",
    )
    return parser


def report(args: argparse.Namespace) -> dict[str, object]:
    rom = RomImage.from_path(args.rom)
    sha256 = hashlib.sha256(rom.data).hexdigest()
    if args.expect_sha256 is not None and sha256 != args.expect_sha256.casefold():
        raise ValueError(
            f"ROM SHA-256 mismatch: expected {args.expect_sha256}, got {sha256}"
        )
    bit_references = scan_indexed_bit_references(
        rom,
        displacement=args.offset,
        bit=args.bit,
        index_register=args.index,
        pages=args.page,
    )
    immediate_writes = scan_indexed_immediate_writes(
        rom,
        displacement=args.offset,
        index_register=args.index,
        pages=args.page,
    )
    references = [
        {
            **asdict(reference),
            "location": str(reference.location),
            "data": reference.data.hex(),
            "value": None,
            "selected_bit_value": None,
        }
        for reference in bit_references
    ]
    references.extend(
        {
            **asdict(write),
            "location": str(write.location),
            "data": write.data.hex(),
            "operation": "ld",
            "bit": None,
            "selected_bit_value": (
                None if args.bit is None else (write.value >> args.bit) & 1
            ),
        }
        for write in immediate_writes
    )
    references.sort(
        key=lambda reference: (
            int(reference["location"][:2], 16),
            int(reference["location"][3:], 16),
        )
    )
    return {
        "rom_sha256": sha256,
        "references": references,
    }


def _operand(reference: dict[str, object]) -> str:
    displacement = reference["displacement"]
    sign = "+" if displacement >= 0 else "-"
    indexed = f"({reference['index_register'].upper()}{sign}0x{abs(displacement):02X})"
    if reference["operation"] == "ld":
        return f"LD {indexed},0x{reference['value']:02X}"
    return f"{reference['operation'].upper()} {reference['bit']},{indexed}"


def print_text(data: dict[str, object], *, summary: bool) -> None:
    references = data["references"]
    if summary:
        counts = Counter(
            (reference["index_register"], reference["operation"], reference["bit"])
            for reference in references
        )
        for (register, operation, bit), count in sorted(counts.items()):
            operand = "byte" if bit is None else f"bit {bit}"
            print(f"{register.upper()} {operation.upper()} {operand}: {count}")
    else:
        for reference in references:
            print(
                f"{reference['location']}  {reference['data'].upper():<8} "
                f"{_operand(reference)}"
            )
    print(f"# {len(references)} raw indexed-flag candidate(s)")
    print(f"# ROM SHA-256 {data['rom_sha256']}")


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
        print_text(data, summary=args.summary)


if __name__ == "__main__":
    main()
