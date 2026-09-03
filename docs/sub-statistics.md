# Statistics

The statistics subsystem reads list data, accumulates moments, solves
regressions, and writes named results such as `x̄`, `Σx`, `Sx`, `a`, `b`, `r`,
and `r²`. This page separates the **CALC**, **STAT-TESTS**, and **DISTR** command
families.

The **CALC** paths read `L1`–`L6` through the VAT and use the BCD
floating-point engine. The engine lives on Flash page `3A`; raw disassembly
supplies indexed-bit and cross-page operations that the decompiler can
mis-render.

## `statVars` result block [confirmed]

Every STAT-CALC result is a 9-byte `TIFloat` (see [floating-point.md](floating-point.md)) written
into a fixed RAM table beginning at `statVars = 0x8A3A` (`statVars EQU 8A3Ah`
in `ti83plus.inc`). Entries are packed at the 9-byte `FPLEN` stride. These are the
system variables recalled by name (`[2nd][STAT] ▸ VARS`):

| Addr | Name (`.inc`) | User-facing var | Meaning |
|------|---------------|-----------------|---------|
| `8A3A` | `StatN`   | `n`   | sample count (Σ of frequencies) |
| `8A43` | `XMean`   | `x̄`   | mean of x |
| `8A4C` | `SumX`    | `Σx`  | sum of x |
| `8A55` | `SumXSqr` | `Σx²` | sum of x² |
| `8A5E` | `StdX`    | `Sx`  | *sample* std dev of x (÷ n−1) |
| `8A67` | `StdPX`   | `σx`  | *population* std dev of x (÷ n) |
| `8A70` | `MinX`    | `minX`| minimum x |
| `8A79` | `MaxX`    | `maxX`| maximum x |
| `8A82` | `MinY`    | `minY`| minimum y (2-Var) |
| `8A8B` | `MaxY`    | `maxY`| maximum y (2-Var) |
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
| `8B1B`…`8B50` | `MedX1/2/3`, `MedY1/2/3` (`8B1B/8B24/8B2D/8B36/8B3F/8B48`) | | Med-Med (×3 partitions) |

These 31 consecutive values form the typed prefix used by the Ghidra database:

```c
typedef struct {
    TIFloat StatN, XMean, SumX, SumXSqr, StdX, StdPX, MinX, MaxX;
    TIFloat MinY, MaxY, YMean, SumY, SumYSqr, StdY, StdPY, SumXY;
    TIFloat Corr, MedX, Q1, Q3, QuadA, QuadB, QuadC, CubeD, QuartE;
    TIFloat MedX1, MedX2, MedX3, MedY1, MedY2, MedY3;
} TIStatResultsPrefix; /* 31 × 9 bytes at statVars */
```

This makes, for example, `statVars.XMean` and `statVars.Corr` distinct fields
rather than unrelated constants `0x8A43` and `0x8ACA`. The address table remains
the byte-level evidence for the layout. [confirmed]

Continuing past the table (also `.inc`): `PStat`/`ZStat`/`TStat`/`ChiStat`/
`FStat`/`DF`/`Phat…`/`MeanX1`/`StdX1`/`StatN1`/`MeanX2`/`StdX2`/`StatN2`/`StdXP2`/
`SLower`/`SUpper`/`SStat` — these hold the inferential-stats outputs (the STAT-TESTS
menu) and are written by the test commands, not by 1/2-Var Stats. An ANOVA block
`anovaf_vars` (`F_DF/F_SS/F_MS/E_DF/E_SS/E_MS`) follows.

