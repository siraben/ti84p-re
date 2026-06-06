# 08 — Display / LCD

> **Deep dives:** [Graphing](sub-graphing.md) (graph buffer → LCD, transforms) · [Table & Y= Variables](sub-table-yvars.md) (text grid).

The TI-84+ shows a **96×64 monochrome** image — the OS only ever drives a 96×64 region (`_ClrLCDFull` writes exactly 12 column-bytes × 8 rows). The underlying controller (Toshiba T6K04 / later Novatek) has wider video RAM (up to 128 px), so 96×64 is the *visible* area, not the controller's geometry. It is reached through I/O ports `0x10` (command) and `0x11` (data). The OS keeps a **graph/screen buffer** in RAM and renders text via a built-in font.

## Controller [confirmed against code]
- `port_lcdCmd` (`0x10`): commands — set row, set column, set Y, on/off, contrast.
- `port_lcdData` (`0x11`): read/write a byte of pixels at the current address.
- The panel is organized in 8-pixel-tall **rows**; `_ClrLCDFull` (`01:60E4`) loads `A=0xB8`, subtracts `8` each pass and stops at `0x80` → **row commands `0xB8 … 0x80`** (8 rows of 8 px = 64 px tall), calling `_ClearRow` per row with interrupts masked (`DI`). **[confirmed]**
- **Command bytes** (all grounded in `_ClrLCDFull`/`_ClearRow`/`lcd_set_col_cmd`):
  - **Row (page) select** = `0xB8 − 8·row` for `row = 0…7` (i.e. `0xB8, 0xB0, … 0x80`), sent to `0x10` via `lcd_set_col_cmd` (`01:5A89`), which only emits the byte when `0x80 ≤ A < 0xC0` (guards the row/Z-address range). `_ClrLCDFull` walks this by loading `A=0xB8`, calling `_ClearRow`, then `SUB 0x8` and looping while `A ≥ 0x80` (`B=0x80`).
  - **Column select** = `0x20 + col`, sent **raw** to `0x10`. `_ClearRow` (`01:6934`) walks `E` from **`0x20` to `0x2B`** (`CP 0x2C` terminates) = **12 columns** (12 bytes × 8 px = 96 px wide), writing one data byte to `0x11` per column (`B=0x08` inner loop = 8 rows of pixels). **[confirmed]**
  - **Contrast**: `lcd_set_contrast` (`01:5A59`) writes the contrast level to the **data** port `0x11`; the level is held in RAM at `contrast` (`0x8447`) and re-sent as a command via `lcd_set_col_cmd` on read-back (`lcd_get_contrast`, `01:5A60`). **[confirmed]**
  - Every port access is preceded by `CALL 0x0CC3` (`lcd_wait`), the controller-busy delay. **[confirmed]**

## Text output [confirmed]
- `curRow`/`curCol` (`0x844B/844C`) — the homescreen text cursor (16 columns wide; `_PutC` wraps at col 16, calls `_NewLine`).
- `_PutMap` (`01:5A98`) draws one large-font character at the cursor: it clamps invalid codes to `0xD0`, computes an initial `char * 8` offset, then bjumps to the page-7 large-font blitter, which adjusts that offset to the actual **7-byte-stride** glyph table before copying an 8-byte render record. **[confirmed]**
- `_PutC` (`01:5B4C`) = `_PutMap` + advance cursor + newline handling; `_PutS` prints a string; `_NewLine` scrolls.
- `_DispHL` (`01:5BF6`) prints `HL` as a right-justified 5-digit decimal: repeated `_DivHLBy10`, digits +`0x30`, leading zeros → spaces, using `OP1.mantissa` as a scratch buffer, then `_PutC`/`_PutMap` each digit. **[confirmed]**

## Screen buffers [standard]
- `plotSScreen` (`0x9340`, 768 bytes = 96×64/8) — the main graph/back buffer.
- `saveSScreen` (`0x86EC`, 768 bytes) — saved copy (e.g. for menus over the graph).
- `_GrBufCpy`/`_GrBufClr`-style bcalls blit the buffer to the LCD.

## Fonts [confirmed]
- **Large font**: glyph table is on **page 7, base `0x45FF`**, with a **7-byte stride** per glyph (not 8). `_PutMap` (`01:5A98`) clamps the code (`0` or `≥0xF8` → `0xD0`), computes `HL = char*8` (three `ADD HL,HL`), then bjumps via trampoline `0x3B3D` to the blitter `put_glyph_large` (`page_07:4588`). The blitter does `HL = 0x45FF + char*8`, then `lgfont_glyph_ptr_adjust` (`07:45EB`) subtracts `char` (it shifts `char*8` right by 3 → `char`, then `SBC HL,DE`), yielding the real glyph pointer **`0x45FF + char*7`**. It then copies an **8-byte record** via `_Mov8B` (`00:1A94`, 8× `LDI`) into RAM at **`0x845A`** (`lFont_record`), which the renderer blits. **[confirmed]** *(The 7-byte stride with an 8-byte copy — the 8th byte overlaps the next glyph's first row — is why a stride-8 render at `0x45FF` didn't line up.)*
- **Alternate large fonts**: two bits in `(IY+0x35)` select replacement glyph sources before the table read — bit 5 calls cross-page `0x01` (**page 1** font) and bit 1 calls cross-page `0x76` (**page 0x36** font); when neither is set, the page-7 table is used. **[confirmed]**
- **Small/variable-width font**: `_VPutMap`/`_VPutS` (graph screen, pixel-addressed via `penCol`/`penRow`).

## Indicators
- `flags.indicFlags` bit 0 = the run/busy indicator (the moving dashes top-right); `_ClrLCDFull` preserves it across a clear; `_RunIndicOn`/`Off` toggle it. **[confirmed]**

## Resolved
- **LCD command bytes confirmed** by tracing `_ClrLCDFull` (`01:60E4`), `_ClearRow` (`01:6934`) and `lcd_set_col_cmd` (`01:5A89`): row (page) select = `0xB8 − 8·row` (range `0xB8 … 0x80`, stepping down by 8), column select = `0x20 + col` (range `0x20 … 0x2B`, 12 columns = 96 px), command port `0x10` / data port `0x11`, busy-wait via `0x0CC3`. Contrast is held at RAM `contrast` (`0x8447`) and written to the data port `0x11` by `lcd_set_contrast` (`01:5A59`). See [Controller](#controller-confirmed-against-code). **[confirmed]**
- **Large-font glyph table pinned**: page **0x07**, base **`0x45FF`**, **7-byte stride** (`put_glyph_large` @ `07:4588` → glyph ptr `0x45FF + char*7` via `07:45EB`, then `_Mov8B` copies an 8-byte record to RAM `0x845A`). See [Fonts](#fonts-confirmed) and [Flash Page Map](13-flash-page-map.md). **[confirmed]**

## TODO
- *(none for this section — items above resolved.)*
