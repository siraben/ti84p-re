# Calculation engine

*TI-84 Plus OS 2.55MP — feature deep dive.*

What happens between a college student typing `2*sin(π/6)+ln(5)` and seeing a number.
All arithmetic is BCD floating point in the **OP registers** (`OP1`–`OP6` @ `0x8478`,
11-byte spaced) with a software **FP stack** (`FPS` @ `0x9824`) for nested temporaries.
See [06-floating-point.md](06-floating-point.md) for the `TIFloat` byte format and `_FPAdd` internals; this doc
covers the rest of the engine: ×, ÷, ^, roots, transcendentals, formatting, and errors.

Address form below is `page:addr` (flash page in slot `4000`) or `ram:addr` for the fixed
page-0 core mapped at `0000`. Page-0 routines are reached by `RST`/direct `CALL`; everything
else through the bcall dispatcher. Confidence: **[confirmed]** = read from disassembly,
**[standard]** = matches documented TI behavior, **[hypothesis]** = inferred.

---

## 1. Register & stack model [confirmed]

Every calculation runs through the OP registers and the software FP stack; the table
gives each register's RAM address and its role during an operation.

| Reg | Addr | Role in a calc |
|-----|------|----------------|
| `OP1` | `0x8478` | primary accumulator / result. Unary ops take arg here, return here. |
| `OP2` | `0x8483` | second operand for binary ops (`OP1 ∘ OP2 → OP1`). |
| `OP3`–`OP6` | `0x848E`… | scratch; sign/exponent staging, complex pairs. |
| guard | `0x8481/8482` (OP1EXT), `0x848C/848D` (OP2EXT) | extended guard digits, zeroed by `fp_clear_guard` at the top of nearly every op. |
| `FPS` | `0x9824` | software FP stack for spilling OP registers during nested evaluation. |

A `TIFloat` is `type(+0) exp(+1) mantissa(+2..+8)`; `type` bit7 = sign, bits set 0x0C = complex.
`exp` is base-10 biased by `0x80`. Sign is sign-magnitude, so **negation is a single XOR 0x80**.

### FP-stack discipline during nested expressions [confirmed]
Binary/transcendental routines that need to preserve an operand spill it to `FPS`:
- `_PushRealO1` (= **RST 18h**, `ram:155C`), `_PushReal`/`_PushRealOn`, `_PushOP1` (`ram:1599`).
- `_PopRealO1`…`_PopRealO6` (`ram:150F`…`14F6`), `_PopReal` (`ram:1512`).
- `_AllocFPS`/`_DeallocFPS` (`ram:1534`/`1526`) grow/shrink the stack frame.

Example seen in the complex-log core (`_CLN`, §5): it does `_PushRealO1` to save the input,
computes the magnitude, then `_PopRealO2` to recover it for the angle — the canonical
"spill then restore" used everywhere the parser evaluates a nested sub-expression.

---

## 2. Basic arithmetic [confirmed]

All four route operands through `OP1`/`OP2`, clear the guard digits, early-out on zero
operands, then do BCD mantissa work and renormalize. Result in `OP1`.

| Op | Routine | Addr | Notes |
|----|---------|------|-------|
| `+` | `_FPAdd` | `ram:229E` (= **RST 30h**) | sign-magnitude BCD add; see [06-floating-point.md](06-floating-point.md). |
| `−` | `_FPSub` | `ram:2297` | flips `OP2.type` bit7 then falls into the add path. |
| `×` | `_FPMult` | `ram:238B` | `FUN_ram_250F` adds exponents (→ `_ErrOverflow` on carry past 0x7F), then digit-by-digit BCD multiply accumulating into OP3. |
| `÷` | `_FPDiv` | `ram:2541` | `_CkOP2FP0` first → `_JError(0x82)` DIVIDE BY 0 if divisor 0; else restoring BCD long division. |
| `1/x` | `_FPRecip` | `ram:253D` | sets `OP1=1` then enters the divide loop (same body as `_FPDiv`). |

Convenience / derived ops:
- `_FPSquare` `ram:238A` = `RST 08h` (OP1→OP2) then `_FPMult`. [confirmed]
- `_Cube` `ram:237D` = `_FPSquare` then `_FPMult`. [confirmed]
- `_Times2` `ram:2282` = `OP1+OP1`; `_TimesPt5` `ram:2382` loads the constant `0.5` (9-byte BCD @ `ram:2635`) into OP2 then `_FPMult`. [confirmed]
- `_InvSub` `ram:227D` = `_InvOP1S` then `_FPAdd` ⇒ `OP2 − OP1` (reversed subtract). [confirmed]
- **Negation**: `_InvOP1S` `ram:24BD` (XOR OP1.type with 0x80, guarding against −0), `_InvOP2S` `ram:24CD`, `_InvOP1SC` `ram:24BA` (both). `_CkOP1Pos` `ram:1E5D` ANDs OP1.type with 0x80. [confirmed]

