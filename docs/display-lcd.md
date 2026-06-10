# Display & LCD

> **Deep dives:** [Graphing](sub-graphing.md) (graph buffer → LCD, transforms) · [Table & Y= Variables](sub-table-yvars.md) (text grid).

The TI-84+ shows a `96×64` monochrome image — the OS only ever drives a 96×64 region (`_ClrLCDFull` clears all 768 bytes of it: 8 row-passes × 12 columns × 8 data bytes). The underlying controller (Toshiba T6K04 / later Novatek) has wider video RAM (up to 128 px), so 96×64 is the *visible* area, not the controller's geometry. It is reached through I/O ports `0x10` (command) and `0x11` (data). The OS keeps a graph/screen buffer in RAM and renders text via a built-in font.

## Controller [confirmed against code]
- `port_lcdCmd` (`0x10`): commands — set row, set column, set Y, on/off, contrast.
- `port_lcdData` (`0x11`): read/write a byte of pixels at the current address.
- The panel is organized in 8-pixel-tall rows; `_ClrLCDFull` (`01:60E4`) loads `A=0xB8`, subtracts `8` each pass and stops at `0x80` → row commands `0xB8 … 0x80` (8 rows of 8 px = 64 px tall), calling `_ClearRow` per row with interrupts masked (`DI`). [confirmed]
- **Command bytes** (all grounded in `_ClrLCDFull`/`_ClearRow`/`lcd_set_col_cmd`):
  - **Row (page) select** = `0xB8 − 8·row` for `row = 0…7` (i.e. `0xB8, 0xB0, … 0x80`), sent to `0x10` via `lcd_set_col_cmd` (`01:5A89`), which only emits the byte when `0x80 ≤ A < 0xC0` (guards the row/Z-address range). `_ClrLCDFull` walks this by loading `A=0xB8`, calling `_ClearRow`, then `SUB 0x8` and looping while `A ≥ 0x80` (`B=0x80`).
  - **Column select** = `0x20 + col`, sent *raw* to `0x10`. `_ClearRow` (`01:6934`) walks `E` from `0x20` to `0x2B` (`CP 0x2C` terminates) = 12 columns (12 bytes × 8 px = 96 px wide), writing 8 data bytes to `0x11` per column — the `B=0x08` inner `djnz` loop writes one byte per pixel row (8 rows). [confirmed]
  - **Contrast**: `lcd_set_contrast` (`01:5A59`) writes the contrast level to the *data* port `0x11`; `lcd_get_contrast` (`01:5A60`) reads it back from the controller with `IN A,(0x11)` (the standard dummy+real LCD read), not a command re-send. The level is also held in RAM at `contrast` (`0x8447`); the *command-port* form `(contrast+0x18)|0xC0` is what `_LCD_DRIVERON` (page 06) and the `_GetKey` contrast keys send to `0x10`. [confirmed]
  - Every port access is preceded by `CALL ram:0CC3` (`lcd_wait`), the controller-busy delay. [confirmed]

## Text output [confirmed]
- `curRow`/`curCol` (`0x844B/844C`) — the homescreen text cursor (16 columns wide; `_PutC` wraps at col 16, calls `_NewLine`).
- `_PutMap` (`01:5A98`) draws one large-font character at the cursor: it clamps invalid codes to `0xD0`, computes an initial `char * 8` offset, then bjumps to the page-7 large-font blitter, which adjusts that offset to the actual `7-byte-stride` glyph table before copying an 8-byte render record. [confirmed]
- `_PutC` (`01:5B4C`) = `_PutMap` + advance cursor + newline handling; `_PutS` prints a string; `_NewLine` scrolls.
- `_DispHL` (`01:5BF6`) prints `HL` as a right-justified 5-digit decimal: repeated `_DivHLBy10`, digits +`0x30`, leading zeros → spaces, writing the digits backward from `0x847C` into the `OP1` scratch area, then `_PutC`/`_PutMap` each digit. [confirmed]

## Screen buffers [standard]
- `plotSScreen` (`0x9340`, 768 bytes = 96×64/8) — the main graph/back buffer.
- `saveSScreen` (`0x86EC`, 768 bytes) — saved copy (e.g. for menus over the graph).
- `_GrBufCpy` (`04:60A3`) blits `plotSScreen` to the LCD; `_GrBufClr` (`04:6071`) zero-fills the 768-byte graph buffer (`LD HL,0x9340; LD (HL),0; LDIR`) and does not touch the LCD.

## Fonts [confirmed]
- **Large font**: glyph table is on page 7, base `07:45FF`, with a `7-byte stride` per glyph (not 8). `_PutMap` (`01:5A98`) clamps the code (`0` or `≥0xF8` → `0xD0`), computes `HL = char*8` (three `ADD HL,HL`), then bjumps via trampoline `ram:3B3D` to the blitter `put_glyph_large` (`07:4588`). The blitter does `HL = 07:45FF + char*8`, then `lgfont_glyph_ptr_adjust` (`07:45EB`) subtracts `char` (it shifts `char*8` right by 3 → `char`, then `SBC HL,DE`), yielding the real glyph pointer **`07:45FF + char*7`**. It then copies an 8-byte record via `_Mov8B` (`ram:1A94`, 8× `LDI`) into RAM at `0x845A` (`lFont_record`), which the renderer blits. [confirmed] *(The stride is 7 bytes while the copy is 8 bytes — the 8th byte overlaps the next glyph's first row — so the table packs glyphs at `07:45FF + char*7`.)*
- **Alternate large fonts**: two bits in `(IY+0x35)` select a replacement glyph source before the page-7 table read — bit 5 loads `A=0x01` and calls `ram:36E7` (bjump to `3B:7BFB`), bit 1 loads `A=0x76` and calls `ram:3E1F` (bjump to `3B:7B9C`); both are font-hook routines on page `3B` that take the `A` value as a selector. When neither bit is set, the page-7 table at `07:45FF` is used. [confirmed]
- **Small/variable-width font**: `_VPutMap`/`_VPutS` (graph screen, pixel-addressed via `penCol`/`penRow`).

## Indicators
- `flags.indicFlags` bit 0 = the run/busy indicator (the moving dashes top-right); `_ClrLCDFull` preserves it across a clear; `_RunIndicOn` / `_RunIndicOff` toggle it. [confirmed]

## LCD command bytes and glyph table
- **LCD command bytes confirmed** by tracing `_ClrLCDFull` (`01:60E4`), `_ClearRow` (`01:6934`) and `lcd_set_col_cmd` (`01:5A89`): row (page) select = `0xB8 − 8·row` (range `0xB8 … 0x80`, stepping down by 8), column select = `0x20 + col` (range `0x20 … 0x2B`, 12 columns = 96 px), command port `0x10` / data port `0x11`, busy-wait via `ram:0CC3`. Contrast is held at RAM `contrast` (`0x8447`) and written to the data port `0x11` by `lcd_set_contrast` (`01:5A59`). See [Controller](#controller-confirmed-against-code). [confirmed]
- **Large-font glyph table pinned**: page `0x07`, base `07:45FF`, `7-byte stride` (`put_glyph_large` @ `07:4588` → glyph ptr `07:45FF + char*7` via `07:45EB`, then `_Mov8B` copies an 8-byte record to RAM `0x845A`). See [Fonts](#fonts-confirmed) and [Flash Page Map](flash-page-map.md). [confirmed]
