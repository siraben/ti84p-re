# TI-BASIC programming patterns

*TI-84 Plus OS 2.55MP -- performance and tracing notes.*

This page turns the interpreter traces into practical programming rules. It is
not a style guide for calculator golf; it is a map from common TI-BASIC
patterns to the OS paths they exercise.

Confidence follows [Conventions](conventions.md): **[confirmed]** = observed in
the disassembly or the headless TilEm traces; **[standard]** = matches TI-BASIC
semantics and the traced interpreter shape; **[hypothesis]** = useful pattern
not yet traced end to end in this repo.

---

## Performance rules from traces

1. **Keep parser work out of hot loops.** Every statement re-enters the page-38
   evaluator (`eval_stmt_entry`, `parse_refill`, `parse_advance`,
   `chk_tok_end`). Tiny loop bodies can still spend most of their time walking
   tokens and rebuilding temporary parse state. The
   [`For(` optional-paren trap](sub-tibasic-for-paren.md) is the sharpest
   example: with a first-line false `If`, dropping the closing `)` made an
   `N=100` benchmark grow from 521,723 to 885,912 marker-to-marker instructions.
   **[confirmed]**
2. **Prefer built-ins for list-wide work.** `SortA(`, `cumSum(`, and `sum(`
   cross into OS routines that run one parser setup and then loop internally.
   The `DATA.8xp` trace hits `list_fold_dispatch` (`02:6104`) for `sum(` rather
   than reparsing an explicit BASIC accumulator loop for every element.
   **[confirmed]**
3. **Cache list elements and dimensions.** List indexing resolves a variable
   name through the VAT, checks type/dimension, computes an element address, and
   shuttles a 9-byte `TIFloat` through OP registers. Repeated `L1(I)` inside a
   loop is much more expensive than storing the element into a scalar once when
   the value is reused. **[confirmed path, standard rule]**
4. **Avoid `Goto` in hot loops.** `Goto` searches for a matching `Lbl` by
   scanning the program token stream, and escaping structured loops through
   `Goto` can leave loop bookkeeping behind. Use `For(`/`While`/`Repeat` plus
   `End` unless the jump is truly cold. **[standard; scanner confirmed in
   `sub-tibasic.md`]**
5. **Batch display and graph output.** `Disp` and `Output(` reach display
   primitives and LCD update paths; graph drawing reaches graph-buffer and pixel
   routines before display copy. Draw into the graph buffer and call
   `DispGraph` once when possible. **[confirmed]**
6. **Write the optional syntax in loops.** Closing `For(` with `)` costs at most
   a small command-finalization path, but it avoids the pathological
   implicit-close/false-`If` interaction. **[confirmed]**

## Run-confirmed fixtures

The generator `tools/tibasic_samples.py` now emits these additional trace-ready
fixtures.

### Text animation with `Output(`

```ti-basic
ClrHome
For(I,1,8)
Output(1,I,"X")
End
Disp "DONE"
```

Observed run: `ANIMTXT.8xp` leaves `DONEXXXX` on the first row, then `Done`. The
trace hits page-38 parser paths, page-33 loop/math helpers, `_OutputExpr`
(`03:4AF2`), `_Disp` (`37:51D3`), and LCD text routines. **[confirmed]**

The performance lesson is that animation is expensive twice: the interpreter
parses each `Output(` call, then the display stack updates text/LCD state. For a
real animation, keep loop bodies tiny and avoid recomputing strings or indexes
inside the drawing loop.

### Graph-buffer visualization

```ti-basic
ClrDraw
Line(0,0,95,63)
Circle(47,31,10)
Text(0,0,"DFS")
DispGraph
```

Observed run: `GRAPHV.8xp` ends on the graph screen with `DFS`, axes, and the
diagonal line visible. The trace hits `_GrBufClr`, `_ILine` (`04:4029`),
`graph_pixel_op`, `_IPoint`, `_PDspGrph` (`04:7904`), and the page-38 argument
parser. **[confirmed]**

