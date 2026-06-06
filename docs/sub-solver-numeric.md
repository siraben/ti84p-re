# Solver & Numerical Methods

*TI-84 Plus OS 2.55MP — feature deep dive.*

What happens when a calculus/algebra student uses the **equation Solver** / `solve(`,
**nDeriv(**, **fnInt(**, or the **TVM finance solver**. All of these are *iterative*
routines that repeatedly evaluate the user's expression through the BCD floating-point
engine (see [sub-calculation.md](sub-calculation.md), [06-floating-point.md](06-floating-point.md)) and the TI-BASIC parser
([sub-tibasic.md](sub-tibasic.md)).

Address form is `page:addr` (flash page banked at `0x4000`) or `ram:addr` for the fixed
page-0 core at `0x0000`. Confidence: **[confirmed]** = read from disassembly,
**[standard]** = matches documented TI behavior, **[hypothesis]** = inferred from
surrounding code. Disassembly was recovered byte-exact from `tools/rom.bin`; the headless
Ghidra project on the banked pages is only partially auto-analyzed, so addresses here were
cross-checked against raw opcodes.

---

## 0. The four solver errors and the error-code table [confirmed]

The numerical routines raise four dedicated errors. Each has a tiny page-0 raiser stub
that loads an error code into `A` and tail-jumps to `_JError` (`ram:2793`); most banked
pages also keep a **local copy** of each stub so the iteration loop can reach it with a
cheap relative jump.

| Error | bcall | page-0 stub | code | Message |
|-------|-------|-------------|------|---------|
| `_ErrSignChange` | `0x44C5` | `ram:2749` → `_JError(0x98)` | `0x98` | NO SIGN CHNG |
| `_ErrIterations` | `0x44C8` | `ram:274D` → `_JError(0x99)` | `0x99` | ITERATIONS |
| `_ErrBadGuess`   | `0x44CB` | `ram:2751` → `_JError(0x9A)` | `0x9A` | BAD GUESS |
| `_ErrTolTooSmall`| `0x44CE` | `ram:2755` → `_JError(0x9C)` | `0x9C` | TOL NOT MET |

The error **message-name table** is on page 0x07 starting at `07:6B81`. It is indexed by
`(code − 0x88)`, so codes `0x88…0x9C` map to consecutive strings:

```
07:6B81 SYNTAX(88) DATA TYPE(89) ARGUMENT(8A) DIM MISMATCH(8B) INVALID DIM(8C)
        UNDEFINED(8D) MEMORY(8E) INVALID(8F) ILLEGAL NEST(90) BOUND(91)
        WINDOW RANGE(92) ZOOM(93) LABEL(94) STAT(95) SOLVER(96) SINGULARTY(97)
        NO SIGN CHNG(98) ITERATIONS(99) BAD GUESS(9A) STAT PLOT(9B) TOL NOT MET(9C)
```

`SOLVER`=`0x96` is the *context name* shown on the Solver app's error screen;
`SINGULARTY`=`0x97` is raised when a step lands on a pole. **[confirmed]**

---

## 1. The equation Solver / `solve(` root finder — page 0x39 [confirmed]

The interactive **Equation Solver** app and the numeric **`solve(`** token share one
root-finding engine living on flash page **0x39**. (The Solver app's UI — the
`EQUATION SOLVER` / `eqn:0=` / `bound=` / `left-rt=` screen — is drawn from strings at
`06:6ABB`, loaded by code at `06:6286`/`06:62EA`/`06:66F3`.)

### 1.1 The function-value evaluator `f(x)` [confirmed]
At the heart is a callback that, given the trial value in `OP1`, returns `f(x) = left − right`
of the equation. Located around `39:468F`:

1. `_CkValidNum` (`ram:1E9B`), then `_MovFrOP1` (`ram:1B0C`) stores the current guess into
   the **solve variable** (named system var addressed via `(065B)`).
2. It installs an **error trap** (`39:46D9 CALL 327F`; `RES/SET 2,(IY+7)`) and re-parses /
   re-evaluates the stored equation formula (page-0x39 hosts a parse/token walker at
   `39:327F` using `parse_advance 7248` / `parse_cur_tok 72DA`-style cursors, mirroring the
   page-0x38 parser — the equation is re-tokenised and evaluated every iteration).
3. The post-eval filter at `39:46C7` inspects the error code in `A`: codes `0x86`/`0x87`
   (out-of-range / NONREAL ANS) and similar are **swallowed** (this `x` is treated as a
   point where `f` is undefined, so the solver can step past it) while harder errors are
   re-raised via `_JErrorNo` (`JP 2799`). This is why `solve(` can skip singularities
   inside the bracket without aborting. **[confirmed]**

The sign test `39:463A` reads `OP1.type` (`8478`) and `OP2.type` (`8483`), masks `0x80`
and XORs them: **Z = same sign, NZ = opposite sign** — the bracket sign-change predicate.
**[confirmed]**

### 1.2 The iteration loop [confirmed]
Setup (`39:43AD…4410`) evaluates `f` at the two user bounds, records their signs, and
seeds the bracket. The main loop runs from `39:4413`:

- **Loop / iteration counter** is carried in `A`, `INC A` each pass (`39:44BF`), pushed on
  the stack. Two caps are compared with `SBC HL,…`:
  - `LD HL,0x01F3` (= **499**) at `39:4479`/`39:458B` → exceeding it jumps to
    `39:45A0 LD A,0x99 … JP 2793` = **ITERATIONS**, and the early `LD A,0x9A` path
    (`39:45AD`) = **BAD GUESS** (raised when the initial bracket is unusable).
  - A small count (`CP 0x04`, `39:44C3`) gates the early Illinois/secant correction.
- **Bisection midpoint:** `_InvSub` (`ram:227D`, = b−a) then `_TimesPt5` (`ram:2382`, ×0.5)
  give the half-width $\tfrac{1}{2}(b-a)$ at `39:443C/443F`; adding $a$ yields the midpoint $m=a+\tfrac{1}{2}(b-a)$. **[confirmed]**
- **Secant / regula-falsi step:** `_FPMult` (`238B`), `_FPSub` (`2297`), `_FPDiv`-class and
  `_InvOP1S` (`24BD`) around `39:4488…44F2` compute the linear-interpolation step
  $x_{n+1}=x_n-f(x_n)\\,\dfrac{b-a}{f(b)-f(a)}$. The result is compared against the bisection bound; the
  algorithm **keeps the secant guess only if it stays inside the bracket**, otherwise it
  falls back to the midpoint — a classic **bisection ⊕ secant (Illinois/regula-falsi)
  hybrid**, the documented TI behavior. **[confirmed for the op sequence; method name standard]**
- **Sign-change bookkeeping:** the byte at `0x84AF` (OP6 area) holds the running sign of
  `f` at the bracket ends; `XOR 0x80` toggles it (`39:44AB…44B3`). If the two bounds never
  bracketed a sign change, the path at `39:45CD…45DA JP 2749` raises **NO SIGN CHNG**.
  **[confirmed]**
- **Convergence / tolerance test:** `_AbsO1O2Cp` (`ram:1987`, compares |OP1| vs |OP2|) is
  used repeatedly (`39:446F`, `44D7`, `44F8`, `45C7`) to test the bracket width / residual
  against tolerance. The tolerance floor is the **TIFloat constant `1.0e-13`** at
  `39:46EA` (`00 73 10 …`); the residual-zero floor is **`1.0e-99`** at `39:46E1`
  (`00 1D 10 …`). Reaching tolerance lands at `39:4547` and returns the root. **[confirmed]**

```pseudocode
\begin{algorithm}
\caption{Solver root-finder --- bracketed secant / regula-falsi (page 0x39)}
\begin{algorithmic}
\REQUIRE bracket $[a,b]$ with $\mathrm{sign}(f(a)) \neq \mathrm{sign}(f(b))$ \COMMENT{else \textsc{no sign change} (0x98)}
\FOR{$k = 0$ \TO $499$}
    \STATE $m \gets a + \tfrac{1}{2}(b-a)$ \COMMENT{bisection midpoint: \texttt{\_InvSub}, \texttt{\_TimesPt5}}
    \STATE $s \gets a - f(a)\,\dfrac{b-a}{f(b)-f(a)}$ \COMMENT{secant: \texttt{\_FPMult/\_FPSub/\_FPDiv}}
    \STATE $x \gets s$ \textbf{if} $s \in [a,b]$ \textbf{else} $m$ \COMMENT{fall back to bisection}
    \STATE $f_x \gets \mathrm{eval\_equation}(x)$ \COMMENT{re-parse, error-trapped (39:468F)}
    \IF{$\mathrm{sign}(f_x) = \mathrm{sign}(f(a))$}
        \STATE $a \gets x$ \COMMENT{keep the sign change in the new bracket}
    \ELSE
        \STATE $b \gets x$
    \ENDIF
    \IF{$|b-a| < 10^{-13}$}
        \RETURN $x$ \COMMENT{converged (39:4547)}
    \ENDIF
\ENDFOR
\STATE \textbf{raise} \textsc{iterations} (0x99) / \textsc{bad guess} (0x9A)
\end{algorithmic}
\end{algorithm}
```

`left-rt` shown on the Solver screen is the final residual `f(root)` (the
`left-side − right-side` value the evaluator computed). **[standard]**

---

## 2. The TVM finance solver — page 0x3A [confirmed]

The five-variable **time-value-of-money** solver (`N`, `I%`, `PV`, `PMT`, `FV`, plus
`P/Y`, `C/Y`, and the PMT:END/BEGIN flag) lives on flash page **0x3A**. Each variable is a
named system FP var; the routine loads them via small accessors:

- `3A:7F02` loads the var named at `(D35B)`, `3A:7F0F` the one at `(D55B)`, etc.
  (`(D?5B)` are the finance sysvar VAT slots). `(84D3)`=`iMathPtr1`, `(84D9)`=`iMathPtr4`,
  `(84AF)`=OP6, `(84D3)`/`(84D9)`/`(84D3)` hold the iteration state. **[confirmed]**

### 2.1 The TVM equation
The solver evaluates the standard cash-flow identity (rate $i = \tfrac{I\\%}{100}\big/\tfrac{C}{Y}$, with $S=0$ for
END / $1$ for BEGIN):

$$0 = PV + (1+iS)\\,PMT\\,\frac{1-(1+i)^{-N}}{i} + FV\\,(1+i)^{-N}$$

Implemented with `_FPRecip` (`ram:253D`, for `(1+i)^(−N)` via reciprocal/power),
`_FPMult` (`238B`), `_FPDiv` (`2541`), `_FPAdd` (RST 30h), `_InvSub`/`_FPSub`
(`227D`/`2297`) around `3A:70D6…7140`. The compound factor `(1+i)^N` is built with the
power/exp helpers. **[confirmed sequence; equation standard]**

### 2.2 The iteration [confirmed]
Solving for `I%` (the only variable with no closed form) uses **Newton's method on the
rate**:

- Iteration state is allocated as a small FPS frame (`LD HL,0x0005; _AllocFPS` at
  `3A:70A2`) and the loop counter is `B = 0x40` (= **64** iterations max), `3A:70AB`.
- Each pass recomputes the TVM residual and its derivative, takes a Newton step, and tests
  the exponent of the correction against `CP 0x74` (`3A:71F7`) — i.e. **converged when the
  update is ≤ ~10⁻¹²**. The new estimate is written back via `(84D9)→(84D3)`
  (`3A:71FB…71FE`). **[confirmed]**
- Exhausting the 64-iteration `DJNZ`/`DEC B` budget falls to `3A:7206 JP 274D` =
  **ITERATIONS (0x99)**. Solving for `N`/`PV`/`PMT`/`FV` is closed-form (algebraic
  rearrangement) and does not iterate. **[confirmed for I%; standard for the rest]**

The amortization helpers (`ΣPrn`, `ΣInt`, `bal(`, `Pmt_End`/`Pmt_Bgn`) and the finance
function tokens (`tFinNPV 0x00`, `tFinIRR 0x01`, `tFinBAL 0x02`, `tFinPRN 0x03`,
`tFinINT 0x04`, `tFinPV 0x2D`, `tFinPMT 0x2E`, `tFinFPMT 0x20`, `tFinPMTend 0x4B`,
`tFinPMTbeg 0x4C`; all 0xEF-prefixed 2-byte tokens) are dispatched into this page.
**IRR(** internally uses the same rate-Newton iteration and can also raise ITERATIONS.
**[confirmed token map; hypothesis for IRR sharing the loop]**

---

## 3. nDeriv( and fnInt( — page 0x33 numeric calculus [confirmed core, method hypothesis]

The numeric-calculus engine is on flash page **0x33** (the graph-math page — appropriate,
since both operate on a Y= expression). The function tokens are 0xBB-prefixed:
**`tRoot 0x22`** (the `solve(`-style root token), **`tFnInt 0x24`** (fnInt), and
**`tNDeriv 0x25`** (nDeriv). They are recognised by the 0xBB-group scanners
(`33:504E CP 0xBB`, also `38:4E3F`).

### 3.1 nDeriv( — symmetric difference quotient [standard]
`nDeriv(expr, var, value [,ε])` computes the **centered difference**
`(f(x+ε) − f(x−ε)) / (2ε)` with default `ε = 1e-3`. The setup region `33:4C80…4D00`
stores/restores the variable, evaluates `f` at `x±ε`, and divides by `2ε` using
`_FPSub`/`_FPDiv` (`2297`/`2541`) and `_TimesPt5`. The `(97E7)`/`(97E9)` counters at
`33:4C80`/`33:4CB4` track the two/three sub-evaluations. **[confirmed it is a finite-
difference with var save/restore; ε-default standard]**

### 3.2 fnInt( — adaptive numeric integration [confirmed iterative; rule hypothesis]
`fnInt(expr, var, a, b [,tol])` is an **adaptive iterative quadrature**. The body
`33:4D00…4E8F`:

- builds interval midpoints and half-widths: `_FPSub` (`2297`), `_TimesPt5` (`2382`, ×0.5),
  `_FPDiv` (`2541`), and `LD A,0x60; _OP2Set… ` loading small BCD weight constants
  (`33:4D1B`). **[confirmed]**
- maintains a working set of partial sums in an **FPS frame** (`_AllocFPS 1534`,
  `_PopRealOx 14F6/150F/1505`, `_DeallocFPS 1526`, with slot offsets `DE=0x15/0x1B/0x24`)
  — endpoint values, the running estimate, and the previous estimate for the error test.
  **[confirmed]**
- iterates, refining the partition (the `97E7`/`84AF` depth counters indicate **recursive
  interval subdivision**), and converges when the change in the estimate has exponent
  `≤ CP 0x74` (~10⁻¹², `33:4E77`). The natural-log constant `ln(10)=2.302585093e0`
  scaled is at `33:4E92` (used to relate digit-tolerance to the decimal error bound).
  Exhausting the refinement budget (`DEC A; JP NZ,4D57`) raises `33:4E8F JP 274D` =
  **ITERATIONS (0x99)**. **[confirmed loop/tolerance; the exact rule — adaptive
  Gauss-Kronrod vs adaptive Simpson — is hypothesis, consistent with the ×0.5 bisection
  of intervals plus a coarse/fine error comparison]**

Both nDeriv( and fnInt( evaluate the user's `f` by storing the running argument into the
integration/derivative variable and re-running the parser, exactly like the Solver's
`f(x)` callback in §1.1 — the same "store var → parse_eval → read OP1" loop. **[standard]**

---

## 4. How the unknown is varied — the parser feedback loop [confirmed/standard]

Every routine above shares this inner cycle, which is the whole reason they are slow:

1. Place the trial value in `OP1` (`_Mov9ToOP1` / arithmetic result).
2. `_MovFrOP1` (`ram:1B0C`) **store it into the named variable** the expression mentions
   (the solve var, the `nDeriv`/`fnInt` integration var, or the TVM var).
3. **Re-evaluate the expression** through the TI-BASIC parser (`_ParseInp 38:5987` /
   `parse_eval_expr 38:5AB3` / `_Find_Parse_Formula 38:758A`; the Solver uses its own
   page-0x39 token walker). The parser walks the *same stored token stream* each pass.
4. Read the numeric result back from `OP1`, form the residual / difference, decide the next
   step. An **error trap** (`39:327F` / `RES 2,(IY+7)`) lets a DOMAIN/NONREAL error at one
   sample be caught and treated as "undefined here" instead of aborting the whole solve
   (§1.1).

Because the expression is re-tokenised and re-evaluated on **every** iteration, a `solve(`
with a 499-iteration cap can parse the equation up to ~499 times, and a `fnInt` over a fine
adaptive partition can parse it thousands of times — the dominant cost.

---

## 5. Routine index (`space:addr  name`) [confirmed unless noted]

Equation Solver / `solve(` (page 0x39):
```
39:43AD  solver_root_setup          (eval f at both bounds, seed bracket)
39:4413  solver_iterate             (bisection+secant hybrid main loop)
39:463A  solver_sign_test           (OP1/OP2 sign-change predicate; Z=same sign)
39:468F  solver_eval_fx             (store guess -> reparse equation -> f=left-right)
39:46C7  solver_eval_errfilter      (swallow 0x86/0x87, re-raise others via _JErrorNo)
39:327F  solver_parse_formula       (page-39 token walker used by the evaluator)
39:46EA  const_tol_1e-13            (convergence tolerance, TIFloat 00 73 10..)
39:46E1  const_floor_1e-99          (residual-zero floor, TIFloat 00 1D 10..)
39:45A0  ->ITERATIONS(0x99)  39:45AD ->BAD GUESS(0x9A)  39:45DA ->NO SIGN CHNG(0x98)
```

TVM / finance solver (page 0x3A):
```
3A:70A2  tvm_solve_iterate          (Newton on I%, 64-iter FPS-framed loop)
3A:7F02  tvm_load_var_D35B          3A:7F0F  tvm_load_var_D55B   (finance var accessors)
3A:7206  ->ITERATIONS(0x99)
```

Numeric calculus (page 0x33):
```
33:4C80  nderiv_body                (centered difference (f(x+e)-f(x-e))/2e, e=1e-3)  [hypothesis label]
33:4D00  fnint_body                 (adaptive subdivision integrator)               [hypothesis label]
33:4E8F  ->ITERATIONS(0x99)
33:4E92  const_ln10                 (TIFloat 00 82 23 02 58 50 92 99 40)
33:504E  bb_token_scanner           (classifies 0xBB-group function tokens)
```

Error stubs / table (page 0 & 0x07):
```
ram:2749 _ErrSignChange(0x98)  ram:274D _ErrIterations(0x99)
ram:2751 _ErrBadGuess(0x9A)    ram:2755 _ErrTolTooSmall(0x9C)
ram:2793 _JError               07:6B81  error_name_table (indexed by code-0x88)
```

Shared FP/parse helpers (page 0): `_FPAdd 229E`, `_FPSub 2297`, `_FPMult 238B`,
`_FPDiv 2541`, `_FPRecip 253D`, `_InvSub 227D`, `_TimesPt5 2382`, `_InvOP1S 24BD`,
`_AbsO1O2Cp 1987`, `_OP1ToOP4 19EC`, `_OP4ToOP2 19FE`, `_CkValidNum 1E9B`,
`_MovFrOP1 1B0C`, `_AllocFPS 1534`, `_DeallocFPS 1526`, `_PopRealOx 14F6/150F/1505`.
Parser entries (page 0x38): `_ParseInp 5987`, `parse_eval_expr 5AB3`,
`_Find_Parse_Formula 758A`.

---

## 6. Open questions / TODO
- Confirm the exact `fnInt(` quadrature rule (adaptive Simpson vs Gauss-Kronrod 7/15) by
  recovering its node/weight constant table on page 0x33 (the small BCD constants around
  `33:4D1B` and the data block after `33:4E92`).
- Pin the per-page bcall id collisions seen in the TVM body (`id=0x40CF` decoded as `_SinH`
  is almost certainly a mis-mapped finance helper) — needs the page-0x3A-local jump targets.
- Trace how the parser's class-3 dispatch (`38:7175` pointer table) routes `tFnInt`/
  `tNDeriv`/`tRoot` argument lists into the page-0x33 bodies (generic app-call, not an
  inline bjump).
- Name the page-0/0x29xx solver helper cluster (`2800/2895/28C3/28D8/28E9/2903/2908/
  2914/291B/29CF/29D7/29DB/2A0B/2A0F/2A13/2A17`) — these are the Solver's OP-register
  save/restore and bracket-bookkeeping primitives.
