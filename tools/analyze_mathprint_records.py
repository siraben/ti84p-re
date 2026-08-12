#!/usr/bin/env python3
"""Capture live MathPrint render records at the page-34 dispatcher.

The settled renderer selects its handler through the table at 34:6119. TLMT's
initial full-range snapshot and subsequent memory-write records are sufficient
to reconstruct the root/current record pointers and the 20-byte header visible
at each dispatch. This analyzer keeps those bytes aligned with the resolved
instruction stream instead of inferring record fields from final pixels.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Iterator

from hardware_trace import make_banker
from tilem_trace_resolve import (
    IDX_CLOCK,
    IDX_HL,
    IDX_PC,
    iter_records,
    read_header,
    resolve_instruction,
)


RENDER_DISPATCH = ("page_34", 0x6105)
RENDER_TABLE = 0x6119
ROOT_POINTER = 0x8DF2
CURRENT_POINTER = 0x8DF4
RENDER_TYPE = 0x8DE7
HEADER_SIZE = 0x14


@dataclass(frozen=True)
class RecordSnapshot:
    pointer: int
    header: tuple[int, ...]


@dataclass(frozen=True)
class DecodedRecord:
    record_id: int
    render_type: int
    word03: int
    word05: int
    word07: int
    word09: int
    word0B: int
    word0D: int
    word0F: int
    word11: int
    byte13: int


@dataclass(frozen=True)
class DispatchSnapshot:
    instruction_index: int
    clock: int
    render_type: int
    root: RecordSnapshot
    current: RecordSnapshot
    child_ids: tuple[int, ...]


def word(memory: bytearray, address: int) -> int:
    if not 0 <= address < 0xFFFF:
        raise ValueError(f"word address 0x{address:X} is outside logical memory")
    return memory[address] | memory[address + 1] << 8


def record(memory: bytearray, pointer: int) -> RecordSnapshot:
    if not 0 <= pointer <= 0x10000 - HEADER_SIZE:
        raise ValueError(f"record pointer 0x{pointer:X} cannot hold a 20-byte header")
    return RecordSnapshot(pointer, tuple(memory[pointer:pointer + HEADER_SIZE]))


def decode_record_header(header: tuple[int, ...]) -> DecodedRecord:
    """Decode the fixed fields without assigning type-specific semantics."""

    if len(header) != HEADER_SIZE:
        raise ValueError("settled record header must contain 20 bytes")
    if any(not 0 <= value <= 0xFF for value in header):
        raise ValueError("settled record header values must be bytes")
    field = lambda offset: header[offset] | header[offset + 1] << 8
    return DecodedRecord(
        record_id=field(0),
        render_type=header[2],
        word03=field(3),
        word05=field(5),
        word07=field(7),
        word09=field(9),
        word0B=field(0x0B),
        word0D=field(0x0D),
        word0F=field(0x0F),
        word11=field(0x11),
        byte13=header[0x13],
    )


def root_child_ids(memory: bytearray, root: int, count: int) -> tuple[int, ...]:
    if count < 0:
        raise ValueError("child count must be nonnegative")
    table = root + HEADER_SIZE
    if table + 2 * count > 0x10000:
        raise ValueError("root child-ID table extends past logical memory")
    return tuple(word(memory, table + 2 * index) for index in range(count))


def iter_dispatches(
    trace: Path,
    *,
    from_index: int = 0,
    child_count: int = 4,
    initial_mapping: str = "ti84p-reset",
    resync: bool = False,
) -> Iterator[DispatchSnapshot]:
    """Yield live records for render-table dispatches at or after an index."""

    banker = make_banker(initial_mapping)
    instruction_index = 0
    with trace.open("rb") as stream:
        header = read_header(stream)
        if header["range_start"] != 0 or header["range_end"] != 0xFFFF:
            raise ValueError("MathPrint record replay requires a full 0x0000–0xFFFF trace")
        if len(header["init"]) != 0x10000:
            raise ValueError("MathPrint record replay requires a 64 KiB initial snapshot")
        memory = bytearray(header["init"])

        for record_type, payload in iter_records(stream, resync=resync):
            if record_type == 0x02:
                address, value = payload
                if 0 <= address < 0x10000:
                    memory[address] = value
                continue
            if record_type != 0x01:
                continue

            location, _switch = resolve_instruction(banker, payload)
            space, address, _flat, _page = location
            if (
                instruction_index >= from_index
                and (space, address) == RENDER_DISPATCH
                and payload[IDX_HL] == RENDER_TABLE
            ):
                root_pointer = word(memory, ROOT_POINTER)
                current_pointer = word(memory, CURRENT_POINTER)
                yield DispatchSnapshot(
                    instruction_index=instruction_index,
                    clock=payload[IDX_CLOCK],
                    render_type=memory[RENDER_TYPE],
                    root=record(memory, root_pointer),
                    current=record(memory, current_pointer),
                    child_ids=root_child_ids(memory, root_pointer, child_count),
                )
            instruction_index += 1


def snapshot_json(snapshot: DispatchSnapshot) -> dict[str, object]:
    result = asdict(snapshot)
    result["render_type"] = f"0x{snapshot.render_type:02X}"
    for key in ("root", "current"):
        item = result[key]
        assert isinstance(item, dict)
        item["pointer"] = f"0x{item['pointer']:04X}"
        item["header"] = " ".join(f"{value:02X}" for value in item["header"])
        item["decoded"] = asdict(decode_record_header(snapshot.root.header if key == "root" else snapshot.current.header))
    result["child_ids"] = [f"0x{value:04X}" for value in snapshot.child_ids]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--from-index", type=int, default=0)
    parser.add_argument("--children", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resync", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.from_index < 0:
        parser.error("--from-index must be nonnegative")
    if args.children < 0:
        parser.error("--children must be nonnegative")
    if args.limit < 0:
        parser.error("--limit must be nonnegative")

    snapshots = []
    counts: Counter[int] = Counter()
    for snapshot in iter_dispatches(
        args.trace,
        from_index=args.from_index,
        child_count=args.children,
        resync=args.resync,
    ):
        counts[snapshot.render_type] += 1
        if not args.limit or len(snapshots) < args.limit:
            snapshots.append(snapshot)

    if args.json:
        json.dump(
            {
                "trace": str(args.trace),
                "from_instruction": args.from_index,
                "dispatch_counts": {
                    f"0x{render_type:02X}": count
                    for render_type, count in sorted(counts.items())
                },
                "dispatches": [snapshot_json(item) for item in snapshots],
            },
            fp=sys.stdout,
            indent=2,
        )
        print()
        return

    print("render types: " + ", ".join(
        f"0x{render_type:02X}={count}" for render_type, count in sorted(counts.items())
    ))
    for snapshot in snapshots:
        root = " ".join(f"{value:02X}" for value in snapshot.root.header)
        current = " ".join(f"{value:02X}" for value in snapshot.current.header)
        children = " ".join(f"0x{value:04X}" for value in snapshot.child_ids)
        print(
            f"{snapshot.instruction_index:9d} type=0x{snapshot.render_type:02X} "
            f"root=0x{snapshot.root.pointer:04X} current=0x{snapshot.current.pointer:04X}"
        )
        print(f"  root    {root}")
        print(f"  current {current}")
        print(f"  child IDs {children}")


if __name__ == "__main__":
    main()