### Roots & integer parts [confirmed]
- `_SqRoot` `page_02:6E38`: `_ErrD_OP1NotPos` (→ DOMAIN if negative/complex-real), `fp_clear_guard`, `_ZeroOP3`, then a **digit-by-digit BCD square-root extraction** loop (`FUN_ram_1C9C` trial-subtract + `FUN_ram_1D4A` compare, halving the exponent up front). Not Newton's method — classic long-hand sqrt.
- `_Int`/`_Intgr` `ram:2621`/`2263`: **floor**. `_Trunc` `ram:2279` drops the fractional part (toward zero); `_Intgr` truncates then subtracts 1 (`_Minus1` `ram:2294`) when the original was negative, giving true floor.
- `_Frac` `ram:24E3`: fractional part = x − trunc(x); shifts mantissa by the exponent and keeps the low digits.
- `_Round` / `_RndGuard` `ram:2623` / `page_02:6A57`: round to the active display-digit count; `_Round` is a thin `cross_page_jump` wrapper (body banked off page 0).

---

## 3. Degree/radian & polar conversions [confirmed]
- `_DToR` `ram:236B` (deg→rad): multiply OP1 by $\pi/180$ (`FUN_ram_235D` loads the constant) then normalize via `FUN_ram_249E`.
- `_RToD` `ram:2374` (rad→deg): multiply by $180/\pi$ (`FUN_ram_2361`).
- `_PToR` `page_02:50BD` polar→rectangular; pairs with the complex trig below.
These constants are the BCD floats `π/180 = 1.745…e-2` and `180/π = 5.729…e1` noted in
[06-floating-point.md](06-floating-point.md)'s constant scan.

---

## 4. Cross-page dispatch (`cross_page_jump` @ `ram:2B09`) [confirmed]
Banked ROM calls use a bcall-style trampoline.
`cross_page_jump`:
1. saves the current page (`IN A,(6)`),
2. builds a `RET`-to-page-0 trampoline on the stack (`bcall` return frame, page restored on exit),
3. reads a 3-byte `{lo, hi, page}` descriptor (page masked with `0x1F`/`0x3F` for 83+/84+ via ports 2/0x21),
4. `OUT (6),A` to bank the target page in at `4000`, then jumps to it.

The ln/e^x sites that look similar are **not** cross-page dispatches. `ram:2362` calls the bcall
entry at `ram:3DD1`, whose inline descriptor is `1E 7D 02`, so it invokes the page-0x02
coefficient fetcher at `page_02:7D1E`. In `LD A,3; CALL 0x2362` / `LD A,6; CALL 0x2362`, the
`3` and `6` are coefficient-table indexes, not target pages. `_EToX` falls through locally into
the `_TenX` body at `page_02:7069`; the ln/e^x/sin-cos coefficient tables are on page 0x02
(`7181`, `7201`, `7281`, and the constant block near `7D42`), not page 0x03/0x06/0x07.

---

## 5. Transcendentals

### Logarithms [confirmed]
- `_LnX` `page_02:6EFD`: `_CkOP1Pos`; **non-positive real → `_ErrDomain`**. For a positive real it calls the real-log core (`_CLN` path, selector `C=2`); the *generic* entry handles complex args.
- `_LogX` `page_02:6F16`: same structure, base-10 selector `C=0`, guards `_ErrD_OP1_0`/`_ErrD_OP1NotPos`.
- `_CLN` `page_02:6CCA` / `_CLog` `page_02:6CE7` — **complex** log: `_CAbs` (magnitude) → real `_LnX`/`_LogX` for the real part, `_ATan2Rad` (`page_02:76D4`) for the imaginary part (the argument/angle). Uses `_PushRealO1`/`_PopRealO2` to juggle the operand. This is why `ln(-2)` returns a complex result in `a+bi` mode but raises `_ErrNonReal` (0x87) in real mode.

### Exponentials [confirmed]
- `_EToX` `page_02:705C` (e^x): loads the `log10(e)` constant through `ram:2362`/`page_02:7D1E`,
  then falls through into the local `_TenX` body.
- `_TenX` `page_02:7066` (10^x): splits exponent into integer (digit shift) + fractional
  (16-slot table-driven evaluation through `page_02:7181`). Argument too large → `_ErrOverflow`.

