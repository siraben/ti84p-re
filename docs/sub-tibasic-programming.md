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

### Trace-backed cost map

| Pattern | Trace evidence | Practical rule |
|---------|----------------|----------------|
| Straight-line display (`HELLO`) | page-38 statement parse plus `_Disp` | Fine for status text; avoid using `Disp` as a frame loop. |
| Prompted arithmetic (`FACTOR`) | loop-body reseed, FP multiply, display | Keep loop bodies short; store loop-invariant values before `For(`. |
| List built-ins (`DATA`) | `sum(` reaches `list_fold_dispatch` | Prefer built-ins when one parser setup can cover many elements. |
| Text animation (`ANIMTXT`) | `Output(` plus LCD text paths on every loop | Precompute positions/strings and update the smallest region possible. |
| Graph drawing (`GRAPHV`) | primitives draw into `plotSScreen`, then `_PDspGrph` | Batch graph primitives before `DispGraph`. |
| BASIC subprogram (`CALLSUB`) | page-38 program-body evaluator and shared VAT variables | Treat globals/lists/`Ans` as the calling convention. |
| List algorithms (`BIGADD`, `DFS`) | VAT lookup, element address, OP-register move per access | Preallocate lists; cache dimensions and reused elements in scalars. |

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
`Ans`; `Return` exits the callee and resumes the caller. The trace hits the
page-38 statement interpreter, VAT/name resolution (`findsym_scan`), parser
entry/refill paths, the program-body evaluator call at `38:6914` into
`eval_eqn_recursive` (`38:778F`), `_StoSysTok`, `_StoAns`, `_RclVarSym`, and
`_Disp`. **[confirmed]**

There is no local variable frame for BASIC programs. A subprogram that uses `A`
modifies the caller's `A`. For reusable routines, document which variables are
inputs, scratch, and outputs.

### Arbitrary-precision decimal addition

`BIGADD.8xp` uses lists of base-10 digits in little-endian order. `12345` is
`{5,4,3,2,1}`, `98765` is `{5,6,7,8,9}`, and the result is the list
`{0,1,1,1,1,1}` for `111110`.

```ti-basic
{5,4,3,2,1}->L1
{5,6,7,8,9}->L2
{0,0,0,0,0,0}->L3
0->C
For(I,1,5)
L1(I)+L2(I)+C->S
int(S/10)->C
S-10C->L3(I)
End
C->L3(6)
Disp L3
Disp L3(6)
```

Observed run: the list line begins `{0 1 1 1 1 ...}`, the explicit carry line is
`1`, and the program ends with `Done`. The trace hits list element address and
store paths (`list_var_index`, `_AdrLEle`, `_GetLToOP1`, `_PutToL`,
`store_list_elem*`) plus `fnint_body`, `_FPDiv`, `_FPAdd`, `_FPSub`, and
`_FPMult`. **[confirmed]**

Performance notes: this is intentionally simple, but it is parser-heavy. For a
general routine, cache `dim(L1)` and `dim(L2)` before the loop, avoid repeated
list indexing when a digit is reused, and use a larger base only if you can
tolerate more carry and display conversion work.

### DFS with a list stack

`DFS.8xp` uses two edge lists (`L1` source, `L2` destination), a visited list
(`L3`), and an explicit stack (`L4`) to traverse this graph:

```text
1 -> 2
1 -> 3
2 -> 4
```

```ti-basic
{1,1,2}->L1
{2,3,4}->L2
{0,0,0,0}->L3
{1,0,0,0}->L4
1->P
While P
L4(P)->V
P-1->P
If L3(V)=0
Then
1->L3(V)
Disp V
For(E,1,3)
If L1(E)=V
Then
P+1->P
L2(E)->L4(P)
End
End
End
End
Disp L3
```

Observed run: traversal order is `1`, `3`, `2`, `4` because the stack is LIFO and
node `3` is pushed after node `2`. The final visited list is `{1 1 1 1}`. The
trace hits `blockmatch_end_else`, `parse_scan_tokens`, `if_isg_stmt_handler`,
parser refill/advance paths, `_Disp`, and the same list read/write helpers used
by `BIGADD`. **[confirmed]**

