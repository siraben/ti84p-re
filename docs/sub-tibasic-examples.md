# TI-BASIC examples and ASM interop

These trace-backed examples connect source-level choices to the interpreter
paths documented in [TI-BASIC execution](sub-tibasic.md). The page also records
how a RAM assembly program calls a BASIC program with the public `_ParseInp`
bcall and returns to its BASIC wrapper.

## Trace-backed examples

| Pattern | Trace evidence | Practical rule |
|---------|----------------|----------------|
| Straight-line display (`HELLO`) | page-38 statement parse plus `_Disp` | Fine for status text; avoid using `Disp` as a frame loop. |
| Prompted arithmetic (`FACTOR`) | loop-body reseed, FP multiply, display | Keep loop bodies short; store loop-invariant values before `For(`. |
| List built-ins (`DATA`) | `sum(` reaches `list_fold_dispatch` | Prefer built-ins when one parser setup can cover many elements. |
| Text animation (`ANIMTXT`) | `Output(` plus LCD text paths on every loop | Precompute positions/strings and update the smallest region possible. |
| Graph drawing (`GRAPHV`) | primitives and `_PDspGrph` update graph state | Keep graph-oriented output together; individual DRAW commands can refresh the display. |
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

Graph commands share `plotSScreen` and graph coordinates. Individual DRAW
handlers also call `_PDspGrph`; placing several before `DispGraph` does not
establish that the LCD is updated only once.

Text animation and graph-buffer animation have different costs. `Output(` keeps
the home/text display model active and pays row/column formatting on every
iteration. Graph-buffer animation pays coordinate conversion, pixel primitive
work, and display updates through the DRAW handlers and `DispGraph`.
Avoid alternating graph primitives with home-screen output inside the same
hot loop when the desired output is one graph view.

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

| Node | DFS value | Graph-coordinate center | Label position |
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
`store_list_elem*`) plus `_FPDiv`, `_FPAdd`, `_FPSub`, and
`_FPMult`. [confirmed]

Performance notes: this is intentionally simple, but it is parser-heavy. For a
general routine, cache `dim(L1)` and `dim(L2)` before the loop, avoid repeated
list indexing when a digit is reused, and use a larger base only if you can
tolerate more carry and display conversion work.

For a reusable arbitrary-precision add routine, treat `L1` and `L2` as
little-endian digit arrays and compute the loop bound from list lengths:

This illustrative variant assumes nonempty lists containing integer digits
`0`–`9` and room for an `N+1`-element destination. The observed run above
belongs to the fixed-size `BIGADD` fixture, not this generalized listing.

```ti-basic
dim(L1)->N
If dim(L2)>N
dim(L2)->N
N+1->dim(L3)
Fill(0,L3)
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
If C=0
N->dim(L3)
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

The ROM setup and cleanup sites are:
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

In this example, the ASM result selects a continuation in BASIC. `ASMSIG.8xp` sets `Ans` to `1` and returns:

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
| ASM → BASIC callback | ASM stores a signal/result such as `Ans=1`, returns, and the BASIC wrapper conditionally runs `prgmNAME`. | In this wrapper, BASIC owns the `prgm` call. |
| ASM → BASIC value return | ASM stores a numeric result in `Ans` with `_StoAns`; BASIC resumes and evaluates `Ans`. | This returns data to BASIC, not control into a BASIC program body. |
| ASM → VAT lookup | `ASMFIND` builds `OP1={ProgObj,"ZZBASIC"}` and bcalls `_ChkFindSym`. | Lookup is not execution; the wrapper returns and `ZZBASIC` does not display `CALLED`. |
| Direct ASM → BASIC | A RAM ASM caller puts the program name in OP1 and bcalls `_ParseInp`. | The paired TilEm run covers a one-statement BASIC target and normal return. |

### ASM to BASIC

Texas Instruments documents `_ParseInp` (`4A9Bh`, `38:5987`) as taking the
name of an equation or a program in OP1. The SDK specifies a result for an
equation and no return value for a program. The worked example evaluates
`Y1`. [standard] [TI-83 Plus System Routines, “ParseInp”](https://education.ti.com/html/eguides/discontinued/computer-software/EN/SDK-TI-83-System-Routines_EN.pdf)

On OS 2.55MP, a RAM assembly program can call a BASIC program directly
through `_ParseInp` and return to its BASIC wrapper. In two TilEm runs on
the canonical retail image, `ASMPARSE` displays `BEFORE`, runs
`Asm(prgmZZPARSE)`, and displays `AFTER`. The ASM payload places the name
`{ProgObj,"ZZBASIC"}` in OP1. Only the bcall operand differs between runs.
[confirmed]

| Bcall operand | Target selected | Final LCD |
|---------------|-----------------|-----------|
| `4A9Bh` (`_ParseInp`) | `ZZBASIC` in RAM, containing `Disp "CALLED"` | `BEFORE`, `CALLED`, `AFTER`, `Done` |
| `4B07h` (`_ParseInpLastEnt`) | The system's last-entry program | `ERR:INVALID`, `1:Quit`, `2:Goto` |

The direct case covers normal return from this one-statement program.
Interactive commands, archived targets, and error unwinding require separate
caller tests. The paired fixtures, ROM and emulator identities, trace hashes,
and LCD checks are in `tools/probes/tibasic-parseinp/result.json`. The replay
requires ImageMagick and a TilEm build that transfers positional program files
before its headless macro runs. The recorded binary includes a local patch
for that transfer. Run from the repository root with a fresh output directory.

```sh
PYTHONPATH=tools python3 tools/probes/tibasic-parseinp/compare.py \
  --tilem "$TILEM" --rom "$ROM" --out-dir /tmp/ti84-parseinp-comparison
