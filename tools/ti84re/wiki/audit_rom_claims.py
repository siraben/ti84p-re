"""Check the wiki's address catalogs against the canonical ROM and name inputs.

This audit establishes mappings and byte identities, not routine semantics or
runtime coverage. It never rewrites a registry or generated evidence file.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from ti84re.paths import DEFAULT_ROM, ROOT
from ti84re.rom.bcall_tables import read_boot_names, read_main_names
from ti84re.rom.signatures import TI84_PLUS_OS_255MP_SHA256


INDEX_ROW = re.compile(
    r"^\| `([^`]+)` \| `([0-9A-Fa-f]{4})` \| `([0-9A-Fa-f]{2}):([0-9A-Fa-f]{4})` \|$",
    re.MULTILINE,
)
INFERRED_BOOT_NAMES = {
    0x804E: "certificate_reconcile_id_fields",
    0x8066: "certificate_find_matching_field_data",
    0x8069: "certificate_count_matching_fields",
    0x810B: "usb_set_port81_bit0_delay",
}


def audit(rom: bytes, root: Path = ROOT) -> dict[str, object]:
    identity = hashlib.sha256(rom).hexdigest()
    if identity != TI84_PLUS_OS_255MP_SHA256:
        raise ValueError("claim audit requires the canonical retail ROM identity")
    symbols = root / "tools/symbols"
    main = read_main_names(symbols / "bcalls.txt")
    boot = read_boot_names(symbols / "ti83plus.inc")
    issues: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            issues.append(message)

    def target(identifier: int) -> tuple[int, int]:
        # Decode directly, independently of the target resolver used to generate
        # the catalogs. The dispatcher selects 3B or 3F from the ID's high bits.
        offset = (0x3B * 0x4000 + identifier - 0x4000 if identifier < 0x8000
                  else 0x3F * 0x4000 + identifier - 0x8000)
        raw = rom[offset:offset + 3]
        return raw[2] & 0x3F, int.from_bytes(raw[:2], "little")

    require(len(main) == 645, f"main name count: {len(main)}, expected 645")
    require(len(boot) == 83, f"SDK boot name count: {len(boot)}, expected 83")
    for filename, names in (("bcall_targets.txt", main), ("bcalls8x_targets.txt", boot)):
        seen: set[int] = set()
        for line in (symbols / filename).read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            name, identifier_text, address_text, page_text = line.split()
            identifier = int(identifier_text, 16)
            require(identifier not in seen, f"{filename}: duplicate {identifier:04X}")
            seen.add(identifier)
            require(names.get(identifier) == name, f"{filename}: name at {identifier:04X}")
            require(target(identifier) == (int(page_text, 16), int(address_text, 16)),
                    f"{filename}: target at {identifier:04X}")
        require(seen == names.keys(), f"{filename}: missing or extra IDs")

    expected_names = main | boot | INFERRED_BOOT_NAMES
    wiki_rows = []
    for line_number, line in enumerate((root / "docs/bcall-index.md").read_text().splitlines(), 1):
        line = line.strip()
        if not line.startswith("|") or line.startswith("| bcall |") or re.fullmatch(r"[| :\-]+", line):
            continue
        match = INDEX_ROW.fullmatch(line)
        if match is None:
            issues.append(f"bcall index: malformed table row at line {line_number}")
        else:
            wiki_rows.append(match.groups())
    seen = set()
    for name, identifier_text, page_text, address_text in wiki_rows:
        identifier = int(identifier_text, 16)
        require(identifier not in seen, f"bcall index: duplicate {identifier:04X}")
        seen.add(identifier)
        require(expected_names.get(identifier) == name, f"bcall index: name at {identifier:04X}")
        require(target(identifier) == (int(page_text, 16), int(address_text, 16)),
                f"bcall index: target at {identifier:04X}")
    require(seen == expected_names.keys(), "bcall index: missing or extra IDs")
    page_counts = Counter(target(identifier)[0] for identifier in main)
    page_rows = []
    in_page_table = False
    for line_number, line in enumerate((root / "docs/flash-page-map.md").read_text().splitlines(), 1):
        line = line.strip()
        if line.startswith("## "):
            in_page_table = line.startswith("## OS pages")
        if not in_page_table or not line.startswith("|"):
            continue
        if line.startswith("| Page |") or re.fullmatch(r"[| :\-]+", line):
            continue
        match = re.match(r"^\| `([0-9A-Fa-f]{2})` \| (\d+) \|", line)
        if match is None:
            issues.append(f"Flash page map: malformed count row at line {line_number}")
        else:
            page_rows.append(match.groups())
    require(len(page_rows) == len(page_counts), "Flash page map: missing or extra count rows")
    require({int(page, 16): int(count) for page, count in page_rows} == page_counts,
            "Flash page map: main-table row counts")
    require(all((identifier - 0x4000) % 3 == 0 for identifier in main),
            "main table: unaligned ID")
    expected_boot = set(range(0x8018, 0x80D3, 3)) | set(range(0x80E4, 0x812A, 3))
    require(boot.keys() | INFERRED_BOOT_NAMES.keys() == expected_boot,
            "boot table: slot coverage differs from both populated ranges")

    jumps = []
    for line in (symbols / "bjumps.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            source, address, page = (int(field, 16) for field in line.split())
            jumps.append(source)
            raw = rom[source:source + 6]
            require(raw[:3] == bytes.fromhex("CD092B") and
                    int.from_bytes(raw[3:5], "little") == address and
                    raw[5] & 0x3F == page, f"bjump descriptor: {source:04X}")
    require(jumps == list(range(0x3B01, 0x3D0B, 6)), "bjump table: slot coverage")
    require(rom[0x3D0B:0x3D0E] == bytes.fromhex("CD492B"), "bjump table: end boundary")
    vectors = {8: 0x1A2F, 0x10: 0x0E65, 0x18: 0x155C, 0x20: 0x1B01,
               0x28: 0x2A2F, 0x30: 0x229E}
    for source, destination in vectors.items():
        require(rom[source:source + 3] == b"\xc3" + destination.to_bytes(2, "little"),
                f"RST vector: {source:04X}")
    blank_pages = [page for page in range(64)
                   if rom[page * 0x4000:(page + 1) * 0x4000] == b"\xff" * 0x4000]
    require(blank_pages == list(range(8, 0x2F)) + list(range(0x30, 0x33)), "blank page ranges")
    require(rom[0x3C * 0x4000:0x3C * 0x4000 + 6] == b"2.55MP", "OS version string")
    return {
        "rom_sha256": identity,
        "scope": "bcall catalogs, bjump descriptors, RST vectors, blank pages, version bytes",
        "main_rows": len(main), "sdk_boot_rows": len(boot),
        "inferred_boot_rows": len(INFERRED_BOOT_NAMES), "wiki_rows": len(wiki_rows),
        "bjump_rows": len(jumps), "blank_pages": len(blank_pages),
        "issues": issues,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    args = parser.parse_args()
    try:
        report = audit(args.rom.read_bytes())
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))
    if report["issues"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
