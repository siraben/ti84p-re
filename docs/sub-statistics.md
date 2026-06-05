# sub-statistics — The STAT subsystem (TI-84 Plus OS 2.55MP)

What happens between a college student entering data into `L1`/`L2`, pressing
**STAT ▸ CALC ▸ 1‑Var Stats** (or `LinReg(ax+b)`, `QuadReg`, …), and seeing
x̄, Σx, Sx, a, b, r, r² appear — and where every result is stored so it can be
recalled by name (`x̄`, `Σx`, `RegEQ`, …).

This doc covers the STAT **CALC** computations. The data source is the L1–L6
lists (VAT/`05-variables-vat.md`, `sub-vat-archive.md`); the arithmetic is the
BCD FP engine (`06-floating-point.md`, `sub-calculation.md`). Stat **plots** and
the **DISTR** menu are noted in §8/§9 — DISTR functions are *parser* functions,
not part of the STAT‑CALC engine.

Address form: `page:addr` (flash page in the `0x4000` slot) or `ram:addr` for the
fixed page‑0 core at `0x0000`. The whole STAT‑CALC engine lives on **flash page
0x3A**. Confidence: **[confirmed]** = read from Z80 disassembly, **[standard]** =
matches documented TI behavior, **[hypothesis]** = inferred.

Verified by headless disassembly/decompilation on the private Ghidra copy
(`/tmp/ti84-stats`). Note the Ghidra decompiler mis-renders the Z80
`SET/RES b,(IY+d)` flag ops, the `RST` macros, and cross-page `CALL 0x2b09`
trampolines, so the algorithm here is read primarily from the **disassembly**.

---

## 1. The `statVars` result block (`0x8A3A`) [confirmed]

Every STAT‑CALC result is a 9‑byte `TIFloat` (see `06-floating-point.md`) written
into a fixed RAM table beginning at **`statVars = 0x8A3A`** (`statVars EQU 8A3Ah`
in `ti83plus.inc`). Entries are packed at the 9‑byte `FPLEN` stride. These are the
system variables a student recalls by name (`[2nd][STAT] ▸ VARS`):

| Addr | Name (`.inc`) | User-facing var | Meaning |
|------|---------------|-----------------|---------|
| `8A3A` | `StatN`   | `n`   | sample count (Σ of frequencies) |
| `8A43` | `XMean`   | `x̄`   | mean of x |
| `8A4C` | `SumX`    | `Σx`  | sum of x |
| `8A55` | `SumXSqr` | `Σx²` | sum of x² |
| `8A5E` | `StdX`    | `Sx`  | **sample** std dev of x (÷ n−1) |
| `8A67` | `StdPX`   | `σx`  | **population** std dev of x (÷ n) |
| `8A70` | `MinX`    | `minX`| minimum x |
| `8A79` | `MaxX`    | `maxX`| maximum x |
| `8A82` | `MinY`    | `minY`| minimum y (2‑Var) |
| `8A8B` | `MaxY`    | `maxY`| maximum y (2‑Var) |
| `8A94` | `YMean`   | `ȳ`   | mean of y |
| `8A9D` | `SumY`    | `Σy`  | sum of y |
| `8AA6` | `SumYSqr` | `Σy²` | sum of y² |
| `8AAF` | `StdY`    | `Sy`  | sample std dev of y |
| `8AB8` | `StdPY`   | `σy`  | population std dev of y |
| `8AC1` | `SumXY`   | `Σxy` | sum of x·y |
| `8ACA` | `Corr`    | `r`   | correlation coefficient |
| `8AD3` | `MedX`    | `Med` | median of x |
| `8ADC` | `Q1`      | `Q1`  | first quartile |
| `8AE5` | `Q3`      | `Q3`  | third quartile |
| `8AEE` | `QuadA`   | `a`   | regression coeff a (highest order) |
| `8AF7` | `QuadB`   | `b`   | regression coeff b |
| `8B00` | `QuadC`   | `c`   | regression coeff c |
| `8B09` | `CubeD`   | `d`   | regression coeff d |
| `8B12` | `QuartE`  | `e`   | regression coeff e |
| `8B1B`…`8B4E` | `MedX1/2/3`, `MedY1/2/3` | | Med‑Med (×3 partitions) |

