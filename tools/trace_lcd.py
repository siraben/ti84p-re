#!/usr/bin/env python3
"""Reconstruct the exact LCD image from a TilEm trace's port writes.

The MathPrint engine draws straight to the LCD via I/O ports, not a RAM buffer,
so the rendered image is fully determined by the OUT (0x10) command / OUT (0x11)
data stream in the instruction trace (each carries its byte in the A register,
recorded as the WZ field for OUT (n),A: WZ = (A<<8)|n). Replaying that stream
through the T6A04 controller (ported from tilem emu/lcd.c) yields the exact
96x64 bitmap at any instruction index — no GIF frame-rate, refresh-blank, or
cursor-blink noise. This is the trace, completely constructed.

Usage: import and call reconstruct(trace_path[, at_index]) -> 64x96 grid (0/1).
       python3 tools/trace_lcd.py TRACE [--at N]  prints the top-left region.
"""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "r", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tilem_trace_resolve.py"))
_r = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_r)

STRIDE = 12          # 96-pixel rows, 8-bit mode (96/8)
ROWS = 64


class T6A04:
    def __init__(self):
        self.x = 0; self.y = 0; self.inc = 7; self.mode = 0
        self.rowshift = 0; self.active = 1
        self.mem = bytearray(STRIDE * ROWS)

    def control(self, val):                       # OUT (0x10),val
        if val <= 1: self.mode = val
        elif val == 2: self.active = 0
        elif val == 3: self.active = 1
        elif val <= 7: self.inc = val
        elif 0x20 <= val <= 0x3F: self.x = val - 0x20
        elif 0x80 <= val <= 0xBF: self.y = val - 0x80
        elif 0x40 <= val <= 0x7F: self.rowshift = val - 0x40
        # >=0xC0: contrast (no effect on the bitmap)

    def write(self, sprite):                       # OUT (0x11),sprite
        stride = STRIDE
        xlimit = stride if self.mode else (stride * 8 + 5) // 6
        if self.x >= xlimit: self.x = 0
        elif self.x < 0: self.x = xlimit - 1
        if self.y >= 0x40: self.y = 0
        elif self.y < 0: self.y = 0x3F
        if self.mode:
            self.mem[self.x + stride * self.y] = sprite
        else:
            col = 6 * self.x
            ofs = self.y * stride + (col >> 3)
            shift = col & 7
            s = sprite << 2
            mask = (~(0xFC >> shift)) & 0xFF
            self.mem[ofs] = (self.mem[ofs] & mask) | ((s >> shift) & 0xFF)
            if shift > 2 and (col >> 3) < stride - 1:
                ofs += 1; shift = 8 - shift
                mask = (~(0xFC << shift)) & 0xFF
                self.mem[ofs] = (self.mem[ofs] & mask) | ((s << shift) & 0xFF)
        if self.inc == 4: self.y -= 1
        elif self.inc == 5: self.y += 1
        elif self.inc == 6: self.x -= 1
        elif self.inc == 7: self.x += 1

    def grid(self):
        """Render mem to a 64x96 0/1 grid, applying the rowshift scroll."""
        g = []
        for py in range(ROWS):
            src = (py + self.rowshift) % ROWS
            row = []
            for px in range(96):
                b = self.mem[src * STRIDE + (px >> 3)]
                row.append((b >> (7 - (px & 7))) & 1)
            g.append(row)
        return g


def reconstruct(trace, at_index=None):
    """Replay OUT 0x10/0x11 up to at_index (or the end) -> 64x96 0/1 grid."""
    fp = open(trace, "rb")
    _r.read_header(fp)
    lcd = T6A04()
    idx = 0
    for t, pl in _r.iter_records(fp, resync=True):
        if t != 0x01:
            continue
        if at_index is not None and idx >= at_index:
            break
        op = pl[_r.IDX_OPCODE]
        if (op & 0xFF) == 0xD3 and (op & 0xFFFFFF00) == 0:   # OUT (n),A
            wz = pl[_r.IDX_WZ]
            port, val = wz & 0xFF, (wz >> 8) & 0xFF
            if port == 0x10:
                lcd.control(val)
            elif port == 0x11:
                lcd.write(val)
        idx += 1
    fp.close()
    return lcd.grid()


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--at", type=int, default=None)
    ap.add_argument("--w", type=int, default=60)
    ap.add_argument("--h", type=int, default=24)
    args = ap.parse_args()
    g = reconstruct(args.trace, args.at)
    for y in range(min(args.h, ROWS)):
        print("".join("#" if g[y][x] else " " for x in range(min(args.w, 96))))


if __name__ == "__main__":
    main()
