# TI-BASIC examples and ASM interop

These trace-backed examples connect source-level choices to the interpreter
paths documented in [TI-BASIC execution](sub-tibasic.md). The page also records
the supported BASIC/ASM boundary and the tested failures around direct
ASM-initiated BASIC execution.

## Trace-backed examples

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

The table is intentionally selective. The complete fixture and evidence list
lives on [the dynamic tracing page](sub-tibasic-tracing.md), where it can be
audited without interrupting the programming guidance.

## Patterns tied to interpreter cost

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
(`03:4AF2`), `_Disp` (`37:51D3`), and LCD text routines. [confirmed]

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
the page-38 argument parser. [confirmed]

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
page-38 statement evaluation. [confirmed]

The performance lesson is to separate graph data from graph drawing. Keep edge
lists and traversal state in lists, but convert them to pixels in a single draw
phase instead of interleaving traversal, display, and recalculation.

`GRAPHLST.8xp` makes that separation explicit. It stores edge endpoint
coordinates in `L1`–`L4` and node centers in `L5`/`L6`, then draws edges and
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
coordinates. [confirmed]

### Subprogram interfaces

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
`_Disp`. [confirmed]

The full smoke trace also hits `_ParseInpLastEnt`/`_ParseInp` once while the
homescreen evaluates the initial `prgmCALLSUB` command selected by the macro.
That launch parse is not the same as the callee transition. The repeated
subprogram body path is the private `38:6910` → `38:6914` → `38:778F`
sequence, reached after `TIBasicParserState` (`0x9652`) and the adjacent stack
pointers have been populated:

| RAM state | Address | Role in the private parser frame |
|-----------|---------|----------------------------------|
| `TIBasicParserState.basic_prog` | `0x9652` | current OP1-style program/object name |
| `TIBasicParserState.basic_start` | `0x965B` | first token byte after the stored program size word |
| `TIBasicParserState.next_parse_byte` | `0x965D` | current parser cursor |
| `TIBasicParserState.basic_end` | `0x965F` | parser end pointer |
| `TIBasicParserState.num_arguments` | `0x9661` | argument count/state byte used by parser helpers |
| `chkDelPtr3` / `chkDelPtr4` | `0x981C` / `0x981E` | temporary VAT/data pointers used during name and object setup |
| `FPS` / `OPS` / `pTemp` / `progPtr` | `0x9824` / `0x9828` / `0x982E` / `0x9830` | live FP/temp/program storage bounds |

There is no local variable frame for BASIC programs. A subprogram that uses `A`
modifies the caller's `A`. For reusable routines, document which variables are
inputs, scratch, and outputs.

| ABI part | Practical convention | Trace evidence |
|----------|----------------------|----------------|
| Inputs | Scalars, lists, and `Ans` are shared across caller and callee. The caller stores them before `prgmNAME`. | `CALLSUB` stores `A`; `ABICALL` seeds `L1` and `Ans`. |
| Outputs | The callee stores results back to globals, list elements, or `Ans`. | `SUBRT` increments shared `A`; `ABISUB` writes `A`, `L1(3)`, and `Ans`. |
| Scratch | No automatic save/restore exists. Routines must document scratch variables. | The VAT and parser state are shared across caller and callee. |
| Return/Stop | `Return` exits the callee and resumes the caller. `Stop` terminates the whole program chain. | `SUBRT` returns to `CALLSUB`, which then runs `Disp A`; `STOPSUB` stops `CALLSTOP` before caller text `AFTER` can display. |
| Parser state | `prgmNAME` runs with private parser/FPS state already set up by BASIC. | The callee path reaches `38:6910` → `38:6914` → `38:778F`. |

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
`_AnsName`, and `store_list_elem`. [confirmed]

`CALLSTOP.8xp` and `STOPSUB.8xp` cover the non-returning branch:

```ti-basic
Disp "BEFORE"
prgmSTOPSUB
Disp "AFTER"
```

with callee:

```ti-basic
Disp "STOP"
Stop
```

Observed run: `CALLSTOP.8xp` and `STOPSUB.8xp` display `BEFORE`, then `STOP`,
then `Done`; `AFTER` never appears. The smoke runner checks the `BEFORE`,
`STOP`, and `Done` regions and also checks a low-pixel region where `AFTER`
would be drawn if the caller resumed. The trace reaches `stmt_eval_body_entry`,
`call_eval_eqn_recursive`, and `_Disp`. This confirms that `Stop` in a callee
terminates the whole BASIC program chain instead of returning to the caller. [confirmed]

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
`_FPMult`. [confirmed]

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
`_FPAdd`, `_FPSub`, `_GetLToOP1`, and `_PutToL`. [confirmed]

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
by `BIGADD`. [confirmed]

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
compile or copy the `AsmPrgm` body and hand off through `07:57B4`, execute the
payload byte at `ram:9D95` with opcode `C9h`, and return to BASIC. [confirmed]

