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
| Graph visualization (`GRAPHDFS`, `GRAPHLST`) | window stores plus repeated `Line(`/`Circle(`/`Text(` reach `_StoSysTok`, `_ILine`, `_IPoint`, `graph_pixel_op`, `_PDspGrph`, and small-font paths; `GRAPHLST` also reaches list indexing in draw arguments | Store graph topology in lists; draw the whole view in one graph-buffer pass. |
| BASIC subprogram (`CALLSUB`, `CALLABI`) | page-38 program-body evaluator and shared VAT variables | Treat globals/lists/`Ans` as the calling convention. |
| List algorithms (`BIGADD`, `BIGMUL`, `DFS`) | VAT lookup, element address, OP-register move per access | Preallocate lists; cache dimensions and reused elements in scalars. |

### Evidence manifest

This branch keeps each claimed behavior tied to a runnable fixture or a
negative probe trace. The visualization fixtures were rerun on 2026-06-07 and
kept because they render visible output and pass first-to-final changed-pixel
checks plus named crop-region checks for text, axes, circle arcs, nodes, and
edges. `ANIMTXT` also has a distinct-frame threshold, so the animation fixture
must show multiple captured LCD states rather than only a final still. The
smoke runner also checks final-screen regions for the main text, list, ASM
interop, arbitrary-precision, and DFS outputs. The full
`tools/tibasic_smoke.py` suite also passed on 2026-06-07 against the current
branch state.

