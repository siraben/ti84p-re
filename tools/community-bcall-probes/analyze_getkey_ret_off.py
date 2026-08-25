#!/usr/bin/env python3
"""Validate the interactive _GetKeyRetOff trace and result snapshot."""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardware_trace import iter_resolved_instructions  # noqa: E402


ORIGIN = 0x9D95


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def unique_site(machine: bytes, needle: bytes) -> int:
    offsets = [index for index in range(len(machine)) if machine.startswith(needle, index)]
    if len(offsets) != 1:
        raise SystemExit(f"fixture pattern {needle.hex()} occurs {len(offsets)} times")
    return ORIGIN + offsets[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--machine", type=Path, required=True)
    parser.add_argument("--rom", type=Path, default=Path("tools/rom.bin"))
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--wrapper", type=Path, required=True)
    parser.add_argument("--macro", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    machine = args.machine.read_bytes()
    call_site = unique_site(machine, bytes((0xEF, 0x0B, 0x50)))
    result_store = unique_site(machine, bytes((0x32, 0x75, 0x98)))
    calls = 0
    result_stores = 0
    path_hits = {address: 0 for address in (0x491A, 0x4A93, 0x4A9B, 0x4A9D, 0x4AA1)}
    instructions = 0
    active = False
    for insn in iter_resolved_instructions(
        args.trace, initial_mapping="ti84p-reset"
    ):
        instructions += 1
        if insn.logical_pc == call_site:
            calls += 1
            active = True
        if insn.logical_pc == result_store:
            result_stores += 1
            active = False
        if active and insn.space == "page_06" and insn.address in path_hits:
            path_hits[insn.address] += 1

    if calls < 1 or result_stores != 1:
        raise SystemExit(f"fixture counts differ: calls={calls}, result stores={result_stores}")
    if any(count < 1 for count in path_hits.values()):
        raise SystemExit(f"ON-return path is incomplete: {path_hits}")

    snapshot = args.snapshot.read_bytes()
    if len(snapshot) < 0x8000:
        raise SystemExit("logical RAM snapshot is truncated")
    result = snapshot[0x1872:0x1879]
    if result != bytes((0x4E, 0x4F, 0x01, 0x3F, 0x02, 0x0D, 0x60)):
        raise SystemExit(f"result block differs: {result.hex()}")

    row = {
        "id": "0x500B",
        "name": "_GetKeyRetOff",
        "body": "06:491A",
        "model": "ti84p",
        "os_version": "2.55MP",
        "fixture_call_site": f"ram:{call_site:04X}",
        "fixture_calls": calls,
        "on_path": ";".join(f"06:{address:04X}={path_hits[address]}" for address in path_hits),
        "returned_a": "0x3F",
        "rom_sha256": digest(args.rom),
        "emulator_sha256": digest(args.emulator),
        "machine_sha256": digest(args.machine),
        "payload_sha256": digest(args.payload),
        "wrapper_sha256": digest(args.wrapper),
        "macro_sha256": digest(args.macro),
        "trace_sha256": digest(args.trace),
        "snapshot_sha256": digest(args.snapshot),
        "instructions": instructions,
        "evidence_limit": (
            "source-built interactive caller; ENTER drain then 2nd+ON; TilEm; "
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
