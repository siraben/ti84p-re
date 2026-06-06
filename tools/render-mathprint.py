#!/usr/bin/env python3
"""Render the TI-84 Plus large-font glyphs and MathPrint 2-D layouts from the ROM.

The large font (used by _PutMap and by the page-0x39 MathPrint typesetter) is on
flash page 0x07 at base 0x45FF with a 7-byte stride: glyph(code) =
ROM[0x45FF + code*7 .. +7], 7 rows, the 5-pixel glyph in the low 5 bits of each
row byte. Codepoint names follow ti83plus.inc (the `L*` font equates).

Usage:
    python3 tools/render-mathprint.py                 # built-in layout examples
    python3 tools/render-mathprint.py --font-index     # every codepoint + glyph
    python3 tools/render-mathprint.py --rom PATH        # use a specific ROM image
ROM image (copyrighted, gitignored) defaults to tools/rom.bin.
"""
import argparse
import os
import sys

FONT_PAGE = 0x07
FONT_ADDR = 0x45FF
FONT_STRIDE = 7
GLYPH_ROWS = 7
GLYPH_W = 5
CELL_W = GLYPH_W + 1

# Small (variable-width) font used for MathPrint super/subscripts and limits.
# page_03:4A8F loads it: glyph = page_03[0x4CD6 + code*8] = [width][7 rows],
# the glyph occupying the low `width` bits of each row byte.
SFONT_PAGE = 0x03
SFONT_ADDR = 0x4CD6
SFONT_STRIDE = 8

# Codepoint names from ti83plus.inc (`L*` font equates). 0x20-0x7E mirror ASCII
# and are named by their character; only the non-ASCII codepoints are listed here.
NAMES = {
    0x01: "LrecurN", 0x02: "LrecurU", 0x03: "LrecurV", 0x04: "LrecurW",
    0x05: "Lconvert", 0x06: "LsqUp", 0x07: "LsqDown", 0x08: "Lintegral",
    0x09: "Lcross", 0x0A: "LboxIcon", 0x0B: "LcrossIcon", 0x0C: "LdotIcon",
    0x0D: "LsubT", 0x0E: "LcubeR", 0x0F: "LhexF", 0x10: "Lroot",
    0x11: "Linverse", 0x12: "Lsquare", 0x13: "Langle", 0x14: "Ldegree",
    0x15: "Lradian", 0x16: "Ltranspose", 0x17: "LLE", 0x18: "LNE",
    0x19: "LGE", 0x1A: "Lneg", 0x1B: "Lexponent", 0x1C: "Lstore",
    0x1D: "Lten", 0x1E: "LupArrow", 0x1F: "LdownArrow",
    0xF0: "LDnBlk", 0xF1: "LcurFull",
    # added in OS 2.53MP for MathPrint (per 83Plus:OS:OS 2.53MP Changes):
    0xF5: "MathPrint _", 0xF6: "fraction slash", 0xF7: "placeholder box",
}
# Subscript digits and accented letters fill 0x80-0xEF; name the families.
for _c in range(0x80, 0x8A):
    NAMES[_c] = f"Lsub{_c - 0x80}"


def name_of(code):
    if 0x20 <= code <= 0x7E:
        return repr(chr(code))
    return NAMES.get(code, "")


# A "box" is (rows, baseline): rows is a list of 0/1 rows; baseline is the row
# index on the text baseline, so a raised exponent or a fraction aligns the way
# the calculator stacks them.

def load_font(rom_path):
    with open(rom_path, "rb") as f:
        rom = f.read()
    base = FONT_PAGE * 0x4000 + (FONT_ADDR - 0x4000)
    if base + 256 * FONT_STRIDE > len(rom):
        sys.exit(f"ROM too small / wrong image: {rom_path}")
    return rom, base


def glyph(rom, base, code):
    o = base + code * FONT_STRIDE
    rows = [[(b >> (GLYPH_W - 1 - i)) & 1 for i in range(GLYPH_W)]
            for b in rom[o:o + GLYPH_ROWS]]
    # align on the math axis (vertical centre), per decr_counters' row model:
    # the page-0x39 engine positions cells by row, so a glyph next to a fraction
    # centres on the bar rather than sitting at the numerator's baseline.
    return rows, GLYPH_ROWS // 2


