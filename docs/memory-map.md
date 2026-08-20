# Memory map

The Z80 sees a flat 64 KiB logical space divided into four 16 KiB windows.
Port `0x04` selects paired or independent mapping; ports `0x05`–`0x07` and
their extensions select the physical Flash or RAM pages. See
[Paging](paging.md) for the complete mapper and [RAM pages](ram-pages.md) for
RAM page `83` and restore rules.

## Logical address space (what the Z80 sees)

| Range | Slot | Contents | Notes |
|-------|------|----------|-------|
| `0000-3FFF` | Window 0 | Flash page 0 (fixed) | Boot/kernel: RST vectors, dispatcher, FP/VAT core. Never swapped. [confirmed] |
| `4000-7FFF` | Window A | Port `0x06` in independent mode; even half of the port-`0x06` pair in paired mode | Paged bcall targets run here after the dispatcher maps their page. [confirmed] |
| `8000-BFFF` | Window B | Port `0x07` in independent mode; odd half of the port-`0x06` pair in paired mode | Normally RAM page `81`; boot executes page `3F` here in paired mode. [confirmed] |
| `C000-FFFF` | Window C | Port `0x05` RAM in independent mode; port `0x07` in paired mode | Normally RAM page `80`; the stack lives near the top. [confirmed] |

In this OS the system RAM variables all live at `8000+`, so the static RE model treats `8000-FFFF` as one RAM block (see `tools/BuildTI84Full.java`).

## Flash layout (physical, 1 MiB = 64 × 16 KiB pages)

| Page(s) | Role | Evidence |
|---------|------|----------|
| `00` | Boot/kernel core, mapped at `0000` | RST vectors, `bcall_dispatcher`, FP/VAT/mem routines [confirmed] |
| `01` | OS routines (display, homescreen text, menus) | `_PutC`,`_PutS`,`_ClrLCDFull`,`_NewLine` resolve here [confirmed] |
| `06` | OS routines (key input, parser-ish) | `_GetKey`→`06:491E` [confirmed] |
| `2F` | USB boot support page | validated local `D84PBE2.8Xv` supplies this page; retail page `3F` maps `_AttemptUSBOSReceive`→`2F:4145`, `_ReceiveOS_USB`→`2F:48CA`, `_InitUSB`→`2F:52A4`, `_KillUSB`→`2F:5961` [confirmed] |
| `3B` | bcall jump table | highest-scoring page for the `0x4xxx` bcall ID table; first entry `_JErrorNo`→`00:2799` [confirmed] |
| `3C` | Link code, archive GC, and OS version string (`"2.55MP"`) | page starts `32 2E 35 35 4D 50`; collector entry `3C:7733` [confirmed] |
| `3E` | Two 8 KiB certificate sectors; the inactive half also carries the transactional GC journal | `_GetCertificateStart` (`8057`) and the GC command trace [confirmed] |
| `3F` | Retail boot page | the patched base and validated local `D84PBE1.8Xv` contain the same page byte for byte; it starts `3E 07 D3 04 3E 7F D3 06 3E 03 D3 0E C3 2C 81`, contains boot version string `1.03`, and hosts the `0x8xxx` boot bcall table [confirmed] |

Pages `01-3F` are loaded in Ghidra as overlays `page_01 … page_3F` (each at `4000`). Goto e.g. `01:5b4c` for `_PutC`.

The assembled `tools/rom.bin` is the Ghidra build input. `tools/assemble_local_rom.py`
starts with `ti84plus_patched.rom`, validates the complete TI AppVar containers,
installs `D84PBE2.8Xv` as page `2F`, and installs `D84PBE1.8Xv` as page `3F`.
The first installation changes 8,615 bytes; the second changes none because the
base already has that exact page. The required SHA-256 identities are
`90472848b5f56902287fd5d8b455e62d60e9ab054647c9a03c1c91a67fc1a95a`
for the base and
`7d9a7d96d89fc552ebee6afdbdd011fdc6047be9c16d308245dff07eb1f7bd6d`
for the result. These checks establish reproducible analysis inputs, not a
physical-capture history. The page-`2F` and page-`3F` bodies above decode
directly from `rom.bin`. The resolver detects a BootFree input and omits retail
targets when the retail pages are absent.

## Key named and typed RAM regions

| Addr | Name | Type | Purpose |
|------|------|------|---------|
| `0x8478-0x84B9` | `OP1`–`OP6` | `TIFloat` slot (9B body + 2B `…EXT` guard, 11B-spaced) | Floating-point accumulators [confirmed] |
| `0x89F0` | `flags` | `SystemFlags` (74B) | IY-indexed system flag bitfield [confirmed] |
| `0x844B/0x844C` | `curRow`/`curCol` | byte | Homescreen text cursor (16 cols) [confirmed] |
| `0x8447` | `contrast` | byte | LCD contrast [confirmed] |
| `0x843F`–`0x8446` | `kbdScanCode` through `keyExtend` | 8 bytes | scan mailbox, release filter, repeat state, and cooked-key workspace; see [Keypad and ON-key hardware](keypad-on-hardware.md) [confirmed] |
| `0x8448`–`0x844A` | `apdSubTimer`/`apdTimer`/`curTime` | 3 bytes | APD low/high countdown and cursor timer [confirmed] |
| `0x8259`–`0x82A1` | MD5 state | 73 bytes, with gaps | working words, bit length, compact length prefix, and digest; see [MD5 accelerator and boot API](md5-hardware.md) [confirmed] |
| `0x83A5`–`0x83E4` | `MD5Buffer` | 64 bytes | partial message block or transformed-hash output [confirmed] |
| `0x9C0C`–`0x9C12` | timer API state | 7 bytes | programmable timer-1 state, durations, and expiry count [confirmed] |
| `0x9340` | `plotSScreen` | byte[768] | Graph/display buffer (96×64/8) [confirmed] |
| `0x86EC` | `saveSScreen` | byte[768] | Saved screen buffer [confirmed] |
| `0x9824` | `FPS` | — | Floating-point stack pointer [standard] |
| `0x85BC` | `onSP` | — | SP saved by ON-interrupt [confirmed] |

