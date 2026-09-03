#!/usr/bin/env python3
"""Scan raw TI ROM bytes for privileged port-0x14 gate sequences."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sys

from ti84re.flash.gate import scan_flash_gate
from ti84re.rom.image import RomImage
from ti84re.paths import DEFAULT_ROM


def integer(value: str) -> int:
    return int(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument(
        "--page",
        action="append",
        type=integer,
        help="physical page to scan; repeat as needed (default: every page)",
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rom = RomImage.from_path(args.rom)
    try:
        result = scan_flash_gate(rom, args.page)
    except ValueError as error:
        parser.error(str(error))

    report = {
        "sequences": [
            {
                **asdict(sequence),
                "start": str(sequence.start),
                "output": str(sequence.output),
                "bytes": sequence.data.hex(),
            }
            for sequence in result.sequences
        ],
        "unclassified_candidates": [
            str(location) for location in result.unclassified_candidates
        ],
    }
    for sequence in report["sequences"]:
        sequence.pop("data")

    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
        return
    if args.summary:
        counts = Counter(sequence["kind"] for sequence in report["sequences"])
        for kind in ("unlock", "lock"):
            print(f"{kind}: {counts[kind]}")
        print(f"unclassified: {len(report['unclassified_candidates'])}")
        return
    for sequence in report["sequences"]:
        print(
            f"{sequence['output']}  {sequence['kind']:<6} "
            f"A=0x{sequence['requested_value']:02X} "
            f"start={sequence['start']} bytes={sequence['bytes'].upper()}"
        )
    for location in report["unclassified_candidates"]:
        print(f"{location}  unclassified raw D3 14 candidate")
    print(
        f"# {len(report['sequences'])} recognized sequence(s), "
        f"{len(report['unclassified_candidates'])} unclassified candidate(s)"
    )


if __name__ == "__main__":
    main()
