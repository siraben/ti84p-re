#!/usr/bin/env python3
"""Compare Flash and RAM execution-protection predicates."""

from __future__ import annotations

import argparse
import json
import sys

from execution_protection import (
    CHUNK_SIZE,
    PAGE_SIZE,
    TI84P_BOOT_PROTECTION,
    TI84P_RAM_PAGES,
    tilem_flash_execution_allowed,
    tilem_ram_mask,
    tilem_ram_page_coverage,
    wabbitemu_flash_execution_allowed,
    wabbitemu_ram_page_coverage,
)


def integer(value: str) -> int:
    return int(value, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    commands = parser.add_subparsers(dest="command", required=True)

    flash = commands.add_parser("flash", help="compare Flash-page predicates")
    flash.add_argument("pages", nargs="*", type=integer)
    flash.add_argument(
        "--lower", type=integer, default=TI84P_BOOT_PROTECTION.flash_lower
    )
    flash.add_argument(
        "--upper", type=integer, default=TI84P_BOOT_PROTECTION.flash_upper
    )

    ram = commands.add_parser("ram", help="enumerate RAM execution coverage")
    ram.add_argument("--mode", action="append", type=integer)
    ram.add_argument(
        "--lower", type=integer, default=TI84P_BOOT_PROTECTION.ram_lower_chunk
    )
    ram.add_argument(
        "--upper", type=integer, default=TI84P_BOOT_PROTECTION.ram_upper_chunk
    )
    ram.add_argument("--ram-pages", type=integer, default=TI84P_RAM_PAGES)
    ram.add_argument(
        "--compare-wabbitemu",
        action="store_true",
        help="include Wabbitemu's executable chunks",
    )
    return parser


def flash_report(args: argparse.Namespace) -> dict[str, object]:
    pages = args.pages or sorted(
        {
            max(0, args.lower - 1),
            args.lower,
            min(0xFF, args.lower + 1),
            args.upper,
            min(0xFF, args.upper + 1),
        }
    )
    return {
        "lower": args.lower,
        "upper": args.upper,
        "pages": [
            {
                "page": page,
                "tilem_allowed": tilem_flash_execution_allowed(
                    page, args.lower, args.upper
                ),
                "wabbitemu_allowed": wabbitemu_flash_execution_allowed(
                    page, args.lower, args.upper
                ),
            }
            for page in pages
        ],
    }


def ram_report(args: argparse.Namespace) -> dict[str, object]:
    modes = args.mode if args.mode is not None else list(range(4))
    reports = []
    for mode in modes:
        pages = []
        tilem_coverage = tilem_ram_page_coverage(
            mode, args.lower, args.upper, ram_pages=args.ram_pages
        )
        wabbitemu_coverage = wabbitemu_ram_page_coverage(
            mode, args.lower, args.upper, ram_pages=args.ram_pages
        )
        for coverage, wabbitemu_page in zip(tilem_coverage, wabbitemu_coverage):
            page = {
                "physical_page": coverage.physical_page,
                "selector_page": coverage.selector_page,
                "tilem_chunks": list(coverage.executable_chunks),
            }
            if args.compare_wabbitemu:
                page["wabbitemu_chunks"] = list(wabbitemu_page.executable_chunks)
            pages.append(page)
        reports.append(
            {"mode": mode, "tilem_mask": tilem_ram_mask(mode), "pages": pages}
        )
    return {"lower_chunk": args.lower, "upper_chunk": args.upper, "modes": reports}


def chunks_text(chunks: list[int]) -> str:
    if not chunks:
        return "-"
    if len(chunks) == PAGE_SIZE // CHUNK_SIZE:
        return "all"
    return ",".join(f"{chunk:X}" for chunk in chunks)


def print_text(report: dict[str, object]) -> None:
    if "pages" in report:
        print(f"Flash bounds 0x{report['lower']:02X}-0x{report['upper']:02X}")
        for page in report["pages"]:
            print(
                f"page 0x{page['page']:02X}: "
                f"TilEm={'allow' if page['tilem_allowed'] else 'deny'} "
                f"Wabbitemu={'allow' if page['wabbitemu_allowed'] else 'deny'}"
            )
        return

    print(
        f"RAM chunks 0x{report['lower_chunk']:02X}-0x{report['upper_chunk']:02X}"
    )
    for mode in report["modes"]:
        print(f"mode {mode['mode']} TilEm-mask=0x{mode['tilem_mask']:X}")
        for page in mode["pages"]:
            line = (
                f"  page 0x{page['selector_page']:02X}: "
                f"TilEm={chunks_text(page['tilem_chunks'])}"
            )
            if "wabbitemu_chunks" in page:
                line += f" Wabbitemu={chunks_text(page['wabbitemu_chunks'])}"
            print(line)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        report = flash_report(args) if args.command == "flash" else ram_report(args)
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print_text(report)


if __name__ == "__main__":
    main()