### Trig — sin/cos/tan [confirmed]
- `_SinCosRad` `page_02:733E`, `_Sin` `7342`, `_Cos` `7346`, `_Tan` `734A`. Each loads a
  **function selector** byte into `0x8499` (`1`=sin, `2`=cos, `4`=tan; `0x80` bit set when
  *not* in the rad-special mode tested by `BIT 2,(IY+0)`; `_SinCosRad` forces `0x81`).
- Range reduction: reads OP1 exponent; **exponent ≥ 0x0C (|x| ≳ 10^12·) → `_ErrDomain`**
  ("argument out of range"). It then reduces the angle modulo a quarter-period using the
  BCD constant table near `page_02:7D81` and runs the **same table-driven digit recurrence**
  as ln/eˣ over the signed near-unity tables at `page_02:7201` and `page_02:7281` (one row
  per digit step, sign-variant picked by `0x84A4` bit 7) — the per-step `bcd_sub_op1_op2`
  (`ram:1D8A`) / `bcd_add_8496_8480` (`ram:1D26`) are the shift-and-add BCD steps of that
  recurrence, *not* a fixed polynomial and *not* CORDIC for the forward trig. The per-row
  decoding of `02:7201`/`02:7281` is detailed in [06-floating-point.md](06-floating-point.md).

### Inverse trig [confirmed]
- `_ASinRad` `76DA`, `_ACosRad` `76C9`, `_ATanRad` `76CF`, `_ATan2Rad` `76D4`, plus the
  degree-mode `_ASin`/`_ACos`/`_ATan`/`_ATan2` at `76F1`/`76DF`/`76E9`/`7749`.
- `_ASin`/`_ACos` call domain check `SUB_page_02:79D3`; **|arg| > 1 → `_ErrDomain`**.
- All inverse trig funnel into the shared **arctangent CORDIC engine** at `page_02:774B`
  (`B=0x20` = 32 iterations), with asin/acos expressed via atan2 of (x, √(1−x²)).

### Hyperbolics [confirmed]
- `_SinHCosH` `7626`, `_TanH` `762A`, `_CosH` `762E`, `_SinH` `7632`; `_ATanH`/`_ASinH`/`_ACosH`
  at `7909`/`7956`/`7964`. Same `0x8499` selector mechanism; built from `_EToX` (`sinh = (e^x−e^-x)/2`, visible in the `_EToX`+`_FPDiv` sequence near `02:6D08`).

### Power operator `^` [confirmed]
The general `a^b` lives at `page_02:6D08`+: it computes `b·ln(a)` then `e^()` and reconstructs
with `_SinCosRad` for the complex case — i.e. `a^b = e^(b·Ln a)`, with `_FPDiv`/`_FPMult`
glue and `_OP2ToOP6`/`_OP6ToOP1` shuffles. Integer/√ special cases short-circuit to
`_FPMult`/`_SqRoot`. This makes `^` the most FP-stack-heavy single operator a student hits.

---

## 6. Number entry & display formatting

When the homescreen shows a result (or `Ans`), the engine converts the `OP1` `TIFloat` to a
digit string honoring the **MODE** screen (Normal/Sci/Eng, Float/Fix 0–9).

- `_FormReal` `page_06:5ACF` — real-number formatter. [confirmed]
  - `fp_clear_guard`; zero → `_OP1Set0`; copies arg to OP5.
  - Reads the digit-count/mode flags from `(IY+0xc)` and the byte at `0x89FA` (active
    fixed/decimal-places setting; `(IX-1)` local holds the effective format byte).
  - Exponent thresholds drive Normal↔Sci switchover: it compares `OP1.exp` against `0x7D`/`0x7F`
    (≈ the ±-exponent window) and renormalizes (`FUN_ram_1BE7`) to bring the value into the
    displayable mantissa range, bumping a digit counter. Negative sign decrements the leading
    column count (`DEC (IX-3)`).
- `_FormEReal` `page_06:5799` — forces **scientific/E** notation by setting `0,(IY+0xc)` then calling `_FormReal`. [confirmed]
- `_FormBase` `page_06:57C0` — integer formatting in a base; requires `_CkOP1Real` (→ DATA TYPE / DOMAIN on non-real). [confirmed]
- `_FormDCplx` `page_06:59D3` — complex `a+bi` / `r∠θ` formatting (calls `_FormReal` twice). [standard]
- Exponent ↔ ASCII helpers on page 0: `_ExpToHex` `ram:1E4E`, `_OP1ExpToDec` `ram:1E77`,
  `_DecO1Exp` `ram:1E6F` (decrement exp), `FUN_ram_1BCB` (BCD-digit → value). [confirmed]
