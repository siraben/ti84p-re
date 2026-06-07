#!/usr/bin/env python3
"""Inject the Bad Apple flash app into a TI-84+ ROM image and patch a launch hook,
so headless TilEm (which has no link/file-send) can run it under the OS.

Background (https://github.com/fb39ca4/badapple-ti84): Bad Apple is a 58-page
signed Flash Application that bank-switches its own video/audio pages. The full
app needs an SE-class (2 MB) calc; on a 1 MB 84+ the OS-only image here has 43
erased pages (0x08-0x32), enough for the first ~2.5 min, which is plenty for an
audio capture. The app is relocatable: at entry it reads its own page with
`in a,($06)` and uses relative offsets, so it runs wherever we place it.

Two obstacles this script handles:

1. Launch. Headless TilEm cannot receive a var/app over the link, and replicating
   the OS app-loader (page-3D, garbled in the decompiler) is fragile. Instead we
   inject the app's pages directly and overwrite the entry of `_GetCSC` (ram:04b2,
   a page-0 key scanner the OS calls at the splash/home wait, after full RAM/IY/
   hardware init) with `ld a,APP_PAGE; out($06),a; jp ENTRY`. The app's entry is
   after its 128-byte header, at 0x4080.

2. Flash execution protection (84+ "memory mapping", emulated in TilEm
   x4_memory.c). Executing a flash page in the no-exec range resets the calc:
       if (PORT22 <= page <= PORT23) -> TILEM_EXC_FLASH_EXEC   (reset)
   RAM is the inverse (executable only within [PORT25,PORT26]*0x400). Boot sets
   $22=0x08 (no-exec from page 0x08 up) and $25=0x10,$26=0x20 (RAM exec
   0x9000-0xA000) -- but the app runs its main loop at statVars=0x8A3A. These
   ports are WRITE-LOCKED: a write only takes effect right after the CPU fetches
   the exact unlock sequence `00 00 ED 56 F3 D3` (NOP;NOP;IM1;DI;OUT), which is
   why boot wraps every protection OUT in it. Rather than reproduce the unlock in
   the launch stub, we patch boot's own immediates (its unlock already runs):
       $22 (0x08 -> 0x40)  no flash page in 0x00-0x3F is forbidden
       $25 (0x10 -> 0x00)  RAM exec lower = 0 (covers statVars 0x8A3A)
       $26 (0x20 -> 0xFF)  RAM exec upper = max

Usage: badapple_inject.py CLEAN_ROM APP_BIN OUT_ROM
  CLEAN_ROM : 1 MB TI-84+ OS image (same one Ghidra/TilEm use)
  APP_BIN   : raw signed app (codepages.bin + videopages.bin, pre-rabbitsign join)
  OUT_ROM   : patched ROM to feed `tilem2 --rom OUT_ROM`
"""
import sys

APP_BASE_PAGE = 0x08      # first free erased page
APP_ENTRY = 0x4080        # 0x4000 + 128-byte app header
PAGESZ = 0x4000

# boot immediates (TI-84+ OS 2.55MP, ROM be820cf0...); asserted before patching
OFF_P22 = 0xfc17b         # LD A,$08 value for OUT($22)  -> 0x40
OFF_P25 = 0xfc184         # LD A,$10 value for OUT($25)  -> 0x00
OFF_P26 = 0xfc18d         # LD A,$20 value for OUT($26)  -> 0xff
OFF_GETCSC = 0x04b2       # _GetCSC entry (page 0, always mapped)


def main():
    if len(sys.argv) != 4:
        print(__doc__); sys.exit(2)
    clean, appbin, out = sys.argv[1:4]
    rom = bytearray(open(clean, "rb").read())
    app = open(appbin, "rb").read()
    if len(rom) != 64 * PAGESZ:
        print(f"warning: ROM is {len(rom)} bytes, expected 1 MiB", file=sys.stderr)

    free = 0x33 - APP_BASE_PAGE                       # 0x08..0x32
    npages = (len(app) + PAGESZ - 1) // PAGESZ
    use = min(npages, free)
    for i in range(use):
        seg = app[i * PAGESZ:(i + 1) * PAGESZ]
        rom[(APP_BASE_PAGE + i) * PAGESZ:(APP_BASE_PAGE + i) * PAGESZ + len(seg)] = seg
    if npages > free:
        print(f"note: app is {npages} pages; injected first {use} "
              f"(pages 0x08-0x32). Capture covers the first ~{use*16}KB of video.",
              file=sys.stderr)

    def patch(off, expect, new, what):
        if rom[off] != expect:
            print(f"warning: {what}: expected {expect:#04x} at {off:#x}, "
                  f"found {rom[off]:#04x} (different ROM?)", file=sys.stderr)
        rom[off] = new

    patch(OFF_P22, 0x08, 0x40, "$22 flash no-exec lower")
    patch(OFF_P25, 0x10, 0x00, "$25 RAM exec lower")
    patch(OFF_P26, 0x20, 0xff, "$26 RAM exec upper")

    stub = bytes([0x3E, APP_BASE_PAGE, 0xD3, 0x06,           # ld a,page; out($06),a
                  0xC3, APP_ENTRY & 0xFF, APP_ENTRY >> 8])   # jp ENTRY
    rom[OFF_GETCSC:OFF_GETCSC + len(stub)] = stub

    open(out, "wb").write(rom)
    print(f"wrote {out}: app at flash 0x{APP_BASE_PAGE:02x}, launch hook in _GetCSC, "
          f"flash/RAM exec protection opened.", file=sys.stderr)


if __name__ == "__main__":
    main()
