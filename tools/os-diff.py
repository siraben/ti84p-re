#!/usr/bin/env python3
"""Diff two TI-84 Plus (Z80) OS versions structurally.

Pipeline (companion to tools/DumpBcalls.java):
  1. decode a TI OS upgrade file (`**TIFL**` + Intel-HEX, e.g. ti84plus_2.53.8Xu)
     into a flat, ROM-aligned image;
  2. compare its bcall jump table (page 0x3B) entry-by-entry against a raw ROM;
  3. diff operand-stripped *mnemonic* dumps produced by DumpBcalls.java on each
     version (relocation-invariant — a routine that only moved looks identical).

Why mnemonics: a positional byte diff of two OS builds is ~all "different" because
almost every routine *relocates* (a few bytes inserted early in a page shift the
rest, and CALL/JP operands get fixed up). Comparing the instruction-mnemonic
sequence ignores both relocation and operand fix-ups, so only genuine structural
changes (added/removed/different instructions) show up.

Usage:
  # 1. decode + align + bcall-table diff:
  python3 tools/os-diff.py decode  OLD.8Xu  rom.bin
  # 2. after running DumpBcalls.java on both build dirs (see the build recipe in
  #    the module docstring of DumpBcalls.java), diff the two mnem dumps:
  python3 tools/os-diff.py mnem  old/mnem.txt  new/mnem.txt

The OS upgrade file and ROM are copyrighted and gitignored; supply your own.
"""
import sys, re, collections

# .8Xu page numbering is logical; for the OS pages that carry bcall bodies the
# empirical map to physical ROM pages is: 0x00-0x07 -> same, 0x14-0x1D -> +0x20.
def rom_page(p):
    return p if p <= 0x07 else p + 0x20

def decode_8xu(path):
    data = open(path, "rb").read()
    i = data.index(b":")
    img = bytearray(0x100000)
    cur = 0
    for ln in data[i:].decode("latin1").splitlines():
        ln = ln.strip()
        if not ln.startswith(":"):
            continue
        h = ln[1:]
        if len(h) % 2 or re.search("[^0-9A-Fa-f]", h):
            continue
        b = bytes.fromhex(h)
        cnt, addr, typ = b[0], (b[1] << 8) | b[2], b[3]
        pl = b[4:4 + cnt]
        if typ == 2:
            cur = (pl[0] << 8) | pl[1]
        elif typ == 0:
            base = rom_page(cur) * 0x4000
            for k, by in enumerate(pl):
                img[base + ((addr + k) & 0x3FFF)] = by
    return bytes(img)

def bcall_table_diff(old_img, rom, table_page=0x3B):
    def ent(buf, idv):
        o = table_page * 0x4000 + (idv - 0x4000)
        return (buf[o] | buf[o + 1] << 8, buf[o + 2] & 0x3F)
    ids = range(0x4000, 0x8000, 3)
    same = moved = 0
    for idv in ids:
        if table_page * 0x4000 + (idv - 0x4000) + 3 > len(rom):
            break
        if ent(rom, idv) == ent(old_img, idv):
            same += 1
        else:
            moved += 1
    print(f"bcall table: {same} identical-target / {moved} relocated "
          f"({100*same/(same+moved):.0f}% at the same address)")

def mnem_diff(old_path, new_path):
    def load(p):
        d = {}
        for l in open(p):
            q = l.rstrip("\n").split("\t")
            if len(q) >= 3:
                d[q[0]] = (q[1], q[2])
        return d
    a, b = load(old_path), load(new_path)
    same = changed = skip = 0
    chg = []
    for idv in a:
        n0, m0 = a[idv]
        n1, m1 = b.get(idv, ("", "?missing"))
        if m0.startswith("?") or m1.startswith("?"):
            skip += 1
            continue
        if m0 == m1:
            same += 1
        else:
            changed += 1
            chg.append((n1 or n0, idv, len(m0.split()), len(m1.split())))
    print(f"comparable: {same+changed} | identical instruction sequence: {same} "
          f"({100*same/(same+changed):.1f}%) | differ: {changed} | skipped: {skip}")
    for nm, idv, c0, c1 in chg:
        print(f"  differ: {nm:<18} id={idv}  [{c0} -> {c1} instrs]  (verify: may be a boundary over-read)")

if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "decode":
        img = decode_8xu(sys.argv[2])
        rom = open(sys.argv[3], "rb").read()
        out = sys.argv[2] + ".aligned.bin"
        open(out, "wb").write(img)
        print(f"wrote {out}")
        bcall_table_diff(img, rom)
    elif len(sys.argv) >= 4 and sys.argv[1] == "mnem":
        mnem_diff(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        sys.exit(1)
