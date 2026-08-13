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
RENDER_ENTRY = ("page_34", 0x660A)
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


@dataclass(frozen=True)
class RecordLocation:
    record_id: int
    pointer: int
    size: int


@dataclass(frozen=True)
class RecordFieldWrite:
    instruction_index: int
    clock: int
    pc_space: str
    pc_address: int
    final_record_id: int
    pointer: int
    offset: int
    field: str
    value: int


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


def record_storage_size(
    snapshot: RecordSnapshot, child_ids: tuple[int, ...] = ()
) -> int:
    """Return the occupied arena bytes for one settled record.

    Leaf payload begins at +13h. Structural records retain the 20-byte header
    and append two-byte child IDs at +14h, as read by 34:4B05.
    """

    decoded = decode_record_header(snapshot.header)
    if decoded.render_type < 0x1F:
        return 0x13 + len(snapshot.payload)
    return HEADER_SIZE + 2 * len(child_ids)


def record_field_name(
    render_type: int, offset: int, payload_length: int = 0
) -> str:
    """Name an address-based settled-record byte without guessing semantics."""

    if not 0 <= render_type <= 0xFF:
        raise ValueError("render type must be a byte")
    if offset < 0:
        raise ValueError("record offset must be nonnegative")
    fixed = {
        0x00: "id.lo", 0x01: "id.hi", 0x02: "type",
        0x03: "word03.lo", 0x04: "word03.hi",
        0x05: "word05.lo", 0x06: "word05.hi",
        0x07: "word07.lo", 0x08: "word07.hi",
        0x09: "word09.lo", 0x0A: "word09.hi",
        0x0B: "word0B.lo", 0x0C: "word0B.hi",
        0x0D: "word0D.lo", 0x0E: "word0D.hi",
        0x0F: "word0F.lo", 0x10: "word0F.hi",
        0x11: "word11.lo", 0x12: "word11.hi",
        0x13: "byte13",
    }
    if offset in fixed:
        if render_type < 0x1F and offset == 0x13 and payload_length:
            return "payload[0]/byte13"
        return fixed[offset]
    if render_type < 0x1F and 0x13 <= offset < 0x13 + payload_length:
        return f"payload[{offset - 0x13}]"
    if render_type >= 0x1F and offset >= HEADER_SIZE:
        index, part = divmod(offset - HEADER_SIZE, 2)
        return f"child[{index + 1}].{'hi' if part else 'lo'}"
    return f"+0x{offset:02X}"


def record_locations(nodes: list[dict[str, object]]) -> list[RecordLocation]:
    """Validate analyzer nodes that retain their live settled pointers."""

    result: list[RecordLocation] = []
    for node in nodes:
        record_id = node.get("record_id")
        pointer = node.get("pointer")
        size = node.get("storage_size")
        if not all(isinstance(value, int) for value in (record_id, pointer, size)):
            raise ValueError("record node is missing integer ID, pointer, or size")
        assert isinstance(record_id, int)
        assert isinstance(pointer, int)
        assert isinstance(size, int)
        if not 0 <= record_id <= 0xFFFF:
            raise ValueError("record ID must be an unsigned word")
        if not 0 <= pointer < 0x10000 or size <= 0 or pointer + size > 0x10000:
            raise ValueError("record location is outside logical memory")
        result.append(RecordLocation(record_id, pointer, size))
    ordered = sorted(result, key=lambda item: item.pointer)
    for left, right in zip(ordered, ordered[1:]):
        if left.pointer + left.size > right.pointer:
            raise ValueError(
                f"record 0x{left.record_id:04X} overlaps record 0x{right.record_id:04X}"
            )
    return ordered


def attribute_record_writes(
    writes: Iterator[object], locations: list[RecordLocation],
    nodes: list[dict[str, object]],
) -> list[RecordFieldWrite]:
    """Map resolved TLMT writes into the final settled record byte ranges."""

    by_id = {int(node["record_id"]): node for node in nodes}
    result: list[RecordFieldWrite] = []
    for write in writes:
        address = getattr(write, "logical_address")
        for location in locations:
            if location.pointer <= address < location.pointer + location.size:
                node = by_id[location.record_id]
                offset = address - location.pointer
                payload = node.get("payload", [])
                result.append(RecordFieldWrite(
                    instruction_index=getattr(write, "instruction_index"),
                    clock=getattr(write, "clock"),
                    pc_space=getattr(write, "pc_space"),
                    pc_address=getattr(write, "pc_address"),
                    final_record_id=location.record_id,
                    pointer=location.pointer,
                    offset=offset,
                    field=record_field_name(
                        int(node["render_type"]), offset,
                        len(payload) if isinstance(payload, list) else 0,
                    ),
                    value=getattr(write, "value"),
                ))
                break
    return result


