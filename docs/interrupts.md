# Interrupts (IM1)

The Z80 runs in interrupt mode 1: every maskable interrupt vectors to `0038h`. There is no vector table — one handler services all sources by polling status ports.

## Vector → handler [confirmed]

```z80
0038:  JR  0x006d        ; RST 38h vector
006d:  int_entry_save_alt_regs ; shadow-register save prologue
006f:  int_dispatch_sources    ; live interrupt-source dispatcher
```

`int_dispatch_sources` @ `ram:006F` runs after the two-byte prologue at `ram:006D`, with `IY = flags` (`0x89F0`), so `(IY+off)` reads/writes `SystemFlags` fields.

## What it does [confirmed]

Entry saves context (`ex af,af'` / `exx` — the Z80 shadow registers, the classic TI ISR convention) then polls:

1. `port_usbIntStatus` (0x55) — the 84+ USB Interrupt State port. This OS overloads it as the ISR's master "anything pending?" gate: `(val ^ 0xFF) & 0x1F` tests the 5 active-low sources.
2. `port_usbLineEvents` (0x56) — the USB Line Events port; a read-only event bitmap whose bits select the timer/link sub-handlers. (Port 0x56 is read-only, so it is not an interrupt mask.)
3. Branches per source:
   - ON key — sets an ON-flag; `onSP` (`0x85BC`) holds the SP to unwind to for the ON-break path.
   - Standard timer 1 — enters `ram:0167`, which scans the keypad and advances the run-indicator, cursor, and APD counters.
   - Programmable timers — checks timer 3 at port `0x37` and timer 1 at port `0x31`, then dispatches their banked handlers.
   - Link activity — services the link port.
4. Hardware-mode housekeeping: checks `port_mapBankB == 0x81` (84+ mode), and on one path sets `port_cpuSpeed = 1` (15 MHz) and `port_mapBankB = 0x81`.
5. Restores context and `EI` / `RET`.

## `(IY+off)` → `SystemFlags` fields the ISR touches [confirmed]

`int_dispatch_sources` reads/writes these flag bits via `BIT/SET/RES b,(IY+d)`. Offsets are confirmed against the standard `ti83plus.inc` group layout; the anchor `apdFlags = IY+0x08` is confirmed in code (`_DisableApd`/`_EnableApd` @ `3B:7AA8`/`3B:7AAD` do `RES/SET 2,(IY+0x8)`), `curFlags = IY+0x0C` is confirmed (`_CursorOn`/`_CursorOff` @ `06:7D34`/`06:7C5F`).

