# Solver and numerical methods

The mapped numeric paths implement root finding, numerical differentiation,
and integration. Root and derivative callbacks repeatedly evaluate a stored
expression through the [calculation engine](sub-calculation.md) and
the [TI-BASIC interpreter](sub-tibasic.md). Finance-command bodies and the
complete integration callback path remain open here.

Raw opcode checks supply banked-page evidence where Ghidra does not recover a
complete function body.

## Solver errors [confirmed]

The numerical routines raise four dedicated errors. Each has a tiny page-0 raiser stub
that loads an error code into `A` and branches to `_JError` (`ram:2793`).

| Error | bcall | page-0 stub | code | Message |
|-------|-------|-------------|------|---------|
| `_ErrSignChange` | `0x44C5` | `ram:2749` → `_JError(0x98)` | `0x98` | NO SIGN CHNG |
| `_ErrIterations` | `0x44C8` | `ram:274D` → `_JError(0x99)` | `0x99` | ITERATIONS |
| `_ErrBadGuess`   | `0x44CB` | `ram:2751` → `_JError(0x9A)` | `0x9A` | BAD GUESS |
| `_ErrTolTooSmall`| `0x44CE` | `ram:2755` → `_JError(0x9C)` | `0x9C` | TOL NOT MET |

`error_name_table` (`07:6B81`) is indexed by
`(code − 0x88)`, so codes `0x88…0x9C` map to consecutive strings:

```text
07:6B81 SYNTAX(88) DATA TYPE(89) ARGUMENT(8A) DIM MISMATCH(8B) INVALID DIM(8C)
        UNDEFINED(8D) MEMORY(8E) INVALID(8F) ILLEGAL NEST(90) BOUND(91)
        WINDOW RANGE(92) ZOOM(93) LABEL(94) STAT(95) SOLVER(96) SINGULARTY(97)
        NO SIGN CHNG(98) ITERATIONS(99) BAD GUESS(9A) STAT PLOT(9B) TOL NOT MET(9C)
```

`SOLVER` (`0x96`) and `SINGULARTY` (`0x97`) are separate error messages.
Their names alone do not establish the exact predicate at each caller.

---

## Equation Solver and `solve(` root finder [confirmed]

The interactive **Equation Solver** app and the numeric `solve(` token share one
root-finding engine living on flash page `0x39`. (The Solver app's UI — the
`EQUATION SOLVER` / `eqn:0=` / `bound=` / `left-rt=` screen — is drawn from strings at
`06:6ABB`, loaded by code at `06:6286`/`06:62EA`/`06:66F3`.)

### Function-value evaluator `f(x)` [confirmed]

A callback, given the trial value in `OP1`, returns `f(x) = left − right`
of the equation. Located around `39:468F`:

1. `_CkValidNum` (`ram:1E9B`), then `_MovFrOP1` (`ram:1B0C`) stores the current guess into
   the solve variable (its data pointer is loaded from `(9306)`, in the expression-stack
   region — the bytes are `ED 5B 06 93` = `LD DE,(9306)`).
2. It installs the error handler at `39:46C7`, then re-evaluates the stored
   equation through `parse_inp_current_state_bjump` (`ram:391B`). The stub's
   inline descriptor targets `parse_inp_current_state` (`38:5992`), an interior
   entry in `_ParseInp` that preserves the already selected parser state.
3. The error filter at `39:46C7` inspects the error code in `A`: codes below `0x86`
   (`OVERFLOW`/`DIV BY 0`/`SINGULAR MAT`/`DOMAIN`) and `0x87` (`NONREAL ANS`) are
   swallowed by these comparisons:

   ```z80
   CP 0x87
   JR Z
   CP 0x86
   JP NC,0x2799
   ```

   This `x` is treated as a point where `f` is undefined, so the solver can step
   past it, while `0x86` (`BREAK`) and
   codes `≥ 0x88` are
   re-raised via `_JErrorNo` (`JP 2799`). Before returning a swallowed error,
   `fix_temp_count_bjump` (`ram:327F`) dispatches to `_FixTempCnt` (`07:4FEC`)
   to repair temporary-object accounting. This is why `solve(` can skip
   singularities inside the bracket without aborting. [confirmed]

