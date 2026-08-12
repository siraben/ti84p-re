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
    IDX_DE,
    IDX_HL,
    IDX_PC,
    IDX_SP,
    iter_records,
    read_header,
    resolve_instruction,
)


RENDER_DISPATCH = ("page_34", 0x6105)
RENDER_TABLE = 0x6119
SELECT_CHILD = ("page_34", 0x6CCD)
CHILD_SELECTED = ("page_34", 0x6CD8)
ROOT_POINTER = 0x8DF2
CURRENT_POINTER = 0x8DF4
RENDER_TYPE = 0x8DE7
X_ORIGIN = 0x8DFE
Y_ORIGIN = 0x8E00
HEADER_SIZE = 0x14


@dataclass(frozen=True)
class RecordSnapshot:
    pointer: int
    header: tuple[int, ...]
    payload: tuple[int, ...] = ()


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


def graph_node_json(snapshot: DispatchSnapshot) -> dict[str, object]:
    """Return one executable graph node without assigning field semantics."""

    return record_node_json(snapshot.root, snapshot.child_ids)


def record_node_json(
    snapshot: RecordSnapshot, child_ids: tuple[int, ...] = ()
) -> dict[str, object]:
    """Return one record in the JavaScript graph executor's input format."""

    decoded = asdict(decode_record_header(snapshot.header))
    decoded["child_ids"] = list(child_ids)
    decoded["payload"] = list(snapshot.payload)
    return decoded


def word(memory: bytearray, address: int) -> int:
    if not 0 <= address < 0xFFFF:
        raise ValueError(f"word address 0x{address:X} is outside logical memory")
    return memory[address] | memory[address + 1] << 8


def record(memory: bytearray, pointer: int) -> RecordSnapshot:
    if not 0 <= pointer <= 0x10000 - HEADER_SIZE:
        raise ValueError(f"record pointer 0x{pointer:X} cannot hold a 20-byte header")
    header = tuple(memory[pointer:pointer + HEADER_SIZE])
    decoded = decode_record_header(header)
    payload_length = decoded.word11 if decoded.render_type < 0x1F else 0
    payload_start = pointer + 0x13
    payload_end = payload_start + payload_length
    if payload_end > 0x10000:
        raise ValueError(f"record pointer 0x{pointer:X} has a payload past logical memory")
    return RecordSnapshot(
        pointer, header, tuple(memory[payload_start:payload_end])
    )


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


def select_entry_dispatch(
    dispatches: list[tuple[int, int, int, int, int]], last_key_press: int
) -> tuple[int, int, int, int, int]:
    """Select the enclosing record for the final key-triggered redraw."""

    if not dispatches:
        raise ValueError("cannot select an entry from an empty dispatch list")
    candidates = [item for item in dispatches if item[0] >= last_key_press]
    if not candidates:
        candidates = dispatches
    shallowest_stack = max(item[2] for item in candidates)
    return next(item for item in candidates if item[2] == shallowest_stack)


