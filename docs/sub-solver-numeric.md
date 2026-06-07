# Solver & numerical methods

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
3. The post-eval filter at `39:46C7` inspects the error code in `A`: codes **below `0x86`**
   (`OVERFLOW`/`DIV BY 0`/`SINGULAR MAT`/`DOMAIN`) and `0x87` (`NONREAL ANS`) are
   **swallowed** (`CP 0x87; JR Z` then `CP 0x86; JP NC,0x2799` — this `x` is treated as a
   point where `f` is undefined, so the solver can step past it) while `0x86` (`BREAK`) and
   codes `≥ 0x88` are
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
  (`00 1D 10 …`). On reaching tolerance the solver exits through the `39:4540 → 4553`
  branch (dynamically traced on an `X²−2 = 0` solve that converged to √2 ≈ 1.41421356);
  `39:4547` is a `CALL`, not the converged return, and was **not** on the observed path.
  The tolerance tests at `446F`/`44D7`/`44F8` run under that trace; `45C7` is reached only
  on other convergence sub-paths. **[confirmed]**

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
        \RETURN $x$ \COMMENT{converged; exits via 39:4540 -> 4553}
    \ENDIF
\ENDFOR
\STATE \textbf{raise} \textsc{iterations} (0x99) / \textsc{bad guess} (0x9A)
\end{algorithmic}
\end{algorithm}
```

> **Dynamic confirmation.** Traced end-to-end under headless TilEm by driving the
> built-in Equation Solver to solve `X²−2 = 0`
> ([`solver-sqrt2.macro`](../tools/macros/solver-sqrt2.macro)). It converged on screen
> to `X = 1.4142135623…` (√2) with `left-rt = 0`. The mem-write records show the guess
> at `0x8478` climbing `1.40898 → 1.41421335 → 1.4142135623645 → 1.4142135623731`
> (|err| ≈ 4.9e-15, crossing below the `1e-13` tolerance on the final step).
> `solver_iterate` (`39:4413`) ran 808×; the per-iteration re-parse
> (`parse_eval_expr` `38:5AB3`) ran 834×; the secant-in-bracket-else-bisect test
> (`39:44F8`), the `499`-cap compare (`39:4479 LD HL,0x01F3`), and the `1e-13`/`1e-99`
> constants (`39:46EA`/`46E1`) all executed as the pseudocode describes.

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
  the exponent of the correction against `CP 0x74` (`3A:71F4`) — i.e. **converged when the
  update is ≤ ~10⁻¹²**. The new estimate is written back via `(84D9)→(84D3)`
  (`3A:71F9…71FE`). **[confirmed]**

### 2.3 The TVM rate loop calls `_SinH` (`3A:710B`) [confirmed]
At **`3A:710B`** the TVM body contains `EF CF 40` = `RST 0x28; .dw 0x40CF`, and the bcall
table maps `0x40CF` to **`_SinH`** (`_SinHCosH`=`0x40C6`, `_SinH`=`0x40CF`, `_ASinH`=`0x40ED`
are three consecutive distinct entries). A scan of the whole loop body (`3A:70A0…7210`) finds
three bcalls: `_SinH` (`0x40CF`, `3A:710B`), an unmapped helper `0x462A` (adjacent to
`_AdrLEle 0x462D` — a list/element accessor for the finance sysvar slots), and `_SetXXOP2`
(`0x478F`, `3A:71C5`). The `_SinH` call carries the math: the surrounding
`_FPMult`/`_OP1ToOP2`/`_FPSub` sequence (`CD 8B 23 … CD D4 16 CD 51 16 EF CF 40 CD 3F 16`)
evaluates the annuity / compound-growth factor in **hyperbolic form** — the numerically
stable way to form `(1+i)^N − 1` and `[1−(1+i)^-N]/i` for small rates `i`, avoiding
catastrophic cancellation. This is the only transcendental call in the rate-Newton loop.
**[confirmed]**
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

### 3.2 fnInt( — adaptive numeric integration [confirmed: adaptive bisection, no node table]
`fnInt(expr, var, a, b [,tol])` is an **adaptive iterative quadrature**. The body is the
Ghidra function `fnint_body` at `33:4D00` (extent `33:4D00…4E91`):

- builds interval midpoints and half-widths: `_FPSub` (`2297`), `_TimesPt5` (`2382`, ×0.5),
  `_FPDiv` (`2541`). The bytes at `33:4D18` are **executable code** — `33:4D18 21 83 84`
  (`LD HL,0x8483`), `33:4D1B 3E 60` (`LD A,0x60`), `33:4D1D CD 65 1B` (`CALL _OP2SetA`/`1B65`) — loading the
  scalar **0x60 = 96**
  (a working digit/scale count), not a quadrature weight. **[confirmed bytes]**
- maintains a working set of partial sums in an **FPS frame** (`_AllocFPS 1534`,
  `_PopRealOx 14F6/150F/1505`, `_DeallocFPS 1526`, with slot offsets `DE=0x15/0x1B/0x24`)
  — endpoint values, the running estimate, and the previous estimate for the error test.
  **[confirmed]**
- iterates, refining the partition by **interval bisection** (the ×0.5 `_TimesPt5` halving;
  the `97E7`/`84AF` depth counters track subdivision depth; the loop tail is
  `33:4E81 LD DE,0x0024 … C3 CB 45` and `33:4E8C 3D F5 C2 57 4D` = `DEC A; …; JP NZ,0x4D57`),
  and converges when the change in the estimate has exponent `≤ CP 0x74` (~10⁻¹²,
  `33:4E74`). Exhausting the refinement budget falls through to `33:4E8F JP 274D` =
  **ITERATIONS (0x99)**. **[confirmed loop/tolerance]**

**Quadrature rule.** A full byte scan of `33:4D00…4F00` finds **exactly one**
floating-point constant in the body: the TIFloat at `33:4E92`
(`00 82 23 02 58 50 92 99 40` = 2.30258509…×10², i.e. `ln(10)·100`). It is referenced at
`33:4E5D` (`LD HL,0x4E92; CALL 0x1982`), immediately after the only transcendental bcall in
the body, `33:4E56 EF AB 40` = bcall **`_LnX` (0x40AB)**. So `ln(10)·100` is used purely to
convert the requested **significant-digit tolerance** into a decimal **error bound** via
`ln` — it is *not* a quadrature node or weight. There is **no node/weight table anywhere in
the body** (the data after `33:4E92`, `FD CB 18 AE …`, decodes as code: `RES 5,(IY+0x18)`
followed by LCD/keypad port I/O `DB 3A / D3 3A`). A Gauss–Kronrod rule would require a fixed
block of ~7–15 irrational node and weight constants stored as TIFloats; their complete
absence, together with the explicit ×0.5 interval bisection and the coarse-vs-fine estimate
comparison, rules out Gauss–Kronrod. The rule is an **adaptive Newton–Cotes-style scheme
with recursive interval bisection** (Simpson-class), not Gauss–Kronrod. **[confirmed: the
only constant present is the ln-based tolerance scaler; no quadrature node table exists]**

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

### 4.1 How `tFnInt`/`tNDeriv`/`tRoot` reach the page-0x33 bodies [confirmed]
These three are **2-byte tokens** with the `t2ByteTok = 0xBB` lead byte (ti83plus.inc:
`tRoot = 0x22`, `tFnInt = 0x24`, `tNDeriv = 0x25`), so in the token stream they appear as
`BB 22` / `BB 24` / `BB 25`. The routing is a **generic paged command call, not an inline
bjump**, and goes through the page-0x02 command-execution layer:

1. The evaluator hands the operand token to the page-0x02 dispatcher, which recognises the
   `0xBB` group and the second byte: `tFnInt` at `02:68F3` (`CP 0x24`), `tNDeriv` at
   `02:6904` (`CP 0x25`), `tRoot` at `02:58AD`/`02:69BC` (`CP 0x22`). **[confirmed bytes]**
2. The page-0x02 handler **parses the comma-separated argument list** and sets defaults — e.g.
   the `nDeriv`/`fnInt` prologue at `02:6AF6` does `LD A,0x7D; LD (8479),A`, seeding the
   default tolerance exponent `0x7D` (= **1e-3**, the documented nDeriv ε) before the call.
   **[confirmed]**
3. It then performs a paged call into page 0x33. The page-0x33 entry re-validates the token
   through the `33:504E` `bb_token_scanner` (`CP 0xBB`, then `CP 0x68 / 0xCF / 0xDB / 0xF6`
   to assign a small class index in `C` and `CALL 0x50AC`) and dispatches into the numeric
   bodies `nderiv_body` (`33:4C80`) / `fnint_body` (`33:4D00`). Because the call crosses
   pages through the bcall/app-call trampoline, **no static xref to these bodies survives**
   in the Ghidra database — the mark of a generic paged call rather than an inline bjump.
   **[confirmed path; trampoline hides the static edge]**

---

## 5. Routine index (`space:addr  name`) [confirmed unless noted]

Equation Solver / `solve(` (page 0x39):
```
39:43AD  solver_root_setup          (eval f at both bounds, seed bracket)
39:4413  solver_iterate             (bisection+secant hybrid main loop)
39:463A  solver_sign_test           (OP1/OP2 sign-change predicate; Z=same sign)
39:468F  solver_eval_fx             (store guess -> reparse equation -> f=left-right)
39:46C7  solver_eval_errfilter      (swallow <0x86 and 0x87/NONREAL; re-raise 0x86/BREAK and >=0x88 via _JErrorNo)
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
33:4C80  nderiv_body                (centered difference (f(x+e)-f(x-e))/2e, e=1e-3)
33:4D00  fnint_body                 (adaptive bisection integrator; extent 4D00..4E91)
33:4E56  ->bcall _LnX (0x40AB)       (digit-tolerance -> decimal error bound)
33:4E8F  ->ITERATIONS(0x99)
33:4E92  const_ln10x100             (TIFloat 00 82 23 02 58 50 92 99 40 = ln(10)*100; the
                                     ONLY FP constant in fnint_body -- no node/weight table)
33:504E  bb_token_scanner           (CP 0xBB then class-index 0x68/0xCF/0xDB/0xF6 -> CALL 50AC)
33:4381  ctrlflow_handler_table     (13-entry jump table for For/While/Repeat/End/Return, etc.)
33:435F  ctrlflow_dispatch          (entry from bcall 0x5140/0x513D; SUB 0x20; index 4381)
```

Page-0 FPS register save/restore + active-frame bookkeeping cluster (the "solver helper
cluster" — these are generic FPS slot accessors used by the solver, fnInt/nDeriv and other
FPS-framed routines; each slot is 9 bytes = one TIFloat, offset `-(9*slot)` from the frame
base pointer `(9302)`):
```
ram:2800  fps_swap_active_frame      (swaps the active FPS frame pointer at (86DE) -- the
                                      bracket/scope bookkeeping primitive)  [renamed]
ram:2895/28C3/28D8/28E9/2903/2908/2914/291B  fp_st_slotN_opX
                                      (store OP1/OP3 into FPS slot 2/4/5/6/7/7/8/9)
ram:29CF/29D7/29DB/2A0B/2A0F/2A13/2A17        fp_ld_op1_slotN
                                      (load OP1 from FPS slot 5/7/8/10/11/12/13)
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

## 6. Resolved / residual

The four open questions from the prior pass are now resolved against the bytes:

- **fnInt( quadrature rule — resolved (§3.2).** Not Gauss–Kronrod. The body has **no node or
  weight table**; its sole FP constant is `ln(10)·100` at `33:4E92`, used (with bcall `_LnX`)
  to convert digit-tolerance to a decimal error bound. With explicit ×0.5 interval bisection
  and a coarse-vs-fine estimate comparison, it is an **adaptive Newton–Cotes / Simpson-class
  bisection** integrator. `33:4D1B` is executable code (`LD A,0x60; _OP2SetA`).
- **TVM `_SinH` (id 0x40CF) — resolved (§2.3).** The TVM rate loop calls `_SinH` at
  `3A:710B` (`0x40C6/0x40CF/0x40ED` are three distinct hyperbolic bcalls); it evaluates the
  annuity / compound factor in hyperbolic form for numerical stability at small rates.
- **class-3 routing of `tFnInt`/`tNDeriv`/`tRoot` — resolved (§4.1).** Path is
  `BB-token → page-0x02 dispatcher (02:68F3/6904/58AD) → arg-parse + default-tol (02:6AF6,
  exp 0x7D = 1e-3) → paged call → page-0x33 bodies`, re-validated by `bb_token_scanner`
  (`33:504E`). The trampoline hides the static xref, confirming it is a generic paged call.
- **page-0 helper cluster — resolved (§5).** Generic **FPS slot save/restore** (9-byte
  TIFloat slots at `-(9*slot)` from frame base `(9302)`) plus the active-frame swapper at
  `ram:2800`, renamed `fps_swap_active_frame`; the store/load stubs are
  `fp_st_slotN_opX` / `fp_ld_op1_slotN`.

Residual (genuinely unverified, would need deeper paged tracing):
- The exact byte layout of the For/While/Repeat **loop-control record** pushed by the
  page-0x33 control-flow handlers (`33:4381` jump table) is not yet field-mapped; only the
  dispatch path is confirmed. (See [sub-tibasic.md](sub-tibasic.md) §4.)
- bcall `0x462A` in the TVM body is unmapped (adjacent to `_AdrLEle`; likely a finance-sysvar
  list/element accessor).
