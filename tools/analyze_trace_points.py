#!/usr/bin/env python3
"""Print visits to selected resolved addresses in a TilEm trace."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from hardware_trace import iter_resolved_instructions, trace_header
from tilem_trace_resolve import parse_clock_range


@dataclass(frozen=True)
class TracePoint:
    space: str
    address: int


def parse_point(value: str) -> TracePoint:
    try:
        space, address = value.rsplit(":", 1)
        if not space:
            raise ValueError
        return TracePoint(space, int(address, 16))
    except ValueError:
        raise argparse.ArgumentTypeError(
            "point must be SPACE:HEXADDR, for example page_3C:7733"
        ) from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument(
        "--point",
        action="append",
        type=parse_point,
        required=True,
        help="resolved SPACE:HEXADDR to match; repeatable",
    )
    parser.add_argument(
        "--initial-mapping",
        choices=("unknown", "ti84p-reset"),
        default="ti84p-reset",
        help="mapping at the first record (default: ti84p-reset)",
    )
    parser.add_argument(
        "--clock",
        type=parse_clock_range,
        metavar="START[-END]",
        help="include instructions whose clock is in this inclusive range",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resync", action="store_true")
    args = parser.parse_args()

    selected = {(point.space, point.address) for point in args.point}
    header = trace_header(args.trace)
    print(
        f"trace v{header.version}, range=0x{header.range_start:04X}-"
        f"0x{header.range_end:04X}"
    )

    shown = 0
    for event in iter_resolved_instructions(
        args.trace,
        initial_mapping=args.initial_mapping,
        resync=args.resync,
    ):
        if (event.space, event.address) not in selected:
            continue
        if args.clock is not None and not args.clock[0] <= event.clock <= args.clock[1]:
            continue
        print(
            f"{event.instruction_index:9d} clk={event.clock:<10d} "
            f"{event.space}:{event.address:04X} op=0x{event.opcode:08X} "
            f"AF={event.af:04X} BC={event.bc:04X} DE={event.de:04X} "
            f"HL={event.hl:04X} IX={event.ix:04X} IY={event.iy:04X} "
            f"SP={event.sp:04X}"
        )
        shown += 1
        if args.limit and shown >= args.limit:
            break


if __name__ == "__main__":
    main()
