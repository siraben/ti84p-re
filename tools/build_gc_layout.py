#!/usr/bin/env python3
"""Build a hash-guarded synthetic archive-sector layout."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from gc_layout import GcLayoutError, build_gc_sector_layout
from rom_signatures import TI84_PLUS_OS_255MP_SHA256


TOOLS = Path(__file__).resolve().parent


def parse_header(value: str) -> tuple[int, int]:
    """Parse one ``PAGE=VALUE`` archive-sector header request."""

    try:
        page_text, state_text = value.split("=", 1)
        page = int(page_text, 0)
        state = int(state_text, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected PAGE=VALUE, such as 0x08=0xFE") from error
    return page, state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--sector-header",
        action="append",
        type=parse_header,
        required=True,
        metavar="PAGE=VALUE",
        help="controlled sector-header byte; repeatable",
    )
    parser.add_argument(
        "--expected-rom-sha256",
        default=TI84_PLUS_OS_255MP_SHA256,
        help="required source identity (default: pinned OS 2.55MP image)",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.output.exists() and not args.force:
        parser.error(f"refusing to overwrite existing output {args.output}; use --force")
    try:
        source = args.rom.read_bytes()
        source_digest = sha256(source).hexdigest()
        expected_digest = args.expected_rom_sha256.casefold()
        if source_digest != expected_digest:
            raise GcLayoutError(
                f"source ROM SHA-256 is {source_digest}; expected {expected_digest}"
            )
        result = build_gc_sector_layout(source, args.sector_header)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(result.image)
        report = {
            "evidence_scope": (
                "synthetic input topology; subsequent OS-written transitions require "
                "independent trace evidence"
            ),
            "source_rom": str(args.rom),
            "source_rom_sha256": source_digest,
            "output": str(args.output),
            "output_sha256": sha256(result.image).hexdigest(),
            "mutations": [
                {
                    "page": mutation.page,
                    "address": mutation.address,
                    "previous": mutation.previous,
                    "value": mutation.value,
                }
                for mutation in result.mutations
            ],
        }
    except (GcLayoutError, OSError) as error:
        parser.error(str(error))
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
        return
    print(f"source ROM SHA-256: {report['source_rom_sha256']}")
    for mutation in report["mutations"]:
        print(
            f"synthetic page 0x{mutation['page']:02X} header: "
            f"0x{mutation['previous']:02X} -> 0x{mutation['value']:02X} "
            f"at physical 0x{mutation['address']:05X}"
        )
    print(f"output: {report['output']} sha256={report['output_sha256']}")


if __name__ == "__main__":
    main()
