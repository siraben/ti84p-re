# Calculation engine

The calculation engine evaluates arithmetic and transcendental expressions in
the `OP1`–`OP6` BCD floating-point registers. The software stack at `FPS`
(`0x9824`) holds nested temporaries. [Floating-point engine](floating-point.md)
defines the `TIFloat` format and `_FPAdd`; this page covers multiplication,
division, powers, roots, transcendentals, formatting, and errors.

## Register and stack model [confirmed]

Scalar floating-point routines use the OP registers; nested evaluations can
spill values to the software FP stack. Integer helpers and aggregate operations
also use ordinary Z80 registers and other RAM buffers.

| Reg | Addr | Role in a calc |
|-----|------|----------------|
| `OP1` | `0x8478` | primary accumulator / result. Unary ops take arg here, return here. |
| `OP2` | `0x8483` | second operand for basic real arithmetic (`OP1 ∘ OP2 → OP1`); complex routines use different pairings. |
| `OP3`–`OP6` | `0x848E`… | scratch; sign/exponent staging, complex pairs. |
| guard | `0x8481/8482` (OP1EXT), `0x848C/848D` (OP2EXT) | extended guard digits, zeroed by `fp_clear_guard` at the top of nearly every op. |
| `FPS` | `0x9824` | software FP stack for spilling OP registers during nested evaluation. |

A `TIFloat` is `type(+0) exp(+1) mantissa(+2..+8)`; `type` bit 7 is the
sign, and low-five-bit class `0x0C` denotes a complex component, not two
independent complex flags. `exp` is base-10 biased by `0x80`. Nonzero negation
toggles sign bit 7; the sign-inversion helpers separately canonicalize zero.

### FP-stack discipline during nested expressions [confirmed]

Binary/transcendental routines that need to preserve an operand spill it to `FPS`:
- `_PushRealO1` (= `RST 18h`, `ram:155C`), `_PushReal`/`_PushRealOn`, `_PushOP1` (`ram:1599`).
- `_PopRealO1`…`_PopRealO6` (`ram:150F`…`14F6`), `_PopReal` (`ram:1512`).
- `_AllocFPS`/`_DeallocFPS` (`ram:1534`/`1526`) grow/shrink the stack frame.

