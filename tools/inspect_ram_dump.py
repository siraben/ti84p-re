#!/usr/bin/env python3
"""Inspect or assert one region in a binary RAM dump."""

from __future__ import annotations

import argparse
from pathlib import Path

from hardware_debug import (
    MemoryExpectation,
    MemoryMismatch,
    check_memory_expectation,
    read_memory_region,
)


def integer(value: str) -> int:
    return int(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--offset", type=integer)
    location.add_argument("--address", type=integer)
    parser.add_argument(
        "--base",
        type=integer,
        default=0x8000,
        help="logical address represented by dump offset zero (default: 0x8000)",
    )
    parser.add_argument(
        "--length",
        type=integer,
        help="bytes to read (default: expected byte count, or 16)",
    )
    parser.add_argument("--expect", help="expected bytes as hexadecimal")
    parser.add_argument("--name", default="memory region")
    args = parser.parse_args()

    offset = args.offset if args.offset is not None else args.address - args.base
    if offset < 0:
        parser.error("address is below the dump base")
    if args.expect is not None:
        try:
            expected = bytes.fromhex(args.expect)
        except ValueError as error:
            parser.error(f"invalid --expect hexadecimal: {error}")
        if args.length is not None and args.length != len(expected):
            parser.error("--length and --expect byte count disagree")
        try:
            actual = check_memory_expectation(
                MemoryExpectation(args.name, args.dump, offset, expected)
            )
        except MemoryMismatch as error:
            parser.exit(1, f"{parser.prog}: error: {error}\n")
    else:
        length = 16 if args.length is None else args.length
        try:
            actual = read_memory_region(args.dump, offset, length)
        except MemoryMismatch as error:
            parser.exit(1, f"{parser.prog}: error: {error}\n")
    print(f"{args.dump}: offset 0x{offset:X}: {actual.hex()}")


if __name__ == "__main__":
    main()