Continuing past the table (also `.inc`): `PStat`/`ZStat`/`TStat`/`ChiStat`/
`FStat`/`DF`/`Phat…`/`MeanX1`/`StdX1`/`StatN1`/`MeanX2`/`StdX2`/`StatN2`/`StdXP2`/
`SLower`/`SUpper`/`SStat` — these hold the inferential‑stats outputs (the STAT‑TESTS
menu) and are written by the test commands, not by 1/2‑Var Stats. An ANOVA block
`anovaf_vars` (`F_DF/F_SS/F_MS/E_DF/E_SS/E_MS`) follows.

A scratch byte **`0x8A36`** (just below `statVars`) holds the **stat‑command
discriminator** (the model index, set from the command token — see §3) for the
duration of the computation. Working list/element pointers used by the loop live
in the OP‑scratch RAM `0x84AF…0x84DB` (`84D3`=median data ptr, `84D5/84D7`=current
x/y element ptr, `84D9`=sums matrix base, `84DB`=freq list ptr, `84B1/84B2`=loop
counters, `84B3`=element count). [confirmed]

**Recall by name:** `_Rcl_StatVar` (`00:2149`, id `0x42DC`) is a page‑0 bcall
trampoline (`CALL 0x3E07` → dispatcher, inline id `0xC9E7`) that loads the named
statVar into `OP1`; the VAT‑level recall (`_RclVarSym`/`_RclVarPush`, see
`sub-vat-archive.md`) routes the stat‑var name tokens (`tRegEq 0x01`, `tStatN 0x02`,
`tXMean 0x03`, … `tCorr 0x12`, the `STATVARS` token group) to it. The name‑token
values are in `ti83plus.inc` (`tStatN=02h … tSumXY=11h, tCorr=12h, tMedX=13h`,
regression coeffs via `tRegEq=01h`). [confirmed/standard]

---

## 2. `_OneVar` — the STAT‑CALC engine entry (`3A:6420`, id `0x4BA3`) [confirmed]

`bcall(_OneVar)` is the single entry point for **all** STAT‑CALC commands
(1‑Var, 2‑Var, and every regression). The parser invokes it after pushing the
list arguments; the command token (`F2`–`FF`, see §3) selects the behaviour.

```
_OneVar (3A:6420):
  SET 5,(IY+9)            ; statFlags: "stat computation active"
  LD B,0                  ; arg counter
  RES 1,(IY+0)  ; RES 1,(IY+1a)
  LD (9817),0             ; clear a status byte
  LD HL,8499 ; CALL 1b33  ; stage the parsed arg descriptor at 8499
  LD A,0FF ; LD (84af),A
  CALL _CkOP1Real (1942-ish) / arg-class checks …
  ; ---- argument parsing (6442..64de) ----
  ;   walks the parser argument list, accepting list-name tokens (0x24 list,
  ;   0x2A list-element, 0x1C/0x25/0x19 = freq/list variants); validates count;
  ;   _JError(0x8A) ARGUMENT / 0x88 SYNTAX on a bad arg list.
  ; ---- set up the data pointers (64e1..6503) ----
  LD HL,847a ; LD DE,8d2a ; CALL 1a9a  ; resolve the x-list (and y/freq) → 84D3..84DB
  POP AF ; LD (8a36),A          ; *** save the command code → model discriminator ***
  LD HL,6352 ; CALL 27da        ; install an on-error cleanup frame
  CALL 6572                     ; *** the accumulation pass (§4) ***
  CALL 2800 ; CALL 6345         ; tear down frame
  ; ---- regression coefficient region select (6506..652f) ----
  LD A,(8a36) ; CP 4 ; JR NC,..  ; A<4 ⇒ polynomial regression
       LD A,16 ; LD HL,8aee      ; coeff dest = QuadA block; … solve (§5)
  …
  SET 7,(IY+9)                  ; mark results valid
  CALL 67c1 …                   ; finalize / median (§6)
```

