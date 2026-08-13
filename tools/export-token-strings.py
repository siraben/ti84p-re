#!/usr/bin/env python3
"""Extract the OS 2.55MP token display-string tables.

`smallfont_glyph_ptr` (`01:6702`) selects a word table from the token's lead
byte, then indexes it with the token byte. Each pointer selects a metadata byte
followed by a counted display-code string. The committed artifact lets the
browser execute this ROM lookup without loading the proprietary ROM.

Usage: python3 tools/export-token-strings.py [--rom tools/rom.bin]
"""

import argparse
import hashlib
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256


PAGE = 0x01
POINTER_TABLE = 0x4252
ENTRY_COUNT = 0x100
TWO_BYTE_LEADS = (0x5C, 0x5D, 0x5E, 0x60, 0x61, 0x62,
                  0x63, 0x7E, 0xAA, 0xBB, 0xEF)
TWO_BYTE_TABLES = (
    # name, pointer-table address, exported index count
    ("5C", 0x4452, 0x0A),
    ("5D", 0x4466, 0x06),
    ("5E10", 0x4472, 0x0A),
    ("5E20", 0x4486, 0x0C),
    ("5E40", 0x449E, 0x06),
    ("5E80", 0x44AA, 0x03),
    ("60", 0x44B0, 0x0A),
    ("61", 0x44C4, 0x0A),
    ("AA", 0x44D8, 0x0A),
    # Index zero is the ROM's question-mark fallback. Valid 62h tokens start
    # at index 01h, so it remains part of the indexed table.
    ("62", 0x44EC, 0x3D),
    ("63", 0x4566, 0x38),
    # Indices 00h..12h are the valid graph-format tokens. The branch from
    # 01:6756 enters at 01:677A and does not execute the unrelated CP 13h code
    # at 01:6774, so invalid indices are not given a fabricated clamp target.
    ("7E", 0x45D6, 0x13),
    # BBh indices F6h..FFh clamp to F6h. That final pointer aliases the first
    # EFh entry at 01:47E8 and is exported so the browser can apply the clamp.
    ("BB", 0x45FC, 0xF7),
    # The EFh pointer array ends after index 40h. Later words are unrelated
    # page-01 data and must not be interpreted as token-string pointers.
    ("EF", 0x47E8, 0x41),
)


def flat(page: int, address: int) -> int:
    return page * 0x4000 + address - 0x4000


def extract_table(rom: bytes, address: int, count: int, label: str) -> dict:
    table = flat(PAGE, address)
    entries = []
    for token in range(count):
        pointer = int.from_bytes(rom[table + 2 * token:table + 2 * token + 2],
                                 "little")
        if not 0x4000 <= pointer < 0x8000:
            raise ValueError(
                f"{label} index 0x{token:02X} points outside page 01"
            )
        offset = flat(PAGE, pointer)
        metadata = rom[offset]
        length = rom[offset + 1]
        if offset + 2 + length > flat(PAGE, 0x8000):
            raise ValueError(f"{label} index 0x{token:02X} crosses page 01")
        entries.append({
            "pointer": pointer,
            "metadata": metadata,
            "codes": list(rom[offset + 2:offset + 2 + length]),
        })
    return {
        "pointerTableAddress": address,
        "entries": entries,
    }


def extract(rom: bytes) -> dict[str, object]:
    single_byte = extract_table(rom, POINTER_TABLE, ENTRY_COUNT, "single byte")
    single_byte["page"] = PAGE
    tables = {
        name: extract_table(rom, address, count, f"two-byte table {name}")
        for name, address, count in TWO_BYTE_TABLES
    }
    return {
        "schema": 2,
        "romSha256": TI84_PLUS_OS_255MP_SHA256,
        "routine": "smallfont_glyph_ptr at 01:6702",
        "singleByte": single_byte,
        "twoByte": {
            "page": PAGE,
            "leadBytes": list(TWO_BYTE_LEADS),
            "tables": tables,
            "bbClampIndex": 0xF6,
        },
    }


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=root / "tools" / "rom.bin")
    parser.add_argument(
        "--json", type=Path,
        default=root / "web" / "mathprint" / "token-strings.json",
    )
    args = parser.parse_args()
    if not args.rom.exists():
        raise SystemExit(f"ROM image not found: {args.rom} (copyrighted, gitignored)")
    rom = args.rom.read_bytes()
    digest = hashlib.sha256(rom).hexdigest()
    if digest != TI84_PLUS_OS_255MP_SHA256:
        raise SystemExit(
            "ROM SHA-256 mismatch: "
            f"expected {TI84_PLUS_OS_255MP_SHA256}, got {digest}"
        )
    data = extract(rom)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    two_byte_count = sum(count for _, _, count in TWO_BYTE_TABLES)
    print(
        f"wrote {args.json} "
        f"({ENTRY_COUNT} single-byte and {two_byte_count} two-byte table entries)"
    )


if __name__ == "__main__":
    main()