The performance lesson is to draw several primitives into the graph buffer, then
display the graph buffer once. Repeated home-screen `Output(` calls give you
more text-layout overhead and less control over redraw timing.

### BASIC subprogram calling convention

Caller:

```ti-basic
0->A
prgmSUBRT
Disp A
```

Callee:

```ti-basic
Disp "SUB"
A+1->A
Return
```

Observed run: loading `CALLSUB.8xp` and `SUBRT.8xp` displays `SUB`, then `1`,
then `Done`. This confirms the practical TI-BASIC calling convention: arguments
and return values live in shared global variables, lists, strings, matrices, or
`Ans`; `Return` exits the callee and resumes the caller. The trace hits VAT/name
resolution (`findsym_scan`), parser entry/refill paths, `_StoSysTok`, `_StoAns`,
`_RclVarSym`, and `_Disp`. **[confirmed]**

There is no local variable frame for BASIC programs. A subprogram that uses `A`
modifies the caller's `A`. For reusable routines, document which variables are
inputs, scratch, and outputs.

## Larger source patterns

The following programs are source-level patterns that exercise the same
interpreter paths. They are not yet part of the generated `.8xp` fixture set.

### DFS with a list stack

This is a compact graph traversal skeleton for an adjacency matrix `[A]`, a
node count `N`, start node `S`, visited list `L1`, and explicit stack `L2`.

```ti-basic
0*seq(I,I,1,N)->L1
{S}->L2
While dim(L2)
L2(dim(L2))->V
dim(L2)-1->dim(L2)
If not(L1(V))
Then
1->L1(V)
Disp V
For(W,1,N)
If [A](V,W) and not(L1(W))
augment(L2,{W})->L2
End
End
End
```

Performance notes: `dim(L2)` and `L2(dim(L2))` both resolve the list and parse
an index; cache `dim(L2)` into a scalar if the body grows. `augment(` allocates
a new list, so this version is easy to read but not memory efficient. A faster
version preallocates `L2`, keeps a scalar stack pointer, and writes `W->L2(P)`.
**[standard]**

### Arbitrary-precision decimal addition

Use lists of base-10 digits in little-endian order. For example, `12345` is
`{5,4,3,2,1}`.

```ti-basic
max(dim(L1),dim(L2))->N
0->C
For(I,1,N)
C->S
If I<=dim(L1)
S+L1(I)->S
If I<=dim(L2)
S+L2(I)->S
int(S/10)->C
S-10C->L3(I)
End
If C
C->L3(N+1)
```

Performance notes: this is intentionally simple, but it is parser-heavy. Cache
`dim(L1)` and `dim(L2)` before the loop, avoid repeated list indexing when a
digit is reused, and use a larger base only if you can tolerate more carry and
display conversion work. **[standard]**

## BASIC and ASM interop

### BASIC to ASM

The validated smoke test is:

```ti-basic
Asm(prgmASMRET)
```

with:

```ti-basic
AsmPrgm
C9
```

`Asm(` is token `BB 6A`; `AsmPrgm` is `BB 6C`; `prgm` is token `5F`. The trace
shows the OS handoff through `07:57B4`, execution of the payload byte at
`ram:9D95 op=0xC9`, and return to BASIC. **[confirmed]**

Practical convention: pass data through OS variables or known RAM locations,
validate inputs on the BASIC side, and make the ASM payload return normally with
`RET` unless it intentionally transfers control elsewhere.

### ASM to BASIC

The inverse direction is not yet run-confirmed in this repo. The standard route
is for ASM to call OS parser/program services: build or locate a program
variable name, use VAT lookup, set up parser state, and enter the same
interpreter machinery used by `prgmNAME`. That path needs a dedicated trace
before this documentation should claim an exact calling sequence. **[hypothesis]**

The current open item is therefore precise: trace a small ASM payload that
invokes a BASIC program, identify the service entry and required parser/VAT
state, and compare it to the already-confirmed BASIC-to-ASM `Asm(` handoff.
