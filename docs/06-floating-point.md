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

$$v = \pm\,(d_0.d_1d_2\cdots d_{13})\times 10^{\,e-\mathtt{0x80}}$$

where $e$ is the biased exponent byte and $d_0\ldots d_{13}$ are the 14 BCD mantissa digits. The BCD scan found 126 such constants ROM-wide ($\pi/180 = 1.745\ldots\mathrm{e}{-2}$, $180/\pi = 5.729\ldots\mathrm{e}{1}$, 65536, plus coefficient tables on page 7).

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

This is the canonical sign-magnitude BCD add. Named helpers [confirmed]:
- `fp_exp_diff` (`1fbf`) — `OP1.exp − OP2.exp` (alignment amount).
- `fp_shift_right_digit` (`1bea`) — shift a 9-byte mantissa right by one BCD digit (nibble cascade); called per-step to align the smaller operand.
- `fp_clear_guard` (`2627`) — zero the extended guard bytes (`OP1EXT`/`OP2EXT` @ `0x8481`/`0x848C`).
- `fp_sub_mantissa` (`1d37`) — BCD subtract of mantissas (with guard-digit borrow) for opposite-sign add.

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

See [Calculation Engine](sub-calculation.md) for the ×/÷/^/root algorithms, the transcendental method, and number formatting.

## TODO
- Name the FP helper cluster `FUN_ram_1bea/1d37/1cb9/1d2f/1fbf` (shift/sign/normalize).
- Map the page-2/page-7 minimax/CORDIC coefficient tables to `_SinCosRad`/`_LnX`/`_EToX` and document the polynomial-eval method (open item 10 in [99](99-open-questions.md)).
