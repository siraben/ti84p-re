#!/usr/bin/env python3
"""Reduce paired For( traces to marker timing and parser-buffer evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ti84re.trace.hardware import make_banker
from ti84re.rom.signatures import TI84_PLUS_OS_255MP_SHA256
from ti84re.trace.resolve import (
    IDX_CLOCK,
    IDX_OPCODE,
    iter_records,
    read_header,
    resolve_instruction,
)
from ti84re.paths import DEFAULT_ROM


MARKER = ("ram", 0x9D95, 0xC9)
CURSOR_BYTES = range(0x965D, 0x9661)
TEMP_BUFFER_FLOOR = 0x9E80
END_HANDLER = ("page_38", 0x4200)
OPS_PTR = 0x9828
FPS_PTR = 0x9824
LOOP_RECORD_SIZE = 5


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def summarize_addresses(values: list[int]) -> dict[str, object]:
    if not values:
        return {"count": 0, "first": None, "last": None, "stride": None}
    strides = {right - left for left, right in zip(values, values[1:])}
    stride = strides.pop() if len(strides) == 1 else None
    return {
        "count": len(values),
        "first": f"0x{values[0]:04X}",
        "last": f"0x{values[-1]:04X}",
        "stride": stride,
    }


def summarize_values(values: list[int]) -> dict[str, object]:
    """Summarize an ordered word-valued state sequence."""

    if not values:
        return {"count": 0, "first": None, "last": None, "distinct": 0}
    return {
        "count": len(values),
        "first": f"0x{values[0]:04X}",
        "last": f"0x{values[-1]:04X}",
        "distinct": len(set(values)),
    }


def analyze_trace(
    path: Path, *, marker: tuple[str, int, int] = MARKER
) -> dict[str, object]:
    banker = make_banker("ti84p-reset")
    instruction_index = 0
    pending_writes: list[tuple[int, int]] = []
    cursor_writes: list[tuple[int, int, int]] = []
    markers: list[tuple[int, int]] = []
    memory: dict[int, int] = {}
    loop_records: list[dict[str, object]] = []

    with path.open("rb") as stream:
        header = read_header(stream)
        if header["version"] != 2:
            raise ValueError(f"{path}: expected TLMT v2, got v{header['version']}")
        for record_type, payload in iter_records(stream):
            if record_type == 0x02:
                address, value = payload
                pending_writes.append((address, value))
                memory[address] = value
                continue
            if record_type != 0x01:
                continue

            for address, value in pending_writes:
                if address in CURSOR_BYTES:
                    cursor_writes.append((instruction_index, address, value))
            pending_writes.clear()

            (space, address, _flat, _page), _switch = resolve_instruction(banker, payload)
            if (space, address) == END_HANDLER:
                ops = memory.get(OPS_PTR, 0) | memory.get(OPS_PTR + 1, 0) << 8
                fps = memory.get(FPS_PTR, 0) | memory.get(FPS_PTR + 1, 0) << 8
                record = bytes(
                    memory.get(ops + offset, 0)
                    for offset in range(1, LOOP_RECORD_SIZE + 1)
                )
                loop_records.append({
                    "ops": f"0x{ops:04X}",
                    "fps": f"0x{fps:04X}",
                    "bytes_from_ops_plus_1": record.hex(),
                    "sentinel": f"0x{record[0]:02X}",
                    "continuation": f"0x{int.from_bytes(record[1:3], 'little'):04X}",
                    "state_word": f"0x{int.from_bytes(record[3:5], 'little'):04X}",
                })
            if (space, address, payload[IDX_OPCODE]) == marker:
                markers.append((instruction_index, payload[IDX_CLOCK]))
            instruction_index += 1

    if len(markers) != 2:
        raise ValueError(f"{path}: expected exactly two ZMARK RETs, found {len(markers)}")
    (start_index, start_clock), (end_index, end_clock) = markers

    byte_state: dict[int, int] = {}
    equal_high_states: list[int] = []
    write_counts: dict[str, int] = {}
    for index, address, value in cursor_writes:
        if not start_index < index <= end_index:
            continue
        byte_state[address] = value
        key = f"0x{address:04X}"
        write_counts[key] = write_counts.get(key, 0) + 1
        if len(byte_state) != 4:
            continue
        cursor = byte_state[0x965D] | byte_state[0x965E] << 8
        parse_end = byte_state[0x965F] | byte_state[0x9660] << 8
        if cursor == parse_end and cursor >= TEMP_BUFFER_FLOOR:
            if not equal_high_states or equal_high_states[-1] != cursor:
                equal_high_states.append(cursor)

    return {
        "sha256": digest(path),
        "bytes": path.stat().st_size,
        "marker": f"{marker[0]}:{marker[1]:04X} opcode=0x{marker[2]:02X}",
        "instructions": end_index - start_index,
        "clocks": (end_clock - start_clock) & 0xFFFFFFFF,
        "parser_pointer_write_counts": dict(sorted(write_counts.items())),
        "equal_cursor_end_high_sequence": summarize_addresses(equal_high_states),
        "loop_end_visits": len(loop_records),
        "loop_record_variants": sorted({
            row["bytes_from_ops_plus_1"] for row in loop_records
        }),
        "loop_record_first": loop_records[0] if loop_records else None,
        "loop_record_steady": loop_records[1] if len(loop_records) > 1 else None,
        "loop_end_fps": summarize_values([
            int(row["fps"], 16) for row in loop_records
        ]),
    }


def build_report(
    explicit: Path, implicit: Path, rom: Path = DEFAULT_ROM
) -> dict[str, object]:
    rom_digest = digest(rom)
    if rom_digest != TI84_PLUS_OS_255MP_SHA256:
        raise ValueError("ROM SHA-256 does not match the pinned TI-84 Plus OS 2.55MP image")
    explicit_row = analyze_trace(explicit)
    implicit_row = analyze_trace(implicit)
    instruction_delta = implicit_row["instructions"] - explicit_row["instructions"]
    clock_delta = implicit_row["clocks"] - explicit_row["clocks"]
    return {
        "schema": 2,
        "rom": {"path": "tools/rom.bin", "sha256": rom_digest},
        "scope": "N=25, first loop-body statement is a false single-line If",
        "traces": {"explicit_rparen": explicit_row, "implicit_close": implicit_row},
        "implicit_minus_explicit": {
            "instructions": instruction_delta,
            "instruction_percent": 100 * instruction_delta / explicit_row["instructions"],
            "clocks": clock_delta,
            "clock_percent": 100 * clock_delta / explicit_row["clocks"],
        },
        "buffer_filter": "nextParseByte == basic_end and address >= 0x9E80",
        "loop_record": {
            "handler": "38:4200",
            "storage": "five bytes beginning at OPS + 1",
            "byte_order": "sentinel, little-endian continuation, little-endian state word",
            "initial_continuation": "38:5836",
            "steady_continuation": "38:587D",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--explicit", type=Path, required=True)
    parser.add_argument("--implicit", type=Path, required=True)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_report(args.explicit, args.implicit, args.rom)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    delta = report["implicit_minus_explicit"]
    print(
        f"wrote {args.output}: implicit close adds {delta['instructions']:,} instructions "
        f"({delta['instruction_percent']:.2f}%)"
    )


if __name__ == "__main__":
    main()
