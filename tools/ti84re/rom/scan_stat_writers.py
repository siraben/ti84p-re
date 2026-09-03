#!/usr/bin/env python3
"""Scan ROM bytes for opcode-shaped references to the inferential-stat window.

Patterns covered: LD (nn),reg / LD reg,(nn) / LD rp,nn immediates that load a
pointer into PStat..SStat or anovaf_vars. This is a reconnaissance scan rather
than an instruction-boundary analysis: candidates can occur inside operands or
data and require disassembly before they count as code references.
"""
from collections import defaultdict

ROM = "tools/rom.bin"
LO, HI = 0x8B5A, 0x8C37          # PStat .. E_MS end

# (prefix bytes, name) -- operand word follows at offset len(prefix)
PATTERNS = [
    (b"\x22", "LD (nn),HL"),
    (b"\x32", "LD (nn),A"),
    (b"\x2a", "LD HL,(nn)"),
    (b"\x3a", "LD A,(nn)"),
    (b"\xed\x43", "LD (nn),BC"),
    (b"\xed\x53", "LD (nn),DE"),
    (b"\xed\x4b", "LD BC,(nn)"),
    (b"\xed\x5b", "LD DE,(nn)"),
    (b"\x21", "LD HL,nn"),
    (b"\x11", "LD DE,nn"),
    (b"\x01", "LD BC,nn"),
]

def main():
    rom = open(ROM, "rb").read()
    npages = len(rom) // 0x4000
    hits = defaultdict(list)     # target -> [(page, off, kind)]
    for pg in range(npages):
        data = rom[pg * 0x4000:(pg + 1) * 0x4000]
        for pre, kind in PATTERNS:
            plen = len(pre)
            start = 0
            while True:
                i = data.find(pre, start)
                if i < 0 or i + plen + 2 > len(data):
                    break
                w = data[i + plen] | (data[i + plen + 1] << 8)
                if LO <= w <= HI:
                    hits[w].append((pg, i, kind))
                start = i + 1
    for w in sorted(hits):
        print(f"{w:04X}: {len(hits[w])} hit(s)")
        bypage = defaultdict(list)
        for pg, off, kind in hits[w]:
            bypage[pg].append((off, kind))
        for pg in sorted(bypage):
            offs = ", ".join(f"{o:04X}({k})" for o, k in sorted(bypage[pg]))
            print(f"   page {pg:02X}: {offs}")

if __name__ == "__main__":
    main()
