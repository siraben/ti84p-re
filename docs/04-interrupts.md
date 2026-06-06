# 04 — Interrupts (IM1)

The Z80 runs in **interrupt mode 1**: every maskable interrupt vectors to `0038h`. There is no vector table — one handler services all sources by polling status ports.

## Vector → handler [confirmed]

```z80
0038:  JR  0x006d        ; RST 38h vector
006d:  int_entry_save_alt_regs ; shadow-register save prologue
006f:  int_dispatch_sources    ; live interrupt-source dispatcher
```

`int_dispatch_sources` @ `ram:006F` (called `isr_im1` in older notes) runs after the two-byte prologue at `ram:006D`, with `IY = flags` (`0x89F0`), so `(IY+off)` reads/writes `SystemFlags` fields.

## What it does [confirmed from decompiler]

Entry saves context (`ex af,af'` / `exx` — the Z80 shadow registers, the classic TI ISR convention) then polls:

1. **`port_usbIntStatus` (0x55)** — the 84+ **USB Interrupt State** port. This OS overloads it as the ISR's master "anything pending?" gate: `(val ^ 0xFF) & 0x1F` tests the 5 active-low sources.
2. **`port_usbLineEvents` (0x56)** — the **USB Line Events** port; a read-only event bitmap whose bits select the timer/link sub-handlers. (It is *not* an interrupt mask — port 0x56 is read-only.)
3. Branches per source:
   - **ON key** — sets an ON-flag; `onSP` (`0x85BC`) holds the SP to unwind to for the ON-break path.
   - **First/second timer** — drives the APD (auto-power-down) countdown and cursor blink; ACKs via the interrupt-mask port `0x03`.
   - **Link activity** — services the link port.
4. Hardware-mode housekeeping: checks `port_mapBankB == 0x81` (84+ mode), and on one path sets `port_cpuSpeed = 1` (15 MHz) and `port_mapBankB = 0x81`.
5. Restores context and `EI` / `RET`.

## `(IY+off)` → `SystemFlags` fields the ISR touches [confirmed from disassembly]

`int_dispatch_sources` reads/writes these flag bits via `BIT/SET/RES b,(IY+d)`. Offsets are confirmed against the standard `ti83plus.inc` group layout; the anchor `apdFlags = IY+0x08` is **confirmed in code** (`_DisableApd`/`_EnableApd` @ `3B:7AA8/7AAD` do `RES/SET 2,(IY+0x8)`), `curFlags = IY+0x0C` is **confirmed** (`_CursorOn`/`_CursorOff` @ `06:7D34/7C5F`).

| `(IY+off)` | bit | field / equate | meaning in the ISR |
|------------|-----|----------------|--------------------|
| `IY+0x03` | 1 | flag byte `0x03` bit1 | ON-key interrupt already latched (guards the ON-set path @ `00F5`) |
| `IY+0x03` | 0 | `graphFlags`·graphDraw | redraw-graph flag the ISR **sets** @ `0109` |
| `IY+0x08` | 2 | `apdFlags`·apdRunning | APD active; toggled by `_DisableApd`/`_EnableApd` |
| `IY+0x09` | 3 | `hardwareType`/sysFlags bit3 | "84+ hardware present" gate before touching ports 0x55/0x56/0x37/0x31 (`008B`, `099E`) |
| `IY+0x09` | 4 | (same byte) | **set** @ `0A87` to mark the crash/RST-5 ON-break path taken |
| `IY+0x0C` | 3 | `curFlags`·curOn | cursor currently drawn (blink phase) |
| `IY+0x0C` | 4 | `curFlags`·curAble | cursor-blink enabled |
| `IY+0x0F` | 7 | `apdFlags`-area | APD sub-state cleared @ `0A8C` on ON-key |
| `IY+0x12` | 3 | `(IY+0x12)`·"INT/LCD busy" | **reset** first thing in the timer-dispatch tail (`01E0`) — re-entrancy guard |
| `IY+0x12` | 0 | (same byte) | run-indicator-on flag (set by `_RunIndicOn`) |
| `IY+0x16` | 0 | speed/ACK select | chooses the value re-written to int-mask port `0x03` on exit (`00E6`) |
| `IY+0x16` | 1 | (same byte) | link-busy sub-flag, reset @ `015E` |
| `IY+0x24` | 2 | link/transfer-active | guards the ON-break vs. link-restore decision (`09EE`, `0AAB`) |
| `IY+0x28` | 7/3 | LCD-busy / deferred | "LCD busy → defer this tick" (`09DB`, `09E1`) |
| `IY+0x2C` | 0 | `kbdScanCode`-scan enable | scanner-active flag tested by `kbd_scan_autorepeat` @ `0415` |
| `IY+0x33` | 5/0 | context-restore sub-flags | branch selectors on the ON-break / restore path |
| `IY+0x3A` | 0 | APD-hook pending | when set, the ISR runs the deferred APD hook (`apd_run_pending_hook` @ `032A`) and ACKs |
| `IY+0x3F` | 7 | RAM-clear control | masked during the ON-key RAM wipe (`0B3C`) |
| `IY+0x44` | 2 | edit/format state | restore-path branch |