Key facts read from the disassembly:
- The command byte is saved at **`(0x8A36)`** and steers everything afterward.
- `LD HL,0x8AEE` (= `QuadA`) is the **regression coefficient destination**; the
  solver writes `a,b,c,d,e` there in descending order of power.
- `_ErrStat` (`00:2741`, id `0x44C2`, code **`0x15`** "STAT") and `_ErrStatPlot`
  (`00:2759`, code `0x1B`) are the STAT‑specific error raisers; the `_OneVar`
  body jumps to `0x2741` on e.g. fewer than the required data points.
  `_ErrDimMismatch` (`0x2715`) is raised if `L1` and `L2`/freq lengths differ
  (the `21bb` length compare at `6584`/`658a`).

---

## 3. STAT command token map (`STATCMD = 0xF2`) [confirmed]

The parser passes the command token; `_OneVar` stores it at `0x8A36` and treats it
as a model index. From `ti83plus.inc`:

| Token | Value | Command | Model |
|-------|-------|---------|-------|
| `tOneVar` | `F2` | `1‑Var Stats` | one variable |
| `tTwoVar` | `F3` | `2‑Var Stats` | two variable |
| `tLR`     | `F4` | `LinReg(a+bx)` | degree‑1 (a+bx form) |
| `tLRExp`  | `F5` | `ExpReg`  | y=a·bˣ (log‑linear) |
| `tLRLn`   | `F6` | `LnReg`   | y=a+b·ln x (log‑x) |
| `tLRPwr`  | `F7` | `PwrReg`  | y=a·xᵇ (log‑log) |
| `tMedMed` | `F8` | `Med‑Med` | resistant line |
| `tQuad`   | `F9` | `QuadReg` | degree‑2 |
| `tLR1`    | `FF` | `LinReg(ax+b)` | degree‑1 (ax+b form) |

`CubicReg`/`QuartReg` come in as the regression tokens `tCubicR=2Eh`/`tQuartR=2Fh`;
`SinReg=32h`, `Logistic=33h`, `LinRegTTest=34h` are the extended (`E1`‑prefixed)
tokens. Degree for the polynomial solver = the model index; the coefficient
fan‑out into `QuadA..QuartE` is naturally sized by degree. [confirmed/standard]

`SortA(`/`SortD(` are **separate** tokens (`tSortA=E3h`, `tSortD=E4h`) handled by
the list‑sort bcalls, not `_OneVar`; `_OneVar` calls the same sort internally
(`3A:7935`) to compute medians/quartiles (§6).

---

## 4. The accumulation pass (`3A:6572` …) [confirmed]

This is the heart of 1/2‑Var Stats and the regression sum‑setup. It makes a
**single pass** over the data list(s), accumulating the power‑sums needed for the
mean, variance, and least‑squares normal equations. Read from disassembly:

```
6572: CALL 6f90/6f7d         ; default freq = 1 if no freq list given
6584: CALL 21bb              ; if freq list present, length-check vs x-list
                             ;   → _ErrDimMismatch (2715) on mismatch
658a: LD HL,(84d3)          ; HL = first element ptr; DE = element count
6590: LD A,(8a36)           ; dispatch on command:
   CP 8 (Med-Med) → jump to the resistant-line path (760f/75e4 → 79b9)
   else compute the matrix dimension from the degree:
        CP 1c/25/19/9 → dim=4 ; CP 5 (CubicReg) NC → dim+? ; default
   65c1: A = dim ; SUB 2 ; PUSH AF
65cd: set up x/y element pointers (84d5/84d7/84db)
65f0: ---- per-element accumulator init ----
   LD DE,8a3a ; … CALL 1a92  ; StatN slot
   LD DE,8a94                ; YMean/Σy slots
   CALL 110f                 ; allocate the sums matrix (84d9 = base)
6646..66fe: ---- per-element loop ----
   6f6a  : fetch next x (and y) list element, advance ptr
   28e4/2297 : loop bound (RST FPSub / compare)
   6567  : helper = (RST 8: OP1→OP2) ; LD HL,(84af) ; CALL 6f7d ; _FPMult (238b)
           → forms the running power x^k · freq
   238a  : _FPSquare (Σx²)
   238b  : _FPMult   (Σxy, Σx^(i+j))
   RST 30: _FPAdd    → accumulate into the matrix cell / Σ-slot
   2999/29db/29a2 : guard-clear / OP-shuffle helpers
   66fe: JP C,6655  ; loop while elements remain
```

