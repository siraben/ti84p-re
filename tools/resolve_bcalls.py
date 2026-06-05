#!/usr/bin/env python3
"""Resolve the bcall jump table from the raw ROM.

The table lives on flash page 0x3B (found by scoring all pages). Each ID
(0x4000.., step 3) maps to a 3-byte entry: addr(2 LE) + page(1). The page
byte's high bits are flags; hardware masks with &0x3F (see cross_page_jump),
so the physical flash page is page&0x3F. Writes bcall_targets.txt.
"""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
rom = open(os.path.join(HERE, 'rom.bin'), 'rb').read()
bc = {}
for line in open(os.path.join(HERE, 'bcalls.txt')):
    p = line.split()
    if len(p) == 2:
        bc[int(p[0], 16)] = p[1]
NPAGES = len(rom) // 0x4000

def entry(page, idv):
    off = page * 0x4000 + (idv - 0x4000)
    if off + 3 > len(rom):
        return None
    return rom[off] | rom[off + 1] << 8, rom[off + 2]

def valid(a, pg):
    pg &= 0x3F
    return pg < NPAGES and (0x4000 <= a <= 0x7FFF or a < 0x4000)

# find table page
best = max(range(NPAGES),
          key=lambda P: sum(1 for i in bc if entry(P, i) and valid(*entry(P, i))))
TABLE_PAGE = best
ids = sorted(bc)
valid_n = 0
with open(os.path.join(HERE, 'bcall_targets.txt'), 'w') as f:
    for idv in ids:
        a, pg = entry(TABLE_PAGE, idv)
        pg &= 0x3F                      # mask to physical flash page
        f.write(f"{bc[idv]}\t{idv:04X}\t{a:04X}\t{pg:02X}\n")
        if 0x4000 <= a <= 0x7FFF or a < 0x4000:
            valid_n += 1
print(f"table page = 0x{TABLE_PAGE:02X}; wrote {len(ids)} targets ({valid_n} valid)")
