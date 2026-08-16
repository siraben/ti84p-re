#!/usr/bin/env python3
"""Extract MathPrint cell-layout and display-byte tables from the ROM.

The page-0x39 typesetter is data-driven: a class table at 39:5E45 maps each
layout class to a handler record, and each record encodes rows and cells. The
interactive renderer consumes this artifact for handler-cell classification
and the related page-7 display-byte remap.

Output: web/mathprint/layout.json
  { handlerTable, classCount, displayByteMap,
    classes: [ {cls, ptr, rows, items:[{count, action, cells:[[d,e],...]}]} | {cls, ptr, null} ],
    descriptors: [ {addr, base_yx, box_yx, row_height, cols_rows, cell_ptr, cells:[[d,e],...]} ] }
"""
import argparse
import hashlib
import json
import os

from rom_signatures import TI84_PLUS_OS_255MP_SHA256

PAGE = 0x39
HANDLER_TABLE = 0x5E45
HANDLER_COUNT = 0x44
DESCRIPTORS = [0x686F, 0x6880, 0x6893, 0x689C, 0x68A5]
DISPLAY_BYTE_PAGE = 0x07


def romoff(page, addr):
    return page * 0x4000 + (addr - 0x4000)


def word(rom, page, addr):
    o = romoff(page, addr)
    return rom[o] | (rom[o + 1] << 8)


def parse_handler_record(rom, cls):
    table = romoff(PAGE, HANDLER_TABLE)
    ptr = rom[table + 2 * cls] | (rom[table + 2 * cls + 1] << 8)
    if not 0x4000 <= ptr < 0x8000:
        return ptr, None
    o = romoff(PAGE, ptr)
    rows = rom[o]
    if rows == 0 or rows > 16:
        return ptr, None
    counts = list(rom[o + 1:o + 1 + rows])
    actions = list(rom[o + 1 + rows:o + 1 + 2 * rows])
    tbase = o + 1 + 2 * rows
    items = []
    pos = 0
    for count, action in zip(counts, actions):
        cells = [[rom[tbase + 2 * (pos + i)], rom[tbase + 2 * (pos + i) + 1]]
                 for i in range(count)]
        items.append({"count": count, "action": action, "cells": cells})
        pos += count
    return ptr, {"rows": rows, "items": items}


def parse_descriptor(rom, addr):
    o = romoff(PAGE, addr)
    base_yx = rom[o] | (rom[o + 1] << 8)
    box_yx = rom[o + 2] | (rom[o + 3] << 8)
    row_height = rom[o + 4]
    cols_rows = rom[o + 5] | (rom[o + 6] << 8)
    cell_ptr = rom[o + 7] | (rom[o + 8] << 8)
    cells = []
    if 0x4000 <= cell_ptr < 0x8000:
        co = romoff(PAGE, cell_ptr)
        cols = cols_rows >> 8
        rows = cols_rows & 0xFF
        for i in range(cols * rows):
            cells.append([rom[co + 2 * i], rom[co + 2 * i + 1]])
    return {"addr": addr, "base_yx": base_yx, "box_yx": box_yx,
            "row_height": row_height, "cols_rows": cols_rows,
            "cell_ptr": cell_ptr, "cells": cells}


def bytes_at(rom, page, addr, length):
    start = romoff(page, addr)
    return list(rom[start:start + length])


def pair_table(rom, page, addr, count):
    raw = bytes_at(rom, page, addr, 2 * count)
    return [[raw[2 * index], raw[2 * index + 1]] for index in range(count)]


def parse_display_byte_map(rom):
    """Extract every table entry addressable from 07:44DE's main entry."""

    return {
        "page": DISPLAY_BYTE_PAGE,
        "routine": "07:44DE–4538",
        "ordinary": {
            "address": 0x4000,
            "values": bytes_at(rom, DISPLAY_BYTE_PAGE, 0x4000, 0x100),
        },
        "feLow": {
            "address": 0x4099,
            "values": bytes_at(rom, DISPLAY_BYTE_PAGE, 0x4099, 0x69),
        },
        "feHigh": {
            "address": 0x4102,
            "entries": pair_table(rom, DISPLAY_BYTE_PAGE, 0x4102, 0x97),
        },
        "fc": {
            "address": 0x422C,
            "entries": pair_table(rom, DISPLAY_BYTE_PAGE, 0x422C, 0x100),
        },
        "fb": {
            "address": 0x4426,
            "entries": pair_table(rom, DISPLAY_BYTE_PAGE, 0x4426, 0x8C),
        },
    }


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default=os.path.join(here, "rom.bin"))
    ap.add_argument("--out", default=os.path.join(root, "web", "mathprint", "layout.json"))
    args = ap.parse_args()
    if not os.path.exists(args.rom):
        raise SystemExit(f"ROM not found: {args.rom} (copyrighted, gitignored)")
    rom = open(args.rom, "rb").read()
    digest = hashlib.sha256(rom).hexdigest()
    if digest != TI84_PLUS_OS_255MP_SHA256:
        raise SystemExit(
            f"ROM SHA-256 mismatch: expected {TI84_PLUS_OS_255MP_SHA256}, got {digest}"
        )

    classes = []
    for cls in range(HANDLER_COUNT):
        ptr, rec = parse_handler_record(rom, cls)
        entry = {"cls": cls, "ptr": ptr}
        if rec:
            entry.update(rec)
        classes.append(entry)
    data = {
        "romSha256": TI84_PLUS_OS_255MP_SHA256,
        "handlerTable": HANDLER_TABLE,
        "classCount": HANDLER_COUNT,
        "classes": classes,
        "descriptors": [parse_descriptor(rom, a) for a in DESCRIPTORS],
        "displayByteMap": parse_display_byte_map(rom),
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(data, f, separators=(",", ":"))
        f.write("\n")
    decoded = sum(1 for c in classes if "rows" in c)
    print(f"wrote {args.out}: {decoded}/{HANDLER_COUNT} classes decoded, "
          f"{len(data['descriptors'])} descriptors, complete 07:44DE tables")


if __name__ == "__main__":
    main()