So one pass builds, for a degree‑*d* fit, the symmetric **moment matrix** of
power‑sums `Σxⁱ` (i = 0 … 2d) and the right‑hand side `Σxⁱy`, stored as a small
2‑D array reached by the index helpers **`3A:3A8F`/`3AA1`/`3AA7`/`3AAD`/`3AB9`**
(matrix‑element get/set by `(row B, col C)`). `StatN`, `SumX`, `SumXSqr`, `SumY`,
`SumYSqr`, `SumXY`, `MinX/MaxX/MinY/MaxY` are filled here directly. [confirmed]

**Non‑polynomial regressions transform first** [confirmed]: the front‑end at
`658a`+ checks the command code and, for `ExpReg`/`PwrReg` (`ln y`),
`LnReg`/`PwrReg` (`ln x`), pre‑applies the logarithm to each element before
accumulating, then exponentiates the resulting linear coefficients (the
`760f/75e4/79b9` and `7002/7013` branches call into the page‑02 `_LnX`/`_EToX`
transcendentals — see `sub-calculation.md §5`). This is the standard
"linearize, fit a line, transform back" method; `r` is the correlation of the
**transformed** data.

### 4a. Mean & standard deviation [confirmed]
After the pass, `_OneVar` finalizes the moments (`3A:6762`+):

```
6762: LD DE,8a67 ; CALL 6984   ; σx  (population) from Σx², Σx, n
6786: LD DE,8a5e ; CALL 6989   ; Sx  (sample), via _Minus1 (n→n-1) at 677c
6798: LD DE,8a55 ; CALL 6998   ; Σx² slot
67a7: LD DE,8aa6 ; CALL 6998   ; Σy²   (2-Var)
```

The variance helpers (`3A:6984`/`6989`/`6998`) implement the one‑pass formula
`var = (Σx² − n·x̄²)/N` then `√`:
```
6998: _FPSquare(x̄) ; recall Σx² (15da) ; _FPMult ; (RST 30 _FPAdd / subtract) ; …
6989: CALL _FPDiv (2541) ; CALL 3939 (_SqRoot wrapper) ; store
```
The **only** difference between σx (population) and Sx (sample) is the divisor:
the population path divides by `n`, the sample path first does `_Minus1`
(`00:2294`, n−1) — confirmed at `3A:677C`. `x̄ = Σx / n` via `_FPDiv`. [confirmed]

---

## 5. The regression solver — Gauss‑Jordan on the normal equations (`3A:67C6` …) [confirmed]

For a polynomial fit the moment matrix from §4 is the augmented normal‑equations
matrix `[ M | Σxⁱy ]`. `_OneVar` solves it **in place by Gauss‑Jordan elimination**
(not a closed‑form determinant), then writes the coefficients to `QuadA…QuartE`.

