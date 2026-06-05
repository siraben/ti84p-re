# 06 — Floating-Point Engine

All TI-BASIC arithmetic runs through a BCD floating-point engine centered on the **OP registers** in RAM. The engine lives mostly on flash page 0 (it's hot), with the RST-30 shortcut for the most common op.

## Number format — `TIFloat` (9 bytes on disk) [confirmed]

```
+0  type      0x00 = real (positive), 0x80 = negative real;
              0x0C/0x8C = complex (paired with the imaginary part)
+1  exp       base-100? no — base-10 exponent, biased by 0x80 (0x80 = 10^0)
+2..+8  mantissa   7 bytes = 14 packed BCD digits, normalized d.dddddddddddddd
```
Value = ±(d0 . d1 d2 … d13) × 10^(exp−0x80). The BCD scan found 126 such constants ROM-wide (π/180=1.745…e-2, 180/π=5.729…e1, 65536, plus coefficient tables on page 7).

## OP registers — 11 bytes each [confirmed]

`OP1`–`OP6` at `0x8478`, spaced **11** bytes (`OP2`=0x8483 …). The extra 2 bytes past the 9-byte number are **extended guard digits** used during math: `OP1EXT`/`OP2EXT` = bytes +9/+10 (seen in `_FPAdd` as `DAT_ram_8481`/`8482`). `OP1` is the primary accumulator; most routines take their argument in `OP1` (and `OP2` for binary ops) and return in `OP1`.

## Core operations [confirmed from disassembly]

| Routine | Addr | Role |
|---------|------|------|
| `_FPAdd` | `00:229E` (= **RST 30h**) | OP1 = OP1 + OP2 |
| `_OP1ToOP2` | `00:1A2F` (= **RST 08h**) | copy OP1→OP2 (11-byte copy via `FUN_ram_1a8e`) |
| `_Mov9ToOP1` | `00:1B01` (= **RST 20h**) | copy 9 bytes at HL → OP1 (load a constant/var) |
| `_CkOP1FP0`/`_CkOP2FP0` | page 0 | test if OP1/OP2 == 0 (sets Z) |
| `_CkOP1Real` | page 0 | type-check OP1 is real |

### `_FPAdd` algorithm (recovered)
1. Early-out: if `OP2==0` return; if `OP1==0` copy OP2→OP1 (incl. extended bytes) and return.
2. Compute exponent difference; shift the smaller operand's mantissa right (`FUN_ram_1bea` per digit) to align — bail if the difference > 15 (one operand negligible).
3. Compare sign bits (`OP1.type^OP2.type & 0x80`): equal → BCD add mantissas; differ → BCD subtract, then renormalize/fix the result sign.
4. Round using the extended guard digits, renormalize, store exponent/type in OP1.

This is the canonical sign-magnitude BCD add. Named helpers [confirmed]:
- `fp_exp_diff` (`1fbf`) — `OP1.exp − OP2.exp` (alignment amount).
- `fp_shift_right_digit` (`1bea`) — shift a 9-byte mantissa right by one BCD digit (nibble cascade); called per-step to align the smaller operand.
- `fp_clear_guard` (`2627`) — zero the extended guard bytes (`OP1EXT`/`OP2EXT` @ `0x8481`/`0x848C`).
- `fp_sub_mantissa` (`1d37`) — BCD subtract of mantissas (with guard-digit borrow) for opposite-sign add.

Multiply/divide/transcendentals (on page 0x02) reuse the same align/normalize primitives.

## Floating-point stack (FPS) [standard]
`FPS` (`0x9824`) is a software stack for temporaries; `_PushRealO1` (= **RST 18h**, `00:155C`), `_PushReal`, `_PopRealOx`, `_AllocFPS`/`_DeallocFPS` manage it. Used to spill OP registers during nested expression evaluation.

## TODO
- Name the FP helper cluster `FUN_ram_1bea/1d37/1cb9/1d2f/1fbf` (shift/sign/normalize).
- Locate `_FPMult`/`_FPDiv`/`_FPRecip` and the transcendental routines (sin/cos/ln/exp) — likely on a banked page using the page-7 coefficient tables.