def construction_write_report(
    trace: Path, graph: dict[str, object], *,
    from_index: int = 0, to_index: int | None = None,
    initial_mapping: str = "ti84p-reset", resync: bool = False,
) -> dict[str, object]:
    """Attribute trace writes to the final record graph's live arena ranges."""

    from hardware_trace import iter_resolved_memory_writes

    raw_nodes = graph.get("nodes")
    if not isinstance(raw_nodes, list):
        raise ValueError("record graph has no node list")
    nodes: list[dict[str, object]] = []
    for node in raw_nodes:
        if not isinstance(node, dict):
            raise ValueError("record graph contains a non-object node")
        nodes.append(node)
    locations = record_locations(nodes)
    writes = (
        write for write in iter_resolved_memory_writes(
            trace, initial_mapping=initial_mapping, resync=resync
        )
        if write.instruction_index >= from_index
        and (to_index is None or write.instruction_index < to_index)
    )
    attributed = attribute_record_writes(writes, locations, nodes)
    return {
        "trace": str(trace),
        "from_instruction": from_index,
        "to_instruction": to_index,
        "entry_id": graph.get("entry_id"),
        "records": [asdict(item) for item in locations],
        "writes": [asdict(item) for item in attributed],
    }


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


def embedded_structural_records(payload: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
    """Return ``EF type id_lo id_hi`` references in leaf-program order."""

    result: list[tuple[int, int]] = []
    index = 0
    while index < len(payload):
        if (
            index + 3 < len(payload)
            and payload[index] == 0xEF
            and 0x1F <= payload[index + 1] <= 0x2B
        ):
            result.append((
                payload[index + 1],
                payload[index + 2] | payload[index + 3] << 8,
            ))
            index += 4
            continue
        index += 1
    return tuple(result)


def decode_settled_expression(
    nodes: list[dict[str, object]], entry_id: int
) -> object:
    """Decode one settled record graph into its expression structure.

    The result retains ordinary leaf runs as token-byte arrays. Structural
    records become nested dictionaries in the same argument order consumed by
    the page-34 renderer. Type ``0x2A`` is a postfix power record: its base is
    the ordinary token run immediately before its embedded-record marker.

    ``EF 1E`` is contextual. The type-``0x23`` construction path substitutes it
    for the one-token ``X`` body in ``nDeriv(X,X,...)``. Outside that body it
    remains an explicit extended token, including editable placeholder state.
    """

    by_id: dict[int, dict[str, object]] = {}
    for node in nodes:
        record_id = node.get("record_id")
        if not isinstance(record_id, int):
            raise ValueError("settled expression node is missing an integer record ID")
        if record_id in by_id:
            raise ValueError(f"duplicate settled expression record ID 0x{record_id:04X}")
        by_id[record_id] = node
    if entry_id not in by_id:
        raise ValueError(f"settled expression entry ID 0x{entry_id:04X} is absent")

    active: set[int] = set()

    def children(node: dict[str, object], count: int) -> list[int]:
        raw = node.get("child_ids")
        if not isinstance(raw, list) or len(raw) != count or not all(
            isinstance(value, int) for value in raw
        ):
            record_id = node["record_id"]
            raise ValueError(
                f"settled record 0x{record_id:04X} requires {count} child IDs"
            )
        return raw

    def collapse(parts: list[object]) -> object:
        merged: list[object] = []
        for part in parts:
            if (
                isinstance(part, list)
                and merged
                and isinstance(merged[-1], list)
            ):
                merged[-1].extend(part)
            else:
                merged.append(part)
        if not merged:
            raise ValueError("settled leaf decodes to an empty expression")
        if len(merged) == 1:
            return merged[0]
        return {"kind": "sequence", "parts": merged}

    def structural(record_id: int) -> object:
        node = by_id.get(record_id)
        if node is None:
            raise ValueError(f"embedded settled record ID 0x{record_id:04X} is absent")
        render_type = node.get("render_type")
        if not isinstance(render_type, int):
            raise ValueError(f"settled record 0x{record_id:04X} has no integer type")
        child_count = {
            0x20: 2, 0x21: 1, 0x22: 4, 0x23: 3,
            0x24: 2, 0x27: 1, 0x29: 4, 0x2A: 1,
        }.get(render_type)
        if child_count is None:
            raise ValueError(
                f"settled record 0x{record_id:04X} type 0x{render_type:02X} "
                "has no translated expression decoder"
            )
        child_ids = children(node, child_count)
        if render_type == 0x20:
            return {
                "kind": "fraction",
                "numerator": leaf(child_ids[0]),
                "denominator": leaf(child_ids[1]),
            }
        if render_type == 0x21:
            return {"kind": "absolute", "body": leaf(child_ids[0])}
        if render_type == 0x22:
            return {
                "kind": "integral",
                "lower": leaf(child_ids[0]),
                "upper": leaf(child_ids[1]),
                "body": leaf(child_ids[2]),
                "variable": leaf(child_ids[3]),
            }
        if render_type == 0x23:
            return {
                "kind": "nDeriv",
                "variable": leaf(child_ids[0]),
                "body": leaf(child_ids[1], context="nderiv_body"),
                "value": leaf(child_ids[2]),
            }
        if render_type == 0x24:
            return {
                "kind": "nthRoot",
                "index": leaf(child_ids[0]),
                "radicand": leaf(child_ids[1]),
            }
        if render_type == 0x27:
            return {"kind": "radical", "radicand": leaf(child_ids[0])}
        if render_type == 0x29:
            return {
                "kind": "summation",
                "variable": leaf(child_ids[0]),
                "lower": leaf(child_ids[1]),
                "upper": leaf(child_ids[2]),
                "body": leaf(child_ids[3]),
            }
        assert render_type == 0x2A
        return {"kind": "powerExponent", "exponent": leaf(child_ids[0])}

    def leaf(record_id: int, *, context: str | None = None) -> object:
        if record_id in active:
            raise ValueError(f"settled expression contains a cycle at ID 0x{record_id:04X}")
        node = by_id.get(record_id)
        if node is None:
            raise ValueError(f"settled leaf ID 0x{record_id:04X} is absent")
        render_type = node.get("render_type")
        if not isinstance(render_type, int) or render_type >= 0x1F:
            raise ValueError(f"settled record 0x{record_id:04X} is not a leaf")
        payload = node.get("payload")
        if not isinstance(payload, list) or not all(isinstance(value, int) for value in payload):
            raise ValueError(f"settled leaf 0x{record_id:04X} has no byte payload")
        active.add(record_id)
        try:
            parts: list[object] = []
            tokens: list[int] = []

            def flush_tokens() -> None:
                if tokens:
                    parts.append(tokens.copy())
                    tokens.clear()

            index = 0
            while index < len(payload):
                token = payload[index]
                if token != 0xEF:
                    tokens.append(token)
                    index += 1
                    continue
                if index + 1 >= len(payload):
                    raise ValueError(f"settled leaf 0x{record_id:04X} ends with EF")
                subtype = payload[index + 1]
                if subtype == 0x2D:
                    index += 2
                    continue
                if subtype == 0x1E:
                    if context == "nderiv_body":
                        tokens.append(0x58)
                    else:
                        flush_tokens()
                        parts.append({"kind": "extendedToken", "tokens": [0xEF, 0x1E]})
                    index += 2
                    continue
                if not 0x1F <= subtype <= 0x2B or index + 3 >= len(payload):
                    raise ValueError(
                        f"settled leaf 0x{record_id:04X} has unsupported EF "
                        f"subtype 0x{subtype:02X}"
                    )
                embedded_id = payload[index + 2] | payload[index + 3] << 8
                expression = structural(embedded_id)
                if subtype == 0x2A:
                    if expression.get("kind") != "powerExponent":
                        raise ValueError(
                            f"settled power marker references non-power ID 0x{embedded_id:04X}"
                        )
                    if not tokens:
                        raise ValueError(
                            f"settled power ID 0x{embedded_id:04X} has no preceding token base"
                        )
                    base = tokens.copy()
                    tokens.clear()
                    parts.append({
                        "kind": "power", "base": base,
                        "exponent": expression["exponent"],
                    })
                else:
                    flush_tokens()
                    parts.append(expression)
                index += 4
            flush_tokens()
            return collapse(parts)
        finally:
            active.remove(record_id)

    return leaf(entry_id)


def resolved_record_graph(
    trace: Path,
    *,
    from_index: int = 0,
    initial_mapping: str = "ti84p-reset",
    resync: bool = False,
) -> dict[str, object]:
    """Recover the final settled record program and its resolved records.

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
    entries: list[tuple[int, int, int, int, int]] = []
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
                elif site == RENDER_ENTRY:
                    entry = record(memory, word(memory, CURRENT_POINTER))
                    entry_id = decode_record_header(entry.header).record_id
                    nodes[entry_id] = entry
                    entries.append((
                        instruction_index,
                        entry_id,
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

    if not entries:
        return {
            "trace": str(trace), "entry_id": None, "root_id": None,
            "entries": [], "dispatches": [], "nodes": [],
        }

    # A final key may enter 34:660A several times. The enclosing leaf program is
    # the first entry at the shallowest Z80 stack depth after that key. Nested
    # structural handlers re-enter 34:660A lower on the stack for their children.
    _entry_instruction, entry_id, _entry_stack, entry_x, entry_y = (
        select_entry_dispatch(entries, last_key_press)
    )
    final_dispatches = [item for item in dispatches if item[0] >= last_key_press]
    if not final_dispatches:
        final_dispatches = dispatches
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
        for embedded_type, embedded_id in embedded_structural_records(
            nodes[record_id].payload
        ):
            if embedded_id not in nodes:
                raise ValueError(
                    f"record 0x{record_id:04X} embeds unresolved structural "
                    f"record 0x{embedded_id:04X}"
                )
            decoded = decode_record_header(nodes[embedded_id].header)
            if decoded.render_type != embedded_type:
                raise ValueError(
                    f"record 0x{record_id:04X} embeds type 0x{embedded_type:02X} "
                    f"but record 0x{embedded_id:04X} has type 0x{decoded.render_type:02X}"
                )
            visit(embedded_id)
        active.remove(record_id)

    visit(entry_id)
    graph_nodes = []
    for record_id in reachable:
        indexed = edges.get(record_id, {})
        child_ids = tuple(indexed[index] for index in sorted(indexed))
        node = record_node_json(nodes[record_id], child_ids)
        node["pointer"] = nodes[record_id].pointer
        node["storage_size"] = record_storage_size(nodes[record_id], child_ids)
        graph_nodes.append(node)
    expression = decode_settled_expression(graph_nodes, entry_id)
    return {
        "trace": str(trace),
        "entry_id": entry_id,
        # Retain the old name while consumers migrate to entry_id.
        "root_id": entry_id,
        "origin": {"x": entry_x, "y": entry_y},
        "entries": [
            {
                "instruction_index": index,
                "record_id": record_id,
                "stack_pointer": stack,
                "origin": {"x": x_origin, "y": y_origin},
            }
            for index, record_id, stack, x_origin, y_origin in entries
            if index >= last_key_press
        ],
        "dispatches": [
            {
                "instruction_index": index,
                "root_id": dispatched_id,
                "stack_pointer": stack,
                "origin": {"x": x_origin, "y": y_origin},
            }
            for index, dispatched_id, stack, x_origin, y_origin in final_dispatches
        ],
        "expression": expression,
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
        help="write the final settled record program and its reachable nodes",
    )
    parser.add_argument(
        "--construction-json",
        action="store_true",
        help="attribute writes to the final settled record byte ranges",
    )
    parser.add_argument(
        "--to-index", type=int,
        help="exclude writes at or after this instruction index",
    )
    args = parser.parse_args()
    if args.from_index < 0:
        parser.error("--from-index must be nonnegative")
    if args.children < 0:
        parser.error("--children must be nonnegative")
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    if args.to_index is not None and args.to_index < 0:
        parser.error("--to-index must be nonnegative")
    if args.to_index is not None and args.to_index < args.from_index:
        parser.error("--to-index must not precede --from-index")
    if args.construction_json and args.graph_json:
        parser.error("--construction-json and --graph-json are mutually exclusive")

    if args.construction_json:
        graph = resolved_record_graph(
            args.trace, from_index=args.from_index, resync=args.resync,
        )
        json.dump(construction_write_report(
            args.trace, graph, from_index=args.from_index,
            to_index=args.to_index, resync=args.resync,
        ), fp=sys.stdout, indent=2)
        print()
        return

    if args.graph_json:
        json.dump(resolved_record_graph(
            args.trace,
            from_index=args.from_index,
            resync=args.resync,
        ), fp=sys.stdout, indent=2)
        print()
        return

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
