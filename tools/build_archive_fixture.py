#!/usr/bin/env python3
"""Build a hash-guarded fresh-sector archive image from generated programs."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from archive_fixture import ArchiveFixtureError, build_fresh_archive_fixture
from hardware_probe import TiVariable
from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from ti_program import PROGRAM_TYPE, filled_program_body


TOOLS = Path(__file__).resolve().parent


def parse_program(value: str) -> tuple[str, int]:
    """Parse ``NAME=BODY_SIZE`` while preserving caller order."""

    try:
        name, raw_size = value.rsplit("=", 1)
        size = int(raw_size, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "program must be NAME=BODY_SIZE, for example ZBIGDATA=17000"
        ) from None
    normalized = name.upper()
    if (
        not 1 <= len(normalized) <= 8
        or not normalized.isascii()
        or not normalized.isalnum()
        or not normalized[0].isalpha()
    ):
        raise argparse.ArgumentTypeError(
            "program name must start with a letter and contain up to eight "
            "alphanumeric characters"
        )
    if not 0 <= size <= 0xFFFD:
        raise argparse.ArgumentTypeError("program body size must be 0–65533")
    return normalized, size


def parse_sector(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "sector base must be decimal or 0x-prefixed hexadecimal"
        ) from None


def byte_value(value: str) -> int:
    try:
        parsed = int(value, 0)
    except ValueError:
        raise argparse.ArgumentTypeError("byte must be an integer") from None
    if not 0 <= parsed <= 0xFF:
        raise argparse.ArgumentTypeError("byte must be between 0 and 255")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--program",
        action="append",
        type=parse_program,
        required=True,
        help="generated NAME=BODY_SIZE in archive order; repeatable",
    )
    parser.add_argument(
        "--sector",
        action="append",
        type=parse_sector,
        required=True,
        help="erased physical 64 KiB sector base; repeatable",
    )
    parser.add_argument("--fill-byte", type=byte_value, default=0x31)
    parser.add_argument("--last-byte", type=byte_value, default=0x3F)
    parser.add_argument(
        "--expected-rom-sha256",
        default=TI84_PLUS_OS_255MP_SHA256,
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.output.exists() and not args.force:
        parser.error(f"refusing to overwrite existing output {args.output}; use --force")
    try:
        source = args.rom.read_bytes()
        source_hash = sha256(source).hexdigest()
        expected_hash = args.expected_rom_sha256.casefold()
        if source_hash != expected_hash:
            raise ArchiveFixtureError(
                f"source ROM SHA-256 is {source_hash}; expected {expected_hash}"
            )
        variables = []
        for name, body_size in args.program:
            body = filled_program_body(
                body_size,
                fill_byte=args.fill_byte,
                last_byte=args.last_byte,
            )
            variables.append(
                TiVariable(
                    variable_type=PROGRAM_TYPE,
                    name=name,
                    version=0,
                    archived=False,
                    data=len(body).to_bytes(2, "little") + body,
                    comment="generated archive fixture",
                )
            )
        fixture = build_fresh_archive_fixture(source, variables, args.sector)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(fixture.image)
    except (OSError, ArchiveFixtureError, ValueError) as error:
        parser.error(str(error))

    output_hash = sha256(fixture.image).hexdigest()
    report = {
        "source_rom": str(args.rom),
        "source_rom_sha256": source_hash,
        "output": str(args.output),
        "output_sha256": output_hash,
        "sector_bases": list(fixture.sector_bases),
        "fill_byte": args.fill_byte,
        "last_byte": args.last_byte,
        "records": [asdict(record) for record in fixture.records],
        "scope": (
            "fresh erased-sector first-fit placement only; existing records, "
            "deleted slots, allocation bounds, and garbage collection are rejected "
            "or outside this constructor"
        ),
    }
    if args.json:
        print(json.dumps(report, indent=2))
        return
    print(f"output SHA-256: {output_hash}")
    for record in fixture.records:
        print(
            f"{record.name}: 0x{record.physical_start:05X}–"
            f"0x{record.physical_end - 1:05X} "
            f"({record.page:02X}:{record.logical_address:04X})"
        )


if __name__ == "__main__":
    main()