The byte `_GetCSC` (`00:04B2`) clears is `(IY+0)` bit3 (`*flags & 0xF7`) — the `kbdSCR`/"new scan code ready" flag in the keyboard group.

## Timer reprogramming, APD timeout, and cursor blink [confirmed mechanism; exact tick value [hypothesis]]

**Interrupt sources & ACK.** The dispatcher polls the 84+ USB-interrupt ports first, then the two crystal **hardware timers**: it reads **port `0x37`** (crystal timer 1 status, `BIT 1` @ `012D`) and **port `0x31`** (crystal timer 2 status, `BIT 1` @ `013B`). Each maskable interrupt is ACKed by rewriting the int-mask port **`0x03`**: the common exit (`00E4`) writes `0x0B`, or `0x0F` when `(IY+0x16)` bit0 is set (the second value re-enables the on-key + both timer sources at the higher CPU speed); the master ACK at `00DC` writes `0x08` then the saved mask. Port **`0x04`** is loaded with `6` (`09B5`/`0C8C`) to re-arm the legacy 83+ timer line.

**APD (auto-power-down) countdown.** APD is a software down-counter, **not** a one-shot hardware timer:
- `0x8476`/`0x8477` is the 16-bit APD counter. `_RunIndicOn` (`01:6518`) seeds it (`0x8477 = 0xF0`, `0x8476 = 1`) and `dec_apd_timer` (`ram:027b`) does `DEC (0x8476); RET NZ` each timer tick, calling the expiry path (`0x3FE1 → 01:6BBA`) only on underflow.
- `_ApdSetup` (`00:03AE`) writes the **reload constant `0x74` to `0x8449`** (`apdSubCount`); this is the value the crystal-timer handler reloads the counter from whenever a key is pressed (so any key keeps the calc awake). The reload itself lives in the **page-35 timer handler (`page_35:4CD2`, reached via the `3FBD` bjump), which is unanalyzed (data) in this DB** — so the exact tick rate, and hence the wall-clock timeout, cannot be read out here. By the standard 83+/84+ design this yields the documented **~2–5 minute** idle power-down. **[reload constant + counter confirmed; absolute seconds [hypothesis]]**

**Cursor blink cadence.** The blink is the same kind of software down-counter, driven off the same timer interrupt:
- `0x844A` (`curTimer`) is the blink down-counter; `_CursorOn`/`_CursorOff` (`06:7D34`/`06:7C5F`) reload it with **`0x32` (50)** (`LD A,0x32; LD (0x844A),A`).
- On each timer tick the handler decrements `0x844A`; on underflow it toggles `curFlags` (`IY+0x0C`) bit3 (curOn) to flip the glyph, then reloads `0x32`. The per-tick handler that does the decrement/toggle is again in the unanalyzed page-35 timer code, so the cadence is **"toggle every 50 timer ticks"**; the WikiTI-documented crystal-timer rate makes that ≈ **2 blinks/second**. **[reload value 0x32 confirmed; Hz [hypothesis]]**

## Notable details
- This OS keys off the **84+ USB-interrupt ports 0x55/0x56** as the primary interrupt-state source, rather than the classic `0x03/0x04`. Port 0x55 is the USB Interrupt State (read; `(v^0xFF)&0x1F` masks the active sources) and 0x56 is USB Line Events (read-only) — *not* a status/mask pair despite the dispatch role. The legacy mask `0x03` is still written to ACK. **[confirmed in code; ports per WikiTI]**
- The ISR is where **APD** (auto power down) and the **blinking cursor** timing originate — both are software down-counters (`0x8476`/`0x844A`) ticked by the crystal timers (ports 0x37/0x31). **[confirmed]**
- `_GetCSC` (`00:04B2`) cooperates with the ISR: the ISR (or keypad path) updates `kbdScanCode`; `_GetCSC` atomically reads and clears it with interrupts masked, also clearing `(IY+0)` bit3. **[confirmed]**

## TODO
- The exact crystal-timer tick period (and therefore APD timeout in seconds and cursor blink in Hz) lives in the **page-35 timer handler (`page_35:4CD2`)**, which is unanalyzed data in this DB. The reload constants (`apdSubCount=0x74`, `curTimer=0x32`) and the counter addresses are confirmed; only the absolute rate is ungrounded.
