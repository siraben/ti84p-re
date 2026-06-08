# 01 — Memory map

The Z80 sees a flat 64 KiB logical space, divided into four 16 KiB slots. Hardware paging (ports 6/7) decides which physical flash page or RAM page is visible in the two middle slots. See [02-paging.md](02-paging.md) for the banking detail and [14-ram-pages.md](14-ram-pages.md) for RAM page `83` and restore rules.

## Logical address space (what the Z80 sees)

| Range | Slot | Contents | Notes |
|-------|------|----------|-------|
| `0000–3FFF` | Flash bank 0 | Flash page 0 (fixed) | Boot/kernel: RST vectors, dispatcher, FP/VAT core. Never swapped. [confirmed] |
| `4000–7FFF` | Flash bank A | Swappable flash page (port 6) | Paged bcall targets run here after the dispatcher banks their page in; page-0 bcall bodies instead execute in place below `4000` (e.g. `_JErrorNo`→`00:2799`). [confirmed] |
| `8000–BFFF` | Bank B | Swappable RAM/flash page (port 7) | Usually RAM. [standard] |
| `C000–FFFF` | RAM | RAM page (MemC) | Normally RAM page 0, but page-selectable via `port 5` on the 84+ (not hard-fixed). Stack lives near the top. [standard] |

In this OS the system RAM variables all live at `8000+`, so the static RE model treats `8000–FFFF` as one RAM block (see `tools/BuildTI84Full.java`).

## Flash layout (physical, 1 MiB = 64 × 16 KiB pages)

| Page(s) | Role | Evidence |
|---------|------|----------|
| `00` | Boot/kernel core, mapped at `0000` | RST vectors, `bcall_dispatcher`, FP/VAT/mem routines [confirmed] |
| `01` | OS routines (display, homescreen text, menus) | `_PutC`,`_PutS`,`_ClrLCDFull`,`_NewLine` resolve here [confirmed] |
| `06` | OS routines (key input, parser-ish) | `_GetKey`→`06:491E` [confirmed] |
| `2F` | USB boot support page | supplied by local `D84PBE2.8Xv`; retail page `3F` maps `_AttemptUSBOSReceive`→`2F:4145`, `_ReceiveOS_USB`→`2F:48CA`, `_InitUSB`→`2F:52A4`, `_KillUSB`→`2F:5961` [confirmed] |
| `3B` | bcall jump table | highest-scoring page for the `0x4xxx` bcall ID table; first entry `_JErrorNo`→`00:2799` [confirmed] |
| `3C` | Link code + OS version string (`"2.55MP"`) | page starts `32 2E 35 35 4D 50` [confirmed] |
| `3E` | Certification page (per-calculator cert sector; effectively blank in this OS-only image — no certificate payload, only a few `00` bytes) | 84+ cert page is `3E`, not `3F` [standard] |
| `3F` | Retail boot page | supplied by local `D84PBE1.8Xv`; starts `3E 07 D3 04 3E 7F D3 06 3E 03 D3 0E C3 2C 81`, contains boot version string `1.03`, and hosts the `0x8xxx` boot bcall table [confirmed] |

Pages `01–3F` are loaded in Ghidra as overlays `page_01 … page_3F` (each at `4000`). Goto e.g. `page_01:5b4c` for `_PutC`.

The assembled `tools/rom.bin` (the Ghidra build input) is a BootFree image — pages `2F` and `3F` are blank or BootFree-substituted there. The `2F`/`3F` rows above describe the retail USB/boot content from the local `D84PBE2.8Xv` / `D84PBE1.8Xv` segment files (the page-3F retail boot is also applied in `ti84plus_patched.rom`); those bodies are byte-decoded from those files, not from `rom.bin`.

## Key RAM regions (named & typed)

| Addr | Name | Type | Purpose |
|------|------|------|---------|
| `0x8478–0x84B9` | `OP1`–`OP6` | `TIFloat` slot (9B body + 2B `…EXT` guard, 11B-spaced) | Floating-point accumulators [confirmed] |
| `0x89F0` | `flags` | `SystemFlags` (74B) | IY-indexed system flag bitfield [confirmed] |
| `0x844B/0x844C` | `curRow`/`curCol` | byte | Homescreen text cursor (16 cols) [confirmed] |
| `0x8447` | `contrast` | byte | LCD contrast [confirmed] |
| `0x843F/0x8444` | `kbdScanCode`/`kbdKey` | byte | Last key scan code / key [confirmed] |
| `0x9340` | `plotSScreen` | byte[768] | Graph/display buffer (96×64/8) [confirmed] |
| `0x86EC` | `saveSScreen` | byte[768] | Saved screen buffer [confirmed] |
| `0x9824` | `FPS` | — | Floating-point stack pointer [standard] |
| `0x85BC` | `onSP` | — | SP saved by ON-interrupt [confirmed] |

`IY` is held at `flags` (`0x89F0`) almost everywhere, so `(IY+off)` accesses index `SystemFlags` fields (`appFlags`, `kbdFlags`, …).

## Principal I/O ports [standard, cross-checked vs code]

A curated selection of the ports most relevant to the memory map and paging; the
kernel touches many more (timer/crystal, USB-assist, and ASIC-control ports).

| Port | Name | Purpose |
|------|------|---------|
| `00` | link | Link port lines |
| `01` | keypad | Keyboard matrix select/read |
| `02` | hwStatus | Status (bit7 used at reset) |
| `03` | intMask | Interrupt enable mask |
| `04` | intStatus / memMapMode | *Read* = interrupting-device ID + ON-held; *write* = memory-map mode + timer rate |
| `05` | mapBankC | RAM page in slot `C000` (MemC) on the 84+ |
| `06` | mapBankA | Flash page in slot `4000` |
| `07` | mapBankB | Page in slot `8000` (`0x81`=84+ mode seen in ISR) |
| `08`–`0D` | usb/link assist | 84+ hardware byte-assist control/status/data/FIFO ports; see [USB ASIC and link assist](sub-usb-asic.md) |
| `10/11` | lcdCmd/lcdData | LCD controller |
| `20` | cpuSpeed | 0=6 MHz, 1=15 MHz (set in ISR) |
| `21` | asicVer/ramSize | ASIC version & RAM-page count; read in the kernel (e.g. `00:02AE`) and its low bits mask the slot-`4000` page number before `OUT (6)` |
| `4D` | usbLineState | USB line-state gate sampled by `_GetVarCmdUSB` (id `50FB`; Ghidra alias `_LinkXferOP`); bits 5/6 gate the `ram:2E0B` bjump to `35:4280` |
| `55/56` | usbIntStatus/usbLineEvents | USB interrupt state / line events (84+) — polled first in `int_dispatch_sources`; both read-only (port 0x56 is a read-only event bitmap, not a write mask) |
