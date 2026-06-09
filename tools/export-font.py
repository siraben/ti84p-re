#!/usr/bin/env python3
"""Extract the TI-84 Plus font tables from the ROM into reusable artifacts.

Two font tables drive the display and the page-0x39 MathPrint typesetter:

- Large font (`_PutMap`): flash page 0x07 at logical 0x45FF, 7-byte stride,
  256 codepoints. Each glyph is 7 rows; the 5-pixel glyph sits in the low 5
  bits of each row byte.
- Small / variable-width font (`_VPutMap`, used for MathPrint super/subscripts
  and limits): flash page 0x03 at logical 0x4CD6, 8-byte stride. Each entry is
  a width byte followed by 7 row bytes; the glyph occupies the low `width` bits.

Output (committed; the CI wiki build has no ROM):
  - web/mathprint/font.json  -> glyph data for the interactive renderer and its
    font-table tab

Usage: python3 tools/export-font.py [--rom tools/rom.bin]
"""
import argparse
import json
import os

LARGE_PAGE, LARGE_ADDR, LARGE_STRIDE, LARGE_W, LARGE_ROWS = 0x07, 0x45FF, 7, 5, 7
SMALL_PAGE, SMALL_ADDR, SMALL_STRIDE, SMALL_ROWS = 0x03, 0x4CD6, 8, 7

# Codepoint names from ti83plus.inc (`L*` font equates). 0x20-0x7E mirror ASCII.
NAMES = {
    0x01: "LrecurN", 0x02: "LrecurU", 0x03: "LrecurV", 0x04: "LrecurW",
    0x05: "Lconvert", 0x06: "LsqUp", 0x07: "LsqDown", 0x08: "Lintegral",
    0x09: "Lcross", 0x0A: "LboxIcon", 0x0B: "LcrossIcon", 0x0C: "LdotIcon",
    0x0D: "LsubT", 0x0E: "LcubeR", 0x0F: "LhexF", 0x10: "Lroot",
    0x11: "Linverse", 0x12: "Lsquare", 0x13: "Langle", 0x14: "Ldegree",
    0x15: "Lradian", 0x16: "Ltranspose", 0x17: "LLE", 0x18: "LNE",
    0x19: "LGE", 0x1A: "Lneg", 0x1B: "Lexponent", 0x1C: "Lstore",
    0x1D: "Lten", 0x1E: "LupArrow", 0x1F: "LdownArrow",
    0xF0: "LDnBlk", 0xF1: "LcurFull", 0xF5: "MathPrint_", 0xF6: "fracSlash",
    0xF7: "placeholder",
}
for _c in range(0x80, 0x8A):
    NAMES[_c] = f"Lsub{_c - 0x80}"


def flat(page, addr):
    return page * 0x4000 + (addr - 0x4000)


def name_of(code):
    if 0x20 <= code <= 0x7E:
        return repr(chr(code))
    return NAMES.get(code, "")


def extract(rom):
    lbase = flat(LARGE_PAGE, LARGE_ADDR)
    large = []
    for code in range(256):
        o = lbase + code * LARGE_STRIDE
        large.append([rom[o + r] & 0x1F for r in range(LARGE_ROWS)])

    sbase = flat(SMALL_PAGE, SMALL_ADDR)
    small = {}
    for code in range(256):
        o = sbase + code * SMALL_STRIDE
        w = rom[o]
        if not (1 <= w <= 7):
            continue  # width 0 or out-of-table garbage marks an undefined slot
        mask = (1 << w) - 1
        small[code] = {"w": w, "rows": [rom[o + 1 + r] & mask for r in range(SMALL_ROWS)]}
    return large, small


def write_json(path, large, small):
    data = {
        "large": {"page": LARGE_PAGE, "addr": LARGE_ADDR, "stride": LARGE_STRIDE,
                  "width": LARGE_W, "rows": LARGE_ROWS, "glyphs": large},
        "small": {"page": SMALL_PAGE, "addr": SMALL_ADDR, "stride": SMALL_STRIDE,
                  "rows": SMALL_ROWS,
                  "glyphs": {str(c): g for c, g in sorted(small.items())}},
        "names": {str(c): NAMES[c] for c in sorted(NAMES)},
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
        f.write("\n")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default=os.path.join(here, "rom.bin"))
    ap.add_argument("--json", default=os.path.join(root, "web", "mathprint", "font.json"))
    args = ap.parse_args()
    if not os.path.exists(args.rom):
        raise SystemExit(f"ROM image not found: {args.rom} (copyrighted, gitignored)")
    rom = open(args.rom, "rb").read()
    large, small = extract(rom)
    write_json(args.json, large, small)
    print(f"wrote {args.json} ({len(large)} large glyphs, {len(small)} small glyphs)")


if __name__ == "__main__":
    main()
