#!/usr/bin/env python3
"""Validate the safe semantics fixture and emit one row per exercised bcall."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from hashlib import sha256
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardware_trace import iter_resolved_executions  # noqa: E402


ORIGIN = 0x9D95
ROUTINES = {
    0x4030: ("_newContext", ("ram", 0x077E)),
    0x41D4: ("_ShRAcc", ("ram", 0x1BCB)),
    0x4744: ("_GetK", ("page_37", 0x746D)),
    0x4A02: ("_ConvKeyToTok", ("page_07", 0x44DE)),
    0x4F3C: ("_FlashWriteDisable", ("page_3C", 0x66D5)),
    0x4F69: ("_ClrCursorHook", ("page_3B", 0x7AEA)),
    0x4F99: ("_SetTokenHook", ("page_3B", 0x7D0B)),
    0x50CE: ("_SetSilentLinkHook", ("page_3B", 0x7DBB)),
}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def call_sites(machine: bytes) -> dict[int, int]:
    sites: dict[int, int] = {}
    for bcall_id in ROUTINES:
        needle = bytes((0xEF, bcall_id & 0xFF, bcall_id >> 8))
        offsets = [index for index in range(len(machine)) if machine.startswith(needle, index)]
        if len(offsets) != 1:
            raise SystemExit(f"bcall 0x{bcall_id:04X} occurs {len(offsets)} times")
        sites[bcall_id] = ORIGIN + offsets[0]
    return sites


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

    sites = call_sites(args.machine.read_bytes())
    raw_counts: Counter[int] = Counter()
    body_counts: Counter[tuple[str, int]] = Counter()
    flash_disable_writes: list[tuple[int, int | None]] = []
    instructions = 0
    for execution in iter_resolved_executions(
        args.trace, initial_mapping="ti84p-reset"
    ):
        instructions += 1
        insn = execution.instruction
        if insn.logical_pc in sites.values():
            raw_counts[insn.logical_pc] += 1
        point = (insn.space, insn.address)
        if point in {item[1] for item in ROUTINES.values()}:
            body_counts[point] += 1
        if point == ("page_3C", 0x66E2) and execution.io_event is not None:
            flash_disable_writes.append(
                (execution.io_event.port, execution.io_event.value)
            )

    bad_sites = {
        bcall_id: raw_counts[address]
        for bcall_id, address in sites.items()
        if raw_counts[address] != 1
    }
    if bad_sites:
        raise SystemExit(f"fixture bcall-site counts differ: {bad_sites}")
    missing = [
        name
        for name, point in ROUTINES.values()
        if not body_counts[point]
    ]
    if missing:
        raise SystemExit(f"trace misses resolved bodies: {', '.join(missing)}")

    snapshot = args.snapshot.read_bytes()
    if len(snapshot) < 0x8000:
        raise SystemExit("logical RAM snapshot is truncated")
    result = snapshot[0x1872:0x1896]
    if result[0:2] != bytes((0x4B, 0xC2)):
        raise SystemExit(f"fixture signature differs: {result.hex()}")
    if result[2] != result[5] or result[3:5] != bytes((0x30, 0x00)):
        raise SystemExit(f"_newContext observation differs: {result[:6].hex()}")
    if result[7] != 0x0A or result[6] & 0x01:
        raise SystemExit(f"_ShRAcc observation differs: {result[6:8].hex()}")
    if result[8:10] != bytes((0x3F, 0x00)):
        raise SystemExit(f"_ConvKeyToTok observation differs: {result[8:10].hex()}")
    if snapshot[0x0483:0x0486] != bytes((0x00, 0x81, 0x34)):
        raise SystemExit(f"_GetK OP2 prefix differs: {snapshot[0x0483:0x048E].hex()}")
    if result[0x15:0x18] != bytes((0x72, 0x98, 0x00)) or not result[0x18] & 0x01:
        raise SystemExit(f"_SetTokenHook observation differs: {result[0x15:0x19].hex()}")
    if result[0x19:0x1C] != bytes((0x75, 0x98, 0x00)) or not result[0x1C] & 0x80:
        raise SystemExit(f"_SetSilentLinkHook observation differs: {result[0x19:0x1D].hex()}")
    if result[0x1D] != (result[0x0E] & 0x7F):
        raise SystemExit(f"_ClrCursorHook observation differs: {result[0x0E]:02x}/{result[0x1D]:02x}")
    if result[0x1E:0x21] != bytes((0x3C, 0x0D, 0x60)):
        raise SystemExit(f"final marker differs: {result[0x1E:0x21].hex()}")
    if snapshot[0x0A24:0x0A27] != bytes((result[0x0E], result[0x21], result[0x22])):
        raise SystemExit("hook flag bytes were not restored")
    if snapshot[0x1BC8:0x1BCB] != result[0x0F:0x12]:
        raise SystemExit("token-hook target record was not restored")
    if snapshot[0x1BD0:0x1BD3] != result[0x12:0x15]:
        raise SystemExit("silent-link-hook target record was not restored")
    if (0x14, 0) not in flash_disable_writes:
        raise SystemExit(f"missing dynamic OUT (0x14),0: {flash_disable_writes}")

    shared = {
        "model": "ti84p",
        "os_version": "2.55MP",
        "rom_sha256": digest(args.rom),
        "emulator_sha256": digest(args.emulator),
        "machine_sha256": digest(args.machine),
        "payload_sha256": digest(args.payload),
        "wrapper_sha256": digest(args.wrapper),
        "macro_sha256": digest(args.macro),
        "trace_sha256": digest(args.trace),
        "snapshot_sha256": digest(args.snapshot),
        "instructions": instructions,
    }
    observations = {
        0x4030: f"kbdKey=0;port6=0x{result[2]:02X}->0x{result[5]:02X}",
        0x41D4: f"A=0xAB->0x{result[7]:02X};F=0x{result[6]:02X}",
        0x4744: "kbdGetKy=0x01 consumed;table[1]=0x22;OP2=real 34",
        0x4A02: "A=0x05->DE=0x003F",
        0x4F3C: "returned;OUT port 0x14 value 0x00 observed",
        0x4F69: f"IY+0x34=0x{result[0x0E] | 0x80:02X}->0x{result[0x1D]:02X}",
        0x4F99: "target=ram:9872,page=0;IY+0x35 bit0 set",
        0x50CE: "target=ram:9875,page=0;IY+0x36 bit7 set",
    }
    rows = []
    for bcall_id, (name, point) in ROUTINES.items():
        rows.append(
            {
                "id": f"0x{bcall_id:04X}",
                "name": name,
                "body": (
                    f"ram:{point[1]:04X}"
                    if point[0] == "ram"
                    else f"{point[0].removeprefix('page_').upper()}:{point[1]:04X}"
                ),
                "fixture_call_site": f"ram:{sites[bcall_id]:04X}",
                "body_hits": body_counts[point],
                "observed": observations[bcall_id],
                **shared,
                "evidence_limit": (
                    "source-built safe caller; TilEm; state restored before halt; "
                    "no physical hardware"
                ),
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(f"{row['id']} {row['name']}: {row['observed']}")


if __name__ == "__main__":
    main()