The sign test `39:463A` reads `OP1.value.type` (`8478`) and `OP2.value.type` (`8483`), masks `0x80`
and XORs them: Z = same sign, NZ = opposite sign — the bracket sign-change predicate. [confirmed]

### Iteration loop [confirmed]

The page-`39` root engine combines bracket/sign checks, half-width
calculations, and interpolation steps. The midpoint calculation uses
`_InvSub` followed by `_TimesPt5` at `39:443C`/`39:443F`.
The sign helper at `39:463A` saves work values, then compares the sign
bits of OP1 and OP2 at `39:4640`–`39:464B`.

Two iteration checks compare a 16-bit counter with `01F3h` (499).
At `39:4479`–`39:447F`, `499-DE` branches to ITERATIONS on
borrow. At `39:458B`–`39:4591`, `HL-499` takes the retry path
only below the threshold. These are distinct control states; an 8-bit
`INC A` elsewhere does not define the total iteration count.

The constants at `39:46E1` and `39:46EA` are
`00 1D 10 00 00 00 00 00 00` (`1e-99`) and
`00 73 10 00 00 00 00 00 00` (`1e-13`).
The latter is multiplied into an operand at `39:4673`–`39:4676`
before the magnitude comparison at `39:467D`. It therefore does not
establish a universal absolute stopping rule `|b-a| < 1e-13`.

The macro `tools/macros/solver-sqrt2.macro` exercises the Equation Solver
on `X²−2=0`. The recorded observation is convergence to
`1.4142135623731` with a zero displayed residual. The retained notes
count 808 visits to `39:4413` and 834 to `38:5AB3`; these
whole-run counts are not one invocation's bounded iteration count.
A reduced trace separating solver calls and counter states is still needed.

The complete recurrence, interpolation acceptance conditions, and convergence
predicate remain [hypothesis]. Half-width arithmetic and a few comparison
sites do not by themselves identify a particular Illinois or regula-falsi
variant.

`left-rt` shown on the Solver screen is the final residual `f(root)` (the
`left-side − right-side` value the evaluator computed). [standard]

---

## `nDeriv(` and `fnInt(` numeric calculus

The source tokens are single bytes: `22h` for `solve(`,
`24h` for `fnInt(`, and `25h` for `nDeriv(`.
The SDK's `IMUN=12h` defines these offsets. They are distinct from the
`BB` extensions with the same second byte. [confirmed]

### `nDeriv(` symmetric difference quotient [confirmed]

The `25h` compare at `02:6904` leads through `02:690B`
to `02:6AF3`. The default-argument entry at `02:6AF6` saves the
operand, constructs one, and sets its exponent to `7Dh` at
`02:6AFB`–`02:6AFD`, giving `ε=1e-3`.

The calculation forms the two trial arguments with addition at `02:6B30`
and subtraction at `02:6B41`. Both call the expression evaluator
helper at `02:6B7C`, which reaches the parser through `ram:391B`
at `02:6B86`. The difference at `02:6B4A`, doubling at
`02:6B51`, and division at `02:6B58` implement the centered
quotient:

$$
\frac{f(x+\varepsilon)-f(x-\varepsilon)}{2\varepsilon}.
$$

The wrapper installs cleanup at `02:6B13`–`02:6B16` and frees
its temporary frame at `02:6B5E`–`02:6B61`. Full error-path and
variable-restoration coverage remains open.

### `fnInt(` adaptive numeric integration [confirmed]

The `24h` compare at `02:68F3` selects the integration path.
Its default-tolerance setup constructs one, sets exponent `7Bh`
(`1e-5`), then executes `EF 83 4A` at `02:6900`.
Bcall ID `4A83h` has table bytes `65 63 07`, so the callee is
`07:6365`.

