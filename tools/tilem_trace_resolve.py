#!/usr/bin/env python3
"""Resolve a TilEm headless instruction trace to TI-84 Plus paged addresses.

TilEm's trace records only the *logical* 16-bit PC of each instruction. On the
TI-84 Plus the two middle 16 KiB windows are banked flash pages, so a logical
address like 0x412c is ambiguous until you know which page port 6 / port 7 had
selected at that moment. This tool replays the banking writes found in the trace
and rewrites every PC into:

  - a Ghidra address that matches this repo's overlay model
    (page 0 -> ram:XXXX, banked flash -> page_NN:XXXX, RAM -> ram:XXXX), and
  - a flat offset into tools/rom.bin (for flash), so you can z80dasm-check it.

How banking is recovered (no operand bytes are stored in the trace):
  OUT (n),A  -> TilEm sets WZ = (A<<8) | n, so port = WZ & 0xFF, value = A = WZ>>8.
  OUT (C),r  -> port = C = BC & 0xFF, value = the source register.
  Port 5 selects the C000-FFFF RAM window (bank C); port 6 selects the
  4000-7FFF window (bank A); port 7 selects 8000-BFFF (bank B).
For ports 6/7, bit 7 selects RAM and low bits select the RAM page; otherwise
the low six bits select flash. Port 5 always selects RAM by low three bits.

See tools/dynamic-tracing.md for the end-to-end capture + analysis workflow.
"""
import argparse
import struct
import sys

MAGIC = b"TLMT"
HEADER_FMT = "<4sHHIII"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

INSTR_FMT = "<III" + "H" * 15 + "BBBBB"
INSTR_SIZE = struct.calcsize(INSTR_FMT)
MEM_WRITE_SIZE = struct.calcsize("<IB")
KEY_EVENT_SIZE = struct.calcsize("<BBIH")

# Indices into the unpacked instruction record (see headless/trace.c).
IDX_PC, IDX_OPCODE, IDX_CLOCK = 0, 1, 2
IDX_AF, IDX_BC, IDX_DE, IDX_HL = 3, 4, 5, 6
IDX_IX, IDX_IY, IDX_SP, IDX_PC_REG = 7, 8, 9, 10
IDX_WZ = 12

PAGE_SIZE = 0x4000
N_FLASH_PAGES = 64  # TI-84 Plus: 1 MiB flash. 84+SE would be 128; override if needed.

# ED-prefixed OUT (C),r -> which register supplies the value.
OUT_C_REG = {
    0xED41: "B", 0xED49: "C", 0xED51: "D", 0xED59: "E",
    0xED61: "H", 0xED69: "L", 0xED79: "A",
}


def read_header(fp):
    data = fp.read(HEADER_SIZE)
    if len(data) != HEADER_SIZE:
        raise ValueError("short header")
    magic, version, flags, rstart, rend, init_size = struct.unpack(HEADER_FMT, data)
    if magic != MAGIC:
        raise ValueError("bad magic (not a TilEm trace)")
    init = fp.read(init_size)
    if len(init) != init_size:
        raise ValueError("short init snapshot")
    return {"version": version, "flags": flags, "range_start": rstart,
            "range_end": rend, "init_size": init_size, "init": init}


def iter_records(fp, resync=False):
    while True:
        typ = fp.read(1)
        if not typ:
            return
        t = typ[0]
        if t == 0x01:
            payload = fp.read(INSTR_SIZE)
            if len(payload) != INSTR_SIZE:
                if resync:
                    return
                raise ValueError("short instruction record")
            yield 0x01, struct.unpack(INSTR_FMT, payload)
        elif t == 0x02:
            payload = fp.read(MEM_WRITE_SIZE)
            if len(payload) != MEM_WRITE_SIZE:
                if resync:
                    return
                raise ValueError("short mem-write record")
            yield 0x02, struct.unpack("<IB", payload)
        elif t == 0x03:
            payload = fp.read(KEY_EVENT_SIZE)
            if len(payload) != KEY_EVENT_SIZE:
                if resync:
                    return
                raise ValueError("short key-event record")
            yield 0x03, struct.unpack("<BBIH", payload)
        elif resync:
            continue
        else:
            raise ValueError(f"unknown record type {t}")


