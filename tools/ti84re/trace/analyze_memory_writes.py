#!/usr/bin/env python3
"""Filter resolved CPU memory-write attempts from a TilEm trace."""

from __future__ import annotations

import argparse
from itertools import islice
import json
from pathlib import Path
import sys
from typing import Iterable, Iterator

from ti84re.trace.analyze_points import parse_point
from ti84re.trace.hardware import (
    ResolvedMemoryWrite,
    iter_resolved_memory_writes,
    trace_header,
)
from ti84re.trace.resolve import parse_clock_range


WRITE_SEMANTICS = (
    "CPU memory-write attempts attributed to the instruction that generated "
    "them; TLMT does not record acceptance by the mapped device"
)


def parse_logical_address(value: str) -> int:
    """Parse one 16-bit logical address accepted by ``--logical``."""

    try:
        address = int(value, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "logical address must be decimal or 0x-prefixed hexadecimal"
        ) from None
    if not 0 <= address <= 0xFFFF:
        raise argparse.ArgumentTypeError("logical address must fit in 16 bits")
    return address


def matching_writes(
    events: Iterable[ResolvedMemoryWrite],
    *,
    logical_addresses: set[int] | None = None,
    pcs: set[tuple[str, int]] | None = None,
    target_kinds: set[str] | None = None,
    clock: tuple[int, int] | None = None,
) -> Iterator[ResolvedMemoryWrite]:
    """Yield resolved writes satisfying every supplied filter."""

    for event in events:
        if (
            logical_addresses is not None
            and event.logical_address not in logical_addresses
        ):
            continue
        if pcs is not None and (event.pc_space, event.pc_address) not in pcs:
            continue
        if target_kinds is not None and event.target_kind not in target_kinds:
            continue
        if clock is not None and not clock[0] <= event.clock <= clock[1]:
            continue
        yield event


def memory_write_report(
    event: ResolvedMemoryWrite,
) -> dict[str, int | str | bool | None]:
    """Return the stable JSON-facing representation of one write attempt."""

    return {
        "instruction_index": event.instruction_index,
        "clock": event.clock,
        "logical_pc": event.logical_pc,
        "pc_space": event.pc_space,
        "pc_address": event.pc_address,
        "logical_address": event.logical_address,
        "value": event.value,
        "target_kind": event.target_kind,
        "target_page": event.target_page,
        "page_offset": event.page_offset,
        "flat_address": event.flat_address,
        "unresolved": event.unresolved,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument(
        "--logical",
        action="append",
        type=parse_logical_address,
        help="restrict writes to a logical address; repeatable",
    )
    parser.add_argument(
        "--pc",
        action="append",
        type=parse_point,
        help="restrict writes to a resolved SPACE:HEXADDR PC; repeatable",
    )
    parser.add_argument(
        "--target-kind",
        action="append",
        choices=("flash", "ram"),
        help="restrict writes to a mapped target kind; repeatable",
    )
    parser.add_argument(
        "--clock",
        type=parse_clock_range,
        metavar="START[-END]",
        help="include writes whose attributed instruction clock is in range",
    )
    parser.add_argument(
        "--initial-mapping",
        choices=("unknown", "ti84p-reset"),
        default="ti84p-reset",
        help="mapping at the first record (default: ti84p-reset)",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resync", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.limit < 0:
        parser.error("--limit must be nonnegative")

    header = trace_header(args.trace)
    writes = matching_writes(
        iter_resolved_memory_writes(
            args.trace,
            initial_mapping=args.initial_mapping,
            resync=args.resync,
        ),
        logical_addresses=set(args.logical) if args.logical else None,
        pcs={(point.space, point.address) for point in args.pc} if args.pc else None,
        target_kinds=set(args.target_kind) if args.target_kind else None,
        clock=args.clock,
    )
    if args.limit:
        writes = islice(writes, args.limit)

    reports = [memory_write_report(event) for event in writes]
    if args.json:
        json.dump(
            {
                "trace": str(args.trace),
                "header": {
                    "version": header.version,
                    "range_start": header.range_start,
                    "range_end": header.range_end,
                },
                "write_semantics": WRITE_SEMANTICS,
                "writes": reports,
            },
            fp=sys.stdout,
            indent=2,
        )
        print()
        return

    print(
        f"trace v{header.version}, range=0x{header.range_start:04X}-"
        f"0x{header.range_end:04X}"
    )
    for event in reports:
        kind = event["target_kind"] or "unresolved"
        page = event["target_page"]
        page_text = "??" if page is None else f"{page:02X}"
        offset = event["page_offset"]
        offset_text = "????" if offset is None else f"{offset:04X}"
        print(
            f"{event['instruction_index']:9d} clock={event['clock']} "
            f"logical={event['logical_address']:04X} value={event['value']:02X} "
            f"target={kind}:{page_text}:{offset_text} "
            f"pc={event['pc_space']}:{event['pc_address']:04X}"
        )
    print(f"# {len(reports)} matching write attempt(s)")


if __name__ == "__main__":
    main()