For example, the [complex-log core](#transcendentals) uses `_PushRealO1` to save the input,
computes the magnitude, then uses `_PopRealO2` to recover the saved real component
for the angle. This is one concrete spill/restore sequence, not a contract for
every parser sub-expression.

---

## Basic arithmetic [confirmed]

All four route operands through `OP1`/`OP2`, clear the guard digits, early-out on zero
operands, then do BCD mantissa work and renormalize. Result in `OP1`.

| Op | Routine | Addr | Notes |
|----|---------|------|-------|
| `+` | `_FPAdd` | `ram:229E` (= `RST 30h`) | sign-magnitude BCD add; see [floating-point.md](floating-point.md). |
| `−` | `_FPSub` | `ram:2297` | flips `OP2.value.type` bit 7, then falls into the add path. |
| `×` | `_FPMult` | `ram:238B` | `ram:250F` adds the biased exponents and subtracts bias `0x80`; exponent overflow raises `_ErrOverflow`, underflow returns zero. Digit-by-digit BCD multiply accumulates into OP3. |
| `÷` | `_FPDiv` | `ram:2541` | `_CkOP2FP0` first → `_JError(0x82)` DIVIDE BY 0 if divisor 0; else restoring BCD long division. |
| `1/x` | `_FPRecip` | `ram:253D` | copies the input to OP2, sets `OP1=1`, then enters `_FPDiv`. |

Convenience / derived ops:
- `_FPSquare` `ram:238A` = `RST 08h` (OP1→OP2) then `_FPMult`. [confirmed]
- `_Cube` `ram:237D` = `_FPSquare` then `_FPMult`. [confirmed]
- `_Times2` `ram:2282` = `OP1+OP1`; `_TimesPt5` `ram:2382` loads the constant `0.5` (9-byte BCD @ `ram:2635`) into OP2 then `_FPMult`. [confirmed]
- `_InvSub` `ram:227D` = `_InvOP1S` then `_FPAdd` ⇒ `OP2 − OP1` (reversed subtract). [confirmed]
- **Negation**: `_InvOP1S` `ram:24BD` (XOR `OP1.value.type` with `0x80`, guarding against −0), `_InvOP2S` `ram:24CD`, `_InvOP1SC` `ram:24BA` (both). `_CkOP1Pos` `ram:1E5D` ANDs `OP1.value.type` with `0x80`. [confirmed]

### Roots and integer parts [confirmed]

- `_SqRoot` `02:6E38` expects a real input. `_ErrD_OP1NotPos` rejects a negative sign but does not check the object class. After zero/guard handling and `_ZeroOP3`, the digit-extraction loop adds a trial digit at `ram:1C9C` and subtracts the trial quantity at `ram:1D4A`, halving the exponent up front. This is a digit-by-digit BCD square root, not Newton iteration.
- `_Intgr` (`ram:2263`) computes floor. It first calls the integer test at `ram:1E03` and returns unchanged for integral inputs. Otherwise it calls `_Trunc` (`ram:2279`), which truncates toward zero, and subtracts 1 for a negative input.
- `_Frac` `ram:24E3`: fractional part = x − trunc(x); shifts mantissa by the exponent and keeps the low digits.
- `_Round` (`ram:2623`) rounds to `D` decimal places through the banked body at `02:5165`. `_Int` (`ram:2621`) selects `D=0`, so it rounds to an integer; it is distinct from TI-BASIC `int(`, which uses floor. The digit tests at `02:51A6`/`02:51AC` round discarded magnitudes of at least one half upward, preserving the input sign.
- `_RndGuard` (`02:6A57`) sets `D=9`, temporarily sets the exponent to `0x80`, calls `_Round`, and restores the exponent with carry correction. This rounds the mantissa to ten significant digits independently of the display setting.

---

## Degree, radian, and polar conversions [confirmed]

- `_DToR` `ram:236B` (deg→rad): multiply OP1 by $\pi/180$ (`ram:235D` loads the constant) then normalize via `ram:249E`.
- `_RToD` `ram:2374` (rad→deg): multiply by $180/\pi$ (`ram:2361`).
- `_PToR` `02:50BD` polar→rectangular; pairs with the complex trig below.
These constants are the BCD floats `π/180 = 1.745…e-2` and `180/π = 5.729…e1` noted in
[floating-point.md](floating-point.md)'s constant scan.

---

## Cross-page dispatch (`cross_page_jump` at `ram:2B09`) [confirmed]

Banked ROM calls use a bcall-style trampoline.
`cross_page_jump`:
1. saves the current page (`IN A,(6)`),
2. builds a `RET`-to-page-0 trampoline on the stack (`bcall` return frame, page restored on exit),
3. reads a 3-byte `{lo, hi, page}` descriptor (page masked with `0x1F`/`0x3F` for 83+/84+ via ports 2/0x21),
4. `OUT (6),A` to bank the target page in at `4000`, then jumps to it.

The ln/e^x sites that look similar are local calls, not cross-page dispatches.
`fp_mul_indexed_constant` (`ram:2362`) reaches `coeff_fetch` (`02:7D1E`)
through the inline descriptor at `ram:3DD1`. The preceding `LD A,3` or
`LD A,6` selects a coefficient, not a page. `_EToX` branches locally into
the `_TenX` body at `02:7069`. `logexp_digit_table` (`02:7181`),
`trig_recurrence_table_a` (`02:7201`), `trig_recurrence_table_b` (`02:7281`),
and `fp_constant_table` (`02:7D42`) all reside on page `02`. [confirmed]

---

## Transcendentals

### Logarithms [confirmed]

- `_LnX` `02:6EFD` is a real-input entry. `_CkOP1Pos` rejects a negative sign, then the routine selects `C=2` and joins `02:6F1B`; a separate guard rejects zero. It does not type-check or dispatch every complex input.
- `_LogX` `02:6F16`: same structure, base-10 selector `C=0`, guards `_ErrD_OP1_0`/`_ErrD_OP1NotPos`.
- `_CLN` `02:6CCA` / `_CLog` `02:6CE7` compute the real part from `_CAbs` followed by `_LnX`/`_LogX`. `_ATan2Rad` supplies the argument in radians. `_CLog` additionally multiplies that angle by `log10(e)` at `02:6CFE`–`6D03`, so its imaginary part is `arg(z)/ln(10)`, not `arg(z)`. `_PushRealO1`/`_PopRealO2` preserve the original real component for the angle calculation. Parser mode checks are separate from these raw arithmetic bodies.

The real-log core has both a table-driven path and a near-one path at
`02:6F33`–`6F7C`. The latter forms and rescales `(x-1)/(x+1)`, calls the digit recurrence
at `02:77A6` with `A=0x80`, and doubles the result. See
[Floating-point engine](floating-point.md).

### Exponentials [confirmed]

- `_EToX` `02:705C` (e^x): loads the `log10(e)` constant through `fp_mul_indexed_constant`,
  then branches into the shared `_TenX` body at `02:7069`.
- `_TenX` `02:7066` (10^x): splits exponent into integer (digit shift) + fractional
  (16-slot table-driven evaluation through `logexp_digit_table`). The magnitude gate at `02:7076`–`7078` reaches `02:7053`: positive inputs of magnitude at least 100 overflow; negative inputs at that gate return zero.

### Trigonometric functions [confirmed]

- `_SinCosRad` `02:733E`, `_Sin` `7342`, `_Cos` `7346`, `_Tan` `734A`. Each loads a
  function selector byte into `0x8499` (`1`=sin, `2`=cos, `4`=tan; `0x80` bit set when
  the rad-special mode tested by `BIT 2,(IY+0)` is off; `_SinCosRad` forces `0x81`).
- Range reduction: subtracts the exponent bias; unbiased exponent ≥ `0x0C` (|x| ≥ 10^12) → `_ErrDomain`
  ("argument out of range"). It then reduces the angle modulo a quarter-period using the
  BCD constants near `02:7D81` and runs a separate table-driven digit recurrence
  over the two trig recurrence tables (one row per digit step,
  sign-variant picked by `OP5.value.type` bit 7) — the per-step `bcd_sub_op1_op2`
  (`ram:1D8A`) / `bcd_add_8496_8480` (`ram:1D26`) are the shift-and-add BCD steps of that
  recurrence, not a fixed polynomial and not CORDIC for the forward trig. The per-row
  decoding of `02:7201`/`02:7281` is detailed in [floating-point.md](floating-point.md).

### Inverse trig [confirmed]

- `_ASinRad` `76DA`, `_ACosRad` `76C9`, `_ATanRad` `76CF`, `_ATan2Rad` `76D4`, plus the
  degree-mode `_ASin`/`_ACos`/`_ATan`/`_ATan2` at `76F1`/`76DF`/`76E9`/`7749`.
- `_ASin`/`_ACos` call domain check `02:79D3`; |arg| > 1 → `_ErrDomain`.
- All inverse trig funnel into the shared arctangent CORDIC engine at `02:774B`
  (`B=0x20` seeds the octant/quadrant base written to `0x84A4`; the core is a base-10
  trial-subtract digit recurrence, not a fixed 32-step loop), with asin/acos expressed
  via atan2 of (x, √(1−x²)).

### Hyperbolics [confirmed]

- `_SinHCosH` `02:7626`, `_TanH` `02:762A`, `_CosH` `02:762E`, `_SinH` `02:7632`; `_ATanH`/`_ASinH`/`_ACosH`
  at `02:7909`/`02:7956`/`02:7964`. The forward entries store their selector at `0x8499`. The large-argument sinh/cosh path calls `_EToX` at `02:7680`, takes a reciprocal at `02:7683`, combines the two magnitudes according to the selector, and halves the result. Small arguments branch through `02:7489`; the exponential identity is not the only path.

### Power operator `^` [confirmed]

The real `_YToX` entry is bcall `47A1h`, targeting `33:6340`. It handles
zero and sign cases, then uses repeated multiplication for suitable small
positive integer exponents (`33:63DD`–`6408`). Its general path calls
`50FEh` → `02:6F1B` with `C=1` for a base-10 logarithm, multiplies by the
saved exponent at `33:641C`, then calls `5101h` → `02:7069` for `10^x`.
Thus this path evaluates `10^(b*log10(a))`; it does not enter at `02:6D08`.

The complex power entry `_CYtoX = 4EB2h` targets `02:6D5C`. Its general
branch calls `_CLN` at `02:6D7B`, `_CMult` at `02:6D7E`, then enters
`_CEtoX` at `02:6D1D`. The neighboring `02:6D08` entry is `_CTenX = 4EA6h`,
complex `10^x`, which rescales its input before joining `_CEtoX`.

---

## Number entry and display formatting

When the homescreen shows a result (or `Ans`), the engine converts the `OP1` `TIFloat` to a
digit string honoring the **MODE** screen (Normal/Sci/Eng, Float/Fix 0–9).

- `_FormReal` `06:5ACF` — real-number formatter. [confirmed]
  - `fp_clear_guard`; zero → `_OP1Set0`; copies arg to OP5.
  - Uses `(IY+0x0C)` bit 0 to select an override or `fmtFlags` at `0x89FA`;
    `(IX-1)` holds the effective format byte. `0x89FA` is not the decimal-place
    count; `fmtDigits` is at `0x97B0`.
  - Exponent thresholds drive Normal↔Sci switchover: it compares `OP1.value.exp` against `0x7D`/`0x7F`
    (≈ the ±-exponent window) and renormalizes (`ram:1BE7`) to bring the value into the
    displayable mantissa range, bumping a digit counter. Negative sign decrements the leading
    column count (`DEC (IX-3)`).
- `_FormEReal` `06:5799` calls `06:57A1`, which sets `(IY+0x0C)` bit 0 but clears it when `cxCurApp` (`0x859A`) equals `0x53`. It calls `_FormReal` and clears the override on return; the override is not unconditional. [confirmed]
- `_FormBase` `06:57C0` is a typed numeric formatter dispatcher, not an arbitrary-radix integer converter. It classifies `OP1.type & 0x1F` through `ram:21C1`, handles types `0x18`/`0x19` through `06:60FC`, and routes to the relevant formatting body. `_CkOP1Real` itself returns a masked type and flags; it does not raise DATA TYPE or DOMAIN. [confirmed]
- `_FormDCplx` `06:59D3` — complex `a+bi` / `r∠θ` formatting (calls `_FormReal` twice). [standard]
- Exponent helpers on page 0: `_ExpToHex` at `ram:1E4E` replaces the pointed exponent with its unbiased magnitude; `_OP1ExpToDec` at `ram:1E77` applies it to OP1 and returns a packed-BCD magnitude in A, not ASCII. `_DecO1Exp` at `ram:1E6F` decrements the exponent; `_ShRAcc` at `ram:1BCB` extracts A's high nibble. [confirmed]
- The formatted string is then drawn by `_DispOP1A` (`04:7844`) / homescreen put-string
  routines (see [display-lcd.md](display-lcd.md)).

`Ans` holds the last result, which may be a real, complex, list, matrix, or
string value. `_RclAns` (`38:679F`) enters the typed recall machinery; the
9-byte `_Mov9ToOP1` transfer describes a real scalar, not every `Ans` value.
[standard]

---

## Error handling [confirmed]

Errors are raised by loading an error code in `A` and jumping to `_JError` (`ram:2793`),
which unwinds to the installed error callback. The callback can handle an error
without displaying it; `_JError` itself does not guarantee a dialog. The raiser cluster lives at
`ram:26E8`+ — exact code map read from disassembly:

| Raiser | Addr | `A` code | Message |
|--------|------|----------|---------|
| `_ErrOverflow` | `ram:26E8` | `0x81` | OVERFLOW |
| `_ErrDivBy0` | `ram:26EC` | `0x82` | DIVIDE BY 0 |
| `_ErrSingularMat` | `ram:26F0` | `0x83` | SINGULAR MAT |
| `_ErrDomain` | `ram:26F4` | `0x84` | DOMAIN |
| `_ErrIncrement` | `ram:26F8` | `0x85` | INCREMENT |
| `_ErrNon_Real` | `ram:26FC` | `0x87` | NONREAL ANS |
| `_ErrSyntax` | `ram:2700` | `0x88` | SYNTAX |
| `_ErrMode` | `ram:2704` | `0x9E` | MODE |
| `_ErrDataType` | `ram:2708` | `0x89` | DATA TYPE |
| `_ErrArgument` | `ram:2711` | `0x8A` | ARGUMENT |
| `_ErrDimMismatch`/`Dimension` | `ram:2715`/`2719` | `0x8B`/`0x8C` | DIM MISMATCH / INVALID DIM |
| `_ErrUndefined`/`Memory` | `ram:271D`/`2721` | `0x8D`/`0x8E` | UNDEFINED / MEMORY |

**Domain pre-checks** (page 0; success flags differ between entries):
- `_ErrD_OP1NotPos` `ram:2119` — tests the sign bit through `_CkOP1Pos`; a negative sign raises DOMAIN. This helper accepts positive zero.
- `_ErrD_OP1Not_R` `ram:2120` — `_CkOP1Real`; any nonzero low-five-bit type raises DOMAIN, while type 0 returns Z.
- `_ErrD_OP1NotPosInt` `ram:2125` — `_CkPosInt`.
- `_ErrD_OP1_LE_0` `ram:212A` checks sign then zero; `_ErrD_OP1_0` `ram:212D` checks zero only. Both return NZ on a nonzero accepted input.

**Where the calc engine raises what:**
- `÷ 0`, `1/0`: `_FPDiv`/`_FPRecip` → `0x82` DIVIDE BY 0.
- `×`/`10^x`/exponent overflow: `ram:250F` exponent-add → `0x81` OVERFLOW.
- `√(neg)`, `ln/log(≤0)`, `asin/acos(|x|>1)`, `tan(π/2)`, |trig arg| ≳ 10^12: `0x84` DOMAIN.
- Complex result requested in real mode: `0x87` NONREAL ANS (the `_CLN`/complex paths).

---

## Routine index

Arithmetic core (page 0): `_FPAdd 229E`, `_FPSub 2297`, `_FPMult 238B`, `_FPDiv 2541`,
`_FPRecip 253D`, `_FPSquare 238A`, `_Cube 237D`, `_Times2 2282`, `_TimesPt5 2382`,
`_InvSub 227D`, `_Int 2621`, `_Intgr 2263`, `_Trunc 2279`, `_Frac 24E3`, `_Round 2623`,
`_InvOP1S 24BD`, `_InvOP2S 24CD`, `_InvOP1SC 24BA`, `_CkOP1Pos 1E5D`, `fp_clear_guard 2627`,
`fpmul_expadd 250F`, `_DToR 236B`, `_RToD 2374`, `cross_page_jump 2B09`.

Transcendentals (page 02): `_SqRoot 6E38`, `_LnX 6EFD`, `_LogX 6F16`, `_CLN 6CCA`,
`_CLog 6CE7`, `_CTenX 6D08`, `_CEtoX 6D1D`, `_CYtoX 6D5C`, `_EToX 705C`, `_TenX 7066`, `_SinCosRad 733E`, `_Sin 7342`,
`_Cos 7346`, `_Tan 734A`, `_SinHCosH 7626`, `_TanH 762A`, `_CosH 762E`, `_SinH 7632`,
`_ACosRad 76C9`, `_ATanRad 76CF`, `_ATan2Rad 76D4`, `_ASinRad 76DA`, `_ACos 76DF`,
`_ATan 76E9`, `_ASin 76F1`, `_ATan2 7749`, `atan_cordic 774B`, `coeff_fetch 7D1E`,
`trig_coeff_table 7D81`.

Formatting (page 06): `_FormReal 5ACF`, `_FormEReal 5799`, `_FormBase 57C0`, `_FormDCplx 59D3`.

Real power (page `33`): `_YToX 6340`.

Errors (page 0): `_JError 2793`, raiser table `26E8`+, domain pre-checks `2119`–`2131`.

---

## Worked flow: `2*sin(π/6)+ln(5)` [hypothesis]

1. Parser pushes `2` (`OP1`), evaluates `sin(π/6)`: loads `π/6` into OP1, `_SinCosRad`/`_Sin`
   (selector `0x8499`), table-driven digit recurrence → `OP1=0.5`.
2. `×`: the saved `2` is in `OP2` (or popped from FPS) → `_FPMult` → `OP1=1`.
3. `ln(5)`: spill `1` to FPS (`_PushRealO1`), `OP1=5`, `_LnX` (`_CkOP1Pos` passes) → `1.6094…`.
4. `+`: pop `1` to `OP2` (`_PopRealO2`), `_FPAdd` → `OP1≈2.6094`.
5. `_FormReal` renders per MODE; result stored as `Ans`.