- The formatted string is then drawn by `_DispOP1A` (`page_04:7844`) / homescreen put-string
  routines (see [08-display-lcd.md](08-display-lcd.md)).

`Ans` is the last-result `TIFloat` saved in a system var and reloaded into `OP1`
(via `_Mov9ToOP1` = RST 20h) when the token `Ans` is evaluated. [standard]

---

## 7. Error handling [confirmed]

Errors are raised by loading an **error code** in `A` and jumping to `_JError` (`ram:2793`),
which unwinds to the error context and shows the named message. The raiser cluster lives at
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

**Domain pre-checks** (page-0, set Z if OK else jump to `_ErrDomain`):
- `_ErrD_OP1NotPos` `ram:2119` — `_CkOP1Pos`; not >0 ⇒ DOMAIN (used by `_SqRoot`, `_LogX`).
- `_ErrD_OP1Not_R` `ram:2120` — `_CkOP1Real`; complex ⇒ DOMAIN.
- `_ErrD_OP1NotPosInt` `ram:2125` — `_CkPosInt`.
- `_ErrD_OP1_LE_0` `ram:212A`, `_ErrD_OP1_0` `ram:212D` — zero/sign guards (e.g. `ln(0)`).

**Where the calc engine raises what:**
- `÷ 0`, `1/0`: `_FPDiv`/`_FPRecip` → `0x82` DIVIDE BY 0.
- `×`/`10^x`/exponent overflow: `FUN_ram_250F` exponent-add → `0x81` OVERFLOW.
- `√(neg)`, `ln/log(≤0)`, `asin/acos(|x|>1)`, `tan(π/2)`, |trig arg| ≳ 10^12: `0x84` DOMAIN.
- Complex result requested in real mode: `0x87` NONREAL ANS (the `_CLN`/complex paths).

---

## 8. Routine index (confident, `space:addr`)

Arithmetic core (page 0): `_FPAdd 229E`, `_FPSub 2297`, `_FPMult 238B`, `_FPDiv 2541`,
`_FPRecip 253D`, `_FPSquare 238A`, `_Cube 237D`, `_Times2 2282`, `_TimesPt5 2382`,
`_InvSub 227D`, `_Int 2621`, `_Intgr 2263`, `_Trunc 2279`, `_Frac 24E3`, `_Round 2623`,
`_InvOP1S 24BD`, `_InvOP2S 24CD`, `_InvOP1SC 24BA`, `_CkOP1Pos 1E5D`, `fp_clear_guard 2627`,
`fpmul_expadd FUN_ram_250F`, `_DToR 236B`, `_RToD 2374`, `cross_page_jump 2B09`.

Transcendentals (page 02): `_SqRoot 6E38`, `_LnX 6EFD`, `_LogX 6F16`, `_CLN 6CCA`,
`_CLog 6CE7`, `pow_core 6D08`, `_EToX 705C`, `_TenX 7066`, `_SinCosRad 733E`, `_Sin 7342`,
`_Cos 7346`, `_Tan 734A`, `_SinHCosH 7626`, `_TanH 762A`, `_CosH 762E`, `_SinH 7632`,
`_ACosRad 76C9`, `_ATanRad 76CF`, `_ATan2Rad 76D4`, `_ASinRad 76DA`, `_ACos 76DF`,
`_ATan 76E9`, `_ASin 76F1`, `_ATan2 7749`, `atan_cordic 774B`, `coeff_fetch 7D1E`,
`trig_coeff_table 7D81`.

Formatting (page 06): `_FormReal 5ACF`, `_FormEReal 5799`, `_FormBase 57C0`, `_FormDCplx 59D3`.

Errors (page 0): `_JError 2793`, raiser table `26E8`+, domain pre-checks `2119`–`2131`.

---

## 9. Worked flow: `2*sin(π/6)+ln(5)` [hypothesis, from the above]
1. Parser pushes `2` (`OP1`), evaluates `sin(π/6)`: loads `π/6` into OP1, `_SinCosRad`/`_Sin`
   (selector `0x8499`), table-driven digit recurrence → `OP1=0.5`.
2. `×`: the saved `2` is in `OP2` (or popped from FPS) → `_FPMult` → `OP1=1`.
3. `ln(5)`: spill `1` to FPS (`_PushRealO1`), `OP1=5`, `_LnX` (`_CkOP1Pos` passes) → `1.6094…`.
4. `+`: pop `1` to `OP2` (`_PopRealO2`), `_FPAdd` → `OP1≈2.6094`.
5. `_FormReal` renders per MODE; result stored as `Ans`.
