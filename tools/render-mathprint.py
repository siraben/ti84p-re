#!/usr/bin/env python3
"""Render MathPrint expressions pixel-accurately from the TI-84 Plus ROM font.

The OS large font (used by _PutMap, and by the page-0x39 MathPrint typesetter for
digits/letters/operators) lives on flash page 0x07 at base 0x45FF with a **7-byte
stride**: glyph(char) = ROM[0x45FF + char*7 .. +7], 7 rows, the 5-pixel glyph in
the low 5 bits of each row byte. (See docs/08-display-lcd.md, docs/sub-equation-display.md.)

This script loads that font from a ROM image and composes the 2-D layouts the
page-0x39 engine builds — fraction stacking, exponent raising, and inline glyphs
(including the Σ summation character, code 0xC6) — so the wiki can show exactly
what the calculator draws. It does NOT execute the ROM; it reproduces the
documented layout rules over the real glyph bitmaps.

Usage:
    python3 tools/render-mathprint.py            # render the built-in examples
    python3 tools/render-mathprint.py --rom PATH # use a specific ROM image
ROM image (copyrighted, gitignored) defaults to tools/rom.bin.
"""
import argparse
import os
import sys

FONT_PAGE = 0x07
FONT_ADDR = 0x45FF          # large-font base on page 7
FONT_STRIDE = 7             # bytes per glyph (8th row overlaps the next glyph)
GLYPH_ROWS = 7
GLYPH_W = 5                 # the glyph sits in the low 5 bits of each row byte
CELL_W = GLYPH_W + 1        # 1px inter-char gap (16 chars * 6 = 96px screen)

# Tokens the OS draws with a single font glyph that has no ASCII code.
SPECIAL = {"Sigma": 0xC6, "sqrt": 0xC5, "theta": 0x5B}

# A "box" is (rows, baseline): rows is a list of 0/1 rows; baseline is the row
# index that sits on the text baseline, so pieces of different height (a raised
# exponent, a fraction) align the way the calculator stacks them.

def load_font(rom_path):
    with open(rom_path, "rb") as f:
        rom = f.read()
    base = FONT_PAGE * 0x4000 + (FONT_ADDR - 0x4000)
    if base + 256 * FONT_STRIDE > len(rom):
        sys.exit(f"ROM too small / wrong image: {rom_path}")
    return rom, base


def glyph(rom, base, code):
    """Return the box (7x5 rows, baseline at the bottom) for a character code."""
    o = base + code * FONT_STRIDE
    rows = [[(b >> (GLYPH_W - 1 - i)) & 1 for i in range(GLYPH_W)]
            for b in rom[o:o + GLYPH_ROWS]]
    return rows, GLYPH_ROWS                # baseline = bottom of the glyph


def blank(h, w):
    return [[0] * w for _ in range(h)]


def width(rows):
    return len(rows[0]) if rows else 0


def hcat(boxes, gap=1):
    """Concatenate boxes left-to-right, aligning their baselines."""
    boxes = [b for b in boxes if b and b[0]]
    if not boxes:
        return ([], 0)
    above = max(bl for _, bl in boxes)            # rows above the baseline
    below = max(len(r) - bl for r, bl in boxes)   # rows below the baseline
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
    """Render a run of characters; '@Name' emits a SPECIAL glyph (e.g. @Sigma)."""
    cells, i = [], 0
    while i < len(s):
        if s[i] == "@":
            name, i = "", i + 1
            while i < len(s) and s[i].isalpha():
                name += s[i]; i += 1
            cells.append(glyph(rom, base, SPECIAL[name]))
        else:
            cells.append(glyph(rom, base, ord(s[i]))); i += 1
    return hcat(cells, gap=1)


def fraction(num, den):
    """Stack numerator over denominator with a full-width bar; baseline = the bar."""
    nrows, drows = num[0], den[0]
    w = max(width(nrows), width(drows)) + 2       # bar overhangs operands by 1px

    def center(rows):
        pad = (w - width(rows)) // 2
        return [[0] * pad + r + [0] * (w - width(rows) - pad) for r in rows]

    bar, gap = [[1] * w], [[0] * w]
    rows = center(nrows) + gap + bar + gap + center(drows)
    return rows, len(center(nrows)) + 1           # baseline sits on the bar row


def superscript(base_box, exp_box, raise_px=4):
    """Place exp raised above-right of base (X^2); baseline = base's baseline."""
    brows, bbl = base_box
    erows, _ = exp_box
    left = (blank(raise_px, width(brows)) + brows, raise_px + bbl)
    right = (erows, len(erows))                    # exp hangs from the top
    return hcat([left, right], gap=1)


def show(box, on="█", off="·"):
    rows = box[0]
    return "\n".join("".join(on if c else off for c in row) for row in rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default=os.path.join(os.path.dirname(__file__), "rom.bin"))
    ap.add_argument("--on", default="█")
    ap.add_argument("--off", default="·")
    args = ap.parse_args()
    if not os.path.exists(args.rom):
        sys.exit(f"ROM image not found: {args.rom} (copyrighted, gitignored)")
    rom, base = load_font(args.rom)
    T = lambda s: text(rom, base, s)

    # Verified 2-D structures (font glyphs + the documented stacking rules).
    # NB: integral/summation render as 2-D ∫/Σ with stacked limits on the 84+;
    # the ∫ has no font glyph (it is stroked by code), so it is not reproduced
    # here yet — see docs/sub-equation-display.md "Remaining unknowns".
    examples = [
        ("1/2  (fraction)", fraction(T("1"), T("2"))),
        ("X²  (exponent)", superscript(T("X"), T("2"))),
        ("(A+B)/C  (fraction with wide numerator)",
         fraction(T("(A+B)"), T("C"))),
        ("1/(2/3)  (nested fraction)",
         fraction(T("1"), fraction(T("2"), T("3")))),
        ("Σ  (the summation glyph, font char 0xC6)", T("@Sigma")),
    ]
    for title, bmp in examples:
        print(f"\n{title}\n" + "-" * len(title))
        print(show(bmp, args.on, args.off))


if __name__ == "__main__":
    main()
