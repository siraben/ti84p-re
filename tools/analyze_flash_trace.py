#!/usr/bin/env python3
"""Decode AMD Flash commands from a resolved TilEm instruction trace."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from flash_trace import (
    decode_amd_flash_commands,
    flash_sector,
    group_byte_program_runs,
)
from hardware_trace import iter_resolved_memory_writes, trace_header
from tilem_trace_resolve import parse_clock_range


def format_target(address: int) -> str:
    page, offset = divmod(address, 0x4000)
    logical = offset if page == 0 else 0x4000 + offset
    return f"{page:02X}:{logical:04X} (phys 0x{address:05X})"


def contiguous_ranges(addresses: list[int]) -> list[tuple[int, int]]:
    if not addresses:
        return []
    result: list[tuple[int, int]] = []
    start = previous = addresses[0]
    for address in addresses[1:]:
        if address == previous + 1:
            previous = address
            continue
        result.append((start, previous))
        start = previous = address
    result.append((start, previous))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
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
        help="include writes whose attributed instruction clock is in range",
    )
    parser.add_argument("--events", action="store_true", help="print decoded commands")
    parser.add_argument(
        "--timeline",
        action="store_true",
        help="print erases and compact contiguous byte-program runs",
    )
    parser.add_argument(
        "--run-gap",
        type=int,
        default=100_000,
        metavar="CLOCKS",
        help="maximum clock gap within a --timeline program run",
    )
    parser.add_argument("--limit", type=int, default=0, help="limit --events rows")
    parser.add_argument(
        "--page",
        action="append",
        type=lambda value: int(value, 0),
        help="restrict command rows to a physical 16 KiB page; repeatable",
    )
    parser.add_argument(
        "--kind",
        action="append",
        choices=("byte_program", "sector_erase", "array_reset", "unmatched_write"),
        help="restrict command rows by decoded kind; repeatable",
    )
    parser.add_argument("--resync", action="store_true")
    args = parser.parse_args()

    header = trace_header(args.trace)
    writes = []
    unresolved = 0
    for event in iter_resolved_memory_writes(
        args.trace,
        initial_mapping=args.initial_mapping,
        resync=args.resync,
    ):
        if event.unresolved:
            unresolved += 1
            continue
        if event.target_kind != "flash":
            continue
        if args.clock is not None:
            start, end = args.clock
            if not start <= event.clock <= end:
                continue
        writes.append(event)

    commands = list(decode_amd_flash_commands(writes))
    counts = Counter(command.kind for command in commands)
    programmed = sorted(
        command.target_address
        for command in commands
        if command.kind == "byte_program"
    )
    programmed_by_page: dict[int, list[int]] = defaultdict(list)
    for address in programmed:
        programmed_by_page[address // 0x4000].append(address)

    print(
        f"trace v{header.version}, range=0x{header.range_start:04X}-"
        f"0x{header.range_end:04X}"
    )
    print(f"resolved Flash writes: {len(writes)}")
    if unresolved:
        print(f"unresolved writes skipped: {unresolved}")
    print(
        "commands: "
        f"byte_program={counts['byte_program']} "
        f"sector_erase={counts['sector_erase']} "
        f"array_reset={counts['array_reset']} "
        f"unmatched={counts['unmatched_write']}"
    )

    for page in sorted(programmed_by_page):
        ranges = contiguous_ranges(sorted(set(programmed_by_page[page])))
        rendered = ", ".join(
            format_target(start)
            if start == end
            else f"{format_target(start)}..{format_target(end)}"
            for start, end in ranges
        )
        values = Counter(
            command.value
            for command in commands
            if command.kind == "byte_program"
            and command.target_address // 0x4000 == page
        )
        value_summary = ", ".join(
            f"0x{value:02X}x{count}" for value, count in values.most_common()
        )
        print(
            f"program page {page:02X}: {len(programmed_by_page[page])} commands, "
            f"{len(set(programmed_by_page[page]))} unique address(es): {rendered}"
        )
        print(f"  values: {value_summary}")

    for command in commands:
        if command.kind != "sector_erase":
            continue
        sector = flash_sector(command.target_address)
        print(
            f"erase target {format_target(command.target_address)} -> "
            f"sector 0x{sector.start:05X}-0x{sector.start + sector.size - 1:05X}"
        )

    if args.events:
        shown = 0
        for command in commands:
            if args.page and command.target_address // 0x4000 not in args.page:
                continue
            if args.kind and command.kind not in args.kind:
                continue
            if args.limit and shown >= args.limit:
                break
            print(
                f"{command.instruction_index:9d} clk={command.clock:<10d} "
                f"{command.kind:<15} {format_target(command.target_address)} "
                f"value=0x{command.value:02X} pc="
                f"{command.writes[-1].pc_space}:{command.writes[-1].pc_address:04X}"
            )
            shown += 1

    if args.timeline:
        selected = [
            command
            for command in commands
            if (not args.page or command.target_address // 0x4000 in args.page)
            and (not args.kind or command.kind in args.kind)
        ]
        timeline = [
            (command.clock, "erase", command)
            for command in selected
            if command.kind == "sector_erase"
        ]
        timeline.extend(
            (run.commands[0].clock, "program", run)
            for run in group_byte_program_runs(
                selected, max_clock_gap=args.run_gap
            )
        )
        print("\nTimeline:")
        for _clock, event_kind, event in sorted(timeline, key=lambda item: item[0]):
            if event_kind == "erase":
                print(
                    f"clk={event.clock:<10d} erase {format_target(event.target_address)}"
                )
                continue
            values = Counter(command.value for command in event.commands)
            value_summary = ",".join(
                f"{value:02X}x{count}" for value, count in values.most_common()
            )
            target = (
                format_target(event.start_address)
                if event.start_address == event.end_address
                else f"{format_target(event.start_address)}.."
                f"{format_target(event.end_address)}"
            )
            print(
                f"clk={event.commands[0].clock:<10d} program {target} "
                f"count={len(event.commands)} values={value_summary}"
            )


if __name__ == "__main__":
    main()