```
67c6: build/copy the augmented matrix; 84d9 = base
67d4..67e3: scale the pivot row
67ec: LD BC,0202 ; CALL 3aad        ; pivot element (2,2)
67f7: CALL 212d                     ; _ErrD check (zero pivot → SINGULAR MAT 0x83)
67fa: RST 8 ; …                     ; pivot reciprocal
6804: CALL 2541 (_FPDiv)            ; divide row by pivot
680d..6815: elimination loop
6845: CALL 3939 (_SqRoot) ; 6849 ; CALL 2541 (_FPDiv)  ; (forms r²/r from the fit)
684f: LD A,12 ; CALL 213d           ; r-related store/guard
6859..6876: row-reduce all other rows (3aa7 get, 238b _FPMult, RST 30 _FPAdd)
6880: CALL 2541 ; on a zero pivot → LD A,35/36 ; CALL 213d  (SINGULAR MAT)
68d6..6953: back-substitution — each coeff = (rhs − Σ known·M) / pivot
   (3aa7/3aa1 matrix access, 238b _FPMult, RST 30/RST 8 accumulate,
    24bd _InvOP1S to subtract, 2541 _FPDiv)
   each solved coefficient is stored via 69af → CALL 3ab9 (matrix set)
       then copied out to the QuadA..QuartE statVars block.
```

- A **zero/near‑zero pivot raises `_ErrSingularMat` (0x83)** "SINGULAR MAT"
  (e.g. all x equal, or too few distinct points for the degree). The `LD A,0x35`/
  `0x36` and `CALL 0x213d` are the in‑solver guards. [confirmed]
- The solver is dimension‑generic: `LinReg` (2×2) → `a,b`; `QuadReg` (3×3) →
  `a,b,c`; `CubicReg` (4×4) → `a,b,c,d`; `QuartReg` (5×5) → `a,b,c,d,e`. The
  coefficients land in `QuadA`(`8AEE`) downward. [confirmed]
- **Correlation `r` and `r²`** are computed for the linear models from the
  centred sums: `r = Σ(x−x̄)(y−ȳ) / √(Σ(x−x̄)²·Σ(y−ȳ)²)` = `(n·Σxy − Σx·Σy) /
  √[(n·Σx²−(Σx)²)(n·Σy²−(Σy)²)]`, assembled with `_FPMult`/`_FPSub`/`_SqRoot`/
  `_FPDiv` (the `6845`/`684c` cluster) and stored to `Corr` (`8ACA`); `r²` (and
  `R²` for higher‑order) is `r·r` / coefficient‑of‑determination, also surfaced.
  [confirmed structure / standard formula]
- The fitted equation is also written to **`RegEQ`** (the `Y=`‑style regression
  equation system var, recalled via token `tRegEq=0x01`) so `RegEQ` can be pasted
  or graphed. [standard]

The **Med‑Med** model (`F8`) takes the resistant‑line branch (`3A:760F/79B9`):
it sorts, splits the x‑sorted data into three equal partitions, takes the median
(x,y) of each (`MedX1/2/3`, `MedY1/2/3` at `8B1B`…), and fits the line through the
outer two summary points adjusted toward the middle — classic Tukey median‑median.
[confirmed path / standard]

---

## 6. Median, quartiles, min/max & the sort (`3A:7935`, `3A:79B9`) [confirmed]

For **1‑Var Stats** the five‑number summary needs the data **sorted**:

- `MinX`/`MaxX` are tracked during the §4 pass (running min/max compares).
- The median/quartile path (`3A:79B9` → `7A0B` …) sorts a working copy via the
  internal sort `3A:7935` (same engine as `SortA(`), then:
  - `Med` (`MedX`, `8AD3`) = middle element (or mean of the two middle for even n),
  - `Q1` (`8ADC`) = median of the lower half, `Q3` (`8AE5`) = median of the upper
    half (TI's "exclude the overall median when n is odd" convention),
  with frequency‑weighted positions (the `7B30`/`7B4C`/`7B6E` helpers walk the
  cumulative‑frequency index, and `198d`/`238b` interpolate the rank). [confirmed
  path / standard quartile rule]

The five‑number summary `(minX, Q1, Med, Q3, maxX)` is what the **MED/box‑plot**
stat plot reads back out of `statVars`.

---

## 7. Worked flow: `2‑Var Stats L1,L2` then `LinReg(ax+b) L1,L2,Y1` [hypothesis, from §§2–6]

1. Parser pushes the list args, sets `A = command token`, `bcall(_OneVar)`.
2. `_OneVar` parses args → x‑list ptr `(84D3)`, y‑list `(84D5)`, freq `(84DB)`;
   saves the model code to `(8A36)`.
3. **Accumulation pass** (§4): one walk of L1/L2 building `n, Σx, Σx², Σy, Σy²,
   Σxy` and `minX/maxX/minY/maxY` into `statVars`, plus the 2×2 moment matrix.
4. **Moments** (§4a): `x̄=Σx/n`, `ȳ=Σy/n`; `Sx,σx,Sy,σy` via the variance helper
   (÷ n−1 vs ÷ n).
5. **Solve** (§5): Gauss‑Jordan on `[ Σ1 Σx ; Σx Σx² | Σy ; Σxy ]` →
   `b=slope`, `a=intercept` → `QuadA/QuadB`; `r,r²` → `Corr`; equation → `RegEQ`,
   pasted into `Y1`.
6. Results displayed by the STAT‑CALC report screen; all of x̄/Σx/…/a/b/r persist
   in `statVars` for later recall by name (`_Rcl_StatVar`).

---

## 8. Stat plots [standard / partially confirmed]

Stat plots (Scatter `tScatter=FE`, xyLine `FD`, Histogram `tHist=FC`, box plots
`tBoxIcon`, normal‑prob) are drawn by the **graphing** subsystem, reading the
five‑number summary and the raw L1/L2 lists. `_ErrStatPlot` (`00:2759`, code
`0x1B`) guards an invalid/undefined plot configuration; `_ZmStats` (`33:65DC`,
id `0x47A4`) is the **ZoomStat** routine that auto‑scales the window to the plotted
list data (sets `Xmin/Xmax/Ymin/Ymax` from `minX/maxX/minY/maxY`). See
`sub-graphing.md`. [confirmed addresses / standard behavior]

---

## 9. Distributions (DISTR menu) — *not* part of STAT‑CALC [confirmed scope]

`normalpdf(`, `normalcdf(`, `invNorm(`, `binompdf(`, `tcdf(`, `χ²cdf(`, `Fcdf(`,
etc. are **parser functions** (DISTR‑menu tokens, the `E1`/`E2`‑prefixed
two‑byte tokens like `tShadeNorm=35h`), evaluated through the normal function
dispatch of the TI‑BASIC parser, **not** through `_OneVar`. They are not
exposed as named bcalls in this OS image (a search of `bcall_targets.txt` finds
only `_SetNorm_Vals` `00:220F`, a helper that copies the *display* "Normal mode"
default values — unrelated to the normal *distribution*). Their numerical cores
(error‑function / incomplete‑gamma / incomplete‑beta continued fractions) live on
a banked flash page reached via the parser's function table and the page‑02 FP
transcendentals; locating them is left as an open item — they belong to the
parser/`sub-tibasic` dispatch rather than the STAT subsystem documented here.
[confirmed: not reachable from `_OneVar`; hypothesis: numerical method]

---

## 10. Integration summary

```
  L1..L6 lists (VAT data)                 statVars (0x8A3A)  ← results, recall-by-name
        │ (element fetch 3A:6F6A)               ▲
        ▼                                       │ (_Rcl_StatVar 00:2149)
   _OneVar (3A:6420, id 0x4BA3)  ──►  per-element accumulation pass (3A:6572)
        │  cmd code → 0x8A36                     │  uses FP engine:
        │                                        │   RST30 _FPAdd, 238B _FPMult,
        ├─ moments / Sx,σx (3A:6984..)           │   238A _FPSquare, 2541 _FPDiv,
        ├─ Gauss-Jordan solve (3A:67C6..) ───►   │   3939 _SqRoot, 2294 _Minus1
        │     → QuadA..QuartE, Corr, RegEQ       │
        └─ sort + median/quartile (3A:7935/79B9) ┘
  errors: _ErrStat 00:2741 (0x15), _ErrStatPlot 00:2759 (0x1B),
          _ErrSingularMat 0x83, _ErrDimMismatch 00:2715 (0x8B)
```

The STAT subsystem is a thin **data‑driven front‑end** on page 0x3A that reads list
data via the VAT, drives the page‑0/page‑02 BCD FP engine to build power‑sums, then
either finalizes simple moments or runs an in‑place Gauss‑Jordan solve of the normal
equations, depositing every output as a named `TIFloat` in the `statVars` block.

---

## 11. Confident address index (`space:addr`)

| space:addr | name | what |
|------------|------|------|
| `3A:6420` | `_OneVar` | STAT‑CALC entry (1/2‑Var + all regressions), id 0x4BA3 |
| `3A:6572` | `onevar_accumulate` | one‑pass power‑sum accumulation loop |
| `3A:6567` | `onevar_powmul` | running power·freq product (OP1→OP2, ×) |
| `3A:6345` | `onevar_frame_teardown` | restore stat error frame |
| `3A:6352` | `onevar_err_cleanup` | on‑error cleanup handler |
| `3A:6984` | `stat_stddev_pop` | population variance/σ finalize (÷ n) |
| `3A:6989` | `stat_stddev_samp` | sample variance/S finalize (÷ n−1) |
| `3A:6998` | `stat_var_core` | (Σx²−n·x̄²) variance core + √ |
| `3A:67C6` | `reg_gauss_solve` | Gauss‑Jordan solve of normal equations |
| `3A:69AF` | `reg_store_coeff` | write a solved coefficient (matrix set) |
| `3A:3A8F`/`3AA1`/`3AA7`/`3AAD`/`3AB9` | `stat_mtx_get/set` | sums‑matrix element access by (row,col) |
| `3A:6F6A` | `stat_next_elem` | fetch next list element, advance ptr |
| `3A:6F7D`/`6F90` | `stat_freq_default` | default frequency = 1 |
| `3A:7935` | `stat_sort` | internal data sort (SortA engine) |
| `3A:79B9` | `stat_median_quartile` | median/Q1/Q3 + Med‑Med medians |
| `3A:760F`/`75E4` | `medmed_partition` | Med‑Med 3‑partition setup |
| `00:2149` | `_Rcl_StatVar` | recall a named statVar into OP1, id 0x42DC |
| `00:2741` | `_ErrStat` | raise STAT error (code 0x15), id 0x44C2 |
| `00:2759` | `_ErrStatPlot` | raise STAT PLOT error (0x1B), id 0x44D1 |
| `00:2294` | `_Minus1` | OP1 − 1 (n→n−1 for sample stddev) |
| `33:65DC` | `_ZmStats` | ZoomStat — fit window to plotted data, id 0x47A4 |
| `00:2715` | `_ErrDimMismatch` | list length mismatch (0x8B) |

**RAM:** `statVars=0x8A3A`, model‑discriminator `0x8A36`, work ptrs `0x84AF–0x84DB`
(`84D3` x/median ptr, `84D5/84D7` element ptrs, `84D9` sums‑matrix base,
`84DB` freq ptr, `84B1/84B2` loop counters, `84B3` element count).
**FP engine reused:** `RST 30h`=`_FPAdd`, `RST 08h`=OP1→OP2, `00:238B`=`_FPMult`,
`00:238A`=`_FPSquare`, `00:2541`=`_FPDiv`, `00:2294`=`_Minus1`, `02:6E38`/`3A:3939`
=`_SqRoot`, `24BD`=`_InvOP1S`.

## 12. Open items
- Pin the exact `r`/`r²`/`R²` store sequence offsets within `3A:6845–6891`
  (formula confirmed; which statVar slot gets `r` vs `r²` for higher‑order fits).
- The DISTR numerical cores (erf/incomplete‑gamma/incomplete‑beta) — locate via
  the parser function table (`sub-tibasic`), outside the STAT‑CALC engine.
- STAT‑TESTS commands (Z/T/χ²/F/ANOVA) that fill `PStat…SStat`/`anovaf_vars` —
  separate command handlers, not reached through `_OneVar`.
- The sort comparator details in `3A:7935` (ascending; frequency handling).