def sglyph(rom, code):
    """Small-font glyph: [width][7 rows], glyph in the low `width` bits."""
    o = SFONT_PAGE * 0x4000 + (SFONT_ADDR - 0x4000) + code * SFONT_STRIDE
    w = rom[o]
    rows = [[(b >> (w - 1 - i)) & 1 for i in range(w)]
            for b in rom[o + 1:o + 8]]
    return rows, len(rows) // 2


def stext(rom, s):
    return hcat([sglyph(rom, ord(ch)) for ch in s], gap=1)


def blank(h, w):
    return [[0] * w for _ in range(h)]


def width(rows):
    return len(rows[0]) if rows else 0


def trim(box):
    """Remove empty border rows/columns from a glyph-like box."""
    rows, baseline = box
    if not rows or not rows[0]:
        return [], 0
    nonblank_rows = [i for i, row in enumerate(rows) if any(row)]
    if not nonblank_rows:
        return [[]], 0
    top, bottom = nonblank_rows[0], nonblank_rows[-1] + 1
    cols = [i for i in range(width(rows)) if any(row[i] for row in rows[top:bottom])]
    left, right = cols[0], cols[-1] + 1
    return [row[left:right] for row in rows[top:bottom]], max(0, baseline - top)


def limit_text(rom, s):
    """Small-font text as MathPrint uses it for compact upper/lower limits."""
    return trim(stext(rom, s))


def hcat(boxes, gap=1):
    boxes = [b for b in boxes if b and b[0]]
    if not boxes:
        return ([], 0)
    above = max(bl for _, bl in boxes)
    below = max(len(r) - bl for r, bl in boxes)
    h = above + below
    out = [[] for _ in range(h)]
    for k, (rows, bl) in enumerate(boxes):
        w = width(rows)
        top, bot = above - bl, below - (len(rows) - bl)
        padded = blank(top, w) + rows + blank(bot, w)
        for r in range(h):
            if k:
                out[r] += [0] * gap
            out[r] += padded[r]
    return out, above


def text(rom, base, s):
    """Render a run of characters; '@CODE' (hex) emits a raw codepoint."""
    cells, i = [], 0
    while i < len(s):
        if s[i] == "@":
            j = i + 1
            while j < len(s) and s[j] in "0123456789abcdefABCDEF":
                j += 1
            cells.append(glyph(rom, base, int(s[i + 1:j], 16))); i = j
        else:
            cells.append(glyph(rom, base, ord(s[i]))); i += 1
    return hcat(cells, gap=1)


def fraction(num, den):
    nrows, drows = num[0], den[0]
    w = max(width(nrows), width(drows)) + 2

    def center(rows):
        pad = (w - width(rows)) // 2
        return [[0] * pad + r + [0] * (w - width(rows) - pad) for r in rows]

    bar, gap = [[1] * w], [[0] * w]
    rows = center(nrows) + gap + bar + gap + center(drows)
    return rows, len(center(nrows)) + 1


def superscript(base_box, exp_box, raise_px=4):
    """Base on the baseline; exponent raised above-right. Baseline = base's."""
    brows, bbl = base_box
    erows = exp_box[0]
    bw, ew = width(brows), width(erows)
    h = raise_px + len(brows)
    out = []
    for r in range(h):
        left = brows[r - raise_px] if raise_px <= r < h else [0] * bw
        right = erows[r] if r < len(erows) else [0] * ew
        out.append(left + [0] + right)
    return out, raise_px + bbl  # axis = base glyph's axis, shifted down by the raise


