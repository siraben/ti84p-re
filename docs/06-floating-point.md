# 06 — Floating-Point Engine

> **Deep dive:** [Calculation Engine](sub-calculation.md) — ×, ÷, ^, roots, the transcendentals (sin/cos/ln/eˣ), and number formatting.

All TI-BASIC arithmetic runs through a BCD floating-point engine centered on the **OP registers** in RAM. The engine lives mostly on flash page 0 (it's hot), with the RST-30 shortcut for the most common op.

## Number format — `TIFloat` (9 bytes on disk) [confirmed]

```
+0  type      0x00 = real (positive), 0x80 = negative real;
              0x0C/0x8C = complex (paired with the imaginary part)
+1  exp       base-100? no — base-10 exponent, biased by 0x80 (0x80 = 10^0)
+2..+8  mantissa   7 bytes = 14 packed BCD digits, normalized d.dddddddddddddd
```
The stored value is

$$v = \pm\\,(d_0.d_1d_2\cdots d_{13})\times 10^{\\,e-\mathtt{0x80}}$$

where $e$ is the biased exponent byte and $d_0\ldots d_{13}$ are the 14 BCD mantissa digits. A local ROM-byte scan found 126 candidate BCD constants ROM-wide ($\pi/180 = 1.745\ldots\mathrm{e}{-2}$, $180/\pi = 5.729\ldots\mathrm{e}{1}$, 65536, plus coefficient tables on page 7). The current MCP interface does not expose raw byte search, so this count should be treated as a scan artifact rather than an MCP-confirmed fact.

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

```pseudocode
\begin{algorithm}
\caption{\texttt{\_FPAdd}: $OP1 \gets OP1 + OP2$ (sign-magnitude BCD)}
\begin{algorithmic}
\IF{$OP2 = 0$}
    \RETURN $OP1$
\ENDIF
\IF{$OP1 = 0$}
    \STATE $OP1 \gets OP2$ \COMMENT{incl. extended bytes}
    \RETURN $OP1$
\ENDIF
\STATE $\Delta \gets \mathrm{exp}(OP1) - \mathrm{exp}(OP2)$ \COMMENT{\texttt{fp\_exp\_diff}}
\STATE shift the smaller mantissa right by $|\Delta|$ digits to align \COMMENT{\texttt{fp\_shift\_right\_digit}}
\IF{$|\Delta| > 15$}
    \RETURN larger operand \COMMENT{other is negligible}
\ENDIF
\IF{$\mathrm{sign}(OP1) = \mathrm{sign}(OP2)$}
    \STATE $\mathrm{mantissa} \gets$ BCD-add
\ELSE
    \STATE $\mathrm{mantissa} \gets$ BCD-subtract; fix result sign \COMMENT{\texttt{fp\_sub\_mantissa}}
\ENDIF
\STATE round via the guard digits, renormalize, store exp/type in $OP1$
\RETURN $OP1$
\end{algorithmic}
\end{algorithm}
```

This is the canonical sign-magnitude BCD add. The full helper cluster is documented below.

### The FP helper cluster [confirmed]

These five page-0 primitives are shared by add/sub/mult/div and the transcendentals. All were decompiled and disassembled in this ROM; the names below were applied to the Ghidra DB. They operate on the OP-register guard region (`OP1EXT`/`OP2EXT` at `0x8481`/`0x848C`) and the 7-byte mantissas of `OP1` (`0x8478`) / `OP2` (`0x8483`).

| Helper | Addr | Role [confirmed] |
|--------|------|------|
| `fp_shift_right_digit` | `ram:1bea` | Mantissa **shift-right by one BCD digit** (one nibble). Cascades nibbles down 8 bytes (`b[i] = b[i]>>4 \| b[i-1]<<4`) and returns the digit shifted out. Called per step to align the smaller operand. |
| `fp_exp_diff` | `ram:1fbf` | **Exponent difference** `OP1.exp − OP2.exp` (signed). Drives how many `fp_shift_right_digit` steps are needed for alignment. |
| `fp_add_mantissa` | `ram:1cb9` | **BCD add** of the two mantissa+guard runs. Sets `HL=0x848C` (OP2 guard), `DE=0x8481` (OP1 guard) and runs the shared BCD add/`DAA`-style adjust loop (`bcd_add_pair`). Used for same-sign add. |
| `fp_sub_mantissa` | `ram:1d37` | **BCD subtract** (`OP1 − OP2`) of mantissa+guard with borrow, via the `BCDadjust`/`BCDadjustCarry` chain across all 7 mantissa bytes plus the guard byte. Used for opposite-sign add. (`ram:1d2f`, `fp_sub_mantissa_fwd`, is the same subtract entered with the operand pointers swapped.) |
| `fp_clear_guard` | `ram:2627` | Zero the extended guard bytes (`OP1EXT`/`OP2EXT`). |

`ram:1d2f` and `ram:1d37` are two entry points into the same BCD-subtract body — `1d2f` loads `HL=0x8481, DE=0x848C` (subtract OP2 from OP1) and `1d37` loads `HL=0x848C` (the reverse direction) before joining the common loop — so the caller picks the subtraction direction by choosing the entry. This is what lets `_FPAdd` produce a non-negative magnitude and then fix the sign.

Multiply/divide/transcendentals (on page 0x02) reuse the same align/normalize primitives.

## Floating-point stack (FPS) [standard]
`FPS` (`0x9824`) is a software stack for temporaries; `_PushRealO1` (= **RST 18h**, `00:155C`), `_PushReal`, `_PopRealOx`, `_AllocFPS`/`_DeallocFPS` manage it. Used to spill OP registers during nested expression evaluation.

## Multiply / divide / transcendentals [confirmed — located]

The rest of the FP op set lives alongside add on page 0, with the transcendentals banked to page 0x02:

| Routine | Addr | Role |
|---------|------|------|
| `_FPSub` | `00:2297` | OP1 = OP1 − OP2 |
| `_FPMult` | `00:238B` | OP1 = OP1 × OP2 |
| `_FPRecip` | `00:253D` | OP1 = 1 / OP1 |
| `_FPDiv` | `00:2541` | OP1 = OP1 / OP2 |
| `_LnX` | `02:6EFD` | natural log |
| `_EToX` | `02:705C` | eˣ |
| `_SinCosRad` | `02:733E` | sin/cos (radians) |

See [Calculation Engine](sub-calculation.md) for the ×/÷/^/root algorithms and number formatting.

## Transcendental method [confirmed structure]

The three transcendental entry points on page 0x02 share a common shape: a **page-0x02 prologue** that does type/domain checking and range reduction (reading BCD constants from the page-0x02 constant block near `0x7d81`), followed by a **cross-page tail call** to the actual series evaluator on a higher flash page. The cross-page hop is the standard `LD A,<page>; CALL 0x2362` trampoline (`0x2362` → `CALL 0x3dd1`, the bank-switch dispatcher), which is why the page-0x02 bodies look truncated in the decompiler.

### `_LnX` — natural log (`02:6EFD`) [confirmed]

`_LnX` first calls `_CkOP1Pos` (`0x1e5d`) and raises a domain error on `x ≤ 0`. The core (`02:6F1B`) performs an **argument/range reduction** that splits `x` into mantissa × 10^exp, then computes a log via the `(x−1)/(x+1)` substitution: at `02:6F45`–`02:6F50` it forms numerator/denominator with `_FPAdd` (RST 30h) / `_FPSub` and divides with `_FPDiv` (`0x2541`), and a digit-driven Horner loop (`02:6F8C`–`02:6FEC`, stepping with the per-term helper at `0x7301`/`0x7302` and `_FPAdd`/mantissa-shift `0x1ca9`) evaluates the odd-power series `2·(t + t³/3 + t⁵/5 + …)` where `t = (x−1)/(x+1)`. The exponent contributes `exp·ln(10)`, recombined at the end. The series **coefficient table and ln(10) constant live on the cross-page tail** (`02:6F70: LD A,3; CALL 0x2362` → page 0x03), so the exact term count is not byte-traced here **[hypothesis: ~8–10 odd terms, atanh-style series]**.

### `_EToX` — eˣ (`02:705C`) [confirmed]

The page-0x02 entry is a thin thunk: `fp_clear_guard` (`0x2627`) then `LD A,3; CALL 0x2362` — it immediately tail-calls the eˣ body on **page 0x03** (`cross_page_jump(3)`). The standard method (exponent split `eˣ = 10^(x·log₁₀e)`, integer part → decimal exponent, fractional part → series) is consistent with the surrounding code but the body and its coefficient table sit on page 0x03 and were not traced byte-for-byte through the thunk **[hypothesis for the page-0x03 series details]**.

### `_SinCosRad` — sin/cos in radians (`02:733E`) [confirmed]

This one keeps its **range reduction on page 0x02** and is the most fully recovered:

1. **Mode/select flags.** `0x8499` holds a sin/cos + quadrant selector (`0x81`/`0x04`/`0x80` bits, partly from `(IY+0)` bit 2). `fp_clear_guard` and `_ZeroOP3` initialize the work area.
2. **Exponent gate.** `LD A,(0x8479); SUB 0x80; CP 0x0C; JP NC` — arguments with decimal exponent ≥ 12 are rejected to the slow/error path (`_JError 0x84` for out-of-range), because reduction can no longer be done accurately.
3. **Reduce mod π/2.** It multiplies by a stored reciprocal constant and takes the fractional part to find the quadrant. The reduction constants are the page-0x02 BCD block:
   - `0x7d81` — reduction reciprocal (2/π-class constant), loaded into the OP3 work reg via `LD HL,0x7d81; CALL 0x1ae2` (`0x1ae2` copies a constant to `0x8490`).
   - `0x7d8e`, `0x7d95`, `0x7d96` — companion constants used in the quadrant-fixup / remainder comparisons (`CALL 0x1d7b` magnitude compare at `02:73B1`/`02:7447`).
   The quadrant (0–3) is accumulated in `B`/`bStack_1` (bits 0/3/6) and decides sin-vs-cos and the result sign (the `XOR 0x1 / OR 0x8 / XOR 0x8` flag juggling at `02:7424`–`02:7464`).
4. **Polynomial evaluation.** After reduction (`02:7475` onward, falling through `02:7488 LD A,B`) the reduced argument in `[0, π/4)` is fed to a Horner polynomial. The **coefficient table for the sin/cos minimax (or Taylor) series is reached through the page tail**, so the term count is not byte-confirmed here **[hypothesis: ~6–7 even/odd terms]**.

### What is confirmed vs. hypothesis

- **Confirmed:** the helper-cluster roles and addresses; that all three transcendentals are page-0x02 prologue + cross-page series tail; the ln `(x−1)/(x+1)` substitution with `_FPDiv` and a Horner digit loop; the SinCos exponent gate (exp ≥ 12 rejected), the mod-π/2 reduction, and the page-0x02 reduction-constant addresses `0x7d81`/`0x7d8e`/`0x7d95`/`0x7d96`; the quadrant bookkeeping.
- **[hypothesis] / residual TODO:** the exact polynomial **coefficient tables and term counts** for ln/eˣ/sin-cos. Those live on the cross-page series bodies (page 0x03, and page 0x06 for one eˣ branch — `02:704A: LD A,6; CALL 0x2362`) reached through the `0x2362` trampoline, and resolving them byte-exactly requires following the bank-switched targets, which the MCP block view truncates at the thunk. No CORDIC iteration was observed — the evidence points to **Horner polynomial / atanh-series evaluation**, not CORDIC.

## TODO (residual)
- Trace the cross-page series bodies (page 0x03 / 0x06, reached via the `0x2362` trampoline) to read the actual ln/eˣ/sin-cos coefficient tables and confirm the exact term counts.
