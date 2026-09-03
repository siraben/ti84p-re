#!/usr/bin/env python3
"""Validate the packaged Cool program's malformed bcall trace."""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
from pathlib import Path
import re

from ti84re.hardware.probe import decode_ti_variable_file
from ti84re.rom.image import RomImage
from ti84re.trace.resolve import IDX_PC, iter_records, read_header


POINTS = (0x9D95, 0x9DAF, 0xEF7A, 0x60A3, 0x57D1, 0x2729, 0x0053)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--wrapper", type=Path, required=True)
    parser.add_argument("--macro", type=Path, required=True)
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    variable = decode_ti_variable_file(args.program.read_bytes())
    if variable.name != "COOL" or variable.data[2:4] != bytes((0xBB, 0x6D)):
        raise ValueError("expected the packaged compiled program COOL")
    code = variable.data[4:]
    if code[26:29] != bytes((0xEF, 0x9C, 0x4B)):
        raise ValueError("packaged program does not contain EF 9C 4B at ram:9DAF")

    source = args.source.read_text(encoding="utf-8", errors="replace")
    if re.search(r"(?im)^\s*_copygbuf\s+equ\s+4B9Ch\b", source) is None:
        raise ValueError("source no longer defines _copygbuf as 4B9Ch")
    if re.search(r"(?im)^\s*\.dw\s+_copygbuf\b", source) is None:
        raise ValueError("source no longer emits the _copygbuf word")

    table_bytes = RomImage.from_path(args.rom).bytes_at(0x3B, 0x4B9C, 3)
    if table_bytes != bytes((0x7A, 0xEF, 0x5E)):
        raise ValueError(f"unexpected overlapping table bytes: {table_bytes.hex()}")

    active = False
    instructions = 0
    counts = {point: 0 for point in POINTS}
    with args.trace.open("rb") as stream:
        header = read_header(stream)
        if header["version"] != 2:
            raise ValueError(f"expected TLMT v2, got {header['version']}")
        for record_type, payload in iter_records(stream):
            if record_type != 1:
                continue
            pc = payload[IDX_PC]
            if pc == 0x9D95:
                active = True
            if not active:
                continue
            instructions += 1
            if pc in counts:
                counts[pc] += 1

    expected = {
        0x9D95: 1,
        0x9DAF: 1,
        0xEF7A: 1,
        0x60A3: 0,
        0x57D1: 0,
        0x2729: 0,
        0x0053: 1,
    }
    if counts != expected:
        raise ValueError(f"unexpected post-entry path: {counts}")

    row = {
        "scenario": "cool-malformed-copygbuf-bcall",
        "model": "ti84p",
        "os_version": "2.55MP",
        "rom_sha256": digest(args.rom),
        "emulator_sha256": digest(args.emulator),
        "archive_sha256": digest(args.archive),
        "source_sha256": digest(args.source),
        "program_sha256": digest(args.program),
        "wrapper_sha256": digest(args.wrapper),
        "macro_sha256": digest(args.macro),
        "trace_sha256": digest(args.trace),
        "recording_sha256": digest(args.recording),
        "post_entry_instructions": instructions,
        "payload_entry_hits": counts[0x9D95],
        "malformed_call_hits": counts[0x9DAF],
        "overlap_target_hits": counts[0xEF7A],
        "intended_grbufcpy_hits": counts[0x60A3],
        "normal_cleanup_hits": counts[0x57D1],
        "error_invalid_hits": counts[0x2729],
        "os_handoff_vector_hits": counts[0x0053],
        "result": "overlap-target-no-normal-return",
        "evidence_limit": (
            "packaged calculator program in TilEm; logical target count; "
            "no physical hardware"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=row, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
    for key, value in row.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