```

A published Flash App caller sets `progExecuting` and `cmdExec`, installs an
error handler, and calls `_ParseInp` with the program name in OP1. It also
manages the App's homescreen hook. This source describes a Flash App caller.
The paired TilEm fixtures exercise the separate RAM caller described above.
[Kerm Martian and Dan E., “RunBASICProgram”](https://www.cemetech.net/forum/viewtopic.php?t=1449)

Four public routines serve other roles:

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
`38:778F`, and lets `Return` unwind to the caller. [confirmed]

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
`38:6910` executes <code>XOR A</code><br><code>CALL 6A15</code> before entering the evaluator. The following probe copies the target's name and parser bounds and enters
that private address directly.

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
`2:Goto`. At `38:5984`, `CALL 1F23h` replaces the OP1 name with `05 23 00`, the system's last-entry program. Control then falls through to
`_ParseInp` at `38:5987`. This run therefore exercises the last-entry
program. A direct bcall to `4A9Bh` skips the name replacement. [confirmed]

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

The OS 2.55MP main bcall table spans `4000h`–`54ACh`. All 1,765 slots
precede the code at `3B:54AF`, and 98 target page `38`. The 1 MiB retail
image also contains 825 raw matches for the cross-page call prefix
`CD 09 2B`. Neither the table slots nor the address/page triples following
those byte matches point to `38:59C5`, `38:6910`, `38:6914`, or `38:778F`.
A raw prefix can occur in data. [confirmed]

A table entry can reach these addresses through ordinary instructions.
Starting at `_ParseInp` (`38:5987`), the fallthrough at `38:59C2` leads to
`38:59C5`. The conditional jump at `38:59CE` can then reach `38:6910`
and the call to `38:778F` at `38:6914`. The conditions on that path depend
on parser state. Six other table entries with paths through this parser
region appear below. [confirmed]

| Bcall | Target | Role |
|-------|--------|------|
| `_FetchQuotedString` (`4AF8`) | `38:5E11` | Consume a quoted parser operand. |
| `_ParseNameTokens` (`4AFE`) | `38:5F4D` | Parse name tokens within an existing expression. |
| `_ExecClassCToken` (`50D7`) | `38:7010` | Dispatch an existing class-C token. |
| `_ExecClass1Token` (`5215`) | `38:6FEC` | Dispatch an existing class-1 token. |
| `_HandleMathTokenParse` (`5218`) | `38:6963` | Continue an existing math-token parse. |
| `_RestartParseOP1Result` (`521E`) | `38:5CA7` | Resume parsing with an existing OP1 result. |

The linear disassembly from `38:4100` through `38:77FF` has two direct
predecessors of `38:59C5`, the jump at `38:5C03` and the fallthrough at
`38:59C2`. The two direct predecessors of `38:6910` are the conditional
jump at `38:59CE` and the fallthrough at `38:690D`. The instruction at
`38:6911` falls through to `38:6914`, the only direct call site for
`38:778F` in this range. [confirmed]

The separate semantic-candidate experiments cover `_ExecutePrgm`,
`_ExecuteNewPrgm`, `_SetParseVarProg`, `_ParsePrgmName`,
`_ParseInpLastEnt`, `_Find_Parse_Formula`, `_JForceCmd`, `_PutTokString`, and
`_rclToQueue`. The tested callers execute compiled ASM, change parser or editor state, or
produce the errors described above. The separate direct `4A9Bh` case above executes the named program and returns. [confirmed]

The census checks table entries, raw byte patterns, and direct branches. It
does not establish complete reachability through computed dispatch, routines
outside that region, or callers with different state. The failed candidate
experiments therefore leave other private calling sequences open.

#### Private-frame comparison evidence gap

The reported T042 comparison used an ASM payload named `ZZFRAME` and a
BASIC target named `ZZGOOD`. The cited manifest
(`tools/probes/scratch-guard/asm-basic-frames-tilem.json`) and both fixtures
are missing from the repository. The error attributed to the private call at `38:59C5` and the claimed
restoration of the caller's state therefore remain unverified. The separate `ASMBRIDG` fixture above exercises the cooperative
`Ans` route.