`IY` is held at `flags` (`0x89F0`) almost everywhere, so `(IY+off)` accesses index `SystemFlags` fields (`appFlags`, `kbdFlags`, …).

## Principal input/output ports [standard]

A curated selection of the ports most relevant to the memory map and paging; the
kernel touches many more (timer/crystal, USB-assist, and ASIC-control ports).

| Port | Name | Purpose |
|------|------|---------|
| `00` | link | Active-high pull-low controls on write and physical high-line levels on read; see [Two-wire link port hardware](link-port-hardware.md) |
| `01` | keypad | Active-low matrix group select/read; see [Keypad and ON-key hardware](keypad-on-hardware.md) |
| `02` | hwStatus | Battery comparator, LCD-ready, Flash-lock, and family status; see [ASIC status, identity, protection, and GPIO](asic-status-gpio.md) |
| `03` | intMask | Legacy interrupt enable/acknowledgement and low-power-on-`HALT` control; see [Interrupts (IM1)](interrupts.md#port-0x03-mask-acknowledgement-and-power-mode) |
| `04` | intStatus / memMapMode | *Read* = legacy pending state, ON level, and programmable completion; *write* = mapping mode, standard-timer rate, and battery selector; see [Interrupts (IM1)](interrupts.md#port-0x04-read-source-and-on-status) |
| `05` | mapBankC | RAM selector for window C in independent mode |
| `06` | mapBankA | Flash/RAM selector for window A in independent mode or the A/B pair in paired mode |
| `07` | mapBankB | Flash/RAM selector for window B in independent mode or window C in paired mode |
| `08`–`0D` | usb/link assist | 84+ hardware byte-assist control/status/data/FIFO ports; see [USB ASIC and link assist](sub-usb-asic.md) |
| `0E`/`0F` | mapBankAHigh/mapBankBHigh | High two Flash-page bits for ports `0x06`/`0x07`; no page effect on this 64-page TI-84 Plus |
| `10/11` | lcdCmd/lcdData | LCD controller |
| `18`–`1F` | MD5 assist | Six serial operand registers, rotate/mode control, and four result bytes; see [MD5 accelerator and boot API](md5-hardware.md) |
| `20` | cpuSpeed | 0=6 MHz, 1=15 MHz (set in ISR) |
| `15` | asicIdentity | Public ASIC/RAM/USB revision value; this ROM has no immediate or statically resolved literal-C access; see [ASIC status, identity, protection, and GPIO](asic-status-gpio.md) |
| `21` | flashGroup/ramExec | Protected writable Flash grouping and RAM-execution mode; the boot writes zero at `3F:41DC`, and the kernel reads the low bits for model-specific page bounds; see [ASIC status, identity, protection, and GPIO](asic-status-gpio.md) |
| `22`–`26` | execution bounds | Protected Flash-page and RAM-chunk bounds; see [Execution protection](execution-protection.md) |
| `27`/`28` | forced RAM overlays | 64-byte-granularity page-`80`/`81` subranges; OS 2.55MP writes only zero, and paired-mode hardware behavior remains open |
| `2D` | crystalControl | Quartz and programmable-timer behavior in low power |
| `29`–`2C` | speedDelay | Speed-selected LCD instruction delays and Flash/RAM wait-state gates; see [Bus timing and wait states](bus-timing.md) |
| `2E` | memoryDelay | Per-access Flash/RAM one-T-state additions; see [Bus timing and wait states](bus-timing.md) |
| `2F` | lcdTimerAdjust | LCD-ready timing and programmable mode-3 prescaler; see [Bus timing and wait states](bus-timing.md) |
| `30`–`38` | programmable timers | Three source/mode/counter triplets; see [Clock, timers, and power](clock-timers-power.md) |
| `39`/`3A` | gpioConfig/gpioData | Battery-comparison and USB GPIO configuration/data; exact electrical signals remain open; see [ASIC status, identity, protection, and GPIO](asic-status-gpio.md) |
| `40`–`48` | RTC | Control, staged set value, and current 32-bit seconds count |
| `4D` | usbLineState | USB line-state gate sampled by `_GetVarCmdUSB` (id `50FB`; Ghidra alias `link_xfer_op`); bits 5/6 gate the `ram:2E0B` bjump to `35:4280` |
| `55/56` | usbIntStatus/usbLineEvents | USB interrupt state / line events (84+) — polled before the separate legacy controller; both read-only (port `0x56` is an event bitmap, not a write mask) |