That body checks the nesting flag at `07:6365`, prepares FP work
storage, sets the flag at `07:63D3`, and installs its error handler
at `07:63D7`. Its loop can reach `_ErrTolTooSmall` through
`07:6412`. The complete quadrature rule and all refinement/error
paths have not been decoded here.

The labels `fnint_body` at `33:4D00` and `nderiv_body` at
`33:4C80` do not establish those functions' identities. Neither is
the callee selected by the dispatch above. In particular, the absence of
quadrature weights in that page-`33` span cannot exclude
Gauss–Kronrod from `fnInt(`. Its instruction pair
`LD A,60h` followed by `CALL 1B65h` stores packed BCD `60h` into a mantissa,
constructing 6 rather than decimal 96. [confirmed]

## Finance and other iterative routines

Finance commands use the `BB` extension family. For example,
`BB 00` is `npv(`, `BB 01` is `irr(`, and
`BB 20`–`BB 24` are the TVM payment, rate, present-value,
period-count, and future-value functions. Their numerical bodies remain
unmapped on this page. [standard]

The iterative body at `3A:70A2` allocates five FP slots, uses a
64-pass counter, and calls `_SinH` at `3A:710B`. It also calls
`_ROWECHELON = 462Ah`, body `02:4663`. Those instructions
describe an iterative matrix-based calculation; they do not establish a
TVM interest-rate solver. Its exact command caller and recurrence remain
[hypothesis].

## Parser feedback loop [confirmed]

The root and derivative evaluators store trial values and evaluate the existing
token stream again. They do not tokenize visible source text on each iteration.
The root callback at `39:46A9` and the derivative callback at
`02:6B86` both call `ram:391B`, whose inline descriptor selects
the prepared-state parser entry at `38:5992`.

The root solver's caught-error behavior belongs to `39:46C7`; it
must not be generalized to integration or derivative errors without following
their respective cleanup handlers.

### Parser routing for `tFnInt`, `tNDeriv`, and `tRoot` [confirmed]

| Source byte | Dispatch | Next numeric entry |
|-------------|----------|--------------------|
| `24h`, `fnInt(` | `02:68F3` → bcall `4A83h` at `02:6900` | `07:6365` |
| `25h`, `nDeriv(` | `02:6904` → call at `02:690B` | `02:6AF3` |
| `22h`, `solve(` | `02:690F` → bcall `4B94h` at `02:6927` on the shown argument path | `_ITSOLVERB`, `39:4039` |

The `BB` scanner at `33:504E` belongs to
`_GetVarVersion` (`33:5023`). Its compatibility-tier comparisons
do not dispatch these numerical functions.

## Routine index [confirmed]

| Address | Role |
|---------|------|
| `39:4039` | `_ITSOLVERB = 4B94h`, root-solver entry |
| `39:4413` | Root-iteration region |
| `39:463A` | Saved-value and sign-comparison helper |
| `39:468F` | Root trial-value evaluator |
| `39:46C7` | Root caught-error filter |
| `ram:391B` | Prepared-state parser stub to `38:5992` |
| `02:6AF3` / `02:6AF6` | Derivative entries with supplied/default step |
| `02:6B7C` | Derivative trial-value evaluator |
| `07:6365` | Integration bcall `4A83h` body |
| `ram:2749` / `ram:274D` | NO SIGN CHNG / ITERATIONS raisers |
| `ram:2751` / `ram:2755` | BAD GUESS / TOL NOT MET raisers |

## Resolved behavior and remaining questions

The token widths and caller-to-body mappings above come from ROM bytes and the
SDK token definitions. The centered derivative formula and default step are
decoded, as are the integration entry/default tolerance and root error filter.

Remaining work includes a complete integration-rule decode, root convergence
and per-invocation counter traces, finance-command caller mapping, and each
function's variable restoration after non-local errors. Five-byte natural-loop
OPS records belong to page `38`, as documented in
[TI-BASIC execution](sub-tibasic.md); they are not established by the
page-`33` dispatcher table.