Performance notes: this version scans all edges for every visited node, so it is
easy to understand but O(VE) in BASIC-level work. For larger graphs, keep an
offset table of edge ranges per node, avoid `augment(` in hot loops, and
preallocate stack/visited lists with scalar pointers as this sample does.

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

`Asm(` is token `BB 6A`; `AsmPrgm` is `BB 6C`; `prgm` is token `5F`. The
`Asm(` command handler parses the following `prgmNAME` token stream, then
bcalls `_ExecutePrgm` (`4E7C`, target `07:5758`). The trace shows that path
compile/copy the `AsmPrgm` body and hand off through `07:57B4`, execute the
payload byte at `ram:9D95 op=0xC9`, and return to BASIC. **[confirmed]**

Practical convention: pass data through OS variables or known RAM locations,
validate inputs on the BASIC side, and make the ASM payload return normally with
`RET` unless it intentionally transfers control elsewhere.

| Direction | Confirmed mechanism | Caveat |
|-----------|---------------------|--------|
| BASIC -> ASM | `Asm(prgmNAME)` parses `prgmNAME`, bcalls `_ExecutePrgm`, copies the `AsmPrgm` payload, then jumps through `ram:9D95`. | The payload runs in the calculator OS process; a bad payload can corrupt interpreter state. |
| BASIC -> BASIC | `prgmNAME` enters the page-38 parser/VAT/body evaluator path and `Return` resumes the caller. | There is no local frame; variables are shared. |
| ASM -> VAT lookup | An `AsmPrgm` can build `OP1={ProgObj,"NAME"}` and bcall `_ChkFindSym`. | Lookup is not execution. |
| ASM -> BASIC | No working public bcall sequence is proven in this repo. | `_Find_Parse_Formula` from an arbitrary `AsmPrgm` context reached `ERR:UNDEFINED`. |

### ASM to BASIC

The inverse direction is not yet run-confirmed in this repo. Two easy-looking
bcalls are not that entry point:

- `_ExecutePrgm` is the `AsmPrgm` executor reached by `Asm(prgmNAME)`, not a
  general "run a BASIC program" entry.
- `_ParsePrgmName` (`4E82`, target `38:40D4`) only consumes a `prgmNAME` token
  from the current parser cursor and builds the name object used by `Asm(`.

The confirmed BASIC subprogram path is different: the `CALLSUB`/`SUBRT` trace
does not hit `_ParsePrgmName`, `_ExecutePrgm`, `_Find_Parse_Formula`, or
`_SetParseVarProg`. It resolves the program name through the page-38
parser/VAT path, enters the program-body evaluator at `38:6914` ->
`38:778F`, and lets `Return` unwind to the caller. Calling that same machinery
from arbitrary ASM requires more than loading OP1 and bcalling a single public
entry; it needs the same parser cursor, stack, error, and run-state setup that a
live BASIC caller already has. **[hypothesis]**

Two temporary ASM probes make the boundary sharper. An `AsmPrgm` payload that
builds `OP1={ProgObj,"ZZBASIC"}` and bcalls `_ChkFindSym` (`42F1`) returns to
the BASIC wrapper, proving that a payload can locate a BASIC program by name:

```asm
ld hl,name
ld de,8478h        ; OP1
ld bc,0009h
ldir
rst 28h
.dw 42F1h          ; _ChkFindSym
ret
name: .db 05h,"ZZBASIC",00h
```

Changing only the bcall to `_Find_Parse_Formula` (`4AF2`) enters `38:758A` and
then stops at `ERR:UNDEFINED`; the `ZZBASIC` body never displays. That failed
run confirms `_Find_Parse_Formula` is not a drop-in BASIC program executor from
an arbitrary `AsmPrgm` context. **[confirmed]**

The current open item is therefore precise: trace a small ASM payload that
successfully invokes a BASIC program, identify the required parser/VAT/error
state, and compare it to both confirmed paths: `Asm(` -> `_ExecutePrgm` ->
`ram:9D95`, and BASIC `prgmNAME` -> `38:6914`/`38:778F` program-body
evaluation.
