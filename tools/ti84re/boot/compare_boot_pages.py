#!/usr/bin/env python3
"""Compare every boot bcall entry in BootFree and retail page 0x3F images."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import sys

from ti84re.rom.bcall_tables import (
    BOOT_TABLE_ID_RANGES,
    boot_target,
    classify_boot_page,
    read_boot_names,
)
from ti84re.rom.image import RomImage
from ti84re.rom.signatures import (
    TI84_PLUS_OS_255MP_BOOTFREE_SHA256,
    TI84_PLUS_OS_255MP_SHA256,
)
from ti84re.paths import SYMBOLS


STUBS = {
    0x531D: "stub-ret",
    0x531E: "stub-A=0x0B-B=0x03",
    0x5323: "stub-A=0x02",
    0x5326: "stub-DE=0x200A",
    0x532A: "stub-ret",
    0x532B: "stub-A=0",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def target_text(target) -> str:
    return f"{target.page:02X}:{target.address:04X}"


def rows(
    bootfree: RomImage,
    retail: RomImage,
    *,
    bootfree_hash: str,
    retail_hash: str,
) -> list[dict[str, str]]:
    names = read_boot_names(SYMBOLS / "ti83plus.inc")
    result = []
    for first, last in BOOT_TABLE_ID_RANGES:
        for identifier in range(first, last + 1, 3):
            left = boot_target(bootfree, identifier, names.get(identifier))
            right = boot_target(retail, identifier, names.get(identifier))
            if left is None or right is None:
                raise ValueError(f"missing populated boot entry 0x{identifier:04X}")
            disposition = STUBS.get(left.address, "implemented")
            result.append({
                "bootfree_rom_sha256": bootfree_hash,
                "retail_rom_sha256": retail_hash,
                "bcall_id": f"0x{identifier:04X}",
                "name": names.get(identifier, "unpublished"),
                "bootfree_target": target_text(left),
                "bootfree_disposition": disposition,
                "retail_target": target_text(right),
                "same_target": str(left.location == right.location).lower(),
            })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootfree-rom", type=Path, required=True)
    parser.add_argument("--retail-rom", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    bootfree_hash = digest(args.bootfree_rom)
    retail_hash = digest(args.retail_rom)
    if bootfree_hash != TI84_PLUS_OS_255MP_BOOTFREE_SHA256:
        parser.error(f"BootFree ROM SHA-256 is {bootfree_hash}")
    if retail_hash != TI84_PLUS_OS_255MP_SHA256:
        parser.error(f"retail ROM SHA-256 is {retail_hash}")
    bootfree = RomImage.from_path(args.bootfree_rom)
    retail = RomImage.from_path(args.retail_rom)
    if classify_boot_page(bootfree) != "bootfree":
        parser.error("BootFree input does not have the BootFree page prefix")
    if classify_boot_page(retail) != "retail":
        parser.error("retail input does not have the retail page prefix")

    fields = (
        "bootfree_rom_sha256", "retail_rom_sha256",
        "bcall_id", "name", "bootfree_target", "bootfree_disposition",
        "retail_target", "same_target",
    )
    stream = args.output.open("w", newline="", encoding="utf-8") if args.output else sys.stdout
    try:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows(
            bootfree,
            retail,
            bootfree_hash=bootfree_hash,
            retail_hash=retail_hash,
        ))
    finally:
        if args.output:
            stream.close()


if __name__ == "__main__":
    main()
