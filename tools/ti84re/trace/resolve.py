#!/usr/bin/env python3
"""Resolve a TilEm headless instruction trace to TI-84 Plus paged addresses.

TilEm's trace records only the *logical* 16-bit PC of each instruction. On the
TI-84 Plus the upper three 16 KiB windows are banked, so a logical address like
0x412c is ambiguous until the memory-mapping ports are known. This tool replays
the mapping writes found in the trace and rewrites every PC into:

  - a Ghidra address that matches this repo's overlay model
    (page 0 -> ram:XXXX, banked flash -> page_NN:XXXX, RAM -> ram:XXXX), and
  - a flat offset into tools/rom.bin (for flash), so you can z80dasm-check it.

The optional --io-ports filter decodes IN/OUT instructions at resolved
addresses. Immediate and register transfers include their byte values; TLMT v2
cannot recover memory bytes used by block-I/O instructions. The optional
--key-events output aligns injected press/release events with the same clocks
and resolved address state.

How banking is recovered (no operand bytes are stored in the trace):
  OUT (n),A  -> TilEm sets WZ = (A<<8) | n, so port = WZ & 0xFF, value = A = WZ>>8.
  OUT (C),r  -> port = C = BC & 0xFF, value = the source register.
  Port 4 bit 0 chooses paired or independent mapping. In paired mode, port 6
  selects the even/odd pages at 4000-7FFF and 8000-BFFF, and port 7 selects
  C000-FFFF. In independent mode, ports 6, 7, and 5 select those windows.
For ports 6/7, bit 7 selects RAM and low bits select the RAM page; otherwise
ports 0x0e/0x0f extend the Flash selector. Their high bits have no effect on
this 64-page TI-84 Plus target. Port 5 always selects RAM by low three bits.
Ports 0x27/0x28 force small ranges in the upper windows to RAM pages 0x80/0x81.

OUT (C),0 has a recoverable zero value. TLMT v2 does not record the memory byte
used by block-output instructions, so a block output to a mapping port makes
that port unknown until a later recoverable write.

TLMT v2 does not store the mapping at the first record. The resolver therefore
keeps banked addresses unresolved until the trace establishes enough state,
unless the initial port values are supplied explicitly. A full TI-84 Plus trace
that starts at TilEm's reset entry can use --initial-mapping ti84p-reset.

See tools/notes/dynamic-tracing.md for the end-to-end capture + analysis workflow.
"""
import argparse
import struct
import sys

from ti84re.hardware.memory_mapper import MAPPING_PORTS, Ti83PlusMapper

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

