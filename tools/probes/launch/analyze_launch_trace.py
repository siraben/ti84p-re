#!/usr/bin/env python3
"""Replay trace writes and print timed resident-launch heap checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ti84re.trace.resolve import (
    IDX_CLOCK,
    IDX_PC,
    IDX_PC_REG,
    IDX_SP,
    iter_records,
    read_header,
)


FIELDS = {
    "fpBase": 0x9822,
    "FPS": 0x9824,
    "OPBase": 0x9826,
    "OPS": 0x9828,
    "pTemp": 0x982E,
    "progPtr": 0x9830,
}


def word(memory: bytearray, address: int) -> int:
    return memory[address] | memory[address + 1] << 8


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(label: str, memory: bytearray,
             payload: tuple[int, ...]) -> dict[str, object]:
    values = {name: word(memory, address) for name, address in FIELDS.items()}
    values["symTable"] = 0xFE66
    values["SP"] = payload[IDX_SP]
    values["MemChk"] = max(0, values["OPS"] - values["FPS"] + 1)
    return {
        "label": label,
        "clock": payload[IDX_CLOCK],
        "pc": payload[IDX_PC],
        "fields": values,
    }


def print_snapshot(checkpoint: dict[str, object]) -> None:
    values = checkpoint["fields"]
    assert isinstance(values, dict)
    rendered = " ".join(
        f"{name}=0x{value:04X}" for name, value in values.items()
    )
    print(
        f"{checkpoint['label']} clk={checkpoint['clock']} "
        f"pc=0x{checkpoint['pc']:04X} {rendered}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("--rom", type=Path)
    parser.add_argument("--model", default="ti84p")
    parser.add_argument("--os-version", default="2.55MP")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    checkpoints: list[dict[str, object]] = []
    with args.trace.open("rb") as stream:
        header = read_header(stream)
        if header["range_start"] != 0 or header["range_end"] != 0xFFFF:
            raise SystemExit("trace must use --trace-range all")
        memory = bytearray(header["init"])

        launched = False
        payload_entered = False
        nested_seen = False
        payload_returned = False
        cleanup_started = False
        post_cleanup = False

        for record_type, payload in iter_records(stream):
            if record_type == 0x02:
                address, value = payload
                memory[address] = value
                continue
            if record_type != 0x01:
                continue

            pc = payload[IDX_PC]
            if not launched and pc == 0x5758:
                checkpoints.append(snapshot("pre_launch", memory, payload))
                launched = True
            elif launched and not payload_entered and pc == 0x9D95:
                checkpoints.append(snapshot("payload_entry", memory, payload))
                payload_entered = True
            elif payload_entered and not nested_seen and pc == 0x0E20:
                checkpoints.append(snapshot("nested_memchk", memory, payload))
                nested_seen = True
            elif (payload_entered and not payload_returned
                  and payload[IDX_PC_REG] == 0x57B7):
                checkpoints.append(snapshot("payload_return", memory, payload))
                payload_returned = True
            elif payload_returned and not cleanup_started and pc == 0x57D1:
                checkpoints.append(snapshot("cleanup_entry", memory, payload))
                cleanup_started = True
            elif (cleanup_started and not post_cleanup and pc == 0x13F1
                  and payload[IDX_PC_REG] != 0x13F2):
                checkpoints.append(snapshot("post_cleanup", memory, payload))
                post_cleanup = True
                break

    required = (launched, payload_entered, nested_seen, payload_returned,
                cleanup_started, post_cleanup)
    if not all(required):
        raise SystemExit(f"incomplete launch checkpoints: {required}")

    if not args.json:
        for checkpoint in checkpoints:
            print_snapshot(checkpoint)
        return

    result: dict[str, object] = {
        "schema": "ti84p-re.resident-launch-snapshot.v1",
        "calculator_model": args.model,
        "os_version": args.os_version,
        "launch_method": "TI-BASIC Asm(prgmRTSNAP)",
        "trace": {
            "path": str(args.trace),
            "sha256": sha256(args.trace),
            "format_version": header["version"],
            "flags": header["flags"],
            "range_start": header["range_start"],
            "range_end": header["range_end"],
            "initial_snapshot_size": header["init_size"],
        },
        "checkpoints": checkpoints,
    }
    if args.rom:
        result["rom"] = {
            "path": str(args.rom),
            "sha256": sha256(args.rom),
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
