# 04 — Interrupts (IM1)

The Z80 runs in interrupt mode 1: every maskable interrupt vectors to `0038h`. There is no vector table — one handler services all sources by polling status ports.

## Vector → handler [confirmed]

```z80
0038:  JR  0x006d        ; RST 38h vector
006d:  int_entry_save_alt_regs ; shadow-register save prologue
006f:  int_dispatch_sources    ; live interrupt-source dispatcher
```

`int_dispatch_sources` @ `ram:006F` runs after the two-byte prologue at `ram:006D`, with `IY = flags` (`0x89F0`), so `(IY+off)` reads/writes `SystemFlags` fields.

## What it does [confirmed from decompiler]

Entry saves context (`ex af,af'` / `exx` — the Z80 shadow registers, the classic TI ISR convention) then polls:

1. `port_usbIntStatus` (0x55) — the 84+ USB Interrupt State port. This OS overloads it as the ISR's master "anything pending?" gate: `(val ^ 0xFF) & 0x1F` tests the 5 active-low sources.
2. `port_usbLineEvents` (0x56) — the USB Line Events port; a read-only event bitmap whose bits select the timer/link sub-handlers. (Port 0x56 is read-only, so it is not an interrupt mask.)
3. Branches per source:
   - **ON key** — sets an ON-flag; `onSP` (`0x85BC`) holds the SP to unwind to for the ON-break path.
   - **First/second timer** — drives the APD (auto-power-down) countdown and cursor blink; ACKs via the interrupt-mask port `0x03`.
   - **Link activity** — services the link port.
4. Hardware-mode housekeeping: checks `port_mapBankB == 0x81` (84+ mode), and on one path sets `port_cpuSpeed = 1` (15 MHz) and `port_mapBankB = 0x81`.
5. Restores context and `EI` / `RET`.

## `(IY+off)` → `SystemFlags` fields the ISR touches [confirmed from disassembly]

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
| `IY+0x12` | 3 | `shiftFlags`·shift2nd | the `[2nd]`-pending modifier flag; the ISR clears it at `ram:01E0` (`RES 3`) so a held `[2nd]` does not linger — see the [keyboard modifier state machine](09-keyboard-link.md) |
| `IY+0x12` | 0 | `indicFlags`·indicRun | run-indicator-on flag (set by `_RunIndicOn`); the byte is shared — bits 0–2 are `indicFlags`, bits 3–7 are `shiftFlags` |
| `IY+0x16` | 0 | speed/ACK select | chooses the value re-written to int-mask port `0x03` on exit (`ram:00E6`) |
| `IY+0x16` | 1 | (same byte) | link-busy sub-flag, reset @ `ram:015E` |
| `IY+0x24` | 2 | link/transfer-active | guards the ON-break vs. link-restore decision (`ram:09EE`, `ram:0AAB`) |
| `IY+0x28` | 7/3 | `APIFlg`·appRetKeyOff (b7) | ISR tests `BIT 7` (`appRetKeyOff`) @ `ram:09DB` and does `SET 3` @ `ram:09E1` on the ON-break path |
| `IY+0x2C` | 0 | `mouseFlag1` bit0 | scanner-active flag tested by `kbd_scan_autorepeat` @ `ram:0415` (the scan code itself is RAM `kbdScanCode` `0x843F`, not an IY flag) |
| `IY+0x33` | 5/0 | context-restore sub-flags | branch selectors on the ON-break / restore path |
| `IY+0x3A` | 0 | `hookflags5`·usbActivityHookActive | when set, the ISR runs the deferred USB-activity hook (`ram:032A`) and ACKs |
| `IY+0x3F` | 7 | RAM-clear control | masked during the ON-key RAM wipe (`ram:0B3C`) |
| `IY+0x44` | 2 | (uncharacterized) | a restore-path branch clears this bit; no standard equate identifies it |

The byte `_GetCSC` (`00:04B2`) clears is `(IY+0)` bit3 (`*flags & 0xF7`) — the `kbdSCR`/"new scan code ready" flag in the keyboard group.

## Timer reprogramming, APD timeout, and cursor blink [confirmed mechanism; exact tick value [hypothesis]]

**Interrupt sources & ACK.** The dispatcher polls the 84+ USB-interrupt ports first, then the two crystal hardware timers: it reads port `0x37` (crystal timer 3 status — `IN A,(0x37)` @ `ram:012D`, `BIT 1,A` @ `ram:012F`) and port `0x31` (crystal timer 1 status — `IN` @ `ram:013B`, `BIT 1` @ `ram:013D`). (Per the WikiTI port map the three crystal timers are `0x30–0x32` = timer 1, `0x33–0x35` = timer 2, `0x36–0x38` = timer 3.) Each maskable interrupt is ACKed by rewriting the int-mask port `0x03`. The common exit (`ram:00E4`) writes `0x0B`, or `0x0F` when `(IY+0x16)` bit0 is set (the second value re-enables the on-key + both timer sources at the higher CPU speed). The master ACK at `ram:00DC` writes `0x08` then the saved mask. Port `0x04` is loaded with `6` (`ram:09B5`/`ram:0C8C`) to re-arm the legacy 83+ timer line.

