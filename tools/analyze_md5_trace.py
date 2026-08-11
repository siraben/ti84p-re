#!/usr/bin/env python3
"""Decode and verify MD5-assist port transactions in a TilEm trace."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from hardware_trace import iter_resolved_io_events, trace_header
from md5_hardware import MODE_NAMES, decode_md5_steps
from tilem_trace_resolve import parse_byte


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument(
        "--initial-mapping",
        choices=("unknown", "ti84p-reset"),
        default="unknown",
    )
    for port in (4, 5, 6, 7, 27, 28):
        parser.add_argument(f"--initial-port{port}", type=parse_byte)
    parser.add_argument(
        "--expect-steps",
        type=int,
        default=0,
        help="fail unless this many complete operations were decoded",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=8,
        help="maximum detail rows (default: 8; 0 prints none)",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--resync", action="store_true")
    args = parser.parse_args()

    initial_ports = {
        f"initial_port{port}": getattr(args, f"initial_port{port}")
        for port in (4, 5, 6, 7, 27, 28)
    }
    events = iter_resolved_io_events(
        args.trace,
        ports=set(range(0x18, 0x20)),
        initial_mapping=args.initial_mapping,
        resync=args.resync,
        **initial_ports,
    )
    steps = list(decode_md5_steps(events))
    mismatches = [step for step in steps if not step.verified]
    if args.expect_steps and len(steps) != args.expect_steps:
        raise SystemExit(
            f"decoded {len(steps)} step(s), expected {args.expect_steps}"
        )
    if mismatches:
        first = mismatches[0]
        raise SystemExit(
            f"step {first.index} returned 0x{first.result:08X}, "
            f"independent calculation gives 0x{first.expected_result:08X}"
        )

    header = trace_header(args.trace)
    modes = Counter(step.mode for step in steps)
    detail = steps[: args.limit]
    if args.json:
        print(
            json.dumps(
                {
                    "trace": str(args.trace),
                    "header": {
                        "version": header.version,
                        "flags": header.flags,
                        "range_start": header.range_start,
                        "range_end": header.range_end,
                    },
                    "steps": len(steps),
                    "verified": len(steps),
                    "modes": {
                        MODE_NAMES.get(mode, str(mode)): count
                        for mode, count in sorted(modes.items())
                    },
                    "detail": [
                        {
                            "index": step.index,
                            "location": f"{step.space}:{step.address:04X}",
                            "clock": step.clock,
                            "mode": step.mode_name,
                            "a": step.a,
                            "b": step.b,
                            "c": step.c,
                            "d": step.d,
                            "x": step.x,
                            "t": step.t,
                            "shift": step.shift,
                            "result": step.result,
                        }
                        for step in detail
                    ],
                },
                indent=2,
            )
        )
        return

    print(f"trace: {args.trace}")
    print(
        f"format: TLMT v{header.version}, range "
        f"0x{header.range_start:04X}–0x{header.range_end:04X}, "
        f"flags 0x{header.flags:04X}"
    )
    print(f"steps: {len(steps)} decoded, {len(steps)} independently verified")
    print(
        "modes: "
        + ", ".join(
            f"{MODE_NAMES.get(mode, mode)}={count}"
            for mode, count in sorted(modes.items())
        )
    )
    if detail:
        print("\n idx  location       mode  X         T         s   result")
        for step in detail:
            print(
                f"{step.index:4d}  {step.space}:{step.address:04X}  "
                f"{step.mode_name:>4}  {step.x:08X}  {step.t:08X}  "
                f"{step.shift:2d}  {step.result:08X}"
            )


if __name__ == "__main__":
    main()
