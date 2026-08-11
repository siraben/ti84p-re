#!/usr/bin/env python3
"""Inspect TI-83 Plus-family memory mappings after a sequence of port writes."""

from __future__ import annotations

import argparse
import json
import sys

from memory_mapper import MAPPING_PORTS, Ti83PlusMapper


def positive_integer(value: str) -> int:
    parsed = int(value, 0)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("page count must be positive")
    return parsed


def port_write(value: str) -> tuple[int, int]:
    try:
        port_text, byte_text = value.split("=", 1)
        port, byte = int(port_text, 0), int(byte_text, 0)
    except ValueError:
        raise argparse.ArgumentTypeError("write must have the form PORT=VALUE") from None
    if port not in MAPPING_PORTS:
        raise argparse.ArgumentTypeError(f"0x{port:02X} is not a mapper port")
    if not 0 <= byte <= 0xFF:
        raise argparse.ArgumentTypeError("write value must be a byte")
    return port, byte


def page_description(kind: str | None, page: int | None) -> str:
    if kind is None or page is None:
        return "unknown"
    return f"{kind} 0x{page:02X}"


def report(mapper: Ti83PlusMapper) -> dict[str, object]:
    mode = "unknown" if mapper.port4 is None else (
        "paired" if mapper.port4 & 1 else "independent"
    )
    windows = []
    for region in range(4):
        start, end = region * 0x4000, region * 0x4000 + 0x3FFF
        kind, page = mapper.mapped_page(region)
        windows.append(
            {
                "start": start,
                "end": end,
                "kind": kind,
                "page": page,
            }
        )
    forced = mapper.forced_ranges()
    return {
        "mode": mode,
        "flash_pages": mapper.flash_pages,
        "ram_pages": mapper.ram_pages,
        "registers": {
            f"0x{port:02X}": value
            for port, value in mapper.register_values().items()
        },
        "windows": windows,
        "forced_ram_ranges": None if forced is None else [
            {"start": start, "end": end, "page": page}
            for start, end, page in forced
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preset",
        choices=("unknown", "ti84p-reset"),
        default="ti84p-reset",
        help="initial mapper state (default: ti84p-reset)",
    )
    parser.add_argument("--flash-pages", type=positive_integer, default=64)
    parser.add_argument("--ram-pages", type=positive_integer, default=8)
    parser.add_argument(
        "--write",
        action="append",
        type=port_write,
        default=[],
        metavar="PORT=VALUE",
        help="apply a mapper write in order; repeat as needed",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.preset == "ti84p-reset":
        if args.flash_pages != 64 or args.ram_pages != 8:
            parser.error("ti84p-reset requires 64 Flash pages and 8 RAM pages")
        mapper = Ti83PlusMapper.ti84p_reset()
    else:
        mapper = Ti83PlusMapper(
            flash_pages=args.flash_pages,
            ram_pages=args.ram_pages,
        )
    for port, value in args.write:
        mapper.write_port(port, value)

    result = report(mapper)
    if args.json:
        json.dump(result, fp=sys.stdout, indent=2)
        print()
        return

    print(
        f"mode={result['mode']} flash_pages={mapper.flash_pages} "
        f"ram_pages={mapper.ram_pages} mapping_writes={mapper.switches}"
    )
    print("registers:")
    for port, value in mapper.register_values().items():
        shown = "unknown" if value is None else f"0x{value:02X}"
        print(f"  0x{port:02X} = {shown}")
    print("windows:")
    for window in result["windows"]:
        print(
            f"  0x{window['start']:04X}-0x{window['end']:04X}  "
            f"{page_description(window['kind'], window['page'])}"
        )
    print("forced RAM ranges:")
    forced = result["forced_ram_ranges"]
    if forced is None:
        print("  unknown")
    elif not forced:
        print("  none")
    else:
        for item in forced:
            print(
                f"  0x{item['start']:04X}-0x{item['end']:04X}  "
                f"ram 0x{item['page']:02X}"
            )


if __name__ == "__main__":
    main()