# ED-prefixed OUT (C),r -> which register supplies the value.
OUT_C_REG = {
    0xED41: "B", 0xED49: "C", 0xED51: "D", 0xED59: "E",
    0xED61: "H", 0xED69: "L", 0xED79: "A",
}
IN_C_REG = {
    0xED40: "B", 0xED48: "C", 0xED50: "D", 0xED58: "E",
    0xED60: "H", 0xED68: "L", 0xED78: "A",
}
BLOCK_OUT = {0xEDA3, 0xEDAB, 0xEDB3, 0xEDBB}
BLOCK_IN = {0xEDA2, 0xEDAA, 0xEDB2, 0xEDBA}
KEY_NAMES = {
    0x01: "DOWN", 0x02: "LEFT", 0x03: "RIGHT", 0x04: "UP",
    0x09: "ENTER", 0x0A: "ADD", 0x0B: "SUB", 0x0C: "MUL",
    0x0D: "DIV", 0x0E: "POWER", 0x0F: "CLEAR", 0x11: "NEG",
    0x12: "3", 0x13: "6", 0x14: "9", 0x15: "RPAREN",
    0x16: "TAN", 0x17: "VARS", 0x19: "DECPNT", 0x1A: "2",
    0x1B: "5", 0x1C: "8", 0x1D: "LPAREN", 0x1E: "COS",
    0x1F: "PRGM", 0x20: "STAT", 0x21: "0", 0x22: "1",
    0x23: "4", 0x24: "7", 0x25: "COMMA", 0x26: "SIN",
    0x27: "APPS", 0x28: "GRAPHVAR", 0x29: "ON", 0x2A: "STO",
    0x2B: "LN", 0x2C: "LOG", 0x2D: "SQUARE", 0x2E: "RECIP",
    0x2F: "MATH", 0x30: "ALPHA", 0x31: "GRAPH", 0x32: "TRACE",
    0x33: "ZOOM", 0x34: "WINDOW", 0x35: "Y=", 0x36: "2ND",
    0x37: "MODE", 0x38: "DEL",
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


class Banker(Ti83PlusMapper):
    """Track TI-84 Plus memory mapping by replaying OUT instructions."""

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
        elif op == 0xED71:  # undocumented OUT (C),0
            port, value = fields[IDX_BC] & 0xFF, 0
        elif op in BLOCK_OUT:
            # OUTI/OUTD/OTIR/OTDR use C as the port. Their memory-sourced
            # value is not present in TLMT v2, so invalidate affected state.
            port, value = fields[IDX_BC] & 0xFF, None

        if port not in MAPPING_PORTS:
            return None
        self.write_port(port, value)
        return port, value


def resolve_instruction(banker, fields):
    """Resolve an instruction under its pre-OUT mapping, then apply its OUT."""
    resolved = banker.resolve(fields[IDX_PC])
    switch = banker.feed(fields)
    return resolved, switch


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


def parse_byte(value):
    parsed = int(value, 0)
    if not 0 <= parsed <= 0xFF:
        raise argparse.ArgumentTypeError("value must be between 0 and 0xff")
    return parsed


def parse_port_set(value):
    """Parse comma-separated hexadecimal ports and inclusive ranges."""
    ports = set()
    try:
        for item in value.split(","):
            bounds = item.strip().split("-", 1)
            lo = int(bounds[0], 16)
            hi = int(bounds[1], 16) if len(bounds) > 1 else lo
            if not 0 <= lo <= hi <= 0xFF:
                raise ValueError
            ports.update(range(lo, hi + 1))
    except (ValueError, IndexError):
        raise argparse.ArgumentTypeError(
            "ports must be hexadecimal bytes or ranges, e.g. 10-13,2f"
        ) from None
    if not ports:
        raise argparse.ArgumentTypeError("at least one port is required")
    return ports


def parse_clock_range(value):
    """Parse a decimal or 0x-prefixed inclusive 32-bit clock range."""
    try:
        bounds = value.split("-", 1)
        lo = int(bounds[0], 0)
        hi = int(bounds[1], 0) if len(bounds) > 1 else lo
        if not 0 <= lo <= hi <= 0xFFFFFFFF:
            raise ValueError
    except (ValueError, IndexError):
        raise argparse.ArgumentTypeError(
            "clock must be a 32-bit value or inclusive range"
        ) from None
    return lo, hi


def clock_selected(clock, bounds):
    return bounds is None or bounds[0] <= clock <= bounds[1]


def register_byte(fields, register):
    """Return an 8-bit register from a post-instruction trace record."""
    pair, high = {
        "A": (IDX_AF, True), "B": (IDX_BC, True),
        "C": (IDX_BC, False), "D": (IDX_DE, True),
        "E": (IDX_DE, False), "H": (IDX_HL, True),
        "L": (IDX_HL, False),
    }[register]
    value = fields[pair]
    return (value >> 8) & 0xFF if high else value & 0xFF


def decode_io_event(fields):
    """Return (direction, port, value, form) for an I/O opcode, else None.

    Trace registers are captured after the instruction. WZ retains the
    immediate port for IN/OUT (n),A and the pre-IN BC value for IN r,(C).
    Block transfers do not retain the memory byte, so their value is None.
    """
    op = fields[IDX_OPCODE]
    if op == 0xD3:                       # OUT (n),A
        return "OUT", fields[IDX_WZ] & 0xFF, register_byte(fields, "A"), "(n),A"
    if op == 0xDB:                       # IN A,(n)
        return "IN", fields[IDX_WZ] & 0xFF, register_byte(fields, "A"), "A,(n)"
    if op in OUT_C_REG:
        reg = OUT_C_REG[op]
        return "OUT", fields[IDX_BC] & 0xFF, register_byte(fields, reg), f"(C),{reg}"
    if op == 0xED71:                     # undocumented OUT (C),0
        return "OUT", fields[IDX_BC] & 0xFF, 0, "(C),0"
    if op in IN_C_REG:
        reg = IN_C_REG[op]
        return "IN", fields[IDX_WZ] & 0xFF, register_byte(fields, reg), f"{reg},(C)"
    if op == 0xED70:                     # undocumented IN (C), flags only
        return "IN", fields[IDX_WZ] & 0xFF, None, "(C)"
    if op in BLOCK_OUT:
        return "OUT", fields[IDX_BC] & 0xFF, None, "block"
    if op in BLOCK_IN:
        return "IN", fields[IDX_BC] & 0xFF, None, "block"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace", help="TilEm trace file (capture with --trace-range all)")
    ap.add_argument("--names", metavar="FILE",
                    help="names.txt (space:addr\\tname) for symbol annotation")
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
    ap.add_argument("--initial-port0e", type=parse_byte, metavar="VALUE",
                    help="port 0x0e value at the first record (hex or decimal)")
    ap.add_argument("--initial-port0f", type=parse_byte, metavar="VALUE",
                    help="port 0x0f value at the first record (hex or decimal)")
    ap.add_argument("--initial-port27", type=parse_byte, metavar="VALUE",
                    help="port 0x27 value at the first record (hex or decimal)")
    ap.add_argument("--initial-port28", type=parse_byte, metavar="VALUE",
                    help="port 0x28 value at the first record (hex or decimal)")
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
                    help="print every mapper write (ports 4-7, 0x0e-0x0f, "
                         "and 0x27-0x28)")
    ap.add_argument("--io-ports", type=parse_port_set, metavar="PORTS",
                    help="print I/O events for hexadecimal ports/ranges, "
                         "e.g. 10-13,2f")
    ap.add_argument("--io-count", type=int, default=0, metavar="N",
                    help="stop printing I/O events after N matches (default: all)")
    ap.add_argument("--io-from", type=int, default=0, metavar="N",
                    help="skip the first N matching I/O events")
    ap.add_argument("--key-events", action="store_true",
                    help="print injected key press/release events with trace clocks")
    ap.add_argument("--event-clock", type=parse_clock_range,
                    metavar="START[-END]",
                    help="restrict --io-ports and --key-events to an inclusive "
                         "decimal or 0x-prefixed trace-clock range")
    ap.add_argument("--ring", action="store_true",
                    help="trace came from --trace-backtrace; enable mapping-"
                         "history safety warnings")
    ap.add_argument("--resync", action="store_true",
                    help="skip unknown bytes while looking for trace records")
    args = ap.parse_args()

    names = load_names(args.names) if args.names else None
    explicit_ports = (args.initial_port4, args.initial_port5,
                      args.initial_port6, args.initial_port7,
                      args.initial_port0e, args.initial_port0f,
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
                        initial_port0e=args.initial_port0e,
                        initial_port0f=args.initial_port0f,
                        initial_port27=args.initial_port27,
                        initial_port28=args.initial_port28)

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
        unresolved = 0
        io_matched = 0
        io_printed = 0
        first_instr = True
        for rtype, payload in iter_records(fp, resync=args.resync):
            if rtype == 0x03:
                pressed, key, clock, pc = payload
                if args.key_events and clock_selected(clock, args.event_clock):
                    space, gaddr, _flat, _page = banker.resolve(pc)
                    action = "pressed" if pressed else "released"
                    key_name = KEY_NAMES.get(key, "?")
                    print(f"{idx:>8} clk={clock:<10} "
                          f"{fmt_addr(space, gaddr):<14} "
                          f"KEY {action:<8} 0x{key:02x} {key_name}"
                          f"{name_for(names, space, gaddr)}")
                continue
            if rtype != 0x01:
                continue
            pc = payload[IDX_PC]
            if first_instr:
                first_instr = False
                if (args.initial_mapping == "ti84p-reset"
                        and pc != 0x8000):
                    print(f"warning: --initial-mapping ti84p-reset requires "
                          f"the first traced PC to be 0x8000; got 0x{pc:04x}. "
                          "Resolved pages may be wrong.", file=sys.stderr)
            (space, gaddr, flat, page), sw = resolve_instruction(banker, payload)
            if space == "page_??":
                unresolved += 1

            if args.page_switches and sw:
                port, val = sw
                if val is None:
                    print(f"{idx:>10}  block OUT (port 0x{port:02x})   "
                          "mapping state = unknown")
                elif port == 4:
                    mode = "paired" if val & 1 else "independent"
                    print(f"{idx:>10}  OUT (port 4) <- 0x{val:02x}   "
                          f"mapping mode = {mode}")
                elif port in (5, 6, 7):
                    page_kind, selected = banker.bank_page(port, val)
                    kind = (f"page_{selected:02X}" if page_kind == "flash"
                            else f"RAM/0x{selected:02x}")
                    print(f"{idx:>10}  OUT (port {port}) <- 0x{val:02x}   "
                          f"select = {kind}")
                elif port in (0x0E, 0x0F):
                    print(f"{idx:>10}  OUT (port 0x{port:02x}) <- "
                          f"0x{val:02x}   Flash selector high bits = "
                          f"0x{val & 3:02x}")
                else:
                    print(f"{idx:>10}  OUT (port 0x{port:02x}) <- "
                          f"0x{val:02x}   forced-RAM extent")

            ioe = decode_io_event(payload) if args.io_ports else None
            if (ioe and ioe[1] in args.io_ports
                    and clock_selected(payload[IDX_CLOCK], args.event_clock)):
                direction, port, value, form = ioe
                if io_matched >= args.io_from and \
                        (not args.io_count or io_printed < args.io_count):
                    arrow = "<-" if direction == "OUT" else "->"
                    value_s = "unknown" if value is None else f"0x{value:02x}"
                    print(f"{idx:>8} clk={payload[IDX_CLOCK]:<10} "
                          f"{fmt_addr(space, gaddr):<14} "
                          f"{direction:<3} (0x{port:02x}) {arrow} {value_s:<7} "
                          f"[{form}]{name_for(names, space, gaddr)}")
                    io_printed += 1
                io_matched += 1

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

        if unresolved:
            print(f"warning: {unresolved} instruction(s) have unresolved bank "
                  "mapping; paged coverage is incomplete. Supply the mapping "
                  "at the first record with --initial-mapping or "
                  "explicit initial-port values.", file=sys.stderr)
        if args.ring and not banker.mapping_complete():
            print("warning: ring/backtrace trace lacks enough page-switch "
                  "history for complete mapping recovery. Supply all mapping "
                  "ports at the oldest record with --initial-portN options.",
                  file=sys.stderr)

        def fmt_port(value):
            return "unknown" if value is None else f"0x{value:02x}"

        print(f"# {idx} instructions, {banker.switches} mapping writes, "
              f"{unresolved} unresolved; final port4={fmt_port(banker.port4)} "
              f"port5={fmt_port(banker.bank_c)} "
              f"port6={fmt_port(banker.bank_a)} "
              f"port7={fmt_port(banker.bank_b)} "
              f"port0e={fmt_port(banker.port0e)} "
              f"port0f={fmt_port(banker.port0f)} "
              f"port27={fmt_port(banker.port27)} "
              f"port28={fmt_port(banker.port28)}",
              file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, BrokenPipeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