`tools/asm_execution.py` byte-pins the complete setup and cleanup path:
[confirmed]

| Address | Operation |
|---------|-----------|
| `07:5758` | Query application restriction selector `3`; reject a disallowed caller. |
| `07:5762` | Resolve the program named by `OP1`; reject an archived data page. |
| `07:5766` | Distinguish compiled marker `BB 6D` from hexadecimal `AsmPrgm` source. |
| `07:577B` | Reject a machine image larger than `0x2000` bytes. |
| `07:5785` | Insert an exact-sized gap at `ram:9D95` and copy compiled bytes. |
| `07:57D4` | For source form, call `_GetAsmSize`, allocate the result, and call `_SquishPrgm`. |
| `07:5791` | Store the allocation length in `asm_prgm_size` (`ram:89EC`). |
| `07:57B1` | Install the error cleanup at `07:5800`. |
| `07:57B4` | Call the `JP ram:9D95` trampoline at `07:57FD`. |
| `07:57C4` | Clear the length and delete the allocation after a normal return. |
| `07:5800` | Restore speed state, delete the allocation, and resume error handling. |

`BB 6C` is the hexadecimal source token. It takes the source/squish path at
`07:57D4`; `BB 6D` identifies an already compiled body. The source pointer is
adjusted after `_InsertMem` because the source object moves when the gap opens.
Normal and error exits therefore delete the recorded allocation length rather
than a fixed-size region. [confirmed]

Practical convention: pass data through OS variables or known RAM locations,
validate inputs on the BASIC side, and make the ASM payload return normally with
`RET` unless it intentionally transfers control elsewhere.

### Cooperative ASM-directed BASIC callback

The run-confirmed way to let ASM choose a BASIC continuation is to keep BASIC in
charge of the program call. `ASMSIG.8xp` sets `Ans` to `1` and returns:

