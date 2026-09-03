#!/usr/bin/env python3
"""Find direct CALL/JP references across a paged TI ROM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from ti84re.rom.image import RomImage, RomLocation
from ti84re.rom.calls import (
    analyze_bjump_calls,
    analyze_bjumps,
    analyze_calls,
)
from ti84re.rom.z80_disassembly import DisassemblyError
from ti84re.paths import DEFAULT_ROM


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "targets",
        nargs="*",
        help="integer call targets, or PAGE:ADDR targets with a bjump mode",
    )
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
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
    parser.add_argument(
        "--bjump-call",
        action="store_true",
        help="find direct callers of page-0 stubs for PAGE:ADDR targets",
    )
    parser.add_argument("--z80dasm", default="z80dasm", help="z80dasm executable")
    parser.add_argument(
        "--page",
        action="append",
        type=integer,
        help="physical source page to scan; repeat as needed (default: every page)",
    )
    parser.add_argument(
        "--target-page",
        action="append",
        type=integer,
        help="with --bjump-call, restrict resolved destinations by physical page",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.before < 0 or args.after < 0:
        parser.error("--before and --after must be nonnegative")
    if sum((args.bcall, args.bjump, args.bjump_call)) > 1:
        parser.error("--bcall, --bjump, and --bjump-call are mutually exclusive")
    if not args.targets and not args.bjump_call:
        parser.error("at least one target is required")
    if args.target_page is not None and not args.bjump_call:
        parser.error("--target-page requires --bjump-call")
    try:
        wanted = (
            None
            if args.bjump_call and not args.targets
            else frozenset(
                paged_target(target)
                if args.bjump or args.bjump_call
                else integer(target)
                for target in args.targets
            )
        )
    except ValueError as error:
        parser.error(str(error))
    rom = RomImage.from_path(args.rom)
    if args.page is not None:
        for page in args.page:
            if not 0 <= page < rom.page_count:
                parser.error(f"page 0x{page:X} is outside this ROM")
    try:
        if args.bjump_call:
            if args.target_page is not None:
                for page in args.target_page:
                    if not 0 <= page < rom.page_count:
                        parser.error(
                            f"target page 0x{page:X} is outside this ROM"
                        )
            reports = analyze_bjump_calls(
                rom,
                wanted,
                before=args.before,
                after=args.after,
                executable=args.z80dasm,
                pages=args.page,
                target_pages=(
                    None
                    if args.target_page is None
                    else frozenset(args.target_page)
                ),
            )
        elif args.bjump:
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
            elif report["kind"] == "bjump-call":
                print(
                    f"# {report['location']} bjump call "
                    f"{report['stub']} -> {report['target']}"
                )
            for context in report["context"]:
                marker = ">" if context["match"] else " "
                print(
                    f"{marker} {context['location']}  "
                    f"{context['bytes'].upper():<12} {context['instruction']}"
                )
        elif args.bjump_call:
            print(
                f"{report['location']}  {report['bytes'].upper():<12} "
                f"{report['instruction']} ; {report['stub']} -> {report['target']}"
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
        "bjump caller candidate"
        if args.bjump_call
        else "bjump descriptor candidate"
        if args.bjump
        else "bcall sequence candidate"
        if args.bcall
        else "direct reference"
    )
    scanned_pages = rom.page_count if args.page is None else len(args.page)
    print(f"# {len(reports)} {kind}(s) across {scanned_pages} physical pages")


if __name__ == "__main__":
    main()
