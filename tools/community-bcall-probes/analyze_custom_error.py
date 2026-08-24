#!/usr/bin/env python3
"""Validate the custom-error probe's ROM path and bounded message writes."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardware_trace import count_resolved_trace_points, iter_resolved_memory_writes


POINTS = {
    ("ram", 0x2771): "err_custom_1",
    ("ram", 0x2793): "j_error",
    ("page_07", 0x6A72): "error_display",
    ("ram", 0x9D95): "payload",
}
EXPECTED_MESSAGE = b"COMMTRACE\x00"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--rom", type=Path, default=Path("tools/rom.bin"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    counts = count_resolved_trace_points(
        args.trace, set(POINTS), initial_mapping="ti84p-reset"
    )
    observed: dict[int, int] = {}
    for event in iter_resolved_memory_writes(
        args.trace, initial_mapping="ti84p-reset"
    ):
        if 0x984D <= event.logical_address < 0x984D + len(EXPECTED_MESSAGE):
            observed[event.logical_address] = event.value
    message = bytes(observed.get(0x984D + offset, -1) for offset in range(len(EXPECTED_MESSAGE)))
    if message != EXPECTED_MESSAGE:
        raise SystemExit(f"appErr1 writes mismatch: {message!r}")
    missing = [name for point, name in POINTS.items() if not counts.counts.get(point)]
    if missing:
        raise SystemExit(f"trace misses required points: {', '.join(missing)}")

    row = {
        "scenario": "community-custom-error",
        "model": "ti84p",
        "os_version": "2.55MP",
        "rom_sha256": sha256(args.rom),
        "trace_sha256": sha256(args.trace),
        "instructions": counts.processed_instructions,
        "payload_hits": counts.counts[("ram", 0x9D95)],
        "err_custom_1_hits": counts.counts[("ram", 0x2771)],
        "j_error_hits": counts.counts[("ram", 0x2793)],
        "error_display_hits": counts.counts[("page_07", 0x6A72)],
        "app_err_1": EXPECTED_MESSAGE[:-1].decode("ascii"),
        "result": "nonlocal-error-path-observed",
        "evidence_limit": "TilEm-x4;BootFree-page3F;no-physical-hardware",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=row, lineterminator="\n")
            writer.writeheader()
            writer.writerow(row)
    for key, value in row.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
