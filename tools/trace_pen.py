#!/usr/bin/env python3
"""Extract the OS pen-geometry timeline from a TilEm trace.

The MathPrint engine tracks the pen position in two RAM bytes:
  penCol = 0x86D7   (x, large-glyph column origin)
  penRow = 0x86D8   (y)
and emits glyphs through two routines, each taking the glyph code in A:
  _PutMap  page_07:4588   (large 5x7 font)
  _VPutMap page_01:6293   (small variable-width font)

This replays the trace, banking PCs with tilem_trace_resolve.Banker, and prints,
for every glyph draw, the (penCol, penRow) at that instant and the glyph code in
A. That is the OS's exact placement list for the rendered expression, which we
diff against web/mathprint/app.js's `marks`.

Usage: python3 tools/trace_pen.py TRACE            -> list every glyph draw
       python3 tools/trace_pen.py TRACE --raw      -> also dump pen-byte writes
"""
import argparse
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "r", os.path.join(_HERE, "tilem_trace_resolve.py"))
_r = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_r)

PEN_COL = 0x86D7
PEN_ROW = 0x86D8
PUTMAP = ("page_07", 0x4588)
VPUTMAP = ("page_01", 0x6293)


def glyph_name(code):
    if 0x20 <= code <= 0x7e:
        return repr(chr(code))
    return f"0x{code:02x}"


def extract(trace):
    """Return (draws, pen_writes).

    draws: list of dicts {idx, font, code, name, col, row}
    pen_writes: list of (idx, addr, val)
    """
    fp = open(trace, "rb")
    _r.read_header(fp)
    banker = _r.Banker()
    pen = {PEN_COL: None, PEN_ROW: None}
    draws = []
    pen_writes = []
    idx = 0
    for t, pl in _r.iter_records(fp, resync=True):
        if t == 0x02:
            addr, val = pl
            if addr in pen:
                pen[addr] = val
                pen_writes.append((idx, addr, val))
            continue
        if t != 0x01:
            continue
        banker.feed(pl)
        space, gaddr, _flat, _page = banker.resolve(pl[_r.IDX_PC])
        if (space, gaddr) in (PUTMAP, VPUTMAP):
            a = pl[_r.IDX_AF] >> 8
            draws.append({
                "idx": idx, "font": "large" if (space, gaddr) == PUTMAP else "small",
                "code": a, "name": glyph_name(a),
                "col": pen[PEN_COL], "row": pen[PEN_ROW],
            })
        idx += 1
    fp.close()
    return draws, pen_writes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--raw", action="store_true", help="also dump pen-byte writes")
    args = ap.parse_args()
    draws, pen_writes = extract(args.trace)
    print(f"# {len(draws)} glyph draws, {len(pen_writes)} pen-byte writes")
    for d in draws:
        col = "?" if d["col"] is None else d["col"]
        row = "?" if d["row"] is None else d["row"]
        print(f"{d['idx']:>9}  {d['font']:<5} A={d['code']:#04x} {d['name']:<6}"
              f"  penCol={col} penRow={row}")
    if args.raw:
        print("# pen-byte writes:")
        for i, addr, val in pen_writes:
            nm = "penCol" if addr == PEN_COL else "penRow"
            print(f"{i:>9}  {nm}={val}")


if __name__ == "__main__":
    main()
