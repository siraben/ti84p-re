#!/usr/bin/env python3
"""Reduce paired For( traces to marker timing and parser-buffer evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from hardware_trace import make_banker
from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from tilem_trace_resolve import (
    IDX_CLOCK,
    IDX_OPCODE,
    iter_records,
    read_header,
    resolve_instruction,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "tools" / "rom.bin"
MARKER = ("ram", 0x9D95, 0xC9)
CURSOR_BYTES = range(0x965D, 0x9661)
TEMP_BUFFER_FLOOR = 0x9E80


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


def analyze_trace(
    path: Path, *, marker: tuple[str, int, int] = MARKER
) -> dict[str, object]:
    banker = make_banker("ti84p-reset")
    instruction_index = 0
    pending_writes: list[tuple[int, int]] = []
    cursor_writes: list[tuple[int, int, int]] = []
    markers: list[tuple[int, int]] = []

    with path.open("rb") as stream:
        header = read_header(stream)
        if header["version"] != 2:
            raise ValueError(f"{path}: expected TLMT v2, got v{header['version']}")
        for record_type, payload in iter_records(stream):
            if record_type == 0x02:
                address, value = payload
                pending_writes.append((address, value))
                continue
            if record_type != 0x01:
                continue

            for address, value in pending_writes:
                if address in CURSOR_BYTES:
                    cursor_writes.append((instruction_index, address, value))
            pending_writes.clear()

            (space, address, _flat, _page), _switch = resolve_instruction(banker, payload)
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
        "schema": 1,
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