| Goal area | Fixture or probe | Current evidence |
|-----------|------------------|------------------|
| Hello world | `HELLO.8xp` | Displays `HELLO, WORLD`, then `Done`; reaches page-38 statement parsing and `_Disp`. |
| Factorial | `FACTOR.8xp` | Prompt input `5` displays `120`; reaches loop parsing and `_FPMult`. |
| Data manipulation | `DATA.8xp` | Sorts, cumulatively sums, and displays list data; reaches list element stores and `sum(`'s list fold path. |
| Text animation | `ANIMTXT.8xp` | Moves/writes `X` characters with `Output(`, then displays `DONE`; reaches LCD text routines each loop. |
| Graph drawing | `GRAPHV.8xp` | Renders `DFS`, axes, a circle, and diagonal line on the graph screen; reaches `_ILine`, `_IPoint`, and `_PDspGrph`. |
| Graph visualization | `GRAPHDFS.8xp`, `GRAPHLST.8xp` | Renders the four-node DFS topology with labels and edges; the list-driven fixture stores edge/node coordinates in lists and loops over them before `DispGraph`. |
| Arbitrary precision arithmetic | `BIGADD.8xp`, `BIGMUL.8xp` | Adds and multiplies digit lists with carry propagation; reaches list indexing and FP helper paths. |
| DFS / stack-style list algorithm | `DFS.8xp` | Displays traversal `1, 3, 2, 4` and visited list `{1 1 1 1}`; reaches nested scanner/control-flow paths. |
| BASIC subprogram calling convention | `CALLSUB.8xp` + `SUBRT.8xp`; `ABICALL.8xp` + `ABISUB.8xp` | Caller and callee share scalar/list/`Ans` state and return through the BASIC program evaluator. |
| BASIC to ASM | `ASMCALL.8xp` + `ASMRET.8xp` | `Asm(` runs an `AsmPrgm` payload (`C9`) and returns to BASIC, displaying `BEFORE` then `AFTER`. |
| ASM-directed BASIC callback | `ASMBRIDG.8xp` + `ASMSIG.8xp` + `ZZBASIC.8xp` | ASM sets `Ans=1` with `_OP1Set1`/`_StoAns`, returns, and BASIC calls `prgmZZBASIC` through `If Ans`. |
| ASM return value | `ASMRTN.8xp` + `ASMVAL.8xp` | ASM sets `Ans=2` with `_OP1Set2`/`_StoAns`; BASIC reads `Ans`, computes `Ans+3`, and displays `5`. |
| Direct ASM to BASIC | temporary probes | VAT lookup from `AsmPrgm` works, but `_Find_Parse_Formula`, `_ParseInpLastEnt`, `_ExecuteNewPrgm`, `_JForceCmd`, `_PutTokString`, and `_rclToQueue` do not prove a standalone callable BASIC-program ABI. |

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
0->Xmin
94->Xmax
0->Ymin
62->Ymax
Line(0,0,94,62)
Line(0,31,94,31)
Line(47,0,47,62)
Circle(47,31,10)
Text(0,0,"DFS")
DispGraph
```

Observed run: `GRAPHV.8xp` ends on the graph screen with `DFS`, axes, a circle,
and the diagonal line visible. The trace hits `_GrBufClr`, `_StoSysTok`,
`_ILine` (`04:4029`), `graph_pixel_op`, `_IPoint`, `_PDspGrph` (`04:7904`), and
the page-38 argument parser. **[confirmed]**

The performance lesson is to draw several primitives into the graph buffer, then
display the graph buffer once. Repeated home-screen `Output(` calls give you
more text-layout overhead and less control over redraw timing.

Text animation and graph-buffer animation have different costs. `Output(` keeps
the home/text display model active and pays row/column formatting on every
iteration. Graph-buffer animation pays coordinate conversion, pixel primitive
work, and a display-buffer copy at `DispGraph`. For visible motion, batch one
frame in `plotSScreen`, call `DispGraph`, then compute the next frame; avoid
alternating graph primitives with home-screen output inside the same hot loop.

### Graph visualization of DFS topology

`GRAPHDFS.8xp` draws the same four-node graph traversed by `DFS.8xp`:

```ti-basic
ClrDraw
0->Xmin
94->Xmax
0->Ymin
62->Ymax
Line(10,44,35,54)
Line(10,44,35,14)
Line(35,54,55,29)
Circle(10,44,3)
Circle(35,54,3)
Circle(35,14,3)
Circle(55,29,3)
Text(16,8,"1")
Text(6,33,"2")
Text(46,33,"3")
Text(31,53,"4")
DispGraph
```

The graph data from `DFS.8xp` maps to graph pixels through fixed coordinate
lists:

| Node | DFS value | Pixel center | Label position |
|------|-----------|--------------|----------------|
| 1 | root | `(10,44)` | `Text(16,8,"1")` |
| 2 | first edge target | `(35,54)` | `Text(6,33,"2")` |
| 3 | second edge target | `(35,14)` | `Text(46,33,"3")` |
| 4 | child of 2 | `(55,29)` | `Text(31,53,"4")` |

The edge lists `L1={1,1,2}` and `L2={2,3,4}` become the three line segments
`1-2`, `1-3`, and `2-4`. The fixture stores window variables first so these
pixel-like coordinates cover the visible graph area.

Observed run: the final graph screen shows four labeled nodes with edges
`1-2`, `1-3`, and `2-4`. The trace hits `_ILine` (`04:4029`),
`graph_pixel_op`, `_IPoint`, `_PDspGrph` (`04:7904`), small-font glyph
rendering, window variable stores through `_StoSysTok`, `_RestoreDisp`, and
page-38 statement evaluation. **[confirmed]**

The performance lesson is to separate graph data from graph drawing. Keep edge
lists and traversal state in lists, but convert them to pixels in a single draw
phase instead of interleaving traversal, display, and recalculation.

`GRAPHLST.8xp` makes that separation explicit. It stores edge endpoint
coordinates in `L1`-`L4` and node centers in `L5`/`L6`, then draws edges and
nodes with loops:

```ti-basic
{10,10,35}->L1
{44,44,54}->L2
{35,35,55}->L3
{54,14,29}->L4
{10,35,35,55}->L5
{44,54,14,29}->L6
For(I,1,3)
Line(L1(I),L2(I),L3(I),L4(I))
End
For(I,1,4)
Circle(L5(I),L6(I),3)
End
```

Observed run: `GRAPHLST.8xp` renders the same four-node topology as
`GRAPHDFS.8xp`; the smoke runner checks the same node and edge crop regions.
The trace additionally hits `list_var_index` and `_GetLToOP1`, proving that the
draw arguments came through list element recall rather than hard-coded
coordinates. **[confirmed]**

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
then `Done`. This confirms the practical TI-BASIC calling convention for
scalars: arguments and return values live in shared global variables; `Return`
exits the callee and resumes the caller. The trace hits the
page-38 statement interpreter, VAT/name resolution (`findsym_scan`), parser
entry/refill paths, the program-body evaluator call at `38:6914` into
`eval_eqn_recursive` (`38:778F`), `_StoSysTok`, `_StoAns`, `_RclVarSym`, and
`_Disp`. **[confirmed]**

The full smoke trace also hits `_ParseInpLastEnt`/`_ParseInp` once while the
homescreen evaluates the initial `prgmCALLSUB` command selected by the macro.
That launch parse is not the same as the callee transition. The repeated
subprogram body path is the private `38:6910` -> `38:6914` -> `38:778F`
sequence, reached after parser RAM has already been populated:

| RAM state | Address | Role in the private parser frame |
|-----------|---------|----------------------------------|
| `basic_prog` | `9652` | current OP1-style program/object name |
| `basic_start` | `965B` | first token byte after the stored program size word |
| `nextParseByte` | `965D` | current parser cursor |
| `basic_end` | `965F` | parser end pointer |
| `numArguments` | `9661` | argument count/state byte used by parser helpers |
| `chkDelPtr3` / `chkDelPtr4` | `981C` / `981E` | temporary VAT/data pointers used during name and object setup |
| `FPS` / `OPS` / `pTemp` / `progPtr` | `9824` / `9828` / `982E` / `9830` | live FP/temp/program storage bounds |

There is no local variable frame for BASIC programs. A subprogram that uses `A`
modifies the caller's `A`. For reusable routines, document which variables are
inputs, scratch, and outputs.

| ABI part | Practical convention | Trace evidence |
|----------|----------------------|----------------|
| Inputs | Scalars, lists, and `Ans` are shared across caller and callee. The caller stores them before `prgmNAME`. | `CALLSUB` stores `A`; `ABICALL` seeds `L1` and `Ans`. |
| Outputs | The callee stores results back to globals, list elements, or `Ans`. | `SUBRT` increments shared `A`; `ABISUB` writes `A`, `L1(3)`, and `Ans`. |
| Scratch | No automatic save/restore exists. Routines must document scratch variables. | The VAT and parser state are shared across caller and callee. |
| Return | `Return` exits the callee and resumes the caller. `Stop` terminates the whole program chain. | `SUBRT` returns to `CALLSUB`, which then runs `Disp A`. |
| Parser state | `prgmNAME` runs with private parser/FPS state already set up by BASIC. | The callee path reaches `38:6910` -> `38:6914` -> `38:778F`. |

`ABICALL.8xp` broadens that scalar-only case:

```ti-basic
{2,4,6}->L1
7
prgmABISUB
Disp A
Disp L1
Disp Ans
```

with callee:

```ti-basic
Ans+L1(2)->A
9->L1(3)
A
Return
```

Observed run: `ABICALL.8xp` and `ABISUB.8xp` display `11`, `{2 4 9}`, `11`,
then `Done`. The callee reads the caller's `Ans=7` and `L1(2)=4`, stores `11`
in shared scalar `A`, mutates shared `L1(3)` to `9`, evaluates `A` as the final
callee expression so `Ans` is also `11`, and returns. The smoke runner checks
the rendered scalar, list, `Ans`, and `Done` regions, and the trace hits
`stmt_eval_body_entry`, `call_eval_eqn_recursive`, `eval_eqn_recursive`,
`_AnsName`, and `store_list_elem`. **[confirmed]**

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

For a reusable arbitrary-precision add routine, treat `L1` and `L2` as
little-endian digit arrays and compute the loop bound from list lengths:

```ti-basic
dim(L1)->N
If dim(L2)>N
dim(L2)->N
0->C
For(I,1,N)
0->A
0->B
If I<=dim(L1)
L1(I)->A
If I<=dim(L2)
L2(I)->B
A+B+C->S
int(S/10)->C
S-10C->L3(I)
End
If C
C->L3(N+1)
```

The invariant after iteration `I` is that `L3(1..I)` contains the low `I`
digits of `L1+L2`, and `C` is the carry into digit `I+1`. Base 10 is easy to
display and debug. A larger base reduces loop count but adds conversion and
larger carry values; on TI-BASIC, that tradeoff only helps when display is not
part of the hot path.

### Arbitrary-precision decimal multiplication

`BIGMUL.8xp` uses the same little-endian digit convention for schoolbook
multiplication. The example multiplies `123` (`{3,2,1}`) by `45` (`{5,4}`), so
the expected result is `5535`, represented as `{5,3,5,5,0}`.

```ti-basic
{3,2,1}->L1
{5,4}->L2
{0,0,0,0,0}->L3
For(I,1,3)
For(J,1,2)
L3(I+J-1)+L1(I)*L2(J)->S
int(S/10)->C
S-10C->L3(I+J-1)
L3(I+J)+C->L3(I+J)
End
End
Disp L3
Disp L3(4)
```

Observed run: `BIGMUL.8xp` displays `{5 3 5 5 0}`, then `5`, then `Done`.
The trace hits nested `For(` loop parsing, list element reads/stores, `_FPMult`,
`_FPAdd`, `_FPSub`, `_GetLToOP1`, and `_PutToL`. **[confirmed]**

The invariant is that each inner-loop step normalizes one result cell
`L3(I+J-1)` and carries into the next cell. This is still base-10 arithmetic,
so it favors trace readability over speed. A larger base reduces the number of
digits but makes the carry path and display conversion heavier.

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
trace hits `blockmatch_end_else`, `parse_scan_tokens`, `eval_stmt_entry`,
parser refill/advance paths, `_Disp`, and the same list read/write helpers used
by `BIGADD`. **[confirmed]**

Performance notes: this version scans all edges for every visited node, so it is
easy to understand but O(VE) in BASIC-level work. For larger graphs, keep an
offset table of edge ranges per node, avoid `augment(` in hot loops, and
preallocate stack/visited lists with scalar pointers as this sample does.

The loop maintains three invariants:

- `L3(V)=1` means node `V` has already been displayed and expanded.
- `L4(1..P)` is the pending stack, with `L4(P)` popped next.
- Edges are scanned from left to right, so pushing node `2` and then node `3`
  makes node `3` display before node `2`.

The trace cost follows those invariants. Every `While` and nested `If Then`
forces the interpreter to scan for block boundaries (`blockmatch_end_else`,
`parse_scan_tokens`), and every `L1(E)`/`L2(E)` access goes through VAT lookup
and list-element address calculation. Precomputed adjacency ranges reduce both
the number of edge scans and the number of interpreted branch scans.

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

### Cooperative ASM-directed BASIC callback

The run-confirmed way to let ASM choose a BASIC continuation is to keep BASIC in
charge of the program call. `ASMSIG.8xp` sets `Ans` to `1` and returns:

```asm
rst 28h
.dw 419Bh         ; _OP1Set1
rst 28h
.dw 4ABFh         ; _StoAns
ret
```

The BASIC wrapper then branches on `Ans` and performs the ordinary `prgmNAME`
call:

```ti-basic
Disp "BEFORE"
Asm(prgmASMSIG)
If Ans
prgmZZBASIC
Disp "AFTER"
```

with target:

```ti-basic
Disp "CALLED"
```

Observed run: `ASMBRIDG.8xp`, `ASMSIG.8xp`, and `ZZBASIC.8xp` display
`BEFORE`, `CALLED`, `AFTER`, then `Done`. The trace hits the `AsmPrgm` payload
at `ram:9D95`, `_OP1Set1` (`00:1B38`), `_StoAns` (`38:6251`), `_AnsName`
(`38:74B7`) while evaluating `If Ans`, and then the normal BASIC program-body
path for `prgmZZBASIC` (`38:6910` -> `38:6914` -> `38:778F`). **[confirmed]**

This is a callback convention, not a direct jump from ASM into a BASIC body.
The ASM side communicates a return code through `Ans`; BASIC owns the parser
state, performs the `prgm` call, and resumes after the target returns.

For a numeric return value without a BASIC callback, `ASMVAL.8xp` stores `2` in
`Ans`:

```asm
rst 28h
.dw 41A7h         ; _OP1Set2
rst 28h
.dw 4ABFh         ; _StoAns
ret
```

The wrapper consumes it as an ordinary BASIC value:

```ti-basic
Asm(prgmASMVAL)
Ans+3->A
Disp A
```

Observed run: `ASMRTN.8xp` and `ASMVAL.8xp` display `5`, then `Done`. The trace
hits `ram:9D95`, `_OP1Set2` (`00:1B50`), `_StoAns` (`38:6251`), `_AnsName`,
`_FPAdd`, and `_Disp`; the smoke runner also checks the final-frame result and
`Done` regions. **[confirmed]**

| Direction | Confirmed mechanism | Caveat |
|-----------|---------------------|--------|
| BASIC -> ASM | `Asm(prgmNAME)` parses `prgmNAME`, bcalls `_ExecutePrgm`, copies the `AsmPrgm` payload, then jumps through `ram:9D95`. | The payload runs in the calculator OS process; a bad payload can corrupt interpreter state. |
| BASIC -> BASIC | `prgmNAME` enters the page-38 parser/VAT/body evaluator path and `Return` resumes the caller. | There is no local frame; variables, lists, and `Ans` are shared. |
| ASM -> BASIC callback | ASM stores a signal/result such as `Ans=1`, returns, and the BASIC wrapper conditionally runs `prgmNAME`. | BASIC must own the actual `prgm` call; this is cooperative, not an arbitrary ASM bcall into BASIC. |
| ASM -> BASIC value return | ASM stores a numeric result in `Ans` with `_StoAns`; BASIC resumes and evaluates `Ans`. | This returns data to BASIC, not control into a BASIC program body. |
| ASM -> VAT lookup | An `AsmPrgm` can build `OP1={ProgObj,"NAME"}` and bcall `_ChkFindSym`. | Lookup is not execution. |
| Direct ASM -> BASIC | No working public bcall sequence is proven in this repo. | `_Find_Parse_Formula` reached `ERR:UNDEFINED`; `_ParseInpLastEnt` reached `ERR:INVALID`; forced-command/edit-buffer probes did not call the target BASIC program. |

### ASM to BASIC

The inverse direction is not yet run-confirmed in this repo. Two easy-looking
bcalls are not that entry point:

- `_ExecutePrgm` is the `AsmPrgm` executor reached by `Asm(prgmNAME)`, not a
  general "run a BASIC program" entry.
- `_ExecuteNewPrgm` (`4C3C`, target `00:265F`) is not a drop-in BASIC runner
  from an arbitrary `AsmPrgm` either. It expects more OS state than just a name
  pointer.
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

`_ParseInpLastEnt` (`4B07`, target `38:5984`) is a useful negative probe because
it sits immediately before `_ParseInp` and the SDK describes it as a parser
variant. A temporary payload that again built `OP1={ProgObj,"ZZBASIC"}` and
bcalls `_ParseInpLastEnt` reached `_ParseInpLastEnt`, `_ParseInp` (`38:5987`),
`parseinp_find_setup` (`38:5B2B`), `findsym_scan`, `parse_init`, and
`eval_stmt_entry`, but the final screen was `ERR:INVALID` / `Goto`; it never
displayed `CALLED`. Static disassembly explains the mismatch: after resolving
the OP1-named object, `_ParseInp` continues through parser setup that expects a
live parser/FPS call-frame shape. It is not a general "run this token stream"
ABI for an arbitrary `AsmPrgm`. **[confirmed]**

The homescreen command/edit-buffer route is also not a safe callable ABI. A
temporary payload that did only:

```asm
ld a,05h          ; kEnter
rst 28h
.dw 402Ah         ; _JForceCmd
ret
```

entered `_JForceCmd` (`00:0747`) but never returned to the BASIC wrapper's
`Disp "AFTER"` statement. The final screen showed repeated `BEFORE`/`Done`
lines, and the trace hit `ram:0747` and `ram:9D95` repeatedly. The disassembly
explains why: `_JForceCmd` reloads `SP` from `85BC` before dispatching the
forced key, discarding the `AsmPrgm` caller's stack. **[confirmed]**

Two edit-buffer variants narrow that path further. A payload that bcalls
`_PutTokString` (`4960`, target `06:46FD`) for the token bytes
`5F 5A 5A 42 41 53 49 43` (`prgmZZBASIC`) returns to the wrapper and reaches
`Disp "AFTER"`, but it only renders/inserts token text; `ZZBASIC` does
not run. Combining those `_PutTokString` calls with `_JForceCmd(kEnter)` hits
both `_PutTokString` and `_JForceCmd`, then repeats the wrapper/inserted text
through the command loop; it still never displays `CALLED` from `ZZBASIC`.
`_rclToQueue` (`49B4`, target `06:5F29`) is a related editor queue helper, but
its ROM path depends on an already-open edit buffer (`editCursor`/`editTail`)
and the `rclFlag.enableQueue` state; it does not create a BASIC program call
frame. **[confirmed probes; `_rclToQueue` role from disassembly]**

`_ExecuteNewPrgm` is the remaining tempting name, but temporary probes reject it
as a public ASM-to-BASIC call path. A payload that sets `OP1` to `ProgObj`
(`05`), points `HL` at the zero-terminated name `ZZBASIC`, and bcalls `4C3C`
enters `_ExecuteNewPrgm` (`00:265F`) and `findsym_scan`, then ends at
`ERR:SYNTAX`; `ZZBASIC` never displays `CALLED`. Repeating the test with
`ZZBASIC` loaded as `ProtProgObj` (`06`) and `OP1=06` gets farther: the trace
hits `_ExecuteNewPrgm`, the copy tail at `00:268A`, and the jump at `00:268F`.
It still ends at `ERR:SYNTAX` and never runs the target body. That makes
`_ExecuteNewPrgm` another stateful OS helper, not a standalone program executor
ABI for `AsmPrgm` payloads. **[confirmed]**

The current open item is therefore precise: trace a small ASM payload that
successfully invokes a BASIC program, identify the required parser/VAT/error
state, and compare it to the rejected public routes above plus both confirmed
paths: `Asm(` -> `_ExecutePrgm` -> `ram:9D95`, and BASIC `prgmNAME` ->
`38:6914`/`38:778F` program-body evaluation.