def subsup(base_box, sup_box, sub_box, ext=3):
    """A base (e.g. ∫) with an upper limit above-right and a lower limit
    below-right — the definite-integral / Σ form. The limits stack on the
    symbol; the symbol itself keeps its glyph height."""
    brows, baxis = base_box
    srows, drows = sup_box[0], sub_box[0]
    bw = width(brows)
    rw = max(width(srows), width(drows))
    h = ext + len(brows) + ext            # room for the two limits
    out = []
    for r in range(h):
        left = brows[r - ext] if ext <= r < ext + len(brows) else [0] * bw
        if r < len(srows):                # upper limit, top-right
            right = srows[r] + [0] * (rw - width(srows))
        elif r >= h - len(drows):         # lower limit, bottom-right
            right = drows[r - (h - len(drows))] + [0] * (rw - width(drows))
        else:
            right = [0] * rw
        out.append(left + [0] + right)
    return out, ext + baxis


def tall_integral(base_box, height=17):
    """Stretch Lintegral's center stem to the calculator's tall-template size."""
    rows, _ = base_box
    if height <= len(rows):
        return rows, len(rows) // 2
    extra = height - len(rows)
    out = rows[:5] + [rows[4]] * extra + rows[5:]
    return out, height // 2


def definite_integral(base_box, sup_box, sub_box):
    """Tall integral with compact upper/lower limits, matching fnInt( layout."""
    irows, iaxis = tall_integral(base_box)
    srows, drows = sup_box[0], sub_box[0]
    rw = max(width(srows), width(drows))
    h = len(irows)
    out = []
    for r in range(h):
        if r < len(srows):
            right = srows[r] + [0] * (rw - width(srows))
        elif r >= h - len(drows):
            right = drows[r - (h - len(drows))] + [0] * (rw - width(drows))
        else:
            right = [0] * rw
        out.append(irows[r] + [0] + right)
    return out, iaxis


def show(box, on="█", off="·"):
    return "\n".join("".join(on if c else off for c in row) for row in box[0])


def font_index(rom, base, on="#", off="."):
    """Print every codepoint, its name, and its glyph (8 codepoints per band)."""
    for lo in range(0, 0x100, 8):
        codes = range(lo, lo + 8)
        print("  ".join(f"{c:02X} {name_of(c):<11}"[:14] for c in codes))
        for r in range(GLYPH_ROWS):
            line = []
            for c in codes:
                g = glyph(rom, base, c)[0]
                line.append("".join(on if g[r][i] else off for i in range(GLYPH_W)))
            print("  ".join(f"{cell:<14}" for cell in line))
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default=os.path.join(os.path.dirname(__file__), "rom.bin"))
    ap.add_argument("--font-index", action="store_true",
                    help="dump every large-font codepoint and glyph")
    ap.add_argument("--on", default="█")
    ap.add_argument("--off", default="·")
    args = ap.parse_args()
    if not os.path.exists(args.rom):
        sys.exit(f"ROM image not found: {args.rom} (copyrighted, gitignored)")
    rom, base = load_font(args.rom)
    if args.font_index:
        font_index(rom, base)
        return
    T = lambda s: text(rom, base, s)
    examples = [
        ("1/2", fraction(T("1"), T("2"))),
        ("X squared (exponent)", superscript(T("X"), T("2"))),
        ("(A+B)/C", fraction(T("(A+B)"), T("C"))),
        ("1/(2/3) (nested)", fraction(T("1"), fraction(T("2"), T("3")))),
        ("Lroot 0x10 (radical glyph)", T("@10")),
        ("Lintegral 0x08 (integral glyph)", T("@08")),
        # MATH > 9 fnInt( as a MathPrint definite-integral template:
        # Lintegral's center stem is stretched to the 17-pixel template seen on
        # the calculator, carrying compact small-font lower/upper limits.
        # Entered as 9 1 RIGHT 2 RIGHT X RIGHT X -> the integral of X dX from 1 to 2.
        ("integral from 1 to 2 of (X) dX  (= 1.5)",
         hcat([definite_integral(T("@08"), limit_text(rom, "2"), limit_text(rom, "1")),
               T("(X)dX")], gap=1)),
    ]
    for title, box in examples:
        print(f"\n{title}\n" + "-" * len(title))
        print(show(box, args.on, args.off))


if __name__ == "__main__":
    main()