**APD (auto-power-down) countdown.** APD is a software down-counter decremented by the timer interrupt:
- `apdSubTimer` (`0x8448`) / `apdTimer` (`0x8449`) hold the APD down-counter. `_ApdSetup` (`00:03AE`) writes the reload constant `0x74` to `0x8449` (`apdTimer`). The per-tick decrement is in page 0 at `ram:036C` (`LD HL,0x8448; DEC (HL); RET NZ; INC HL; DEC (HL)` — decrement `apdSubTimer`, and on its underflow `apdTimer`); a key press reloads the counter, so any key keeps the calc awake. The crystal-timer interrupt rate remains unreadable from this DB: when a timer-status bit is set the ISR dispatches to an unanalyzed handler — `35:4792` (via the `ram:3FB1` bjump) for timer 3 / port `0x37`, and `33:5EB4` (via `ram:3FB7`) for timer 1 / port `0x31` — so the wall-clock timeout cannot be derived from this DB. By the standard 83+/84+ design this yields the documented ~2–5 minute idle power-down. [reload constant + counter addresses + decrement site `ram:036C` confirmed; tick rate / absolute seconds [hypothesis]]
- The unrelated `indicCounter`/`indicBusy` pair (`0x8476`/`0x8477`) drives the run indicator (the moving-dashes busy spinner), not APD: `_RunIndicOn` (`01:6518`) seeds it (`0x8477 = 0xF0`, `0x8476 = 1`) and the tick routine at `ram:027B` (`dec_apd_timer` in the symbol map, though it decrements the run-indicator counter) does `DEC (0x8476); RET NZ` each timer tick, advancing the spinner via the expiry path (`ram:3FE1`) only on underflow. [confirmed]

**Cursor blink cadence.** The blink is the same kind of software down-counter, driven off the same timer interrupt:
- `0x844A` (`curTime`) is the blink down-counter; `_CursorOn`/`_CursorOff` (`06:7D34`/`06:7C5F`) reload it with `0x32` (50) (`LD A,0x32; LD (0x844A),A`).
- The ISR tests `curAble` (`IY+0x0C` bit 2) at `ram:019B` and, if enabled, calls the cursor tick through the `ram:3FCF` bjump to `06:7C45`, which decrements `0x844A`; on underflow it toggles `curFlags` (`IY+0x0C`) bit 3 (curOn) to flip the glyph and reloads `0x32`. So the cadence is "toggle every 50 timer ticks"; only the absolute rate (the crystal-timer tick frequency) is ungrounded, which by the WikiTI-documented rate is ≈ 2 blinks/second. [reload value `0x32`, counter `0x844A`, and tick site `06:7C45` confirmed; Hz [hypothesis]]

## Notable details
- This OS keys off the 84+ USB-interrupt ports 0x55/0x56 as the primary interrupt-state source, rather than the classic `0x03/0x04`. Port 0x55 is the USB Interrupt State (read; `(v^0xFF)&0x1F` masks the active sources) and 0x56 is USB Line Events (read-only) — both are read sources, not a status/mask pair, despite the dispatch role. The legacy mask `0x03` is still written to ACK. [confirmed in code; ports per WikiTI]
- The ISR is where APD (auto power down) and the blinking cursor timing originate — both are software down-counters (`apdTimer 0x8449`/`curTime 0x844A`) ticked by the crystal timers (ports 0x37/0x31). The separate run-indicator spinner uses `indicCounter`/`indicBusy` (`0x8476`/`0x8477`), seeded by `_RunIndicOn`. [confirmed]
- `_GetCSC` (`00:04B2`) cooperates with the ISR: the ISR (or keypad path) updates `kbdScanCode`; `_GetCSC` atomically reads and clears it with interrupts masked, also clearing `(IY+0)` bit3. [confirmed]

## TODO
- The crystal-timer tick period (and therefore the APD timeout in seconds and cursor blink in Hz) depends on the unanalyzed timer-status handlers `35:4792` (timer 3 / port `0x37`, via `ram:3FB1`) and `33:5EB4` (timer 1 / port `0x31`, via `ram:3FB7`), which are data in this DB. The reload constants (`apdTimer 0x8449 = 0x74`, `curTime 0x844A = 0x32`), the counter addresses, and the page-0 / page-06 decrement sites (`ram:036C`, `06:7C45`) are confirmed; only the absolute tick rate is ungrounded.
