#!/usr/bin/env python3
"""Reduce a one-sided community link-wait TLMT trace to one CSV row."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import sys

from ti84re.trace.resolve import (
    IDX_CLOCK,
    IDX_PC,
    decode_io_event,
    iter_records,
    read_header,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--failed-release-trace", type=Path)
    parser.add_argument("--release-file", type=Path, action="append", default=[])
    parser.add_argument("--release-output", type=Path)
    args = parser.parse_args()

    entered = False
    returned = False
    start_clock = end_clock = None
    instructions = 0
    events: dict[tuple[str, int, int], int] = {}
    first_port_zero_read = None

    with args.trace.open("rb") as stream:
        header = read_header(stream)
        if header["version"] != 2:
            raise ValueError(f"expected TLMT v2, got {header['version']}")
        for record_type, payload in iter_records(stream):
            if record_type != 1:
                continue
            pc = payload[IDX_PC]
            if not entered and pc == 0x9D95:
                entered = True
                start_clock = payload[IDX_CLOCK]
            if not entered:
                continue
            instructions += 1
            event = decode_io_event(payload)
            if event is not None and event[1] in (0, 1):
                direction, port, value, _form = event
                if value is not None:
                    events[(direction, port, value)] = (
                        events.get((direction, port, value), 0) + 1
                    )
                    if direction == "IN" and port == 0 and first_port_zero_read is None:
                        first_port_zero_read = value
            if pc == 0x57D1:
                returned = True
                end_clock = payload[IDX_CLOCK]
                break

    if not entered:
        raise ValueError("trace never entered the payload at ram:9D95")
    if not returned:
        raise ValueError("trace did not return through _ExecutePrgm cleanup at 07:57D1")
    if first_port_zero_read != 3:
        raise ValueError(f"expected idle port-00 read 03, got {first_port_zero_read!r}")
    if events.get(("OUT", 0, 0xD1), 0) < 1:
        raise ValueError("trace did not write D1 to port 00")
    if events.get(("OUT", 1, 0xBF), 0) < 1:
        raise ValueError("trace did not select the MODE key row")
    if events.get(("IN", 1, 0xBF), 0) < 1:
        raise ValueError("trace did not observe MODE pressed")

    row = {
        "case": "linktutorial-initial-wait-no-peer",
        "platform": "TilEm-x4-ti84p",
        "rom_sha256": sha256(args.rom),
        "trace_sha256": sha256(args.trace),
        "archive_sha256": sha256(args.archive),
        "source_sha256": sha256(args.source),
        "entry": "ram:9D95",
        "cleanup": "07:57D1",
        "first_port00_read": f"{first_port_zero_read:02X}",
        "port00_out_D1_count": events[("OUT", 0, 0xD1)],
        "port01_out_BF_count": events[("OUT", 1, 0xBF)],
        "port01_in_BF_count": events[("IN", 1, 0xBF)],
        "instructions": instructions,
        "start_clock": start_clock,
        "end_clock": end_clock,
        "result": "pass",
        "evidence_limit": (
            "transcribed initial wait only; no peer; emulator, not physical hardware; "
            "release calculator files are TI-83 containers"
        ),
    }
    fields = list(row)
    target = args.output.open("w", newline="") if args.output else sys.stdout
    try:
        writer = csv.DictWriter(target, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
    finally:
        if args.output:
            target.close()

    if args.failed_release_trace is not None:
        if len(args.release_file) != 2 or args.release_output is None:
            raise ValueError(
                "failed-release analysis requires two --release-file values and "
                "--release-output"
            )
        release_hits = {0x2729: 0, 0x57B4: 0, 0x9D95: 0}
        with args.failed_release_trace.open("rb") as stream:
            read_header(stream)
            for record_type, payload in iter_records(stream):
                if record_type == 1 and payload[IDX_PC] in release_hits:
                    release_hits[payload[IDX_PC]] += 1
        if release_hits != {0x2729: 1, 0x57B4: 0, 0x9D95: 0}:
            raise ValueError(f"unexpected failed-release path: {release_hits}")
        signatures = [path.read_bytes()[:11].decode("ascii") for path in args.release_file]
        if signatures != ["**TI83**\x1a\n\x00", "**TI83**\x1a\n\x00"]:
            raise ValueError(f"unexpected release signatures: {signatures!r}")
        release_row = {
            "case": "linktutorial-shipped-files-on-ti84p",
            "platform": "TilEm-x4-ti84p",
            "rom_sha256": sha256(args.rom),
            "trace_sha256": sha256(args.failed_release_trace),
            "file_one_sha256": sha256(args.release_file[0]),
            "file_two_sha256": sha256(args.release_file[1]),
            "file_one_signature": "2A2A544938332A2A1A0A00",
            "file_two_signature": "2A2A544938332A2A1A0A00",
            "err_invalid_hits": release_hits[0x2729],
            "execute_handoff_hits": release_hits[0x57B4],
            "payload_entry_hits": release_hits[0x9D95],
            "result": "rejected",
            "evidence_limit": (
                "headless transfer plus Asm wrapper; rejection is emulator-only; "
                "does not test a source-built TI-83+ edition"
            ),
        }
        with args.release_output.open("w", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=list(release_row), lineterminator="\n"
            )
            writer.writeheader()
            writer.writerow(release_row)


if __name__ == "__main__":
    main()
