#!/usr/bin/env python3
"""Resolve the bcall jump table from the raw ROM.

The table lives on flash page 0x3B (found by scoring all pages). Each ID
(0x4000.., step 3) maps to a 3-byte entry: addr(2 LE) + page(1). The page
byte's high bits are flags; hardware masks with &0x3F (see cross_page_jump),
so the physical flash page is page&0x3F. Writes bcall_targets.txt.
"""
import sys, os, re
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

def x8_entry(idv):
    off = 0x3F * 0x4000 + (idv & 0x7FFF)
    if off + 3 > len(rom):
        return None
    raw = rom[off:off + 3]
    if raw in (b"\x00\x00\x00", b"\xff\xff\xff"):
        return None
    return rom[off] | rom[off + 1] << 8, rom[off + 2]

def valid(a, pg):
    pg &= 0x3F
    return pg < NPAGES and (0x4000 <= a <= 0x7FFF or a < 0x4000)

def table_entry_score(page, idv):
    off = page * 0x4000 + (idv - 0x4000)
    if off + 3 > len(rom):
        return 0
    raw = rom[off:off + 3]
    if raw in (b"\x00\x00\x00", b"\xff\xff\xff"):
        return 0
    ent = entry(page, idv)
    return 1 if ent and valid(*ent) else 0

# find table page
best = max(range(NPAGES),
          key=lambda P: sum(table_entry_score(P, i) for i in bc))
TABLE_PAGE = best
best_score = sum(table_entry_score(TABLE_PAGE, i) for i in bc)
if best_score == 0:
    sys.exit("could not find a plausible bcall table; is tools/rom.bin a complete ROM dump?")
ids = sorted(i for i in bc if 0x4000 <= i < 0x8000)
valid_n = 0
with open(os.path.join(HERE, 'bcall_targets.txt'), 'w') as f:
    for idv in ids:
        a, pg = entry(TABLE_PAGE, idv)
        pg &= 0x3F                      # mask to physical flash page
        f.write(f"{bc[idv]}\t{idv:04X}\t{a:04X}\t{pg:02X}\n")
        if 0x4000 <= a <= 0x7FFF or a < 0x4000:
            valid_n += 1
print(f"table page = 0x{TABLE_PAGE:02X}; wrote {len(ids)} main targets ({valid_n} valid)")

# Also emit the page-0 RAM-resident bjump trampoline table:
#   each entry = CALL cross_page_jump (CD 09 2B) ; .dw addr ; .db page  (6 bytes packed)
with open(os.path.join(HERE, 'bjumps.txt'), 'w') as f:
    off = 0x3B01; n = 0
    while off < 0x3E80 and rom[off] == 0xCD and rom[off+1] == 0x09 and rom[off+2] == 0x2B:
        addr = rom[off+3] | rom[off+4] << 8
        page = rom[off+5] & 0x3F
        f.write(f"{off:04X}\t{addr:04X}\t{page:02X}\n")
        off += 6; n += 1
print(f"wrote {n} bjump trampoline entries (0x3B01..0x{off:04X})")

# Page 0x3F is often replaced by BootFree in ROM dumps and emulator images.
# The BootFree prefix below is not the retail TI boot page. Do not derive
# 0x8xxx bcall bodies from it.
BOOTFREE_PAGE3F_PREFIX = bytes.fromhex("3e3fd306d307c32c81")
RETAIL_PAGE3F_PREFIX = bytes.fromhex("3e07d3043e7fd3063e03d30ec32c81")
page3f = rom[0x3F * 0x4000:(0x3F * 0x4000) + 0x20]

def page3f_kind(buf):
    if buf.startswith(BOOTFREE_PAGE3F_PREFIX):
        return "bootfree"
    if buf.startswith(RETAIL_PAGE3F_PREFIX):
        return "retail"
    return "unknown"

def boot_bcalls():
    out = {}
    in_boot_section = False
    inc = os.path.join(HERE, 'ti83plus.inc')
    for line in open(inc, encoding='latin1'):
        if 'bootbtf' in line and 'equ' in line and '8000h' in line:
            in_boot_section = True
        if in_boot_section and line.strip().startswith(';RAM Equates'):
            break
        if not in_boot_section:
            continue
        m = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*)\s+equ\s+([0-9A-Fa-f]{4})h\b', line)
        if not m:
            continue
        idv = int(m.group(2), 16)
        if 0x8018 <= idv <= 0x8129:
            out[idv] = m.group(1)
    return out

kind = page3f_kind(page3f)
with open(os.path.join(HERE, 'bcalls8x_targets.txt'), 'w') as f:
    if kind == "bootfree":
        f.write("# 0x8xxx body targets intentionally unresolved.\n")
        f.write("# Skipped: page 0x3F starts with the BootFree replacement prefix ")
        f.write(page3f[:len(BOOTFREE_PAGE3F_PREFIX)].hex(" ").upper())
        f.write(".\n")
    elif kind == "retail":
        count = 0
        for idv, name in sorted(boot_bcalls().items()):
            ent = x8_entry(idv)
            if not ent:
                continue
            addr, page = ent
            page &= 0x3F
            if not valid(addr, page):
                continue
            f.write(f"{name}\t{idv:04X}\t{addr:04X}\t{page:02X}\n")
            count += 1
        print(f"wrote {count} retail 0x8xxx boot targets")
    else:
        f.write("# 0x8xxx body targets intentionally unresolved.\n")
        f.write("# Skipped: page 0x3F has an unknown boot prefix ")
        f.write(page3f[:16].hex(" ").upper())
        f.write(".\n")
print(f"0x8xxx body target status: page 0x3F kind={kind}")
