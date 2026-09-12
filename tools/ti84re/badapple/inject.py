#!/usr/bin/env python3
"""Inject a partial Bad Apple app fixture and patch an emulator launch hook.

Background (https://github.com/fb39ca4/badapple-ti84): Bad Apple is a 58-page
signed Flash Application that bank-switches its own video/audio pages. The full
app needs an SE-class (2 MB) calc. The canonical retail image has 39 contiguous
erased pages at 0x08-0x2E; page 0x2F contains the boot USB stack and must not be
overwritten. This deliberately partial injection is an emulator experiment,
not a complete installed app. The app is relocatable: at entry it reads its own page with
`in a,(0x06)` and uses relative offsets, so it runs wherever we place it.

Two obstacles this script handles:

1. Launch. This experiment bypasses link installation and the OS app loader.
   It injects the app's pages directly and overwrites `_GetCSC` (ram:04b2,
   a page-0 key scanner the OS calls at the splash/home wait, after full RAM/IY/
   hardware init) with `ld a,APP_PAGE; out(0x06),a; jp ENTRY`. The app's entry is
   after its 128-byte header, at 0x4080.

2. Flash execution protection (emulated in TilEm x4_memory.c). Executing a
   Flash page in the no-execute range resets the calculator:
       if (PORT22 <= page <= PORT23) -> TILEM_EXC_FLASH_EXEC   (reset)
   RAM is the inverse (executable only within inclusive 1 KiB chunks
   [PORT25,PORT26]). Boot sets PORT22=0x08,PORT23=0x29 (TilEm no-execute pages
   0x08-0x29) and PORT25=0x10,PORT26=0x20 (permitted masked physical RAM
   chunks). The app runs copied code at statVars=0x8A3A; its physical backing
   depends on the active bank-B mapping. This experiment relaxes both bounds. TilEm
   accepts these protected outputs after its privileged-page byte-sequence
   gate. Rather than reproduce that emulator-specific gate in the launch stub,
   we patch the boot's own immediates:
       PORT22 (0x08 -> 0x40)  reverse the Flash no-execute interval
       PORT25 (0x10 -> 0x00)  lower the RAM execution bound
       PORT26 (0x20 -> 0xFF)  raise the RAM execution bound

Usage: python3 -m ti84re.badapple.inject CLEAN_ROM APP_BIN OUT_ROM
  CLEAN_ROM : 1 MB TI-84+ OS image (same one Ghidra/TilEm use)
  APP_BIN   : raw app (codepages.bin + videopages.bin, pre-rabbitsign join)
  OUT_ROM   : patched ROM to feed `tilem2 --rom OUT_ROM`
"""
import hashlib
from pathlib import Path
import sys

from ti84re.rom.signatures import TI84_PLUS_OS_255MP_SHA256

APP_BASE_PAGE = 0x08      # first free erased page
APP_ENTRY = 0x4080        # 0x4000 + 128-byte app header
PAGESZ = 0x4000

# Canonical retail boot immediates; checked before patching.
OFF_P22 = 0xfc1e0         # 3F:41DF LD A,$08; OUT($22) at 41E6
OFF_P25 = 0xfc1f4         # 3F:41F3 LD A,$10; OUT($25) at 41FA
OFF_P26 = 0xfc1fe         # 3F:41FD LD A,$20; OUT($26) at 4204
OFF_GETCSC = 0x04b2       # _GetCSC entry (page 0, always mapped)
APP_LIMIT_PAGE = 0x2F    # exclusive: preserve the retail USB stack
APP_FIRST_PAGE = APP_LIMIT_PAGE - 1  # TI Flash apps traverse decreasing pages


def inject_rom(clean_rom: bytes, app: bytes) -> bytes:
    """Build a partial emulator fixture without altering occupied OS pages."""
    if hashlib.sha256(clean_rom).hexdigest() != TI84_PLUS_OS_255MP_SHA256:
        raise ValueError("Bad Apple injection requires the canonical retail OS 2.55MP ROM")
    if len(app) < 128:
        raise ValueError("application must include its 128-byte header")
    rom = bytearray(clean_rom)
    free = APP_LIMIT_PAGE - APP_BASE_PAGE
    if rom[APP_BASE_PAGE * PAGESZ:APP_LIMIT_PAGE * PAGESZ] != b"\xFF" * (free * PAGESZ):
        raise ValueError("application target pages are not erased")
    npages = (len(app) + PAGESZ - 1) // PAGESZ
    use = min(npages, free)
    for i in range(use):
        seg = app[i * PAGESZ:(i + 1) * PAGESZ]
        destination = (APP_FIRST_PAGE - i) * PAGESZ
        rom[destination:destination + len(seg)] = seg
    if npages > free:
        print(f"note: app is {npages} pages; injected first {use} "
              f"(pages 0x08-0x2E); later app pages are unavailable.",
              file=sys.stderr)

    def patch(off, expect, new, what):
        if rom[off] != expect:
            raise ValueError(f"{what}: expected {expect:#04x} at {off:#x}, "
                             f"found {rom[off]:#04x}")
        rom[off] = new

    patch(OFF_P22, 0x08, 0x40, "$22 flash no-exec lower")
    patch(OFF_P25, 0x10, 0x00, "$25 RAM exec lower")
    patch(OFF_P26, 0x20, 0xff, "$26 RAM exec upper")

    stub = bytes([0x3E, APP_FIRST_PAGE, 0xD3, 0x06,          # ld a,page; out($06),a
                  0xC3, APP_ENTRY & 0xFF, APP_ENTRY >> 8])   # jp ENTRY
    rom[OFF_GETCSC:OFF_GETCSC + len(stub)] = stub

    return bytes(rom)


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    clean, appbin, out = map(Path, sys.argv[1:4])
    try:
        if out.resolve() in (clean.resolve(), appbin.resolve()) or (
            out.exists() and any(out.samefile(source) for source in (clean, appbin))
        ):
            raise ValueError("output must not overwrite either input")
        rom = inject_rom(clean.read_bytes(), appbin.read_bytes())
    except ValueError as error:
        sys.exit(str(error))
    out.write_bytes(rom)
    print(f"wrote {out}: app at flash 0x{APP_FIRST_PAGE:02x} descending, launch hook in _GetCSC, "
          f"flash/RAM exec protection opened.", file=sys.stderr)


if __name__ == "__main__":
    main()