| `(IY+off)` | bit | field / equate | meaning in the ISR |
|------------|-----|----------------|--------------------|
| `IY+0x03` | 1 | flag byte `0x03` bit1 | ON-key interrupt already latched (guards the ON-set path @ `ram:00F5`) |
| `IY+0x03` | 0 | `graphFlags`·graphDraw | redraw-graph flag the ISR sets @ `ram:0109` |
| `IY+0x08` | 2 | `apdFlags`·apdAble | APD enabled; toggled by `_DisableApd`/`_EnableApd` |
| `IY+0x09` | 3 | `onFlags`·onRunning | calculator-running flag; tested before the 84+ USB-port path (`ram:008B`, `ram:099E`) |
| `IY+0x09` | 4 | `onFlags`·onInterrupt | ON-key interrupt-request flag; set @ `ram:0A87` |
| `IY+0x0C` | 3 | `curFlags`·curOn | cursor currently drawn (blink phase) |
| `IY+0x0C` | 2 | `curFlags`·curAble | cursor-blink enabled (`curLock` is bit 4) |
| `IY+0x0F` | 7 | `seqFlags` bit7 | cleared @ `ram:0A8C` (`RES 7,(IY+0Fh)`) on the ON-key path |
| `IY+0x12` | 3 | `shiftFlags`·shift2nd | the **2nd**-pending modifier flag; the ISR clears it at `ram:01E0` (`RES 3`) so a held **2nd** does not linger — see [Keypad and ON-key hardware](keypad-on-hardware.md#modifier-state) |
| `IY+0x12` | 0 | `indicFlags`·indicRun | run-indicator-on flag (set by `_RunIndicOn`); the byte is shared — bits 0–2 are `indicFlags`, bits 3–7 are `shiftFlags` |
| `IY+0x16` | 0 | speed/ACK select | chooses the value re-written to int-mask port `0x03` on exit (`ram:00E6`) |
| `IY+0x16` | 1 | (same byte) | link-busy sub-flag, reset @ `ram:015E` |
| `IY+0x24` | 2 | link/transfer-active | guards the ON-break vs. link-restore decision (`ram:09EE`, `ram:0AAB`) |
| `IY+0x28` | 7/3 | `APIFlg`·appRetKeyOff (b7) | ISR tests `BIT 7` (`appRetKeyOff`) @ `ram:09DB` and does `SET 3` @ `ram:09E1` on the ON-break path |
| `IY+0x2C` | 0 | `mouseFlag1` bit0 | enables four diagonal-arrow raw values in `kbd_scan_matrix` at `ram:0415`; the wider mode remains open |
| `IY+0x33` | 5/0 | context-restore sub-flags | branch selectors on the ON-break / restore path |
| `IY+0x3A` | 0 | `hookflags5`·usbActivityHookActive | when set, the ISR runs the deferred USB-activity hook (`ram:032A`) and ACKs |
| `IY+0x3F` | 7 | RAM-clear control | masked during the ON-key RAM wipe (`ram:0B3C`) |
| `IY+0x44` | 2 | (uncharacterized) | a restore-path branch clears this bit; no standard equate identifies it |

The byte `_GetCSC` (`00:04B2`) clears is `(IY+0)` bit3 (`*flags & 0xF7`) — the `kbdSCR`/"new scan code ready" flag in the keyboard group.

## Standard and programmable timers

Reading port `0x04` reports all legacy and programmable timer sources. Bit 1 is standard hardware timer 1; bits 5–7 are programmable timers 1–3. These are separate hardware blocks. [standard]

The OS writes `0x06` to port `0x04`, selecting the slowest standard-timer rate. Timer 1 then fires every $304/32768$ seconds, about 107.789 Hz. Port `0x03` normally enables this source with value `0x0B`. [confirmed] for the writes; [standard] for the quartz-derived rate.

The banked programmable-timer handlers have distinct jobs: [confirmed]

- Timer 3 status at port `0x37` dispatches to `usb_timeout_irq` at `35:4792`, which accesses the USB controller ports `0x8E`, `0x91`, and `0x92`.
- Timer 1 status at port `0x31` dispatches to `timer_irq` at `33:5EB4`, which advances the `_StartTimer` bcall state machine.
- Standard timer 1 enters `standard_timer1_irq` at `ram:0167`; this is the source that reaches APD and cursor code.

The common exit at `ram:00E4` writes `0x0B`, or `0x0F` when `(IY+0x16)` bit 0 is set. The master acknowledge at `ram:00DC` writes `0x08` and then the desired mask. [confirmed]

## APD and cursor cadence

`standard_timer1_irq` calls `apd_timer_tick` at `ram:0355`. When APD is enabled and running, the tail at `ram:036C` decrements `apdSubTimer` (`0x8448`) and then `apdTimer` (`0x8449`). `_ApdSetup` at `ram:03AE` reloads only the high byte with `0x74`, leaving the low-byte phase unchanged. Expiry therefore occurs after 29,441–29,696 ticks, or 273.134277–275.500000 seconds at the documented timer rate. [confirmed] for the counter; [standard] for wall time.

The cursor handler at `06:7C45` toggles after 50 ticks. That is 0.4638671875 seconds per state and 0.927734375 seconds per full on/off cycle. `run_indicator_tick` at `ram:027B` uses the separate `indicCounter` at `0x8476`. [confirmed] for the counters; [standard] for wall time.

See [Clock, timers, and power](clock-timers-power.md) for the complete port maps, timer bcall ABI, RTC protocol, APD derivation, power-off flow, dynamic traces, and TilEm fidelity gaps.

## Interrupt-source details

- This OS polls the 84+ USB interrupt ports `0x55`/`0x56` before port `0x04`. Port `0x55` is the USB interrupt state; `(v^0xFF)&0x1F` selects active-low sources. Port `0x56` is a read-only line-event bitmap. [confirmed]
- `_GetCSC` (`ram:04B2`) cooperates with the ISR: the keypad path updates `kbdScanCode`; `_GetCSC` atomically reads and clears it with interrupts masked, also clearing `(IY+0)` bit 3. See [Keypad and ON-key hardware](keypad-on-hardware.md) for matrix timing, repeat, and ON debounce. [confirmed]
