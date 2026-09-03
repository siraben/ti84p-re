#!/usr/bin/env python3
"""Measure writes to advertised TI-OS scratch buffers in a TilEm trace.

Capture the trace with ``tilem2 --trace TRACE --trace-range all``. The trace
contains logical write addresses. This analyzer replays ports 5, 6, and 7 and
only counts writes made while physical RAM page 0x81 is visible. A zero count
means that the scenario did not write the range; it is not a safety proof.
"""

import argparse
from collections import Counter
import csv
import hashlib
import json
import sys

from ti84re.trace.resolve import IDX_PC, Banker, fmt_addr, iter_records, read_header


BUFFERS = (
    ("OP1-OP6", 0x8478, 0x84B9),
    ("iMathPtr1-iMathPtr5", 0x84D3, 0x84DC),
    ("textShadow", 0x8508, 0x8587),
    ("saveSScreen", 0x86EC, 0x89EB),
    ("statVars", 0x8A3A, 0x8C4C),
    ("table_solver_workspace", 0x91DC, 0x9301),
    ("plotSScreen", 0x9340, 0x963F),
    ("appBackUpScreen", 0x9872, 0x9B71),
)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def map_page81_write(banker, logical):
    """Return the canonical page-0x81 address, or None for another page."""
    region = logical >> 14
    if region == 1:
        kind, page = banker.bank_page(6, banker.bank_a)
        offset = logical - 0x4000
    elif region == 2:
        kind, page = banker.bank_page(7, banker.bank_b)
        offset = logical - 0x8000
    elif region == 3:
        kind, page = banker.bank_page(5, banker.bank_c)
        offset = logical - 0xC000
    else:
        return None
    if kind != "ram" or page != 0x81:
        return None
    return 0x8000 + offset


def find_buffer(address):
    for name, start, end in BUFFERS:
        if start <= address <= end:
            return name, start, end
    return None


def compact_ranges(addresses):
    if not addresses:
        return []
    result = []
    start = previous = min(addresses)
    for address in sorted(addresses)[1:]:
        if address == previous + 1:
            previous = address
            continue
        result.append([start, previous])
        start = previous = address
    result.append([start, previous])
    return result