class Banker:
    """Tracks port 5 / port 6 / port 7 page selection by replaying OUT instructions."""

    def __init__(self, flash_pages=N_FLASH_PAGES):
        self.bank_c = None  # port 5 -> C000-FFFF
        self.bank_a = None  # port 6 -> 4000-7FFF
        self.bank_b = None  # port 7 -> 8000-BFFF
        self.flash_pages = flash_pages
        self.switches = 0

    def feed(self, fields):
        """Apply this instruction's effect on banking; return (port, value) or None."""
        op = fields[IDX_OPCODE]
        low = op & 0xFF
        port = value = None
        if (op & 0xFFFF0000) == 0 and (op & 0xFF00) == 0 and low == 0xD3:
            # OUT (n),A : WZ = (A<<8)|n
            wz = fields[IDX_WZ]
            port, value = wz & 0xFF, (wz >> 8) & 0xFF
        elif (op & 0xFFFF) in OUT_C_REG and (op & 0xFFFF0000) == 0:
            reg = OUT_C_REG[op & 0xFFFF]
            port = fields[IDX_BC] & 0xFF
            value = {
                "A": fields[IDX_AF] >> 8, "B": fields[IDX_BC] >> 8,
                "C": fields[IDX_BC] & 0xFF, "D": fields[IDX_DE] >> 8,
                "E": fields[IDX_DE] & 0xFF, "H": fields[IDX_HL] >> 8,
                "L": fields[IDX_HL] & 0xFF,
            }[reg]
        if port == 5:
            self.bank_c, self.switches = value, self.switches + 1
            return (5, value)
        if port == 6:
            self.bank_a, self.switches = value, self.switches + 1
            return (6, value)
        if port == 7:
            self.bank_b, self.switches = value, self.switches + 1
            return (7, value)
        return None

    def is_flash(self, page):
        return page is not None and 0 <= page < self.flash_pages

    def bank_page(self, port, value):
        if value is None:
            return None, None
        if port == 5:
            return "ram", 0x80 | (value & 0x07)
        if value & 0x80:
            return "ram", 0x80 | (value & 0x07)
        return "flash", value & 0x3F

    def resolve(self, logical):
        """Map a logical PC to (space, ghidra_addr, flat_rom_off_or_None, page_or_None)."""
        region = logical >> 14
        off = logical & 0x3FFF
        if region == 0:                       # 0000-3FFF: fixed flash page 0
            return ("ram", logical, logical, 0)
        if region == 3:                       # C000-FFFF: high RAM window
            return ("ram", logical, None, None)
        raw = self.bank_a if region == 1 else self.bank_b
        kind, page = self.bank_page(6 if region == 1 else 7, raw)
        if page is None:
            return ("page_??", PAGE_SIZE + off, None, None)
        if kind == "flash":
            return (f"page_{page:02X}", PAGE_SIZE + off, page * PAGE_SIZE + off, page)
        return ("ram", logical, None, None)    # banked RAM (e.g. 84+ RAM mode)


def fmt_addr(space, addr):
    return f"{space}:{addr:04x}"


def load_names(path):
    """Load names.txt: '<space>:<addr_hex>\\t<name>' -> {(space, addr): name}."""
    names = {}
    with open(path) as fp:
        for line in fp:
            line = line.rstrip("\n")
            if not line or line.lstrip().startswith("#"):
                continue
            loc, _, name = line.partition("\t")
            name = name.strip()
            space, _, addr = loc.partition(":")
            if not name or not addr:
                continue
            try:
                names[(space.strip(), int(addr, 16))] = name
            except ValueError:
                continue
    return names


def name_for(names, space, addr):
    if names is None:
        return ""
    n = names.get((space, addr))
    return f"  {n}" if n else ""


def build_func_index(names):
    """From {(space,addr): name} build {space: (sorted_addrs, names)} for
    nearest-preceding (containing-function) lookup."""
    import bisect  # noqa: F401 (used by enclosing_func)
    by_space = {}
    for (space, addr), name in names.items():
        by_space.setdefault(space, []).append((addr, name))
    for space in by_space:
        by_space[space].sort()
    return {space: ([a for a, _ in lst], [n for _, n in lst])
            for space, lst in by_space.items()}


