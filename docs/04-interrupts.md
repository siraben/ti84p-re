# 04 — Interrupts (IM1)

The Z80 runs in **interrupt mode 1**: every maskable interrupt vectors to `0038h`. There is no vector table — one handler services all sources by polling status ports.

## Vector → handler [confirmed]

```
0038:  JR  0x006d        ; RST 38h vector
006d:  isr_im1           ; the real handler
```

`isr_im1` @ `ram:006d` runs with `IY = flags` (`0x89F0`), so `(IY+off)` reads/writes `SystemFlags` fields.

## What it does [confirmed from decompiler]

Entry saves context (`ex af,af'` / `exx` — the Z80 shadow registers, the classic TI ISR convention) then polls:

1. **`port_intStatusExt` (0x55)** — primary interrupt status on this 84+ OS. `(val ^ 0xFF) & 0x1F` tests the 5 active-low sources.
2. **`port_intMaskExt` (0x56)** — extended mask; gates timer/link sub-handlers.
3. Branches per source:
   - **ON key** — sets an ON-flag; `onSP` (`0x85BC`) holds the SP to unwind to for the ON-break path.
   - **First/second timer** — drives the APD (auto-power-down) countdown and cursor blink; reprograms `port_intStatus` (0x04) and `port_intMask` (0x03).
   - **Link activity** — services the link port.
4. Hardware-mode housekeeping: checks `port_mapBankB == 0x81` (84+ mode), and on one path sets `port_cpuSpeed = 1` (15 MHz) and `port_mapBankB = 0x81`.
5. Restores context and `EI` / `RET`.

## Notable details
- This OS keys off **ports 0x55/0x56** as the primary interrupt status/mask rather than the classic `0x03/0x04` — consistent with a TI-84+ (extended interrupt controller). The legacy `0x03/0x04` ports are still written for compatibility. **[confirmed in code; interpretation standard]**
- The ISR is where **APD** (auto power down) and the **blinking cursor** timing originate — both are timer-interrupt driven.
- `_GetCSC` (`00:04B2`) cooperates with the ISR: the ISR (or keypad path) updates `kbdScanCode`; `_GetCSC` atomically reads and clears it with interrupts masked. **[confirmed]**

## TODO
- Map each `(IY+off)` flag the ISR touches to its `SystemFlags` field name (apdFlags, onFlags, …) and annotate.
- Trace the timer reprogramming to recover the APD timeout value and cursor blink rate.
