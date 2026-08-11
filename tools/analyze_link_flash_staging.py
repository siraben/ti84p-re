#!/usr/bin/env python3
"""Verify and model the OS 2.55MP link-to-Flash staging path."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from link_flash_staging import (
    LinkFlashStagingSignatureError,
    PAGE_RANGE_PROFILES,
    analyze_link_flash_staging,
    classify_page,
    flush_paged_flash_block,
    receive_data_staging,
)
from rom_image import RomImage


TOOLS = Path(__file__).resolve().parent


def integer(value: str) -> int:
    return int(value, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    commands = parser.add_subparsers(dest="command", required=True)

    rom = commands.add_parser("rom", help="verify ROM signatures and callers")
    rom.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")

    page = commands.add_parser("page", help="classify one raw Flash page")
    page.add_argument("page", type=integer)
    page.add_argument("--profile", choices=PAGE_RANGE_PROFILES, default="ti84-plus")

    flush = commands.add_parser("flush", help="model one 3C:6AB1 invocation")
    flush.add_argument("--page", type=integer, required=True)
    flush.add_argument("--destination", type=integer, required=True)
    flush.add_argument("--count", type=integer, required=True)
    flush.add_argument("--profile", choices=PAGE_RANGE_PROFILES, default="ti84-plus")

    receive = commands.add_parser("receive", help="model one received DATA payload")
    receive.add_argument("--destination", type=integer, required=True)
    receive.add_argument("--length", type=integer, required=True)
    receive.add_argument("--page", type=integer, default=0x08)
    receive.add_argument(
        "--profile", choices=PAGE_RANGE_PROFILES, default="ti84-plus"
    )
    return parser


def result(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "rom":
        return analyze_link_flash_staging(RomImage.from_path(args.rom)).as_dict()
    if args.command == "page":
        return asdict(classify_page(args.page, args.profile))
    if args.command == "flush":
        return asdict(
            flush_paged_flash_block(
                args.page,
                args.destination,
                args.count,
                args.profile,
            )
        )
    if args.command == "receive":
        return asdict(
            receive_data_staging(
                args.destination,
                args.length,
                page=args.page,
                profile=args.profile,
            )
        )
    raise AssertionError(f"unhandled command {args.command!r}")


def print_text(command: str, report: dict[str, object]) -> None:
    if command == "rom":
        print(f"ROM SHA-256: {report['rom_sha256']}")
        print(f"verified signatures: {len(report['signatures'])}")
        abi = report["abi"]
        print(
            f"flush: {abi['entry']} -> {abi['bcall_name']} "
            f"(0x{abi['bcall_id']:04X})"
        )
        for reference in report["direct_references"]:
            print(
                f"direct {reference['kind']}: {reference['location']} "
                f"{reference['condition']} -> {reference['target']}"
            )
        for caller in report["dispatcher_callers"]:
            print(
                f"dispatcher caller: {caller['location']} mode=0x{caller['mode']:02X} "
                f"-> {caller['target']}"
            )
        owner = report["usb_receive_owner"]
        print(
            f"mode-3 owner: {owner['entry']} -> {owner['endpoint_stub']} -> "
            f"{owner['endpoint_helper']} reads port 0x{owner['endpoint_data_port']:02X}"
        )
        return
    if command == "page":
        print(
            f"{report['profile']}: input=0x{report['input_page']:02X} "
            f"normalized=0x{report['normalized_page']:02X} "
            f"eligible={str(report['eligible']).lower()}"
        )
        return
    if command == "flush":
        print(
            f"page 0x{report['input_page']:02X}->0x{report['output_page']:02X}; "
            f"destination 0x{report['input_destination']:04X}->"
            f"0x{report['output_destination']:04X}; "
            f"count={report['count']}; {report['reason']}"
        )
        return
    counts = [flush["count"] for flush in report["flushes"]]
    print(
        f"{report['storage']}: length={report['length']} "
        f"direct_ram_bytes={report['direct_ram_bytes']} flush_counts={counts}; "
        f"destination=0x{report['output_destination']:04X} "
        f"page=0x{report['output_page']:02X}"
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        report = result(args)
    except (OSError, ValueError, LinkFlashStagingSignatureError) as error:
        parser.error(str(error))
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print_text(args.command, report)


if __name__ == "__main__":
    main()
