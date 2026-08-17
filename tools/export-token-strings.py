#!/usr/bin/env python3
"""Extract the OS 2.55MP token and MathPrint cell display strings.

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
KEY_TO_STRING_POINTER_TABLE = 0x6E05
KEY_TO_STRING_POINTER_COUNT = 0x65
KEY_TO_STRING_SPECIAL_TABLE = 0x6DDE
KEY_TO_STRING_SPECIAL_COUNT = 0x0D
KEY_TO_STRING_LITERAL_1040 = 0x6F4D
MATHPRINT_INLINE_STRINGS = (
    (0xFB, 0xC8, 0x6BB2, True),
    (0xFB, 0xCA, 0x6BA9, False),
    (0xFB, 0xCB, 0x6BAD, False),
    (0xFB, 0xD6, 0x6BBF, False),
    (0xFB, 0xD7, 0x6BD7, False),
    (0xFB, 0xD8, 0x6BCB, False),
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


def counted_string(rom: bytes, page: int, pointer: int, label: str) -> dict:
    if not 0x4000 <= pointer < 0x8000:
        raise ValueError(f"{label} points outside page {page:02X}")
    offset = flat(page, pointer)
    length = rom[offset]
    if length > 0x10 or pointer + 1 + length > 0x8000:
        raise ValueError(f"{label} has invalid counted length 0x{length:02X}")
    return {
        "pointer": pointer,
        "codes": list(rom[offset + 1:offset + 1 + length]),
    }


def extract_key_to_string(rom: bytes) -> dict[str, object]:
    table = flat(PAGE, KEY_TO_STRING_POINTER_TABLE)
    pointers = [
        int.from_bytes(rom[table + 2 * index:table + 2 * index + 2], "little")
        for index in range(KEY_TO_STRING_POINTER_COUNT)
    ]
    entries = [
        counted_string(rom, PAGE, pointers[index],
                       f"_KeyToString index 0x{index:02X}")
        for index in range(KEY_TO_STRING_POINTER_COUNT)
    ]
    specials = []
    for index in range(KEY_TO_STRING_SPECIAL_COUNT):
        address = KEY_TO_STRING_SPECIAL_TABLE + 3 * index
        offset = flat(PAGE, address)
        value = rom[offset]
        pointer = int.from_bytes(rom[offset + 1:offset + 3], "little")
        specials.append({
            "value": value,
            **counted_string(
                rom, PAGE, pointer,
                f"_KeyToString high-byte special 0x{value:02X}",
            ),
        })
    return {
        "page": PAGE,
        "routine": "01:6D10–6DBC",
        "pointerTableAddress": KEY_TO_STRING_POINTER_TABLE,
        "pointerWords": pointers,
        "semanticEntries": entries,
        "highByteSpecialTableAddress": KEY_TO_STRING_SPECIAL_TABLE,
        "highByteSpecials": specials,
        "special1040": counted_string(
            rom, PAGE, KEY_TO_STRING_LITERAL_1040,
            "_KeyToString 10:40 literal",
        ),
    }


def extract_mathprint_inline_strings(rom: bytes) -> dict[str, object]:
    return {
        "page": 0x39,
        "routine": "39:6B62–6BA8",
        "entries": [
            {
                "cell": [lead, second],
                "requiresHBit0": requires_h_bit0,
                **counted_string(
                    rom, 0x39, pointer,
                    f"MathPrint inline string {lead:02X}:{second:02X}",
                ),
            }
            for lead, second, pointer, requires_h_bit0
            in MATHPRINT_INLINE_STRINGS
        ],
    }


def extract(rom: bytes) -> dict[str, object]:
    single_byte = extract_table(rom, POINTER_TABLE, ENTRY_COUNT, "single byte")
    single_byte["page"] = PAGE
    tables = {
        name: extract_table(rom, address, count, f"two-byte table {name}")
        for name, address, count in TWO_BYTE_TABLES
    }
    return {
        "schema": 3,
        "romSha256": TI84_PLUS_OS_255MP_SHA256,
        "routine": "smallfont_glyph_ptr at 01:6702",
        "singleByte": single_byte,
        "twoByte": {
            "page": PAGE,
            "leadBytes": list(TWO_BYTE_LEADS),
            "tables": tables,
            "bbClampIndex": 0xF6,
        },
        "keyToString": extract_key_to_string(rom),
        "mathPrintInlineStrings": extract_mathprint_inline_strings(rom),
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
        f"({ENTRY_COUNT} single-byte, {two_byte_count} two-byte, "
        f"{KEY_TO_STRING_POINTER_COUNT} _KeyToString, and "
        f"{len(MATHPRINT_INLINE_STRINGS)} inline entries)"
    )


if __name__ == "__main__":
    main()
