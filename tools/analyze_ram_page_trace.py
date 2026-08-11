#!/usr/bin/env python3
"""Summarize TilEm memory-write records for one physical RAM page.

Capture with ``tilem2 --trace TRACE --trace-range all``. The trace contains
logical write addresses, so this tool replays page-select OUT instructions and
maps each write back to the physical RAM page selected for that 16 KiB window.
TilEm emits writes before the instruction record that generated them; this tool
buffers each write until that following instruction record for PC attribution.
"""
import argparse
from collections import Counter, defaultdict
import sys

from hardware_trace import MemoryWriteAttributor, resolve_memory_target
from tilem_trace_resolve import (
    IDX_PC,
    Banker,
    fmt_addr,
    iter_records,
    parse_byte,
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
    kind, page, offset, _flat, _unresolved = resolve_memory_target(
        banker, logical
    )
    if kind != "ram" or page is None or offset is None:
        return None
    return page, offset, logical >> 14


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
                    help="skip unknown bytes while looking for trace records")
    ap.add_argument("--ring", action="store_true",
                    help="trace came from --trace-backtrace; enable mapping-"
                         "history safety warnings")
    ap.add_argument("--initial-mapping", choices=("unknown", "ti84p-reset"),
                    default="unknown",
                    help="mapping at the first record; ti84p-reset is valid only "
                         "when capture starts at the TI-84 Plus reset entry")
    ap.add_argument("--initial-port4", type=parse_byte, metavar="VALUE",
                    help="port 4 value at the first record (hex or decimal)")
    ap.add_argument("--initial-port5", type=parse_byte, metavar="VALUE",
                    help="port 5 value at the first record (hex or decimal)")
    ap.add_argument("--initial-port6", type=parse_byte, metavar="VALUE",
                    help="port 6 value at the first record (hex or decimal)")
    ap.add_argument("--initial-port7", type=parse_byte, metavar="VALUE",
                    help="port 7 value at the first record (hex or decimal)")
    ap.add_argument("--initial-port27", type=parse_byte, metavar="VALUE",
                    help="port 0x27 value at the first record (hex or decimal)")
    ap.add_argument("--initial-port28", type=parse_byte, metavar="VALUE",
                    help="port 0x28 value at the first record (hex or decimal)")
    args = ap.parse_args()

    explicit_ports = (args.initial_port4, args.initial_port5,
                      args.initial_port6, args.initial_port7,
                      args.initial_port27, args.initial_port28)
    if args.initial_mapping == "ti84p-reset":
        if any(value is not None for value in explicit_ports):
            ap.error("--initial-mapping ti84p-reset cannot be combined with "
                     "explicit initial-port values")
        banker = Banker.ti84p_reset()
    else:
        banker = Banker(initial_port4=args.initial_port4,
                        initial_port5=args.initial_port5,
                        initial_port6=args.initial_port6,
                        initial_port7=args.initial_port7,
                        initial_port27=args.initial_port27,
                        initial_port28=args.initial_port28)
    writes = defaultdict(lambda: {"count": 0, "first": None, "last": None,
                                  "values": Counter(), "pcs": Counter()})
    events = []
    matched = 0
    unresolved_writes = 0
    first_instr = True
    attributor = MemoryWriteAttributor(banker)

    with open(args.trace, "rb") as fp:
        hdr = read_header(fp)
        if hdr["range_start"] != 0 or hdr["range_end"] != 0xFFFF:
            print("warning: trace was not captured with --trace-range all",
                  file=sys.stderr)

        for rtype, payload in iter_records(fp, resync=args.resync):
            if rtype == 0x01 and first_instr:
                first_instr = False
                pc = payload[IDX_PC]
                if (args.initial_mapping == "ti84p-reset"
                        and pc != 0x8000):
                    print(f"warning: --initial-mapping ti84p-reset requires "
                          f"the first traced PC to be 0x8000; got 0x{pc:04x}. "
                          "Resolved pages may be wrong.", file=sys.stderr)

            for event in attributor.feed(rtype, payload):
                if event.unresolved:
                    unresolved_writes += 1
                    continue
                if (event.target_kind != "ram"
                        or event.target_page is None
                        or event.page_offset is None):
                    continue
                page = event.target_page
                offset = event.page_offset
                region = event.logical_address >> 14
                if page != args.page:
                    continue

                ent = writes[offset]
                ent["count"] += 1
                ent["first"] = (event.instruction_index if ent["first"] is None
                                else ent["first"])
                ent["last"] = event.instruction_index
                ent["values"][event.value] += 1
                ent["pcs"][(event.pc_space, event.pc_address)] += 1

                matched += 1
                if args.events and (args.limit == 0
                                    or len(events) < args.limit):
                    events.append((event, offset, region))

    print(f"RAM page 0x{args.page:02X} writes: {matched}")
    print(f"unique page addresses: {len(writes)}")
    if unresolved_writes:
        print(f"warning: skipped {unresolved_writes} write(s) with unresolved "
              "bank mapping; supply --initial-mapping or "
              "explicit initial-port values", file=sys.stderr)
    if attributor.pending:
        print(f"warning: {len(attributor.pending)} trailing write record(s) "
              "have no following instruction record", file=sys.stderr)
    if args.ring and not banker.mapping_complete():
        print("warning: ring/backtrace trace lacks enough page-switch history "
              "for complete mapping recovery", file=sys.stderr)
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
        for event, offset, region in events:
            pc_s = fmt_addr(event.pc_space, event.pc_address)
            print(f"{event.instruction_index:9d}  logical={event.logical_address:04X}  "
                  f"page_addr={fmt_page_addr(offset)}  value={event.value:02X}  "
                  f"window={region}  pc={pc_s}")


if __name__ == "__main__":
    main()
