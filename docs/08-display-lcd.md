# 08 — Display / LCD

The TI-84+ drives a **96×64 monochrome LCD** through a controller on I/O ports `0x10` (command) and `0x11` (data). The OS keeps a **graph/screen buffer** in RAM and renders text via a built-in font.

## Controller [standard, consistent with code]
- `port_lcdCmd` (`0x10`): commands — set row/column page, set Y, on/off, contrast.
- `port_lcdData` (`0x11`): read/write a byte of pixels at the current address.
- The panel is organized in 8-pixel-tall **rows**; `_ClrLCDFull` walks row commands `0xB8 → 0x80` (8 rows of 8 px = 64 px tall), calling `_ClearRow` per row with interrupts masked. **[confirmed]**

## Text output [confirmed]
- `curRow`/`curCol` (`0x844B/844C`) — the homescreen text cursor (16 columns wide; `_PutC` wraps at col 16, calls `_NewLine`).
- `_PutMap` (`01:5A98`) draws one character's **8-byte glyph** at the cursor: it clamps invalid codes to `0xD0`, then `cross_page_jump(char * 8)` indexes the font (each glyph = 8 bytes). **[confirmed]**
- `_PutC` (`01:5B4C`) = `_PutMap` + advance cursor + newline handling; `_PutS` prints a string; `_NewLine` scrolls.
- `_DispHL` (`01:5BF6`) prints `HL` as a right-justified 5-digit decimal: repeated `_DivHLBy10`, digits +`0x30`, leading zeros → spaces, using `OP1.mantissa` as a scratch buffer, then `_PutC`/`_PutMap` each digit. **[confirmed]**

## Screen buffers [standard]
- `plotSScreen` (`0x9340`, 768 bytes = 96×64/8) — the main graph/back buffer.
- `saveSScreen` (`0x86EC`, 768 bytes) — saved copy (e.g. for menus over the graph).
- `_GrBufCpy`/`_GrBufClr`-style bcalls blit the buffer to the LCD.

## Fonts [confirmed page; exact base to-pin]
- **Large font**: 8-byte glyphs indexed by `char*8`, used by `_PutMap`/`_PutC` (homescreen). `_PutMap` bjumps (via trampoline `0x3B3D`) to the blitter `put_glyph_large` (`page_07:4588`), which reads the glyph from a table on **page 7** (≈`0x45FF`+`char*8`, copied 8 bytes via `_Mov8B` into `lFont_record`). Two flag bits select **alternate fonts** on page 1 and page 0x36. *(The exact table base needs `FUN_page_07_45eb` traced — a quick render at `0x45FF` didn't line up.)*
- **Small/variable-width font**: `_VPutMap`/`_VPutS` (graph screen, pixel-addressed via `penCol`/`penRow`).

## Indicators
- `flags.indicFlags` bit 0 = the run/busy indicator (the moving dashes top-right); `_ClrLCDFull` preserves it across a clear; `_RunIndicOn`/`Off` toggle it. **[confirmed]**

## TODO
- Confirm exact LCD command bytes (contrast set, X/Y addressing) by tracing `_ClearRow` and the buffer-copy routines.
- Map the large-font glyph table location (the `cross_page_jump` target page in `_PutMap`).
