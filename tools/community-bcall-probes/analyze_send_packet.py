#!/usr/bin/env python3
"""Validate the one-sided _SendPacket trace and handled link error."""

from __future__ import annotations

import argparse
from collections import Counter
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
    call_site = unique_site(machine, bytes((0xEF, 0xD6, 0x4E)))
    handler = unique_site(machine, bytes((0xCD, 0x5C, 0x00, 0x3E, 0xEE)))
    finish = unique_site(machine, bytes((0x32, 0x74, 0x98)))
    points = {
        ("page_3C", 0x4139): "send_packet",
        ("page_3C", 0x41C3): "send_header",
        ("page_3C", 0x420D): "send_a_byte",
        ("page_3C", 0x4160): "payload_read",
        ("ram", 0x278D): "link_error",
        ("ram", 0x2799): "j_error_no",
    }
    counts: Counter[str] = Counter()
    calls = handler_hits = finish_hits = instructions = 0
    active = False
    for insn in iter_resolved_instructions(
        args.trace, initial_mapping="ti84p-reset"
    ):
        instructions += 1
        if insn.logical_pc == call_site:
            calls += 1
            active = True
        if active and (insn.space, insn.address) in points:
            counts[points[(insn.space, insn.address)]] += 1
        if active and insn.logical_pc == handler:
            handler_hits += 1
        if insn.logical_pc == finish:
            finish_hits += 1
            active = False
    if calls != 1 or handler_hits != 1 or finish_hits != 1:
        raise SystemExit(
            f"fixture counts differ: call={calls}, handler={handler_hits}, finish={finish_hits}"
        )
    for name in ("send_packet", "send_header", "send_a_byte", "link_error", "j_error_no"):
        if not counts[name]:
            raise SystemExit(f"trace misses {name}: {counts}")
    if counts["payload_read"]:
        raise SystemExit(f"one-sided run unexpectedly reached payload loop: {counts}")

    snapshot = args.snapshot.read_bytes()
    if len(snapshot) < 0x8000:
        raise SystemExit("logical RAM snapshot is truncated")
    result = snapshot[0x1872:0x1877]
    if result != bytes((0x50, 0x4B, 0xEE, 0x0D, 0x60)):
        raise SystemExit(f"result block differs: {result.hex()}")

    row = {
        "id": "0x4ED6",
        "name": "_SendPacket",
        "body": "3C:4139",
        "model": "ti84p",
        "os_version": "2.55MP",
        "fixture_call_site": f"ram:{call_site:04X}",
        "observed_path": (
            f"3C:4139={counts['send_packet']};3C:41C3={counts['send_header']};"
            f"3C:420D={counts['send_a_byte']};ram:278D={counts['link_error']};"
            f"ram:2799={counts['j_error_no']};fixture-error-handler=1"
        ),
        "payload_loop_hits": counts["payload_read"],
        "result": "no peer; header send failed before payload; error handler returned",
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
            "source-built one-sided caller; no link peer; payload/checksum/ACK "
            "success path remains static ROM evidence; no physical hardware"
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
