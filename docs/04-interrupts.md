# 04 — Interrupts (IM1)

The Z80 runs in **interrupt mode 1**: every maskable interrupt vectors to `0038h`. There is no vector table — one handler services all sources by polling status ports.

## Vector → handler [confirmed]

```z80
0038:  JR  0x006d        ; RST 38h vector
006d:  isr_im1           ; the real handler
```

`isr_im1` @ `ram:006d` runs with `IY = flags` (`0x89F0`), so `(IY+off)` reads/writes `SystemFlags` fields.

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

## Notable details
- This OS keys off the **84+ USB-interrupt ports 0x55/0x56** as the primary interrupt-state source, rather than the classic `0x03/0x04`. Port 0x55 is the USB Interrupt State (read; `(v^0xFF)&0x1F` masks the active sources) and 0x56 is USB Line Events (read-only) — *not* a status/mask pair despite the dispatch role. The legacy mask `0x03` is still written to ACK. **[confirmed in code; ports per WikiTI]**
- The ISR is where **APD** (auto power down) and the **blinking cursor** timing originate — both are timer-interrupt driven.
- `_GetCSC` (`00:04B2`) cooperates with the ISR: the ISR (or keypad path) updates `kbdScanCode`; `_GetCSC` atomically reads and clears it with interrupts masked. **[confirmed]**

## TODO
- Map each `(IY+off)` flag the ISR touches to its `SystemFlags` field name (apdFlags, onFlags, …) and annotate.
- Trace the timer reprogramming to recover the APD timeout value and cursor blink rate.