def enclosing_func(func_index, space, addr):
    """Nearest-preceding (addr, name) in `space`, or None."""
    import bisect
    idx = func_index.get(space)
    if not idx:
        return None
    addrs, fnames = idx
    i = bisect.bisect_right(addrs, addr) - 1
    return (addrs[i], fnames[i]) if i >= 0 else None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace", help="TilEm trace file (capture with --trace-range all)")
    ap.add_argument("--names", metavar="FILE",
                    help="names.txt (space:addr\\tname) for symbol annotation")
    ap.add_argument("--flash-pages", type=int, default=N_FLASH_PAGES,
                    help="flash page count (64 for 84+, 128 for 84+SE)")
    ap.add_argument("--print", dest="print_count", type=int, default=0,
                    help="print N resolved instructions (honors --only-space / "
                         "--only-addr / --print-from filters)")
    ap.add_argument("--print-from", dest="print_from", type=int, default=0,
                    help="skip the first N matching instructions before printing "
                         "(window into a long trace; use with --print)")
    ap.add_argument("--only-addr", metavar="LO[-HI]",
                    help="restrict --print to a logical-address window in the "
                         "selected space, hex, e.g. 6efd-6ff0 (walk one routine)")
    ap.add_argument("--coverage", action="store_true",
                    help="list distinct executed addresses with hit counts")
    ap.add_argument("--funcs", action="store_true",
                    help="function-level coverage: roll hits up to the nearest-"
                         "preceding name (needs --names)")
    ap.add_argument("--only-space", metavar="SPACE",
                    help="restrict --coverage/--funcs/--print to one space, "
                         "e.g. page_39")
    ap.add_argument("--sort", choices=("count", "addr", "first"), default="first",
                    help="coverage sort order (default: first-seen)")
    ap.add_argument("--page-switches", action="store_true",
                    help="print every port 5 / port 6 / port 7 bank switch")
    ap.add_argument("--resync", action="store_true",
                    help="skip partial records (use for --trace-backtrace rings)")
    args = ap.parse_args()

    names = load_names(args.names) if args.names else None
    banker = Banker(flash_pages=args.flash_pages)

    addr_lo = addr_hi = None
    if args.only_addr:
        parts = args.only_addr.split("-", 1)
        addr_lo = int(parts[0], 16)
        addr_hi = int(parts[1], 16) if len(parts) > 1 else addr_lo

    with open(args.trace, "rb") as fp:
        hdr = read_header(fp)
        print(f"version={hdr['version']} "
              f"range=0x{hdr['range_start']:04x}-0x{hdr['range_end']:04x} "
              f"flags=0x{hdr['flags']:04x}", file=sys.stderr)
        if hdr["range_start"] != 0 or hdr["range_end"] != 0xFFFF:
            print("warning: trace was not captured with --trace-range all; "
                  "banked/page-0 PCs may be missing.", file=sys.stderr)

        cov = {}            # (space, addr) -> [count, first_idx, flat_off]
        idx = 0
        printed = 0
        matched = 0         # instructions passing the --print filters (pre-skip)
        for rtype, payload in iter_records(fp, resync=args.resync):
            if rtype != 0x01:
                continue
            pc = payload[IDX_PC]
            sw = banker.feed(payload)
            space, gaddr, flat, page = banker.resolve(pc)

            if args.page_switches and sw:
                port, val = sw
                window = {5: "C000-FFFF", 6: "4000-7FFF", 7: "8000-BFFF"}[port]
                page_kind, page = banker.bank_page(port, val)
                kind = f"page_{page:02X}" if page_kind == "flash" else f"RAM/0x{page:02x}"
                print(f"{idx:>10}  OUT (port {port}) <- 0x{val:02x}   "
                      f"{window} = {kind}")

            if (args.coverage or args.funcs) and \
                    (not args.only_space or space == args.only_space):
                key = (space, gaddr)
                ent = cov.get(key)
                if ent is None:
                    cov[key] = [1, idx, flat]
                else:
                    ent[0] += 1

            if args.print_count and printed < args.print_count and \
                    (not args.only_space or space == args.only_space) and \
                    (addr_lo is None or addr_lo <= gaddr <= addr_hi):
                if matched < args.print_from:
                    matched += 1
                    idx += 1
                    continue
                matched += 1
                op = payload[IDX_OPCODE]
                flat_s = f" rom=0x{flat:06x}" if flat is not None else ""
                print(f"{idx:>8} clk={payload[IDX_CLOCK]:<10} "
                      f"{fmt_addr(space, gaddr):<14} op=0x{op:08x} "
                      f"AF={payload[IDX_AF]:04x} BC={payload[IDX_BC]:04x} "
                      f"DE={payload[IDX_DE]:04x} HL={payload[IDX_HL]:04x} "
                      f"SP={payload[IDX_SP]:04x}{flat_s}"
                      f"{name_for(names, space, gaddr)}")
                printed += 1

            idx += 1

        if args.funcs:
            if names is None:
                print("error: --funcs needs --names", file=sys.stderr)
                sys.exit(2)
            findex = build_func_index(names)
            agg = {}  # (space, base, name) -> [hits, first_idx]
            for (space, gaddr), (count, first, _flat) in cov.items():
                fn = enclosing_func(findex, space, gaddr)
                base, fname = fn if fn else (gaddr, "?")
                k = (space, base, fname)
                e = agg.get(k)
                if e is None:
                    agg[k] = [count, first]
                else:
                    e[0] += count
                    e[1] = min(e[1], first)
            items = sorted(agg.items(),
                           key=lambda kv: (-kv[1][0] if args.sort == "count"
                                           else kv[1][1] if args.sort == "first"
                                           else (kv[0][0], kv[0][1])))
            print(f"# {len(items)} functions over {idx} instructions"
                  + (f" (space {args.only_space})" if args.only_space else ""),
                  file=sys.stderr)
            for (space, base, fname), (hits, first) in items:
                print(f"{hits:>10}  {fmt_addr(space, base):<14} {fname}")

        if args.coverage:
            items = list(cov.items())
            if args.sort == "count":
                items.sort(key=lambda kv: -kv[1][0])
            elif args.sort == "addr":
                items.sort(key=lambda kv: (kv[0][0], kv[0][1]))
            else:
                items.sort(key=lambda kv: kv[1][1])
            print(f"# {len(items)} distinct addresses over {idx} instructions",
                  file=sys.stderr)
            for (space, gaddr), (count, first, flat) in items:
                flat_s = f"  rom=0x{flat:06x}" if flat is not None else ""
                print(f"{count:>8}  {fmt_addr(space, gaddr):<14}{flat_s}"
                      f"{name_for(names, space, gaddr)}")

        print(f"# {idx} instructions, {banker.switches} bank switches; "
              f"final bankC(port5)={banker.bank_c} "
              f"bankA(port6)={banker.bank_a} bankB(port7)={banker.bank_b}",
              file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, BrokenPipeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