def resolved_record_graph(
    trace: Path,
    *,
    from_index: int = 0,
    initial_mapping: str = "ti84p-reset",
    resync: bool = False,
) -> dict[str, object]:
    """Recover the last dispatched structural graph and its resolved records.

    ``34:6CCD`` receives a one-based child index in ``DE`` and resolves the ID
    stored after the parent's 20-byte header. At ``34:6CD8``, ``DE`` is that ID
    and ``HL`` points at its record. Replaying both sites recovers the leaf
    records that never pass through the structural dispatcher.
    """

    banker = make_banker(initial_mapping)
    instruction_index = 0
    nodes: dict[int, RecordSnapshot] = {}
    edges: dict[int, dict[int, int]] = {}
    dispatches: list[tuple[int, int, int, int, int]] = []
    pending: tuple[int, int, int] | None = None
    last_key_press = 0

    with trace.open("rb") as stream:
        header = read_header(stream)
        if header["range_start"] != 0 or header["range_end"] != 0xFFFF:
            raise ValueError("MathPrint graph replay requires a full 0x0000–0xFFFF trace")
        if len(header["init"]) != 0x10000:
            raise ValueError("MathPrint graph replay requires a 64 KiB initial snapshot")
        memory = bytearray(header["init"])

        for record_type, payload in iter_records(stream, resync=resync):
            if record_type == 0x02:
                address, value = payload
                if 0 <= address < 0x10000:
                    memory[address] = value
                continue
            if record_type == 0x03:
                pressed, _key, _clock, _pc = payload
                if pressed:
                    last_key_press = instruction_index
                continue
            if record_type != 0x01:
                continue

            location, _switch = resolve_instruction(banker, payload)
            site = location[:2]
            if instruction_index >= from_index:
                if site == RENDER_DISPATCH and payload[IDX_HL] == RENDER_TABLE:
                    root = record(memory, word(memory, ROOT_POINTER))
                    root_id = decode_record_header(root.header).record_id
                    nodes[root_id] = root
                    edges[root_id] = {}
                    dispatches.append((
                        instruction_index,
                        root_id,
                        payload[IDX_SP],
                        word(memory, X_ORIGIN),
                        word(memory, Y_ORIGIN),
                    ))
                elif site == SELECT_CHILD:
                    parent = record(memory, word(memory, ROOT_POINTER))
                    parent_id = decode_record_header(parent.header).record_id
                    child_index = payload[IDX_DE]
                    if not 1 <= child_index <= 0xFFFF:
                        raise ValueError(
                            f"instruction {instruction_index}: child index must be one-based"
                        )
                    child_id = root_child_ids(memory, parent.pointer, child_index)[-1]
                    nodes[parent_id] = parent
                    edges.setdefault(parent_id, {})[child_index] = child_id
                    pending = (parent_id, child_index, child_id)
                elif site == CHILD_SELECTED:
                    child_id = payload[IDX_DE]
                    child = record(memory, payload[IDX_HL])
                    decoded_id = decode_record_header(child.header).record_id
                    if decoded_id != child_id:
                        raise ValueError(
                            f"instruction {instruction_index}: resolver returned record "
                            f"0x{decoded_id:04X} for child ID 0x{child_id:04X}"
                        )
                    if pending is not None and pending[2] != child_id:
                        raise ValueError(
                            f"instruction {instruction_index}: child resolution changed "
                            f"ID 0x{pending[2]:04X} to 0x{child_id:04X}"
                        )
                    nodes[child_id] = child
                    pending = None
            instruction_index += 1

    if not dispatches:
        return {"trace": str(trace), "root_id": None, "nodes": []}

    # A final key may trigger several structural dispatches. Summation first
    # dispatches its 0x29 operator record, then reaches a 0x2A exponent wrapper
    # from child 4's object renderer. The entry record is the first dispatch at
    # the shallowest Z80 stack depth after the last injected key press.
    final_dispatches = [item for item in dispatches if item[0] >= last_key_press]
    if not final_dispatches:
        final_dispatches = dispatches
    _root_dispatch, root_id, _stack, _x_origin, _y_origin = select_entry_dispatch(
        dispatches, last_key_press
    )
    reachable: list[int] = []
    active: set[int] = set()

    def visit(record_id: int) -> None:
        if record_id in active:
            raise ValueError(f"resolved record graph contains a cycle at 0x{record_id:04X}")
        if record_id in reachable:
            return
        if record_id not in nodes:
            raise ValueError(f"resolved child ID 0x{record_id:04X} has no captured record")
        active.add(record_id)
        reachable.append(record_id)
        indexed = edges.get(record_id, {})
        if indexed:
            expected = set(range(1, max(indexed) + 1))
            if set(indexed) != expected:
                missing = ", ".join(str(index) for index in sorted(expected - set(indexed)))
                raise ValueError(
                    f"record 0x{record_id:04X} is missing resolved child index {missing}"
                )
            for index in sorted(indexed):
                visit(indexed[index])
        active.remove(record_id)

    visit(root_id)
    for _index, dispatched_id, _stack, _x_origin, _y_origin in final_dispatches:
        visit(dispatched_id)
    graph_nodes = []
    for record_id in reachable:
        indexed = edges.get(record_id, {})
        child_ids = tuple(indexed[index] for index in sorted(indexed))
        graph_nodes.append(record_node_json(nodes[record_id], child_ids))
    return {
        "trace": str(trace),
        "root_id": root_id,
        "dispatches": [
            {
                "instruction_index": index,
                "root_id": dispatched_id,
                "stack_pointer": stack,
                "origin": {"x": x_origin, "y": y_origin},
            }
            for index, dispatched_id, stack, x_origin, y_origin in final_dispatches
        ],
        "nodes": graph_nodes,
    }


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
    parser.add_argument(
        "--graph-json",
        action="store_true",
        help="write de-duplicated root nodes accepted by executeSettledRecordGraph",
    )
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

    if args.graph_json:
        json.dump(resolved_record_graph(
            args.trace,
            from_index=args.from_index,
            resync=args.resync,
        ), fp=sys.stdout, indent=2)
        print()
        return

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