```z80
RST 28h
.dw 419Bh         ; _OP1Set1
RST 28h
.dw 4ABFh         ; _StoAns
RET
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
at `userMem`, `_OP1Set1` (`00:1B38`), `_StoAns` (`38:6251`), `_AnsName`
(`38:74B7`) while evaluating `If Ans`, and then the normal BASIC program-body
path for `prgmZZBASIC` (`38:6910` → `38:6914` → `38:778F`). [confirmed]

This is a callback convention, not a direct jump from ASM into a BASIC body.
The ASM side communicates a return code through `Ans`; BASIC owns the parser
state, performs the `prgm` call, and resumes after the target returns.

For a numeric return value without a BASIC callback, `ASMVAL.8xp` stores `2` in
`Ans`:

```z80
RST 28h
.dw 41A7h         ; _OP1Set2
RST 28h
.dw 4ABFh         ; _StoAns
RET
```

The wrapper consumes it as an ordinary BASIC value:

```ti-basic
Asm(prgmASMVAL)
Ans+3->A
Disp A
```

Observed run: `ASMRTN.8xp` and `ASMVAL.8xp` display `5`, then `Done`. The trace
hits `userMem`, `_OP1Set2` (`00:1B50`), `_StoAns` (`38:6251`), `_AnsName`,
`_FPAdd`, and `_Disp`; the smoke runner also checks the final-frame result and
`Done` regions. [confirmed]

| Direction | Confirmed mechanism | Caveat |
|-----------|---------------------|--------|
| BASIC → ASM | `Asm(prgmNAME)` parses `prgmNAME`, bcalls `_ExecutePrgm`, copies the `AsmPrgm` payload, then jumps through `userMem`. | The payload runs in the calculator OS process; a bad payload can corrupt interpreter state. |
| BASIC → BASIC | `prgmNAME` enters the page-38 parser/VAT/body evaluator path and `Return` resumes the caller. | There is no local frame; variables, lists, and `Ans` are shared. |
| ASM → BASIC callback | ASM stores a signal/result such as `Ans=1`, returns, and the BASIC wrapper conditionally runs `prgmNAME`. | BASIC must own the actual `prgm` call; this is cooperative, not an arbitrary ASM bcall into BASIC. |
| ASM → BASIC value return | ASM stores a numeric result in `Ans` with `_StoAns`; BASIC resumes and evaluates `Ans`. | This returns data to BASIC, not control into a BASIC program body. |
| ASM → VAT lookup | `ASMFIND` builds `OP1={ProgObj,"ZZBASIC"}` and bcalls `_ChkFindSym`. | Lookup is not execution; the wrapper returns and `ZZBASIC` does not display `CALLED`. |
| Direct ASM → BASIC | The bounded OS 2.55MP census finds no distinct callable ABI. | A private construction must reproduce the ordinary parser, VAT, FPS/OPS, error, and return records; supported applications should return to a BASIC-owned `prgmNAME` call. |

### ASM to BASIC

OS 2.55MP has no distinct public or private-funnel ABI for calling a BASIC
program from arbitrary ASM within the bounded search described below. ASM can
enter private parser addresses after constructing their state, but the required
parser, VAT, FPS, OPS, error, and return records are the ordinary BASIC caller
frame. Constructing all of them duplicates that caller rather than invoking a
separate ABI. [confirmed]

Four apparent public candidates are not that entry point:

- `_ExecutePrgm` is the `AsmPrgm` executor reached by `Asm(prgmNAME)`, not a
  general "run a BASIC program" entry.
- `_ExecuteNewPrgm` (`4C3C`, target `00:265F`) is not a drop-in BASIC runner
  from an arbitrary `AsmPrgm` either. It expects OS state beyond a name
  pointer.
- `_ParsePrgmName` (`4E82`, target `38:40D4`) only consumes a `prgmNAME` token
  from the current parser cursor and builds the name object used by `Asm(`.
- `_SetParseVarProg` (`4C5A`, target `3B:73F5`) preserves `AF`, stores `06h`
  at `basic_prog` (`ram:9652`), and returns. It constructs none of the caller
  frame.

The confirmed BASIC subprogram path is different: the `CALLSUB`/`SUBRT` trace
does not hit `_ParsePrgmName`, `_ExecutePrgm`, `_Find_Parse_Formula`, or
`_SetParseVarProg`. It resolves the program name through the page-38
parser/VAT path, enters the program-body evaluator at `38:6914` →
`38:778F`, and lets `Return` unwind to the caller. Calling that same machinery
from arbitrary ASM requires more than loading OP1 and bcalling a single public
entry; it needs the same parser cursor, stack, error, and run-state setup that a
live BASIC caller already has. [confirmed]

A typed two-program trace of `prgmPP` calling `prgmOO` captures the live parser
frame at each `38:6914` entry through shadow-memory replay. The reproduction
macro is `tools/macros/run-callsub-typed.macro`.

| Field | Observed value at callee entry |
|-------|-------------------------------|
| `basic_prog` (`0x9652`) | `05h`, two encoded name bytes, six zeros |
| `basic_start` (`0x965B`) | callee body start (first token) |
| `next_parse_byte` (`0x965D`) | equals start before execution; end when finished |
| `basic_end` (`0x965F`) | start + body size |
| state byte (`0x9661`) | `01h` |
| `FPS` / `OPS` pointers | valid live pointers (`0x9E94` / `0xFCB1` on one entry) |
| gate bits | `BIT 0,(IY+28h)` and `BIT 7,(IY+48h)` are both zero (`IY=0x89F0`; bytes at `0x8A18` and `0x8A38`) |

Both gate bits read zero in the working path. The private callee transition at
`38:6910` executes <code>XOR A</code><br><code>CALL 6A15</code> before entering the evaluator. These
observations suggest that an ASM payload must locate the target through
`_ChkFindSym` into OP1, copy the name header to `0x9652`, point
`start`/`cursor` at `_ChkFindSym`'s data pointer plus two (past the size word),
set `end` = start + size, store `01h` at `0x9661`, ensure the FPS/OPS bounds
are sane, bank page `38` into port `0x06`, and enter `38:6910`. No identified
public bcall performs this setup. This proposed hand-built state transplant
also accounts for the parser-frame failures in the negative probes
(`ZZFIND`/`ZZFORM`/`ZZPARSE`). [hypothesis]

The generated negative probe consists of `OO.8xp`, `ZZRUN.8xp`, and
`ZZRUNWR.8xp`. `ZZRUN` is an 81-byte payload targeting `prgmOO`; it returns
immediately if `_ChkFindSym` sets carry. `ZZRUNWR` contains the one-line
`Asm(prgmZZRUN)` launcher.

A link-loaded run resolves `OO` through `_ChkFindSym` with `DE=0x9E76`, then
sets the parser interval to `0x9E78`–`0x9E7F` and enters `38:6910`. The trace
reaches `38:6914` and `38:778F`, walks the target body, and terminates at
`_ErrSyntax` (`ram:2700`) with the parser cursor at `0x9E7C`. The final frame
shows `ERR:SYNTAX`. An otherwise equivalent 80-byte layout without the
`_ChkFindSym` carry guard instead ended at `_ErrArgument` (`ram:2711`). The
layout-sensitive error indicates that the copied name and cursor interval do not
reproduce the native BASIC call frame. [confirmed]

`ASMFIND.8xp` and `ZZFIND.8xp` make the VAT lookup boundary reproducible. The
wrapper displays `BEFORE`, runs `Asm(prgmZZFIND)`, and displays `AFTER`. The
payload builds `OP1={ProgObj,"ZZBASIC"}` and bcalls `_ChkFindSym` (`42F1`):

```z80
LD HL,name
LD DE,8478h        ; OP1
LD BC,0009h
LDIR
RST 28h
.dw 42F1h          ; _ChkFindSym
RET
name: .db 05h,"ZZBASIC",00h
```

Observed run: `ASMFIND.8xp`, `ZZFIND.8xp`, and `ZZBASIC.8xp` display `BEFORE`,
`AFTER`, and `Done`; `ZZBASIC`'s `CALLED` text does not display. The trace hits
`userMem` and `findsym_scan`, and the smoke runner checks the wrapper output
and a low-pixel region where an unexpected third line would appear. This proves
ASM-side VAT lookup from an `AsmPrgm` context, not BASIC program execution. [confirmed]

Generated negative fixtures make the execution boundary sharper.

`ASMFORM.8xp` and `ZZFORM.8xp` make the `_Find_Parse_Formula` negative probe
reproducible. The payload is the same OP1-name setup as `ZZFIND`, but it bcalls
`_Find_Parse_Formula` (`4AF2`, target `38:758A`) instead of `_ChkFindSym`.
Observed run: the trace reaches `userMem`, `_Find_Parse_Formula`,
`parse_init_findsym`, `findsym_scan`, and `eval_stmt_entry`; the final screen is
`ERR:UNDEFINED` with `1:Quit` and `2:Goto`. `ZZBASIC` never displays `CALLED`.
That failed run confirms `_Find_Parse_Formula` is not a drop-in BASIC program
executor from an arbitrary `AsmPrgm` context. [confirmed]

`ASMPARSE.8xp` and `ZZPARSE.8xp` make the `_ParseInpLastEnt` negative probe
reproducible. The payload is the same OP1-name setup as `ZZFIND`, but it bcalls
`_ParseInpLastEnt` (`4B07`, target `38:5984`) instead of `_ChkFindSym`.
Observed run: the trace reaches `_ParseInpLastEnt`, `_ParseInp` (`38:5987`),
`parseinp_find_setup` (`38:5B2B`), `findsym_scan`, `parse_init`, and
`eval_stmt_entry`; the final screen is `ERR:INVALID` with `1:Quit` and
`2:Goto`. `ZZBASIC` never displays `CALLED`. Static disassembly explains the
mismatch: after resolving the OP1-named object, `_ParseInp` continues through
parser setup that expects a live parser/FPS call-frame shape. It is not a
general "run this token stream" ABI for an arbitrary `AsmPrgm`. [confirmed]

The homescreen command/edit-buffer route is also not a safe callable ABI. A
payload that did only:

```z80
LD A,05h          ; kEnter
RST 28h
.dw 402Ah         ; _JForceCmd
RET
```

entered `_JForceCmd` (`00:0747`) but never returned to the BASIC wrapper's
`Disp "AFTER"` statement. The final screen showed repeated `BEFORE`/`Done`
lines, and the trace hit `ram:0747` and `userMem` repeatedly. The disassembly
explains why: `_JForceCmd` reloads `SP` from `85BC` before dispatching the
forced key, discarding the `AsmPrgm` caller's stack. [confirmed]

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
frame. [confirmed]

`_ExecuteNewPrgm` (`00:265F`) is not a public ASM-to-BASIC entry — a payload
that sets `OP1` to `ProgObj` (`05`), points `HL` at the zero-terminated name
`ZZBASIC`, and bcalls `4C3C` enters it and `findsym_scan`, then ends at
`ERR:SYNTAX` [confirmed]; `ZZBASIC` never displays `CALLED`. Repeating the test with
`ZZBASIC` loaded as `ProtProgObj` (`06`) and `OP1=06` gets farther: the trace
hits `_ExecuteNewPrgm`, the copy tail at `00:268A`, and the jump at `00:268F`.
It still ends at `ERR:SYNTAX` and never runs the target body. That makes
`_ExecuteNewPrgm` another stateful OS helper, not a standalone program executor
ABI for `AsmPrgm` payloads. [confirmed]

#### Bounded ABI census

The bounded census covers:

- all 1,732 three-byte main bcall slots from `4000h` through `5449h`;
- all 825 raw `CALL 2B09h` cross-page-call descriptors in the 1 MiB ROM; and
- every direct control-flow edge in the disassembled page-38 parser region
  `38:4100`–`38:77FF`.

None of the 1,732 public slots and none of the 825 cross-page descriptors
targets `38:59C5`, `38:6910`, `38:6914`, or `38:778F`. Of the 95 public slots
whose target is on page `38`, only six land in the conservative 613-instruction
direct reverse slice of `38:778F`:

| Bcall | Target | Role |
|-------|--------|------|
| `_FetchQuotedString` (`4AF8`) | `38:5E11` | Consume a quoted parser operand. |
| `_ParseNameTokens` (`4AFE`) | `38:5F4D` | Parse name tokens within an existing expression. |
| `_ExecClassCToken` (`50D7`) | `38:7010` | Dispatch an existing class-C token. |
| `_ExecClass1Token` (`5215`) | `38:6FEC` | Dispatch an existing class-1 token. |
| `_HandleMathTokenParse` (`5218`) | `38:6963` | Continue an existing math-token parse. |
| `_RestartParseOP1Result` (`521E`) | `38:5CA7` | Resume parsing with an existing OP1 result. |

These are mid-parser helpers, not frame constructors. The exact incoming-edge
census further narrows the private funnel: `38:59C5` has the local
`38:5C03` jump and the `38:59C2` fallthrough; `38:6910` has the conditional
`38:59CE` jump and `38:690D` fallthrough; `38:6914` follows `38:6911`; and
only `38:6914` calls `38:778F`. [confirmed]

The separate semantic-candidate experiments cover `_ExecutePrgm`,
`_ExecuteNewPrgm`, `_SetParseVarProg`, `_ParsePrgmName`,
`_ParseInpLastEnt`, `_Find_Parse_Formula`, `_JForceCmd`, `_PutTokString`, and
`_rclToQueue`. They either execute compiled ASM, modify only part of parser or
editor state, or enter the parser with a malformed caller frame. None is a
standalone direct-call ABI. [confirmed]

This is a scoped negative result for the complete public table, standard
cross-page-call descriptors, and the declared page-38 direct graph on OS
2.55MP. It does not claim that manually reproducing every private caller record
cannot execute a token stream; that construction is specifically excluded
because it is a reimplementation of the ordinary BASIC caller, not a distinct
callable ABI.

#### Private-frame comparison

The T042 probe compares an incomplete direct call with the ordinary caller in
one reset-origin TilEm run. `ZZFRAME` saves four state groups before the
experiment: [confirmed]

| Saved group | Range | Contents |
|-------------|-------|----------|
| Parser and name | `0x9652`–`0x9662` | `basic_prog`, parser pointers, and `numArguments` |
| VAT and temporary stacks | `0x981C`–`0x9831` | VAT scratch, FPS, OPS, `pTemp`, and `progPtr` |
| Parser flags | `0x89F0`–`0x8A39` | IY flags read by the page-38 parser |
| Error state | `0x86DD` | prior `errNo` value |

The payload installs a caught-error frame through `_pushErrorHandleR` at
`ram:27DA`, substitutes a token stream containing `prgmZZGOOD`, and calls
`eval_stmt_entry` at `38:59C5`. It reaches the statement entry once, then
raises `E_DataType` before `38:6910`, `38:6914`, or `38:778F`. `_JError`
transfers through `ram:27BB`; the payload restores every saved group before it
stores error code `9` in `Ans`. The combined frame SHA-256 matches before and
after the failed call. [confirmed]

The BASIC wrapper then calls `prgmZZGOOD` normally. That path reaches
`38:59C5` twice and `38:6910`, `38:6914`, and `38:778F` once each, returns
value `2`, and resumes at `AFTER`. The final screen reads `BEFORE`, `9`, `2`,
`AFTER`, and `Done`. [confirmed]

The comparison pins the missing boundary for this construction. Parser
pointers and copied RAM blocks do not create the OPS grammar/type record, FPS
baselines, VAT adoption, and return record consumed before `38:6914`. The
ordinary `prgmNAME` handler creates them. Reproducing all of that state would
duplicate the BASIC caller rather than expose a separate supported ABI.
[confirmed]

`tools/probes/scratch-guard/asm-basic-frames-tilem.json` records the pinned TilEm run,
screen contract, ROM spans, SPASM-ng output, and source/program hashes. The
supported application pattern remains `Asm(` → `_ExecutePrgm` → `ram:9D95`,
return a value through `Ans`, and let BASIC perform `prgmNAME`.
