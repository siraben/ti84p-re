#!/usr/bin/env python3
"""Validate safe manual-bcall targets and emit one evidence row."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from hashlib import sha256
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardware_trace import count_resolved_trace_points  # noqa: E402
from tilem_trace_resolve import IDX_PC, iter_records, read_header  # noqa: E402


POINTS = {
    ("ram", 0x0CC3): "_lcd_busy",
    ("page_06", 0x42E5): "_bufInsert",
    ("ram", 0x222E): "_BufClear",
    ("ram", 0x1837): "_NZIf83Plus",
}
CALL_SITES = (0x9D9F, 0x9DA7, 0x9DB2, 0x9DBA, 0x9DC4)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def raw_pc_counts(path: Path, wanted: tuple[int, ...]) -> Counter[int]:
    counts: Counter[int] = Counter()
    with path.open("rb") as stream:
        read_header(stream)
        for record_type, record in iter_records(stream):
            if record_type == 0x01 and record[IDX_PC] in wanted:
                counts[record[IDX_PC]] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--rom", type=Path, default=Path("tools/rom.bin"))
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--wrapper", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    counts = count_resolved_trace_points(
        args.trace, set(POINTS), initial_mapping="ti84p-reset"
    )
    missing = [name for point, name in POINTS.items() if not counts.counts.get(point)]
    if missing:
        raise SystemExit(f"trace misses required points: {', '.join(missing)}")
    call_counts = raw_pc_counts(args.trace, CALL_SITES)
    if any(call_counts[address] != 1 for address in CALL_SITES):
        raise SystemExit(f"fixture call-site counts differ: {call_counts}")

    snapshot = args.snapshot.read_bytes()
    if len(snapshot) < 0x8000:
        raise SystemExit("logical RAM snapshot is truncated")
    marker = snapshot[0x1872:0x187C]
    if marker[8:] != bytes((0x0D, 0x60)):
        raise SystemExit(f"final return marker differs: {marker.hex()}")
    nz_flags = marker[6]
    if not nz_flags & 0x40:
        raise SystemExit(f"_NZIf83Plus returned NZ on TI-84 Plus: F=0x{nz_flags:02X}")
    if marker[7] != 0xA5:
        raise SystemExit(f"_NZIf83Plus did not preserve A: {marker.hex()}")

    row = {
        "scenario": "community-symbolic-bcalls-safe",
        "model": "ti84p",
        "os_version": "2.55MP",
        "rom_sha256": digest(args.rom),
        "emulator_sha256": digest(args.emulator),
        "payload_sha256": digest(args.payload),
        "wrapper_sha256": digest(args.wrapper),
        "trace_sha256": digest(args.trace),
        "snapshot_sha256": digest(args.snapshot),
        "instructions": counts.processed_instructions,
        "lcd_busy_hits": counts.counts[("ram", 0x0CC3)],
        "buf_insert_hits": counts.counts[("page_06", 0x42E5)],
        "buf_clear_hits": counts.counts[("ram", 0x222E)],
        "nz_if_83_plus_hits": counts.counts[("ram", 0x1837)],
        "fixture_call_sites": ";".join(
            f"0x{address:04X}={call_counts[address]}" for address in CALL_SITES
        ),
        "nz_if_83_plus_a": "0xA5",
        "nz_if_83_plus_f": f"0x{nz_flags:02X}",
        "result": "all-four-returned;NZIf83Plus-returned-Z",
        "evidence_limit": (
            "source-built caller; controlled home-screen edit buffer; "
            "TilEm; no physical hardware"
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