def analyze(path, resync=False, initial_port5=None, initial_port6=None,
            initial_port7=None):
    banker = Banker()
    banker.bank_c = initial_port5
    banker.bank_a = initial_port6
    banker.bank_b = initial_port7
    stats = {}
    for name, start, end in BUFFERS:
        stats[name] = {
            "name": name,
            "start": start,
            "end": end,
            "size": end - start + 1,
            "writes": 0,
            "addresses": set(),
            "values": Counter(),
            "pcs": Counter(),
            "first_instruction": None,
            "last_instruction": None,
        }

    instruction = 0
    pending_write_rows = []
    with open(path, "rb") as fp:
        header = read_header(fp)
        for record_type, payload in iter_records(fp, resync=resync):
            if record_type == 0x01:
                # TilEm reports a memory write while the instruction executes,
                # then emits that instruction's record. Attribute pending writes
                # to this record before applying an OUT instruction's new map.
                resolved = banker.resolve(payload[IDX_PC])[:2]
                for pending_row in pending_write_rows:
                    pending_row["pcs"][resolved] += 1
                pending_write_rows.clear()
                banker.feed(payload)
                instruction += 1
                continue
            if record_type != 0x02:
                continue
            logical, value = payload
            address = map_page81_write(banker, logical)
            if address is None:
                continue
            matched = find_buffer(address)
            if matched is None:
                continue
            name, _, _ = matched
            row = stats[name]
            row["writes"] += 1
            row["addresses"].add(address)
            row["values"][value] += 1
            pending_write_rows.append(row)
            if row["first_instruction"] is None:
                row["first_instruction"] = instruction
            row["last_instruction"] = instruction

    rows = []
    for name, _, _ in BUFFERS:
        raw = stats[name]
        top_pcs = [
            {"pc": fmt_addr(space, address), "writes": count}
            for (space, address), count in raw["pcs"].most_common(12)
        ]
        rows.append({
            "name": raw["name"],
            "start": f"0x{raw['start']:04X}",
            "end": f"0x{raw['end']:04X}",
            "size": raw["size"],
            "writes": raw["writes"],
            "touched_bytes": len(raw["addresses"]),
            "coverage_percent": round(100 * len(raw["addresses"]) / raw["size"], 2),
            "touched_ranges": [
                f"0x{start:04X}" if start == end
                else f"0x{start:04X}-0x{end:04X}"
                for start, end in compact_ranges(raw["addresses"])
            ],
            "first_instruction": raw["first_instruction"],
            "last_instruction": raw["last_instruction"],
            "top_write_pcs": top_pcs,
        })
    return header, instruction, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", help="TilEm trace captured with --trace-range all")
    parser.add_argument("--format", choices=("text", "json", "csv"), default="text")
    parser.add_argument("--scenario", default="unspecified")
    parser.add_argument("--model", default="unspecified")
    parser.add_argument("--asic", default="unspecified")
    parser.add_argument("--os-version", default="unspecified")
    parser.add_argument("--launch-method", default="unspecified")
    parser.add_argument("--initial-port-5", type=lambda value: int(value, 0),
                        help="port 5 selector at trace start, for example 0")
    parser.add_argument("--initial-port-6", type=lambda value: int(value, 0),
                        help="port 6 selector at trace start")
    parser.add_argument("--initial-port-7", type=lambda value: int(value, 0),
                        help="port 7 selector at trace start, for example 0x81")
    parser.add_argument("--resync", action="store_true",
                        help="accept a trace ending in a partial ring-buffer record")
    args = parser.parse_args()

    header, instructions, rows = analyze(
        args.trace, args.resync, args.initial_port_5, args.initial_port_6,
        args.initial_port_7,
    )
    metadata = {
        "scenario": args.scenario,
        "model": args.model,
        "asic": args.asic,
        "os_version": args.os_version,
        "launch_method": args.launch_method,
        "trace": args.trace,
        "trace_sha256": file_sha256(args.trace),
        "trace_version": header["version"],
        "trace_range": f"0x{header['range_start']:04X}-0x{header['range_end']:04X}",
        "instructions": instructions,
        "initial_ports": {
            "5": args.initial_port_5,
            "6": args.initial_port_6,
            "7": args.initial_port_7,
        },
        "warning": "zero writes means not observed in this scenario, not safe",
    }

    if header["range_start"] != 0 or header["range_end"] != 0xFFFF:
        print("warning: trace was not captured with --trace-range all", file=sys.stderr)

    if args.format == "json":
        json.dump({"metadata": metadata, "buffers": rows}, sys.stdout, indent=2)
        print()
        return
    if args.format == "csv":
        fields = ("scenario", "model", "asic", "os_version", "launch_method",
                  "trace_sha256",
                  "name", "start", "end", "size", "writes", "touched_bytes",
                  "coverage_percent", "touched_ranges", "top_write_pcs")
        writer = csv.DictWriter(sys.stdout, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            flat = {key: metadata[key] for key in fields[:6]}
            flat.update({key: row[key] for key in fields[6:-2]})
            flat["touched_ranges"] = ";".join(row["touched_ranges"])
            flat["top_write_pcs"] = ";".join(
                f"{item['pc']}:{item['writes']}" for item in row["top_write_pcs"]
            )
            writer.writerow(flat)
        return

    print(f"Scenario: {args.scenario}")
    print(f"Model/ASIC/OS: {args.model} / {args.asic} / {args.os_version}")
    print(f"Launch method: {args.launch_method}")
    print(f"Instructions: {instructions}")
    for row in rows:
        ranges = ", ".join(row["touched_ranges"]) or "none"
        print(f"{row['name']:24s} writes={row['writes']:8d} "
              f"bytes={row['touched_bytes']:4d}/{row['size']:4d} ranges={ranges}")
        for item in row["top_write_pcs"][:3]:
            print(f"  {item['writes']:8d}  {item['pc']}")
    print("Warning: zero writes means not observed in this scenario, not safe.")


if __name__ == "__main__":
    main()
