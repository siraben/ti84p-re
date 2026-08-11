#!/usr/bin/env python3
"""Report visits to selected resolved addresses in a TilEm trace."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from itertools import islice
import json
from pathlib import Path
import re
import sys
from typing import Iterable, Iterator

from hardware_trace import (
    ResolvedInstruction,
    iter_resolved_instructions,
    trace_header,
)
from tilem_trace_resolve import parse_clock_range


@dataclass(frozen=True)
class TracePoint:
    space: str
    address: int


@dataclass(frozen=True)
class RegisterPredicate:
    register: str
    operator: str
    value: int


REGISTER_ATTRIBUTES = {
    "AF": "af",
    "BC": "bc",
    "DE": "de",
    "HL": "hl",
    "IX": "ix",
    "IY": "iy",
    "SP": "sp",
    "WZ": "wz",
}
PREDICATE_RE = re.compile(
    rf"^({'|'.join(REGISTER_ATTRIBUTES)})(==|!=|<=|>=|<|>)(0[xX][0-9a-fA-F]+|[0-9]+)$",
    re.IGNORECASE,
)


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


def parse_integer(value: str) -> int:
    try:
        parsed = int(value, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "value must be decimal or 0x-prefixed hexadecimal"
        ) from None
    if not 0 <= parsed <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("value must fit in 32 bits")
    return parsed


def parse_predicate(value: str) -> RegisterPredicate:
    """Parse a register comparison such as ``HL>=0x8000``."""

    match = PREDICATE_RE.fullmatch(value.replace(" ", ""))
    if match is None:
        raise argparse.ArgumentTypeError(
            "predicate must be REGISTER OP VALUE, for example HL>=0x8000"
        )
    register, operator, number = match.groups()
    parsed = int(number, 0)
    if parsed > 0xFFFF:
        raise argparse.ArgumentTypeError("register comparison value must fit in 16 bits")
    return RegisterPredicate(register.upper(), operator, parsed)


def predicate_matches(
    event: ResolvedInstruction, predicate: RegisterPredicate
) -> bool:
    actual = getattr(event, REGISTER_ATTRIBUTES[predicate.register])
    return {
        "==": actual == predicate.value,
        "!=": actual != predicate.value,
        "<": actual < predicate.value,
        "<=": actual <= predicate.value,
        ">": actual > predicate.value,
        ">=": actual >= predicate.value,
    }[predicate.operator]


def matching_visits(
    events: Iterable[ResolvedInstruction],
    points: set[tuple[str, int]],
    *,
    opcodes: set[int] | None = None,
    predicates: tuple[RegisterPredicate, ...] = (),
    clock: tuple[int, int] | None = None,
) -> Iterator[ResolvedInstruction]:
    """Yield visits satisfying resolved-address, opcode, and register filters."""

    for event in events:
        if (event.space, event.address) not in points:
            continue
        if opcodes is not None and event.opcode not in opcodes:
            continue
        if clock is not None and not clock[0] <= event.clock <= clock[1]:
            continue
        if not all(predicate_matches(event, item) for item in predicates):
            continue
        yield event


def register_summary(
    events: Iterable[ResolvedInstruction], register: str
) -> list[dict[str, int]]:
    """Count one 16-bit register value across a stream of trace visits."""

    attribute = REGISTER_ATTRIBUTES[register]
    counts = Counter(getattr(event, attribute) for event in events)
    return [
        {"value": value, "count": count}
        for value, count in sorted(counts.items())
    ]


def instruction_report(event: ResolvedInstruction) -> dict[str, int | str | None]:
    return {
        "instruction_index": event.instruction_index,
        "clock": event.clock,
        "space": event.space,
        "address": event.address,
        "flat_address": event.flat_address,
        "opcode": event.opcode,
        "af": event.af,
        "bc": event.bc,
        "de": event.de,
        "hl": event.hl,
        "ix": event.ix,
        "iy": event.iy,
        "sp": event.sp,
        "wz": event.wz,
    }


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
    parser.add_argument(
        "--opcode",
        action="append",
        type=parse_integer,
        help="opcode value to include; repeatable",
    )
    parser.add_argument(
        "--where",
        action="append",
        type=parse_predicate,
        default=[],
        help="register predicate such as DE<0x8000; repeatable",
    )
    parser.add_argument(
        "--summary-register",
        choices=tuple(REGISTER_ATTRIBUTES),
        help="count matching values of one 16-bit register",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resync", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.limit < 0:
        parser.error("--limit must be nonnegative")

    selected = {(point.space, point.address) for point in args.point}
    header = trace_header(args.trace)
    visits = matching_visits(
        iter_resolved_instructions(
            args.trace,
            initial_mapping=args.initial_mapping,
            resync=args.resync,
        ),
        selected,
        opcodes=set(args.opcode) if args.opcode else None,
        predicates=tuple(args.where),
        clock=args.clock,
    )

    if args.limit:
        visits = islice(visits, args.limit)

    if args.summary_register:
        summary = register_summary(visits, args.summary_register)
        if args.json:
            json.dump(
                {
                    "trace": str(args.trace),
                    "register": args.summary_register,
                    "visits": sum(item["count"] for item in summary),
                    "values": summary,
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
        for item in summary:
            print(
                f"{item['count']:9d} {args.summary_register}="
                f"0x{item['value']:04X}"
            )
        print(f"# {sum(item['count'] for item in summary)} matching visit(s)")
        return

    if args.json:
        reports = [instruction_report(event) for event in visits]
        json.dump(reports, fp=sys.stdout, indent=2)
        print()
        return

    print(
        f"trace v{header.version}, range=0x{header.range_start:04X}-"
        f"0x{header.range_end:04X}"
    )
    for visit in visits:
        event = instruction_report(visit)
        print(
            f"{event['instruction_index']:9d} clk={event['clock']:<10d} "
            f"{event['space']}:{event['address']:04X} "
            f"op=0x{event['opcode']:08X} AF={event['af']:04X} "
            f"BC={event['bc']:04X} DE={event['de']:04X} "
            f"HL={event['hl']:04X} IX={event['ix']:04X} "
            f"IY={event['iy']:04X} SP={event['sp']:04X}"
        )


if __name__ == "__main__":
    main()
