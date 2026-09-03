#!/usr/bin/env python3
"""Validate the interactive _GetStringInput2 trace and parsed OP1 result."""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
from pathlib import Path

from ti84re.trace.hardware import iter_resolved_instructions


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
    call_site = unique_site(machine, bytes((0xEF, 0x61, 0x4E)))
    result_copy = unique_site(machine, bytes((0x21, 0x78, 0x84, 0x11, 0x75, 0x98)))
    calls = body_hits = context_hits = handoff_hits = result_copies = 0
    instructions = 0
    active = False
    for insn in iter_resolved_instructions(
        args.trace, initial_mapping="ti84p-reset"
    ):
        instructions += 1
        if insn.logical_pc == call_site:
            calls += 1
            active = True
        if active and insn.space == "page_37" and insn.address == 0x5194:
            body_hits += 1
        if active and insn.space == "ram" and insn.address == 0x077E:
            context_hits += 1
        if active and insn.space == "ram" and insn.address == 0x04F9:
            handoff_hits += 1
        if insn.logical_pc == result_copy:
            result_copies += 1
            active = False
    if (
        calls != 1
        or body_hits != 1
        or context_hits < 1
        or handoff_hits < 1
        or result_copies != 1
    ):
        raise SystemExit(
            "path counts differ: "
            f"call={calls}, body={body_hits}, context={context_hits}, "
            f"handoff={handoff_hits}, result={result_copies}"
        )

    snapshot = args.snapshot.read_bytes()
    if len(snapshot) < 0x8000:
        raise SystemExit("logical RAM snapshot is truncated")
    result = snapshot[0x1872:0x1883]
    expected_op1 = bytes((0x00, 0x80, 0x10, 0, 0, 0, 0, 0, 0, 0, 0))
    if result[:3] != bytes((0x53, 0x32, 0x01)):
        raise SystemExit(f"fixture signature/stage differs: {result.hex()}")
    if result[3:14] != expected_op1:
        raise SystemExit(f"parsed OP1 differs: {result[3:14].hex()}")
    if result[14:17] != bytes((0x02, 0x0D, 0x60)):
        raise SystemExit(f"final marker differs: {result[14:17].hex()}")

    row = {
        "id": "0x4E61",
        "name": "_GetStringInput2",
        "body": "37:5194",
        "model": "ti84p",
        "os_version": "2.55MP",
        "fixture_call_site": f"ram:{call_site:04X}",
        "path": (
            f"37:5194=1;ram:077E={context_hits};ram:04F9={handoff_hits};"
            "caller-result=1"
        ),
        "input": "1 ENTER",
        "op1": "00 80 10 00 00 00 00 00 00 00 00 (real 1)",
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
            "source-built caller reconstructed from Elite; one valid numeric input; "
            "TilEm; cancel/error paths and physical hardware not tested"
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