**STAT-TESTS are separate command handlers.** [confirmed] `Z-Test`/`T-Test`/`χ²-Test`/
`2-SampFTest`/`ANOVA(` etc. come in as their own 2-byte `t2ByteTok` (`0xBB`)-prefixed command tokens — e.g.
`LinRegTTest=34h` in the [STAT command token map](#stat-command-token-map-confirmed) — and are not dispatched through `_OneVar` (whose token map is
only `F2`–`FF`). They fill the `PStat…SStat`/`anovaf_vars` block above directly. Test
handlers appear on both sides of the named `stat_*` accumulation, variance,
median, and regression routines within `3A:4A00`–`3A:7E60`. See
[STAT-TESTS engine](#stat-tests-engine-on-page-3a-confirmed). The per-test entry addresses are
not exposed as named routines and remain [hypothesis].

A scratch byte `stat_calc_command` (`0x8A36`, immediately below `statVars`) holds the stat-command
discriminator (the model index set from the [command token](#stat-command-token-map-confirmed)) for the
duration of the computation. Working list/element pointers used by the loop live
in the OP-scratch RAM `0x84AF…0x84DB` (`84D3`=median data ptr, `84D5/84D7`=current
x/y element ptr, `84D9`=sums matrix base, `84DB`=freq list ptr, `84B1/84B2`=loop
counters, `84B3`=element count). [confirmed]

**Recall by name:** `_Rcl_StatVar` (`00:2149`, id `0x42DC`) is a page-0 bcall
trampoline (`CALL 0x3E07` → dispatcher, inline id `0xC9E7`) that loads the named
statVar into `OP1`; the VAT-level recall (`_RclVarSym`/`rcl_var_push`, see
[sub-vat-archive.md](sub-vat-archive.md)) routes the stat-var name tokens (`tRegEq 0x01`, `tStatN 0x02`,
`tXMean 0x03`, … `tCorr 0x12`, the `STATVARS` token group) to it. The name-token
values are in `ti83plus.inc` (`tStatN=02h … tSumXY=11h, tCorr=12h, tMedX=13h`,
regression coeffs via `tRegEq=01h`). [standard]

---

## `_OneVar` STAT-CALC entry [confirmed]

`bcall(_OneVar)` is the single entry point for *all* STAT-CALC commands
(1-Var, 2-Var, and every regression). The parser invokes it after pushing the
list arguments; the [command token](#stat-command-token-map-confirmed) (`F2`–`FF`) selects the behavior.

```z80
_OneVar (3A:6420):
  SET 5,(IY+9)            ; statFlags: "stat computation active"
  LD B,0                  ; arg counter
  RES 1,(IY+0)
  RES 1,(IY+1a)
  LD (9817),0             ; clear a status byte
  LD HL,8499
  CALL 1b33  ; stage the parsed arg descriptor at 8499
  LD A,0FF
  LD (84af),A
  CALL _CkOP1Real (1942-ish) / arg-class checks …
  ; ---- argument parsing (6442..64de) ----
  ;   walks the parser argument list, accepting list-name tokens (0x24 list,
  ;   0x2A list-element, 0x1C/0x25/0x19 = freq/list variants); validates count;
  ;   _JError(0x8A) ARGUMENT / 0x88 SYNTAX on a bad arg list.
  ; ---- set up the data pointers (64e1..6503) ----
  LD HL,847a
  LD DE,8d2a
  CALL 1a9a  ; resolve the x-list (and y/freq) → 84D3..84DB
  POP AF
  LD (8a36),A          ; *** save the command code → model discriminator ***
  LD HL,6352
  CALL 27da        ; install an on-error cleanup frame
  CALL 6572                     ; accumulation pass
  CALL 2800
  CALL 6345         ; tear down frame
  ; ---- regression coefficient region select (6506..652f) ----
  LD A,(8a36)
  CP 4
  JR NC,..  ; A<4 ⇒ polynomial regression
       LD A,16
       LD HL,8aee      ; coeff dest = QuadA block; … solve
  …
  SET 7,(IY+9)                  ; mark results valid
  CALL 67c1 …                   ; finalize / median
```

Key facts read from the disassembly:
- The command byte is saved in `stat_calc_command` and steers everything afterward.
- `LD HL,0x8AEE` (= `QuadA`) is the regression coefficient destination; the
  solver writes `a,b,c,d,e` there in descending order of power.
- `_ErrStat` (`00:2741`, id `0x44C2`, code `0x15` "STAT") and `_ErrStatPlot`
  (`00:2759`, code `0x1B`) are the STAT-specific error raisers; the `_OneVar`
  body jumps to `0x2741` on e.g. fewer than the required data points.
  `_ErrDimMismatch` (`0x2715`) is raised if `L1` and `L2`/freq lengths differ
  (the `21bb` length compare at `6584`/`658a`).

---

## STAT command token map [confirmed]

The parser passes the command token; `_OneVar` stores it in
`stat_calc_command` (`0x8A36`) and treats it as a model index. From
`ti83plus.inc`:

| Token | Value | Command | Model |
|-------|-------|---------|-------|
| `tOneVar` | `F2` | `1-Var Stats` | one variable |
| `tTwoVar` | `F3` | `2-Var Stats` | two variable |
| `tLR`     | `F4` | `LinReg(a+bx)` | degree-1 (a+bx form) |
| `tLRExp`  | `F5` | `ExpReg`  | y=a·bˣ (log-linear) |
| `tLRLn`   | `F6` | `LnReg`   | y=a+b·ln x (log-x) |
| `tLRPwr`  | `F7` | `PwrReg`  | y=a·xᵇ (log-log) |
| `tMedMed` | `F8` | `Med-Med` | resistant line |
| `tQuad`   | `F9` | `QuadReg` | degree-2 |
| `tLR1`    | `FF` | `LinReg(ax+b)` | degree-1 (ax+b form) |

`CubicReg`/`QuartReg` come in as the regression tokens `tCubicR=2Eh`/`tQuartR=2Fh`;
`SinReg=32h`, `Logistic=33h`, `LinRegTTest=34h` are 2-byte `t2ByteTok` (`0xBB`)-prefixed
tokens (their `2Eh`/`2Fh`/`32h`/`33h`/`34h` values are the *second* byte after `0xBB`). Degree for the polynomial solver = the model index; the coefficient
fan-out into `QuadA..QuartE` is naturally sized by degree. [standard]

`SortA(`/`SortD(` are separate tokens (`tSortA=E3h`, `tSortD=E4h`) with their
own command handler — not `_OneVar`. The sort used here, `stat_sort` (`3A:7935`),
is stat-internal: its only callers are `stat_median_quartile` (`3A:79B9`) and
`medmed_partition` (`3A:760F`) (xref-confirmed), so it powers the 1-Var median/
quartile and Med-Med paths in [Median, quartiles, extrema, and sorting](#median-quartiles-extrema-and-sorting-confirmed). The `SortA(`/`SortD(` *command* sort is a
different routine on `page 0x02` (≈`02:5939`, comparator `_CpOP1OP2`) — see
[Matrices and lists](sub-matrix-list.md#sorta-and-sortd-list-sorting-confirmed).

---

## Accumulation pass [confirmed]

This builds the power-sums for 1/2-Var Stats and the regression sum-setup. It makes a
single pass over the data list(s), accumulating the power-sums needed for the
mean, variance, and least-squares normal equations. Read from disassembly:

```z80
6572: CALL 6f90/6f7d         ; default freq = 1 if no freq list given
6584: CALL 21bb              ; if freq list present, length-check vs x-list
                             ;   → _ErrDimMismatch (2715) on mismatch
658a: LD HL,(84d3)          ; HL = first element ptr; DE = element count
6590: LD A,(8a36)           ; dispatch on command:
   CP 8 (Med-Med) → jump to the resistant-line path (760f/75e4 → 79b9)
   else compute the matrix dimension from the degree:
        CP 1c/25/19/9 → dim=4
        CP 5 (CubicReg) NC → dim+? ; default
   65c1: A = dim
   SUB 2
   PUSH AF
65cd: set up x/y element pointers (84d5/84d7/84db)
65f0: ---- per-element accumulator init ----
   LD DE,8a3a ; … CALL 1a92  ; StatN slot
   LD DE,8a94                ; YMean/Σy slots
   CALL 110f                 ; allocate the sums matrix (84d9 = base)
6646..66fe: ---- per-element loop ----
   6f6a  : fetch next x (and y) list element, advance ptr
   28e4/2297 : loop bound (RST FPSub / compare)
   6567  : helper = (RST 8: OP1→OP2)
   LD HL,(84af)
   CALL 6f7d ; _FPMult (238b)
           → forms the running power x^k · freq
   238a  : _FPSquare (Σx²)
   238b  : _FPMult   (Σxy, Σx^(i+j))
   RST 30: _FPAdd    → accumulate into the matrix cell / Σ-slot
   2999/29db/29a2 : guard-clear / OP-shuffle helpers
   66fe: JP C,6655  ; loop while elements remain
```

So one pass builds, for a degree-*d* fit, the symmetric moment matrix of
power-sums `Σxⁱ` (i = 0 … 2d) and the right-hand side `Σxⁱy`, stored as a small
2-D array reached by the RAM trampoline helpers `00:3A8F`/`3AA1`/`3AA7`/`3AAD`/`3AB9`
(matrix-element get/set by `(row B, col C)`). `StatN`, `SumX`, `SumXSqr`, `SumY`,
`SumYSqr`, `SumXY`, `MinX/MaxX/MinY/MaxY` are filled here directly. [confirmed]

**Non-polynomial regressions transform first** [confirmed]: the front-end at
`658a`+ checks the command code and, for `ExpReg`/`PwrReg` (`ln y`),
`LnReg`/`PwrReg` (`ln x`), pre-applies the logarithm to each element before
accumulating, then exponentiates the resulting linear coefficients off page 0x3A. The
per-element `ln` is in the element fetch `stat_next_elem` (`3A:6F6A`):

```z80
LD A,(8A36)
CP 4
RET NC
```

It then bcalls `_LnX` at `3A:6F72` for model codes `< 4` (`ExpReg`/`LnReg`/`PwrReg`); the
back-transform `_EToX`/`_TenX` lives on page `02`; see [Transcendentals](sub-calculation.md#transcendentals). This is the standard
"linearize, fit a line, transform back" method; `r` is the correlation of the
*transformed* data.

### Mean and standard deviation [confirmed]

After the pass, `_OneVar` finalizes the moments (`3A:6762`+):

```z80
6762: LD DE,8a67
CALL 6984   ; σx  (population) from Σx², Σx, n
6786: LD DE,8a5e
CALL 6989   ; Sx  (sample), via _Minus1 (n→n-1) at 677c
6798: LD DE,8a55
CALL 6998   ; Σx² slot
67a7: LD DE,8aa6
CALL 6998   ; Σy²   (2-Var)
```

The variance helpers (`3A:6984`/`6989`/`6998`) implement the one-pass formula
`var = (Σx² − n·x̄²)/N` then `√`:
```z80
6998: _FPSquare(x̄) ; recall Σx² (15da) ; _FPMult ; (RST 30 _FPAdd / subtract) ; …
6989: CALL _FPDiv (2541)
CALL 3939 (_SqRoot wrapper) ; store
```
The *only* difference between σx (population) and Sx (sample) is the divisor:
the population path divides by `n`, the sample path first does `_Minus1`
(`00:2294`, n−1) — confirmed at `3A:677C`. `x̄ = Σx / n` via `_FPDiv`. [confirmed]

---

## Regression solver [confirmed]

For a polynomial fit the moment matrix from the [accumulation pass](#accumulation-pass-confirmed) is the augmented normal-equations
matrix `[ M | Σxⁱy ]`. `_OneVar` solves it in place by Gauss-Jordan elimination
(not a closed-form determinant), then writes the coefficients to `QuadA…QuartE`.

```z80
67c6: build/copy the augmented matrix; 84d9 = base
67d4..67e3: scale the pivot row
67ec: LD BC,0202
CALL 3aad        ; pivot element (2,2)
67f7: CALL 212d                     ; _ErrD check (zero pivot → SINGULAR MAT 0x83)
67fa: RST 8 ; …                     ; pivot reciprocal
6804: CALL 2541 (_FPDiv)            ; divide row by pivot
680d..6815: elimination loop
```

The `3A:6845`–`6891` cluster, byte by byte:

```text
6845  CALL 3939  (cross_page_jump)   ; OP1 = √OP1 (page-39 _SqRoot body)
6848  RST 08h   (_OP1ToOP2)          ; OP2 = √…
6849  CALL 1674  (_CpyTo1FPST)       ; OP1 ← FPS−9 (the saved numerator sum)
684C  CALL 2541  (_FPDiv)            ; OP1 = numerator/denominator = r
684F  LD A,0x12 ; CALL 213D          ; _Sto_StatVar(tCorr): Corr (8ACA) ← r
6854  CALL 1BA4  (_OP1Set0)          ; accumulator = 0
6857  POP BC / PUSH BC               ; BC = augmented-matrix row count
685B  LD B,2                         ; start at row 2 (first data column)
685D  loop:
        CALL 19EC (_OP1ToOP4); CALL 150A (_PopRealO2)   ; OP2 ← popped FPS value
        CALL 3AA7 (cross_page_jump)  ; matrix element (col B) → OP1
        CALL 238B (_FPMult)          ; element · value
        CALL 19FE; RST 30h (_FPAdd)  ; accumulate into OP4/OP1
        INC B until B = H            ; walk the column
6878  CALL 2903 (fp_st_slot7_op3)    ; stash the column sum
687B  CALL 1DEE  (_CkOP2FP0)         ; denominator zero?
687E  JR Z,6891                      ; yes → skip r² store
6880  CALL 2541  (_FPDiv)            ; ratio for r²/R²
6885  LD A,B; CP 2                   ; model order == 2 (linear)?
6888  LD A,0x35 / 0x36               ; id 0x35 = r² (slot 8C05), 0x36 = R² (8C0E)
688E  CALL 213D  (_Sto_StatVar)
```

The region forms `r = num/den` and stores it to `Corr` at `0x8ACA`. It then
accumulates a column-weighted residual sum over the augmented matrix. When the
denominator is nonzero, it stores `r²` for linear fits or `R²` for higher-order
fits in separate statVar slots at `0x8C05` and `0x8C0E`. [confirmed]

```z80
68d6..6953: back-substitution — each coeff = (rhs − Σ known·M) / pivot
   (3aa7/3aa1 matrix access, 238b _FPMult, RST 30/RST 8 accumulate,
    24bd _InvOP1S to subtract, 2541 _FPDiv)
   each solved coefficient is stored via 69af → CALL 3ab9 (matrix set)
       then copied out to the QuadA..QuartE statVars block.
```

- A zero/near-zero pivot raises `_ErrSingularMat` (`0x83`, `SINGULAR MAT`),
  for example when all x values are equal or the degree exceeds the number of
  distinct points. The guard is the `3A:67F7` call to `ram:212D`; the
  `0x35`/`0x36` calls at `3A:6888`–`3A:688E` are stat-variable stores.
  [confirmed]
- The solver is dimension-generic: `LinReg` (2×2) → `a,b`; `QuadReg` (3×3) →
  `a,b,c`; `CubicReg` (4×4) → `a,b,c,d`; `QuartReg` (5×5) → `a,b,c,d,e`. The
  coefficients land in `QuadA`(`8AEE`) downward. [confirmed]
- Correlation `r` and `r²` are computed for the linear models from the
  centred sums:
  $$r=\frac{\sum (x-\bar x)(y-\bar y)}{\sqrt{\sum (x-\bar x)^2\\,\sum (y-\bar y)^2}}=\frac{n\sum xy-\sum x\sum y}{\sqrt{\big(n\sum x^2-(\sum x)^2\big)\big(n\sum y^2-(\sum y)^2\big)}}$$

  assembled with `_FPMult`/`_FPSub`/`_SqRoot`/
  `_FPDiv` (the `6845`/`684c` cluster) and stored to `Corr` (`8ACA`). The store offset is
  pinned: at `3A:684F` the code does <code>LD A,0x12</code><br><code>CALL 0x213D</code>, and `0x213D` is
  `_Sto_StatVar` (the store counterpart of `_Rcl_StatVar 00:2149` — both funnel through the
  `0x3E07` statVar dispatcher with the name id in `A`). Id `0x12` = `tCorr` = the `Corr`
  slot, so this single sequence is exactly `r → Corr (8ACA)`. The preceding `3A:6845`
  `_SqRoot`/`_FPDiv` cluster forms the ratio; `r²` (and `R²` for higher-order fits) is the
  coefficient of determination derived by the following column-weighted pass. It is stored
  separately through IDs `0x35` and `0x36`, at `0x8C05` and `0x8C0E` respectively.
  [confirmed]
- The fitted equation is also written to `RegEQ` (the `Y=`-style regression
  equation system var, recalled via token `tRegEq=0x01`) so `RegEQ` can be pasted
  or graphed. [standard]

The **Med-Med** model (`F8`) takes the resistant-line branch (`3A:760F/79B9`):
it sorts, splits the x-sorted data into three equal partitions, takes the median
(x,y) of each (`MedX1/2/3`, `MedY1/2/3` at `8B1B`…), and fits the line through the
outer two summary points adjusted toward the middle — classic Tukey median-median. [standard]

---

## Median, quartiles, extrema, and sorting [confirmed]

For **1-Var Stats** the five-number summary needs the data sorted:

- `MinX`/`MaxX` are tracked during the [accumulation pass](#accumulation-pass-confirmed) with running min/max compares.
- The median/quartile path (`3A:79B9` → `7A0B` …) sorts a working copy via the
  internal sort `stat_sort` (`3A:7935`), then:
  - `Med` (`MedX`, `8AD3`) = middle element (or mean of the two middle for even n),
  - `Q1` (`8ADC`) = median of the lower half, `Q3` (`8AE5`) = median of the upper
    half (TI's "exclude the overall median when n is odd" convention),
  with frequency-weighted positions (the `7B30`/`7B4C`/`7B6E` helpers walk the
  cumulative-frequency index, and `198d`/`238b` interpolate the rank). The ROM
  path is [confirmed]. The quartile rule is [standard].

The five-number summary `(minX, Q1, Med, Q3, maxX)` is what the MED/box-plot
stat plot reads back out of `statVars`.

---

## Worked two-variable statistics and regression flow [hypothesis]

1. Parser pushes the list args, sets `A = command token`, `bcall(_OneVar)`.
2. `_OneVar` parses args → x-list ptr `(84D3)`, y-list `(84D5)`, freq `(84DB)`;
   saves the model code to `stat_calc_command`.
3. **Accumulation pass:** one walk of L1/L2 building `n, Σx, Σx², Σy, Σy²,
   Σxy` and `minX/maxX/minY/maxY` into `statVars`, plus the 2×2 moment matrix.
4. **Moments:** $\bar x=\tfrac{\sum x}{n}$, $\bar y=\tfrac{\sum y}{n}$; the sample/population
   spreads $S_x,\sigma_x,S_y,\sigma_y$ via the variance helper (divide by $n-1$ vs $n$).
5. **Solve:** Gauss-Jordan on the normal equations $\left[\begin{array}{cc|c}\sum 1&\sum x&\sum y\\\\\sum x&\sum x^2&\sum xy\end{array}\right]$ →
   `b=slope`, `a=intercept` → `QuadA/QuadB`; `r,r²` → `Corr`; equation → `RegEQ`,
   pasted into `Y1`.
6. Results displayed by the STAT-CALC report screen; all of x̄/Σx/…/a/b/r persist
   in `statVars` for later recall by name (`_Rcl_StatVar`).

---

## Stat plots [standard]

Stat plots (Scatter `tScatter=FE`, xyLine `FD`, Histogram `tHist=FC`, box plots
`tBoxIcon`, normal-prob) are drawn by the graphing subsystem, reading the
five-number summary and the raw L1/L2 lists. `_ErrStatPlot` (`00:2759`, code
`0x1B`) guards an invalid/undefined plot configuration; `_ZmStats` (`33:65DC`,
id `0x47A4`) is the **ZoomStat** routine that auto-scales the window to the plotted
list data (sets `Xmin/Xmax/Ymin/Ymax` from `minX/maxX/minY/maxY`). See
[sub-graphing.md](sub-graphing.md). [standard]

---

## DISTR functions [confirmed]

`normalpdf(`, `normalcdf(`, `invNorm(`, `binompdf(`, `tcdf(`, `χ²cdf(`, `Fcdf(`,
etc. are parser functions (DISTR-menu tokens, the `t2ByteTok` (`0xBB`)-prefixed
two-byte tokens like `tShadeNorm=35h`), evaluated through the normal function
dispatch of the TI-BASIC parser, not through `_OneVar`. They are not
exposed as named bcalls in this OS image (a search of `bcall_targets.txt` finds
only `_SetNorm_Vals` `00:220F`, a helper that copies the *display* "Normal mode"
default values — unrelated to the normal *distribution*). Their numerical cores
(error-function / incomplete-gamma / incomplete-beta continued fractions) live on
a banked flash page reached via the parser's function table and the page-02 FP
transcendentals; they belong to the parser/`sub-tibasic` dispatch rather than the
STAT subsystem documented here. [hypothesis]

**Negative search.** [confirmed] A name search of the whole-OS image for `norm`/`stat`/distribution
cores returns no `normalcdf`/`erf`/incomplete-gamma/incomplete-beta entry points — the only
`*norm*` symbols are `_SetNorm_Vals` (`00:220F`, display "Normal mode" defaults),
`fp_normalize`/`fp_norm_left` (mantissa normalisation), `cplx_norm_*` (complex modulus) and the
`eqdisp_setnorm_split` layout helpers — none is a distribution. Likewise every `stat_*`
symbol on page 0x3A is part of the `_OneVar` STAT-CALC engine (accumulate / variance / median /
sort / regression), not a DISTR core. The `normalcdf(` evaluation path runs in the
page `39` FP core described below. The STAT-TESTS p-value approximation carries
its coefficients in a table on page `3A`
([STAT-TESTS engine](#stat-tests-engine-on-page-3a-confirmed)). The erf / incomplete-gamma /
incomplete-beta continued fractions behind the remaining DISTR tokens remain
[hypothesis]. The parser's two-byte, `0xBB`-prefixed DISTR-token function table does
not expose them as named routines in this database.

**Traced `normalcdf(` path.** [confirmed] A headless TilEm trace of
`normalcdf(0,1)` through the OS 2.55 interactive prompt identifies the evaluation
path (`tools/macros/distr-normalcdf.macro`). Coverage against `boot-idle.macro`
shows the parser collecting the fields on the FP stack. A `cross_page_jump` chain
through `ram:2B09` reaches page `39` through page `01` glue. The numerical core
occupies `39:4A02`–`39:4F5B`, with helpers at `39:5D2D`–`39:5E41`,
`39:6C63`–`39:6D31`, and `39:57CF`–`39:57FC`. The trace does not execute the
page `38` slot suggested by a raw token-index read (`38:459F` for `tDNormal`).
The table at `38:4000` contains parse-side argument-class stubs such as
<code>LD B,0x29</code><br><code>JR 4A44</code>; it is not the execution dispatch.

---

## STAT-TESTS engine on page 3A [confirmed]

The inferential-statistics commands execute in their own engine on page `3A`, sharing the bank
with `_OneVar` but distinct from it. Three byte-pinned structures locate it:

**Candidate `PStat`–`SStat` references.** A ROM-wide byte-pattern scan
(`tools/ti84re/rom/scan_stat_writers.py`, immediate or absolute operands landing in
`0x8B5A`–`0x8C37`) finds about 50 opcode-shaped candidates on page `3A`
(`3A:4B15`–`3A:6BDC`) plus candidates on pages `06`, `35`, `37`, and `39`.
Because the scan does not recover instruction boundaries, these hits locate a
search cluster but do not by themselves establish a writer count or exclude
references on other pages. [hypothesis]

**A T-Test output stage at `3A:5500`.** [confirmed] The routine multiplies `OP1` through
`fp_mult_const` (`ram:2385`), scales by `StdPX` (`0x8A67`), divides through `fp_div_const`
(`ram:2532`) against `SStat` (`0x8BFC`), then stores the result with
<code>LD A,0x24</code><br><code>CALL _Sto_StatVar</code>. ID `0x24` is `tStatT`, the `TStat` slot. The
routine then references `DF` at `0x8B87`. The surrounding code reads and clears
`statFlags` bits and dispatches on the stored model ID.

**The normal p-value coefficient table at `3A:554F`.** [confirmed] Nine-byte `TIFloat`
constants, byte-verified in sequence:

| Addr | Value | Role |
|------|-------|------|
| `3A:554F` | `0.2316419` | threshold `p` |
| `3A:5558` | `1.330274429` | coefficient `b5` |
| `3A:5561` | `-1.821255978` | coefficient `b4` |
| `3A:556A` | `1.781477937` | coefficient `b3` |
| `3A:5573` | `-0.356563782` | coefficient `b2` |
| `3A:557C` | `0.319381530` | coefficient `b1` |

This coefficient set matches the Zelen–Severo approximation of the standard normal tail,
$\Phi(z)\approx 1-\varphi(z)\,(b_1t+b_2t^2+b_3t^3+b_4t^4+b_5t^5)$ with
$t=1/(1+pz)$. The loop at `3A:551F` evaluates the five coefficients in descending order by
Horner steps; `LD HL,554Fh` at `3A:550E` pins the table start. The type bytes at `3A:5561`
and `3A:5573` are `0x80`, which supplies the negative signs on `b4` and `b2`.
The STAT-TESTS handlers use the result to form `PStat`. [confirmed]

**UI descriptor tables at `3A:7D00`–`3A:7E60`.** [confirmed] The same bank carries
the test editor's data. It includes alternative-hypothesis strings for the
1-PropZTest and 2-PropZTest menus, plus the `F`-test tail strings. It also contains
SinReg and Logistic formula templates, three-byte dispatch stubs into fixed page 0
vectors, and an ascending handler-pointer array at `3A:7DF4`–`3A:7E1E`. The mapping
from array slots to menu items remains open.

---

## Subsystem integration

```text
  L1..L6 lists (VAT data)                 statVars (0x8A3A)  ← results, recall-by-name
        │ (element fetch 3A:6F6A)               ▲
        ▼                                       │ (_Rcl_StatVar 00:2149)
   _OneVar (3A:6420, id 0x4BA3)  ──►  per-element accumulation pass (3A:6572)
        │  cmd code → stat_calc_command          │  uses FP engine:
        │                                        │   RST30 _FPAdd, 238B _FPMult,
        ├─ moments / Sx,σx (3A:6984..)           │   238A _FPSquare, 2541 _FPDiv,
        ├─ Gauss-Jordan solve (3A:67C6..) ───►   │   3939 _SqRoot, 2294 _Minus1
        │     → QuadA..QuartE, Corr, RegEQ       │
        └─ sort + median/quartile (3A:7935/79B9) ┘
  errors: _ErrStat 00:2741 (0x15), _ErrStatPlot 00:2759 (0x1B),
          _ErrSingularMat 0x83, _ErrDimMismatch 00:2715 (0x8B)
```

The STAT subsystem is a thin data-driven front-end on page 0x3A that reads list
data via the VAT, drives the page-0/page-02 BCD FP engine to build power-sums, then
either finalizes the moments or runs an in-place Gauss-Jordan solve of the normal
equations, depositing every output as a named `TIFloat` in the `statVars` block.

---

## Routine index

| space:addr | name | what |
|------------|------|------|
| `3A:6420` | `_OneVar` | STAT-CALC entry (1/2-Var + all regressions), id 0x4BA3 |
| `3A:6572` | `onevar_accumulate` | one-pass power-sum accumulation loop |
| `3A:6567` | `onevar_powmul` | running power·freq product (OP1→OP2, ×) |
| `3A:6345` | `onevar_frame_teardown` | restore stat error frame |
| `3A:6352` | `onevar_frame_teardown_tail` | on-error tail calling `onevar_frame_teardown` |
| `3A:6984` | `stat_stddev_pop` | population variance/σ finalize (÷ n) |
| `3A:6989` | `stat_stddev_samp` | sample variance/S finalize (÷ n−1) |
| `3A:6998` | `stat_var_core` | (Σx²−n·x̄²) variance core + √ |
| `3A:67C6` | `reg_gauss_solve` | Gauss-Jordan solve of normal equations |
| `3A:69AF` | `reg_store_coeff` | write a solved coefficient (matrix set) |
| `00:3A8F`/`3AA1`/`3AA7`/`3AAD`/`3AB9` | `stat_mtx_index/get/set` | RAM trampolines for sums-matrix element access by (row,col) |
| `3A:6F6A` | `stat_next_elem` | fetch next list element, advance ptr |
| `3A:6F7D`/`6F90` | `stat_freq_default` | default frequency = 1 |
| `3A:7935` | `stat_sort` | stat-internal data sort (median/quartile, Med-Med) |
| `3A:79B9` | `stat_median_quartile` | median/Q1/Q3 + Med-Med medians |
| `3A:760F`/`75E4` | `medmed_partition` | Med-Med 3-partition setup |
| `3A:5500` | `ttest_output_stage` | T-Test result store: ×`StdPX`, ÷`SStat`, `_Sto_StatVar` ID `0x24` (`TStat`) |
| `3A:554F` | `normal_tail_coef_tbl` | Zelen–Severo coefficients (`p`, `b5`…`b1`) for `PStat` p-values |
| `00:2385` | `fp_mult_const` | OP1 ×= (HL)-pointed float constant |
| `00:2532` | `fp_div_const` | OP1 ÷= (HL)-pointed float constant |
| `39:4A02`–`39:4F5B` | `distr_normal_core` (unnamed) | traced `normalcdf(` evaluation core on page 39 |
| `00:2149` | `_Rcl_StatVar` | recall a named statVar into OP1, id 0x42DC |
| `00:2741` | `_ErrStat` | raise STAT error (code 0x15), id 0x44C2 |
| `00:2759` | `_ErrStatPlot` | raise STAT PLOT error (0x1B), id 0x44D1 |
| `00:2294` | `_Minus1` | OP1 − 1 (n→n−1 for sample stddev) |
| `33:65DC` | `_ZmStats` | ZoomStat — fit window to plotted data, id 0x47A4 |
| `00:2715` | `_ErrDimMismatch` | list length mismatch (0x8B) |

**RAM:** `statVars=0x8A3A`, `stat_calc_command=0x8A36`, work pointers `0x84AF`–`0x84DB`
(`84D3` x/median ptr, `84D5/84D7` element ptrs, `84D9` sums-matrix base,
`84DB` freq ptr, `84B1/84B2` loop counters, `84B3` element count).
**FP engine reused:** `RST 30h`=`_FPAdd`, `RST 08h`=OP1→OP2, `00:238B`=`_FPMult`,
`00:238A`=`_FPSquare`, `00:2541`=`_FPDiv`, `00:2294`=`_Minus1`, `02:6E38`/`3A:3939`
=`_SqRoot`, `24BD`=`_InvOP1S`.

## Remaining questions

- **Correlation stores.** `3A:684F` does <code>LD A,0x12</code><br><code>CALL 0x213D</code>
  (`_Sto_StatVar`, ID `0x12` = `tCorr`), i.e. `r → Corr (0x8ACA)`; `r²`/`R²` is the
  coefficient of determination from the following column-weighted pass, stored through IDs
  `0x35`/`0x36` at `0x8C05`/`0x8C0E`. See the annotated `3A:6845`–`3A:6891`
  listing under [Regression solver](#regression-solver-confirmed). [confirmed]
- **DISTR numerical cores.** The `normalcdf(` evaluation path is traced to the
  page `39` FP core (`39:4A02`–`39:4F5B` and helpers) — see
  [DISTR functions](#distr-functions-confirmed). The erf / incomplete-gamma /
  incomplete-beta continued fractions behind the remaining DISTR tokens are unnamed and
  untraced; the page `38` parse-side table is not the execution dispatch. The exact algorithm in
  the page `39` core (continued fraction versus polynomial or rational fit) remains
  [hypothesis].
- **STAT-TESTS** (Z/T/χ²/F/ANOVA) fill `PStat…SStat`/`anovaf_vars` from their own engine on
  page `3A`. A pinned T-Test output stage, the normal-tail coefficient table, and
  the UI descriptor area locate the engine. See
  [STAT-TESTS engine](#stat-tests-engine-on-page-3a-confirmed). The per-test entry
  addresses and the slot-to-menu mapping for the `3A:7DF4` pointer array remain
  [hypothesis].
  The `_Sto_StatVar`/`_Rcl_StatVar` stubs (`ram:213D`/`ram:2149`) funnel through the
  cross-page-jump table at `ram:3E07` (one `CALL 2B09` + inline `addr,page`
  descriptor per ID); resolving those descriptors gives the per-ID bodies
  without needing a live trace.
- `stat_sort` (`3A:7935`) is a 49-byte setup that validates/counts the elements
  then dispatches the compare-swap via `rst 28h` (the bcall site isn't fully
  analyzed in the DB). The `SortA(`/`SortD(` *command* sort is a different routine
  (page 0x02, comparator `_CpOP1OP2`) — its complex-list ordering is documented in
  [Matrices and lists](sub-matrix-list.md#sorta-and-sortd-list-sorting-confirmed).
