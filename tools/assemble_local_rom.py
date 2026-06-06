#!/usr/bin/env python3
"""Assemble the local complete TI-84 Plus ROM image from ignored artifacts.

Inputs are copyrighted and intentionally gitignored:
  tools/roms/ti84plus_patched.rom
  tools/roms/D84PBE1.8Xv
  tools/roms/D84PBE2.8Xv

D84PBE1 is the retail boot page, installed as page 0x3F.
D84PBE2 is the USB/OS-receive boot support page, installed as page 0x2F.
"""
from pathlib import Path
import os
import sys


HERE = Path(__file__).resolve().parent
ROMS = HERE / "roms"
BASE_ROM = ROMS / "ti84plus_patched.rom"
BOOT_PAGE_APPVAR = ROMS / "D84PBE1.8Xv"
USB_PAGE_APPVAR = ROMS / "D84PBE2.8Xv"
OUT_ROM = ROMS / "ti84plus_2.55mp_complete.rom"
ROM_LINK = HERE / "rom.bin"
PAGE0 = HERE / "ti84_page00.bin"

PAGE_SIZE = 0x4000
ROM_SIZE = 0x100000
APPVAR_PAYLOAD_OFFSET = 0x4A


def read_appvar_page(path: Path) -> bytes:
    data = path.read_bytes()
    payload = data[APPVAR_PAYLOAD_OFFSET:APPVAR_PAYLOAD_OFFSET + PAGE_SIZE]
    if len(payload) != PAGE_SIZE:
        raise SystemExit(f"{path} does not contain a 16 KiB payload at offset 0x4A")
    return payload


def patch_page(rom: bytearray, page: int, payload: bytes) -> None:
    start = page * PAGE_SIZE
    rom[start:start + PAGE_SIZE] = payload


def relpath(path: Path, start: Path) -> str:
    return os.path.relpath(path, start)


def main() -> None:
    missing = [p for p in (BASE_ROM, BOOT_PAGE_APPVAR, USB_PAGE_APPVAR) if not p.exists()]
    if missing:
        names = "\n".join(f"  {p}" for p in missing)
        raise SystemExit(f"missing local ROM artifact(s):\n{names}")

    rom = bytearray(BASE_ROM.read_bytes())
    if len(rom) != ROM_SIZE:
        raise SystemExit(f"{BASE_ROM} is {len(rom)} bytes, expected {ROM_SIZE}")

    boot_page = read_appvar_page(BOOT_PAGE_APPVAR)
    usb_page = read_appvar_page(USB_PAGE_APPVAR)
    patch_page(rom, 0x3F, boot_page)
    patch_page(rom, 0x2F, usb_page)

    ROMS.mkdir(exist_ok=True)
    OUT_ROM.write_bytes(rom)
    PAGE0.write_bytes(rom[:PAGE_SIZE])

    try:
        ROM_LINK.unlink()
    except FileNotFoundError:
        pass
    ROM_LINK.symlink_to(relpath(OUT_ROM, HERE))

    print(f"wrote {OUT_ROM}")
    print(f"wrote {PAGE0}")
    print(f"linked {ROM_LINK} -> {os.readlink(ROM_LINK)}")
    page2f = 0x2F * PAGE_SIZE
    page3f = 0x3F * PAGE_SIZE
    print("page 2F start:", rom[page2f:page2f + 16].hex(" ").upper())
    print("page 2F:4145:", rom[page2f + 0x145:page2f + 0x155].hex(" ").upper())
    print("page 3F start:", rom[page3f:page3f + 16].hex(" ").upper())


if __name__ == "__main__":
    sys.exit(main())
