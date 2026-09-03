#!/usr/bin/env python3
"""Resolve TI-84 Plus OS error codes to the ROM's displayed messages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ti84re.rom.error_table import ERROR_MESSAGE_PAGE, error_message
from ti84re.rom.image import RomImage
from ti84re.paths import DEFAULT_ROM


def error_code(value: str) -> int:
    parsed = int(value, 0)
    if not 0 <= parsed <= 0xFF:
        raise argparse.ArgumentTypeError("error code must be between 0 and 255")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("codes", nargs="+", type=error_code)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rom = RomImage.from_path(args.rom)
    reports = [error_message(rom, code).as_dict() for code in args.codes]
    if args.json:
        print(json.dumps(reports, indent=2))
        return

    for report in reports:
        entry = report["pointer_entry"]
        provenance = (
            "fallback"
            if entry is None
            else f"pointer {ERROR_MESSAGE_PAGE:02X}:{entry:04X}"
        )
        editable = " editable" if report["editable"] else ""
        print(
            f"0x{report['raw_code']:02X} -> code 0x{report['code']:02X}"
            f"{editable} -> {report['message_location']} "
            f"{report['message']!r} ({provenance})"
        )


if __name__ == "__main__":
    main()
