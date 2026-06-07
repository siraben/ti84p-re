#!/usr/bin/env python3
"""Summarize TilEm memory-write records for one physical RAM page.

Capture with ``tilem2 --trace TRACE --trace-range all``. The trace contains
logical write addresses, so this tool replays page-select OUT instructions and
maps each write back to the physical RAM page selected for that 16 KiB window.
"""
import argparse
from collections import Counter, defaultdict
import sys

from tilem_trace_resolve import (
    IDX_PC,
    Banker,
    fmt_addr,
    iter_records,
    read_header,
)


WINDOW_BASE = {
    1: 0x4000,
    2: 0x8000,
    3: 0xC000,
}


def parse_int(value):
    return int(value, 0)


def map_ram_write(banker, logical):
    region = logical >> 14
    if region == 0:
        return None
    if region == 1:
        kind, page = banker.bank_page(6, banker.bank_a)
    elif region == 2:
        kind, page = banker.bank_page(7, banker.bank_b)
    else:
        kind, page = banker.bank_page(5, banker.bank_c)
    if kind != "ram" or page is None:
        return None
    return page, logical - WINDOW_BASE[region], region


def ranges_for(offsets):
    if not offsets:
        return []
    ordered = sorted(offsets)
    ranges = []
    start = prev = ordered[0]
    for off in ordered[1:]:
        if off == prev + 1:
            prev = off
            continue
        ranges.append((start, prev))
        start = prev = off
    ranges.append((start, prev))
    return ranges


def fmt_page_addr(offset):
    return f"{0x4000 + offset:04X}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("trace", help="TilEm trace captured with --trace-range all")
    ap.add_argument("--page", type=parse_int, default=0x83,
                    help="physical RAM page to summarize (default: 0x83)")
    ap.add_argument("--events", action="store_true",
                    help="print every matching memory-write event")
    ap.add_argument("--limit", type=int, default=0,
                    help="maximum event rows to print with --events")
    ap.add_argument("--resync", action="store_true",
                    help="skip partial records in ring-buffer traces")
    args = ap.parse_args()

    banker = Banker()
    writes = defaultdict(lambda: {"count": 0, "first": None, "last": None,
                                  "values": Counter(), "pcs": Counter()})
    events = []
    instr_idx = 0
    last_pc = None
    last_resolved = None
    matched = 0

    with open(args.trace, "rb") as fp:
        hdr = read_header(fp)
        if hdr["range_start"] != 0 or hdr["range_end"] != 0xFFFF:
            print("warning: trace was not captured with --trace-range all",
                  file=sys.stderr)

        for rtype, payload in iter_records(fp, resync=args.resync):
            if rtype == 0x01:
                last_pc = payload[IDX_PC]
                banker.feed(payload)
                space, gaddr, _, _ = banker.resolve(last_pc)
                last_resolved = (space, gaddr)
                instr_idx += 1
                continue
            if rtype != 0x02:
                continue

            logical, value = payload
            mapped = map_ram_write(banker, logical)
            if mapped is None:
                continue
            page, offset, region = mapped
            if page != args.page:
                continue

            ent = writes[offset]
            ent["count"] += 1
            ent["first"] = instr_idx if ent["first"] is None else ent["first"]
            ent["last"] = instr_idx
            ent["values"][value] += 1
            if last_resolved is not None:
                ent["pcs"][last_resolved] += 1

            matched += 1
            if args.events and (args.limit == 0 or len(events) < args.limit):
                events.append((instr_idx, logical, value, offset, region,
                               last_pc, last_resolved))

    print(f"RAM page 0x{args.page:02X} writes: {matched}")
    print(f"unique page addresses: {len(writes)}")
    for start, end in ranges_for(writes):
        if start == end:
            print(f"range {fmt_page_addr(start)}")
        else:
            print(f"range {fmt_page_addr(start)}-{fmt_page_addr(end)}")

    if writes:
        print("\nTop write PCs:")
        pc_counts = Counter()
        for ent in writes.values():
            pc_counts.update(ent["pcs"])
        for (space, addr), count in pc_counts.most_common(12):
            print(f"{count:6d}  {fmt_addr(space, addr)}")

    if args.events:
        print("\nEvents:")
        for instr_idx, logical, value, offset, region, pc, resolved in events:
            pc_s = "unknown"
            if resolved is not None:
                pc_s = fmt_addr(*resolved)
            print(f"{instr_idx:9d}  logical={logical:04X}  "
                  f"page_addr={fmt_page_addr(offset)}  value={value:02X}  "
                  f"window={region}  pc={pc_s}")


if __name__ == "__main__":
    main()
