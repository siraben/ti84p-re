#!/usr/bin/env python3
"""Replay a resident-allocation trace and emit checkpoint CSV."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tilem_trace_resolve import (  # noqa: E402
    IDX_CLOCK, IDX_PC, IDX_PC_REG, IDX_SP, iter_records, read_header,
)

FIELDS = {
    "fpBase": 0x9822, "FPS": 0x9824, "OPBase": 0x9826,
    "OPS": 0x9828, "pTemp": 0x982E, "progPtr": 0x9830,
}
ROUTINES = {
    "CreateAppVar": 0x114B, "CreateProg": 0x1153,
    "InsertMem": 0x0F81, "DelMem": 0x1368,
    "EnoughMem": 0x0FA6, "DelVar": 0x1308,
}
CHECKPOINTS = (
    "program_start", "after_enough_mem", "after_create_appvar",
    "after_delete_appvar", "after_create_program", "after_delete_program",
    "after_insert_mem", "after_delete_mem", "after_max_create",
    "after_max_delete",
)


def word(memory: bytearray, address: int) -> int:
    return memory[address] | memory[address + 1] << 8


def labels(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    pattern = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*).*?\$([0-9A-Fa-f]{4})")
    for line in path.read_text(encoding="ascii").splitlines():
        match = pattern.search(line)
        if match:
            result[match.group(1).lower()] = int(match.group(2), 16)
    required = set(CHECKPOINTS) | {
        "source_before", "source_expected_up", "source_after_insert",
        "source_after_delete", "execution_guard", "execution_guard_end",
        "max_free_before", "max_request", "max_plus_one_carry",
    }
    missing = required - result.keys()
    if missing:
        raise SystemExit(f"labels missing: {sorted(missing)}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--rom", type=Path, required=True)
    args = parser.parse_args()
    symbol = labels(args.labels)
    by_pc = {symbol[name]: name for name in CHECKPOINTS}

    with args.trace.open("rb") as stream:
        header = read_header(stream)
        memory = bytearray(header["init"])
        guard = None
        guard_after = None
        rows = []
        hits = {name: 0 for name in ROUTINES}
        seen = set()
        active = False
        for record_type, payload in iter_records(stream):
            if record_type == 0x02:
                address, value = payload
                memory[address] = value
                continue
            if record_type != 0x01:
                continue
            pc = payload[IDX_PC]
            if active:
                for routine, address in ROUTINES.items():
                    if pc == address:
                        hits[routine] += 1
            name = by_pc.get(payload[IDX_PC_REG])
            if name is None or name in seen:
                continue
            seen.add(name)
            if name == "program_start":
                active = True
                guard = bytes(
                    memory[symbol["execution_guard"]:symbol["execution_guard_end"]]
                )
            elif name == "after_delete_mem":
                guard_after = bytes(
                    memory[symbol["execution_guard"]:symbol["execution_guard_end"]]
                )
            elif name == "after_max_delete":
                active = False
            values = {key: word(memory, address) for key, address in FIELDS.items()}
            values["MemChk"] = max(0, values["OPS"] - values["FPS"] + 1)
            rows.append({
                "checkpoint": name, "clock": payload[IDX_CLOCK],
                **{key: f"0x{value:04X}" for key, value in values.items()},
                "SP": f"0x{payload[IDX_SP]:04X}",
                "source_before": f"0x{word(memory, symbol['source_before']):04X}",
                "source_expected_up": f"0x{word(memory, symbol['source_expected_up']):04X}",
                "source_after_insert": f"0x{word(memory, symbol['source_after_insert']):04X}",
                "source_after_delete": f"0x{word(memory, symbol['source_after_delete']):04X}",
                "max_free_before": f"0x{word(memory, symbol['max_free_before']):04X}",
                "max_request": f"0x{word(memory, symbol['max_request']):04X}",
                "max_plus_one_carry": memory[symbol["max_plus_one_carry"]],
            })

    if seen != set(CHECKPOINTS):
        raise SystemExit(f"missing checkpoints: {sorted(set(CHECKPOINTS) - seen)}")
    if guard is None:
        raise SystemExit("execution guard was not captured")
    if guard_after != guard:
        raise SystemExit("execution guard changed")
    if any(count == 0 for count in hits.values()):
        raise SystemExit(f"missing allocator routine: {hits}")
    last = rows[-1]
    if last["source_after_insert"] != last["source_expected_up"]:
        raise SystemExit(f"source VAT pointer was not advanced by InsertMem: {last}")
    if last["source_after_delete"] != last["source_before"]:
        raise SystemExit(f"source VAT pointer was not restored by DelMem: {last}")
    if last["max_plus_one_carry"] != 0:
        raise SystemExit("raw _EnoughMem unexpectedly rejected max_request + 1")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rom_sha256 = hashlib.sha256(args.rom.read_bytes()).hexdigest()
    trace_sha256 = hashlib.sha256(args.trace.read_bytes()).hexdigest()
    for row in rows:
        row["model"] = "TI-84 Plus"
        row["os_version"] = "2.55MP"
        row["rom_sha256"] = rom_sha256
        row["trace_sha256"] = trace_sha256
    with args.output.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=rows[0].keys(), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    print("routine_hits " + " ".join(f"{key}={value}" for key, value in hits.items()))
    print(f"wrote {len(rows)} checkpoints to {args.output}")


if __name__ == "__main__":
    main()
