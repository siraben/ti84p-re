#!/usr/bin/env python3
"""Compare the page-3D and boot Flash program workers."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from flash_workers import compare_workers, extract_length_prefixed_worker
from rom_image import RomImage, RomLocation


TOOLS = Path(__file__).resolve().parent
PAGE3D_PROGRAM_DESCRIPTOR = RomLocation(0x3D, 0x7308)
BOOT_PROGRAM_DESCRIPTOR = RomLocation(0x3F, 0x4CC8)


def location(value: str) -> RomLocation:
    try:
        page_text, address_text = value.split(":", 1)
        page = int(page_text, 16)
        address = int(address_text, 16)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "worker must be PAGE:ADDR in hexadecimal, for example 3D:7308"
        ) from None
    return RomLocation(page, address)


def worker_report(worker) -> dict[str, object]:
    """Return JSON-safe metadata for one extracted worker."""

    return {
        "descriptor": str(worker.descriptor),
        "entry": str(worker.entry),
        "length": worker.length,
        "sha256": worker.sha256,
    }


def report(
    rom: RomImage,
    left_descriptor: RomLocation = PAGE3D_PROGRAM_DESCRIPTOR,
    right_descriptor: RomLocation = BOOT_PROGRAM_DESCRIPTOR,
) -> dict[str, object]:
    """Extract two workers and return a structured byte comparison."""

    left = extract_length_prefixed_worker(rom, left_descriptor)
    right = extract_length_prefixed_worker(rom, right_descriptor)
    comparison = compare_workers(left, right)
    return {
        "left": worker_report(left),
        "right": worker_report(right),
        "matching_bytes": comparison.matching_bytes,
        "differences": [
            {
                **asdict(difference),
                "left_bytes": difference.left_bytes.hex(),
                "right_bytes": difference.right_bytes.hex(),
            }
            for difference in comparison.differences
        ],
    }


def print_text(data: dict[str, object]) -> None:
    for side in ("left", "right"):
        worker = data[side]
        print(
            f"{side}: descriptor={worker['descriptor']} entry={worker['entry']} "
            f"length={worker['length']} sha256={worker['sha256']}"
        )
    print(f"matching bytes: {data['matching_bytes']}")
    for difference in data["differences"]:
        print(
            f"{difference['operation']}: "
            f"left+0x{difference['left_offset']:02X}={difference['left_bytes'] or '-'} "
            f"right+0x{difference['right_offset']:02X}="
            f"{difference['right_bytes'] or '-'}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    parser.add_argument("--left", type=location, default=PAGE3D_PROGRAM_DESCRIPTOR)
    parser.add_argument("--right", type=location, default=BOOT_PROGRAM_DESCRIPTOR)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        data = report(RomImage.from_path(args.rom), args.left, args.right)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.json:
        json.dump(data, sys.stdout, indent=2)
        print()
    else:
        print_text(data)


if __name__ == "__main__":
    main()
