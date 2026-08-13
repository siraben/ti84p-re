#!/usr/bin/env python3
"""Extract the OS 2.55MP single-byte token display-string table.

`smallfont_glyph_ptr` (`01:6702`) indexes the word table at `01:4252` for a
single-byte token. Each pointer selects a metadata byte followed by a counted
display-code string. The committed artifact lets the browser execute this ROM
lookup without loading the proprietary ROM.

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


def flat(page: int, address: int) -> int:
    return page * 0x4000 + address - 0x4000


def extract(rom: bytes) -> dict[str, object]:
    table = flat(PAGE, POINTER_TABLE)
    entries = []
    for token in range(ENTRY_COUNT):
        pointer = int.from_bytes(rom[table + 2 * token:table + 2 * token + 2],
                                 "little")
        if not 0x4000 <= pointer < 0x8000:
            raise ValueError(f"token 0x{token:02X} points outside page 01")
        offset = flat(PAGE, pointer)
        metadata = rom[offset]
        length = rom[offset + 1]
        if offset + 2 + length > flat(PAGE, 0x8000):
            raise ValueError(f"token 0x{token:02X} string crosses page 01")
        entries.append({
            "pointer": pointer,
            "metadata": metadata,
            "codes": list(rom[offset + 2:offset + 2 + length]),
        })
    return {
        "schema": 1,
        "romSha256": TI84_PLUS_OS_255MP_SHA256,
        "routine": "smallfont_glyph_ptr at 01:6702",
        "singleByte": {
            "page": PAGE,
            "pointerTableAddress": POINTER_TABLE,
            "entries": entries,
        },
        "twoByteLeadBytes": list(TWO_BYTE_LEADS),
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
    print(f"wrote {args.json} ({ENTRY_COUNT} single-byte token strings)")


if __name__ == "__main__":
    main()
