#!/usr/bin/env python3
"""Replay TI-84 Plus LCD I/O recorded in a TilEm TLMT v2 trace.

The replay models the pinned TilEm TI-84 Plus T6A04 implementation: its reset
state, 128x64 backing RAM, 6- and 8-bit transfers, 50-clock busy interval, and
the 0x12/0x13 port mirrors.  Immediate and register-based Z80 OUT forms are
decoded through :mod:`tilem_trace_resolve`.

TLMT v2 does not record the byte read by block-output instructions.  A block
OUT to an LCD port therefore makes an exact replay impossible and is rejected
by default.  The trace must begin at calculator reset because TLMT stores no
initial LCD-controller snapshot.

Usage: import and call reconstruct(trace_path[, at_index]) -> 64x96 grid (0/1).
       python3 tools/trace_lcd.py TRACE [--at N] prints the top-left region.
"""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "r", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tilem_trace_resolve.py"))
_r = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_r)

STRIDE = 16         # TilEm TI-84 Plus: 128 columns / 8 bits
VISIBLE_WIDTH = 96
ROWS = 64
BUSY_CLOCKS = 50
CONTROL_PORTS = {0x10, 0x12}
DATA_PORTS = {0x11, 0x13}


class T6A04:
    """The LCD state transitions used by pinned TilEm for a TI-84 Plus."""

    def __init__(self):
        self.x = 0
        self.y = 0
        self.inc = 7
        self.mode = 1
        self.rowshift = 0
        self.active = 0
        self.mem = bytearray(STRIDE * ROWS)
        self.busy_until = None

    def _accept(self, clock):
        if clock is not None and self.busy_until is not None and clock < self.busy_until:
            return False
        if clock is not None:
            self.busy_until = clock + BUSY_CLOCKS
        return True

    def control(self, val, clock=None):
        """Apply a control write; return whether TilEm accepts it."""
        if not self._accept(clock):
            return False
        if val <= 1:
            self.mode = val
        elif val == 2:
            self.active = 0
        elif val == 3:
            self.active = 1
        elif val <= 7:
            self.inc = val
        elif 0x20 <= val <= 0x3F:
            self.x = val - 0x20
        elif 0x80 <= val <= 0xBF:
            self.y = val - 0x80
        elif 0x40 <= val <= 0x7F:
            self.rowshift = val - 0x40
        # Other commands do not affect the reconstructed monochrome bitmap.
        return True

    def _normalize_pointer(self):
        xlimit = STRIDE if self.mode else (STRIDE * 8 + 5) // 6
        if self.x >= xlimit:
            self.x = 0
        elif self.x < 0:
            self.x = xlimit - 1
        if self.y >= ROWS:
            self.y = 0
        elif self.y < 0:
            self.y = ROWS - 1

    def _move_pointer(self):
        if self.inc == 4:
            self.y -= 1
        elif self.inc == 5:
            self.y += 1
        elif self.inc == 6:
            self.x -= 1
        elif self.inc == 7:
            self.x += 1

    def read(self, clock=None):
        """Apply a data read's pointer and busy-state effects."""
        if not self._accept(clock):
            return False
        self._normalize_pointer()
        self._move_pointer()
        return True

    def write(self, sprite, clock=None):
        """Apply a data write; return whether TilEm accepts it."""
        if not self._accept(clock):
            return False
        self._normalize_pointer()
        if self.mode:
            self.mem[self.x + STRIDE * self.y] = sprite
        else:
            col = 6 * self.x
            ofs = self.y * STRIDE + (col >> 3)
            shift = col & 7
            sprite = (sprite << 2) & 0x3FC
            mask = (~(0xFC >> shift)) & 0xFF
            self.mem[ofs] = (self.mem[ofs] & mask) | ((sprite >> shift) & 0xFF)
            if shift > 2 and (col >> 3) < STRIDE - 1:
                ofs += 1
                shift = 8 - shift
                mask = (~(0xFC << shift)) & 0xFF
                self.mem[ofs] = (self.mem[ofs] & mask) | ((sprite << shift) & 0xFF)
        self._move_pointer()
        return True

    def grid(self):
        """Render visible columns to a 64x96 grid, applying row shift."""
        grid = []
        for py in range(ROWS):
            src = (py + self.rowshift) % ROWS
            row = []
            for px in range(VISIBLE_WIDTH):
                byte = self.mem[src * STRIDE + (px >> 3)]
                row.append((byte >> (7 - (px & 7))) & 1)
            grid.append(row)
        return grid


def reconstruct(trace, at_index=None, strict=True):
    """Replay LCD I/O before the exclusive instruction cutoff ``at_index``.

    ``at_index`` counts instruction records, matching tilem_trace_resolve's
    displayed index.  In strict mode, an unrecoverable block OUT to an LCD port
    raises ValueError instead of silently producing a non-exact bitmap.
    """
    lcd = T6A04()
    idx = 0
    with open(trace, "rb") as fp:
        header = _r.read_header(fp)
        if header["version"] != 2:
            raise ValueError(f"unsupported TLMT version {header['version']}; expected 2")
        if not (header["flags"] & 0x01):
            raise ValueError("trace lacks required instruction records")
        if (header["range_start"], header["range_end"]) != (0, 0xFFFF):
            raise ValueError("LCD replay requires a full-range reset-origin trace")
        first_instruction = True
        for record_type, payload in _r.iter_records(fp, resync=not strict):
            if record_type != 0x01:
                continue
            if at_index is not None and idx >= at_index:
                break
            if first_instruction:
                first_instruction = False
                if payload[_r.IDX_PC] != 0x8000:
                    raise ValueError(
                        "LCD replay requires a reset-origin trace whose first PC is 0x8000"
                    )
            event = _r.decode_io_event(payload)
            if event:
                direction, port, value, form = event
                port &= 0xFF
                if port in CONTROL_PORTS | DATA_PORTS:
                    if form == "block":
                        if strict:
                            raise ValueError(
                                f"instruction {idx}: block {direction} to LCD port "
                                f"0x{port:02x} cannot be replayed from TLMT v2"
                            )
                    elif direction == "IN" and port in DATA_PORTS:
                        lcd.read(payload[_r.IDX_CLOCK])
                    elif direction == "OUT" and port in CONTROL_PORTS:
                        lcd.control(value, payload[_r.IDX_CLOCK])
                    elif direction == "OUT":
                        lcd.write(value, payload[_r.IDX_CLOCK])
            idx += 1
        if first_instruction:
            raise ValueError("LCD replay requires at least one instruction record")
    return lcd.grid()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("trace")
    parser.add_argument("--at", type=int, default=None)
    parser.add_argument("--w", type=int, default=60)
    parser.add_argument("--h", type=int, default=24)
    parser.add_argument("--allow-unknown-block-io", action="store_true")
    args = parser.parse_args()
    grid = reconstruct(args.trace, args.at, strict=not args.allow_unknown_block_io)
    for y in range(min(args.h, ROWS)):
        print("".join("#" if grid[y][x] else " "
                      for x in range(min(args.w, VISIBLE_WIDTH))))


if __name__ == "__main__":
    main()
