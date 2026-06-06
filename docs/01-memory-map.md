# 01 — Memory Map

The Z80 sees a flat **64 KiB** logical space, divided into four **16 KiB** slots. Hardware paging (ports 6/7) decides which physical flash page or RAM page is visible in the two middle slots. See [02-paging.md](02-paging.md) for the banking detail.

## Logical address space (what the Z80 sees)

| Range | Slot | Contents | Notes |
|-------|------|----------|-------|
| `0000–3FFF` | Flash bank 0 | **Flash page 0** (fixed) | Boot/kernel: RST vectors, dispatcher, FP/VAT core. Never swapped. **[confirmed]** |
| `4000–7FFF` | Flash bank A | Swappable **flash page** (port 6) | bcall routines run here after the dispatcher banks their page in. **[confirmed]** |
| `8000–BFFF` | Bank B | Swappable **RAM/flash page** (port 7) | Usually RAM. **[standard]** |
| `C000–FFFF` | RAM | **RAM page** (MemC) | Normally RAM page 0, but page-selectable via **port 5** on the 84+ (not hard-fixed). Stack lives near the top. **[standard]** |

In this OS the system RAM variables all live at `8000+`, so for static RE we model `8000–FFFF` as one RAM block (see `tools/BuildTI84Full.java`).

## Flash layout (physical, 1 MiB = 64 × 16 KiB pages)

| Page(s) | Role | Evidence |
|---------|------|----------|
| `00` | Boot/kernel core, mapped at `0000` | RST vectors, `bcall_dispatcher`, FP/VAT/mem routines **[confirmed]** |
| `01` | OS routines (display, homescreen text, menus) | `_PutC`,`_PutS`,`_ClrLCDFull`,`_NewLine` resolve here **[confirmed]** |
| `06` | OS routines (key input, parser-ish) | `_GetKey`→`06:491E` **[confirmed]** |
| `3B` | **bcall jump table** | scored 447/535 named .inc IDs; first entry `_JErrorNo`→`00:2799` **[confirmed]** |
| `3C` | Link code + OS version string (`"2.55MP"`) | page starts `32 2E 35 35 4D 50` **[confirmed]** |
| `3E` | **Certification page** (per-calculator cert sector; blank in this OS-only image) | 84+ cert page is `3E`, not `3F` **[standard]** |
| `3F` | **Boot page** — maps itself into both banks at power-on | starts `3E 3F D3 06 D3 07` = `LD A,3F; OUT (6),A; OUT (7),A` **[confirmed]** |

Pages `01–3F` are loaded in Ghidra as overlays `page_01 … page_3F` (each at `4000`). Goto e.g. `page_01:5b4c` for `_PutC`.

## Key RAM regions (named & typed)

| Addr | Name | Type | Purpose |
|------|------|------|---------|
| `8478–84B9` | `OP1`–`OP6` | `TIFloat` (9B, 11B-spaced) | Floating-point accumulators **[confirmed]** |
| `89F0` | `flags` | `SystemFlags` (51B) | IY-indexed system flag bitfield **[confirmed]** |
| `844B/844C` | `curRow`/`curCol` | byte | Homescreen text cursor (16 cols) **[confirmed]** |
| `8447` | `contrast` | byte | LCD contrast **[confirmed]** |
| `843F/8444` | `kbdScanCode`/`kbdKey` | byte | Last key scan code / key **[confirmed]** |
| `9340` | `plotSScreen` | byte[768] | Graph/display buffer (96×64/8) **[confirmed]** |
| `86EC` | `saveSScreen` | byte[768] | Saved screen buffer **[confirmed]** |
| `9824` | `FPS` | — | Floating-point stack pointer **[standard]** |
| `85BC` | `onSP` | — | SP saved by ON-interrupt **[confirmed]** |

`IY` is held at `flags` (`0x89F0`) almost everywhere, so `(IY+off)` accesses index `SystemFlags` fields (`appFlags`, `kbdFlags`, …).

## I/O ports (referenced in the kernel) [standard, cross-checked vs code]

| Port | Name | Purpose |
|------|------|---------|
| `00` | link | Link port lines |
| `01` | keypad | Keyboard matrix select/read |
| `02` | hwStatus | Status (bit7 used at reset) |
| `03` | intMask | Interrupt enable mask |
| `04` | intStatus / memMapMode | **Read** = interrupting-device ID + ON-held; **write** = memory-map mode + timer rate |
| `05` | mapBankC | RAM page in slot `C000` (MemC) on the 84+ |
| `06` | mapBankA | Flash page in slot `4000` |
| `07` | mapBankB | Page in slot `8000` (`0x81`=84+ mode seen in ISR) |
| `10/11` | lcdCmd/lcdData | LCD controller |
| `20` | cpuSpeed | 0=6 MHz, 1=15 MHz (set in ISR) |
| `55/56` | usbIntStatus/usbLineEvents | USB interrupt state / line events (84+) — polled first in `int_dispatch_timer1` (older notes: `isr_im1`; read-only; **not** a status/mask pair) |
