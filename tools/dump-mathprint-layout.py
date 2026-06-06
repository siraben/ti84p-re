#!/usr/bin/env python3
"""Dump page-0x39 MathPrint handler records and box descriptors from a ROM."""
import argparse
from pathlib import Path

PAGE = 0x39
HANDLER_TABLE = 0x5E45
HANDLER_COUNT = 0x44
DESCRIPTORS = [0x686F, 0x6880, 0x6893, 0x689C, 0x68A5]


def romoff(page, addr):
    return page * 0x4000 + (addr - 0x4000)


def word(rom, page, addr):
    o = romoff(page, addr)
    return rom[o] | (rom[o + 1] << 8)


def token_name(d, e):
    names = {
        (0x00, 0xC7): "nDeriv(",
        (0x00, 0xC8): "fnInt(",
        (0xFB, 0xC7): "sqDown/template marker",
        (0xFB, 0xC8): "sqUp/template marker",
        (0xFB, 0xCA): "n/d menu string",
        (0xFB, 0xCB): "Un/d menu string",
        (0xFB, 0xD6): "AUTO Answer string",
        (0xFB, 0xD7): "DEC Answer string",
        (0xFB, 0xD8): "FRAC Answer string",
    }
    return names.get((d, e), "")


def fmt_cell(d, e):
    label = token_name(d, e)
    return f"{d:02X}{e:02X}" + (f"={label}" if label else "")


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
    parsed = []
    pos = 0
    for row, (count, action) in enumerate(zip(counts, actions)):
        cells = []
        for i in range(count):
            d = rom[tbase + 2 * (pos + i)]
            e = rom[tbase + 2 * (pos + i) + 1]
            cells.append((d, e))
        parsed.append({"row": row, "count": count, "action": action, "cells": cells})
        pos += count
    return ptr, {"rows": rows, "items": parsed}


def dump_handler_records(rom, only_class=None):
    for cls in range(HANDLER_COUNT):
        if only_class is not None and cls != only_class:
            continue
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            if 0x4000 <= ptr < 0x8000:
                print(f"class {cls:02X}: ptr {ptr:04X} (not a decoded record)")
            else:
                print(f"class {cls:02X}: ptr {ptr:04X} (outside page)")
            continue

        print(f"class {cls:02X}: ptr {ptr:04X} rows={record['rows']}")
        for item in record["items"]:
            cells = [fmt_cell(d, e) for d, e in item["cells"]]
            print(
                f"  row {item['row']}: count={item['count']:02X} "
                f"action={item['action']:02X} {' '.join(cells)}"
            )


def parse_descriptors(rom):
    descriptors = []
    for addr in DESCRIPTORS:
        p = addr
        base = word(rom, PAGE, p)
        p += 2
        box = word(rom, PAGE, p)
        p += 2
        row_height = rom[romoff(PAGE, p)]
        p += 1
        dims = word(rom, PAGE, p)
        p += 2
        cols = dims >> 8
        rows = dims & 0xFF
        cells_ptr = word(rom, PAGE, p)
        cells = []
        for i in range(cols * rows):
            d = rom[romoff(PAGE, cells_ptr + 2 * i)]
            e = rom[romoff(PAGE, cells_ptr + 2 * i + 1)]
            cells.append((d, e))
        descriptors.append(
            {
                "addr": addr,
                "base": base,
                "box": box,
                "row_height": row_height,
                "cols": cols,
                "rows": rows,
                "cells_ptr": cells_ptr,
                "cells": cells,
            }
        )
    return descriptors


def dump_descriptors(rom):
    for desc in parse_descriptors(rom):
        cells = [fmt_cell(d, e) for d, e in desc["cells"]]
        print(
            f"desc {desc['addr']:04X}: base={desc['base']:04X} "
            f"box={desc['box']:04X} row_h={desc['row_height']:02X} "
            f"cols={desc['cols']} rows={desc['rows']} "
            f"cells={desc['cells_ptr']:04X}"
        )
        print("  " + " ".join(cells))


def parse_cell(s):
    text = s.replace(":", "").replace(",", "").strip()
    if len(text) != 4:
        raise argparse.ArgumentTypeError("cell must be two bytes, e.g. 00C8 or FB:C8")
    try:
        value = int(text, 16)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("cell must be hexadecimal") from exc
    return value >> 8, value & 0xFF


def find_cell(rom, target):
    td, te = target
    found = False
    print(f"searching page-39 decoded records/descriptors for {fmt_cell(td, te)}")
    for cls in range(HANDLER_COUNT):
        ptr, record = parse_handler_record(rom, cls)
        if record is None:
            continue
        for item in record["items"]:
            for idx, (d, e) in enumerate(item["cells"]):
                if (d, e) == target:
                    found = True
                    print(
                        f"  class {cls:02X} ptr {ptr:04X} "
                        f"row {item['row']} cell {idx}"
                    )

    for desc in parse_descriptors(rom):
        for idx, (d, e) in enumerate(desc["cells"]):
            if (d, e) == target:
                found = True
                print(
                    f"  desc {desc['addr']:04X} cells {desc['cells_ptr']:04X} "
                    f"cell {idx}"
                )

    if not found:
        print("  no decoded record/descriptor hits")


def token_class(raw):
    """Model eqdisp_dispatch_token's coarse class for single-byte tokens only.

    Two-byte TI tokens such as BB 24 (tFnInt) are normalized before this page-39
    class byte is used, so this helper is intentionally limited to the simple
    `A - 0x2A` path visible at 39:4A74.
    """
    if raw == 0x3D:
        return "special 39:672E"
    cls = raw - 0x2A
    if not 0 <= cls <= 0xFF:
        return "outside coarse single-byte range"
    return f"class {cls:02X}"


def explain_token(raw):
    print(f"raw byte {raw:02X} -> {token_class(raw)}")
    print("notes:")
    print("  - page-39 handler records use normalized class bytes in 0x85DE")
    print("  - display cells like 00C8 are menu/name cells, not raw TI tokens")
    print("  - tFnInt is the two-byte parser token BB 24; it is not a 00C8 cell")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default=Path(__file__).with_name("rom.bin"))
    ap.add_argument("--class", dest="only_class", type=lambda s: int(s, 0))
    ap.add_argument("--descriptors", action="store_true")
    ap.add_argument("--find-cell", type=parse_cell, metavar="HHLL")
    ap.add_argument("--explain-token", type=lambda s: int(s, 0), metavar="BYTE")
    args = ap.parse_args()

    rom = Path(args.rom).read_bytes()
    if args.find_cell is not None:
        find_cell(rom, args.find_cell)
    elif args.explain_token is not None:
        explain_token(args.explain_token)
    elif args.descriptors:
        dump_descriptors(rom)
    else:
        dump_handler_records(rom, args.only_class)


if __name__ == "__main__":
    main()
