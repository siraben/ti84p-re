# TI-BASIC dynamic tracing

TI-BASIC behavior in these notes is grounded by generated programs, headless
TilEm runs, resolved instruction coverage, and screen captures. This page is
the book-facing recipe for reproducing those traces; the lower-level tooling
details live in `tools/dynamic-tracing.md`.

## Fixture suite

The fixture generator emits readable source, token bytes, and `.8xp` link files:

```sh
tools/tibasic_samples.py --write-dir tools/tibasic-samples
```

The smoke runner executes the exported programs, records a GIF, extracts the
final frame, resolves trace coverage through `tools/tilem_trace_resolve.py`, and
checks each case's expected anchors:

```sh
TILEM=~/Git/tilem-headless/result/bin/tilem2
tools/tibasic_smoke.py --tilem "$TILEM" --rom tools/rom.bin \
  --out-dir /tmp/tibasic-smoke-full
```

Use `--case NAME` to run a subset, and `--keep-trace` when the raw binary trace
is needed for instruction-level inspection. The runner deletes trace files by
default because several cases produce hundreds of MiB per run.

The full suite passed on 2026-06-07 with the command above against OS 2.55MP and
the local patched TilEm runner. The output directory kept final PNGs, GIFs, and
coverage text for all cases; raw trace files were deleted by default.

The current headless workflow relies on a local TilEm patch that loads command
line `.8xp` files before the macro starts. Without that patch, load the target
programs into calculator RAM first, then run the same macro and resolver steps.

## Operation coverage

| Case | Program(s) | Operations exercised | Anchor examples |
|------|------------|----------------------|-----------------|
| `hello` | `HELLO.8xp` | `ClrHome`, `Disp`, string scan, `Done` | `eval_stmt_entry`, `_Disp` |
| `factorial` | `FACTOR.8xp` | `Prompt`, scalar stores, `For(`/`End`, FP multiply | `_FPMult`, `_Disp` |
| `data` | `DATA.8xp` | list literal, `SortA(`, `cumSum(`, `sum(` | `store_list_elem`, `list_fold_dispatch` |
| `asmcall` | `ASMCALL.8xp` + `ASMRET.8xp` | BASIC `Asm(prgmNAME)` into `AsmPrgm` payload | `_ExecutePrgm`, `ram:9D95` |
| `asmbridge` | `ASMBRIDG.8xp` + `ASMSIG.8xp` + `ZZBASIC.8xp` | ASM return code through `Ans`, BASIC callback | `_OP1Set1`, `_StoAns`, `_AnsName`, `eval_eqn_recursive` |
| `asmreturn` | `ASMRTN.8xp` + `ASMVAL.8xp` | ASM return value through `Ans`, then BASIC arithmetic | `_OP1Set2`, `_StoAns`, `_AnsName`, `_FPAdd` |
| `asmfind` | `ASMFIND.8xp` + `ZZFIND.8xp` + `ZZBASIC.8xp` | ASM-side VAT lookup of a BASIC program without executing it | `ram:9D95`, `findsym_scan`, `_Disp` |
| `asmparse` | `ASMPARSE.8xp` + `ZZPARSE.8xp` + `ZZBASIC.8xp` | ASM parser-entry negative probe ending at `ERR:INVALID` | `_ParseInpLastEnt`, `_ParseInp`, `parseinp_find_setup` |
| `animtext` | `ANIMTXT.8xp` | text placement animation with `Output(` | `_OutputExpr`, `_Disp` |
| `graphviz` | `GRAPHV.8xp` | graph-buffer primitives and `DispGraph` | `_GrBufClr`, `_ILine`, `_IPoint`, `_PDspGrph` |
| `graphdfs` | `GRAPHDFS.8xp` | graph visualization from DFS topology | `_StoSysTok`, `_ILine`, `_IPoint`, `_PDspGrph` |
| `graphlist` | `GRAPHLST.8xp` | list-driven graph visualization from edge/node coordinate lists | `list_var_index`, `_GetLToOP1`, `_ILine`, `_IPoint` |
| `callsub` | `CALLSUB.8xp` + `SUBRT.8xp` | BASIC `prgmNAME`, shared globals, `Return` | `stmt_eval_body_entry`, `call_eval_eqn_recursive` |
| `callabi` | `ABICALL.8xp` + `ABISUB.8xp` | BASIC subprogram ABI through `Ans`, scalar `A`, and list `L1` | `_AnsName`, `store_list_elem`, `eval_eqn_recursive` |
| `callstop` | `CALLSTOP.8xp` + `STOPSUB.8xp` | BASIC subprogram `Stop` terminates the caller chain | `stmt_eval_body_entry`, `call_eval_eqn_recursive`, `_Disp` |
| `bigadd` | `BIGADD.8xp` | list-digit arithmetic and carry propagation | `list_var_index`, `_GetLToOP1`, `_PutToL`, `_FPMult` |
| `bigmul` | `BIGMUL.8xp` | list-digit multiplication, nested loops, carry normalization | `list_var_index`, `_GetLToOP1`, `_PutToL`, `_FPMult` |
| `dfs` | `DFS.8xp` | list-backed stack, nested `While`/`If`/`For` | `blockmatch_end_else`, `parse_scan_tokens`, `eval_stmt_entry` |

The visualization cases also enforce visible output by thresholding the final
frame and comparing it with the first recorded frame. `ANIMTXT`, `GRAPHV`,
`GRAPHDFS`, and `GRAPHLST` must contain at least 100, 100, 200, and 200 dark
pixels respectively, and must change by at least the same number of pixels from
first to final frame. `ANIMTXT` must also produce at least five distinct
captured frames. The smoke runner also checks named crop regions. Visual cases
check home-screen text, graph labels, axes, circle arcs, and node/edge regions.
Text/list cases check important final-screen lines such as `HELLO, WORLD`,
factorial `120`, `DATA` list outputs, `BEFORE`/`CALLED`/`AFTER`, `SUB`,
big-integer digit lists, and the DFS traversal/visited-list output. `ASMRTN`
checks the displayed `5`, `ABICALL` checks the scalar line, mutated list line,
returned `Ans` line, and `Done`, and `CALLSTOP` checks `BEFORE`, `STOP`,
`Done`, and a bounded low-pixel region where caller text `AFTER` would appear.
`ASMFIND` checks the wrapper's `BEFORE`, `AFTER`, and `Done` output plus a
bounded low-pixel region where an unexpected third line would appear.
`ASMPARSE` checks the `ERR:INVALID`, `1:Quit`, and `2:Goto` error-screen
regions.

For the visual graph cases, the 2026-06-07 run measured 212, 619, 466, and 466
dark pixels, with matching first-to-final pixel changes.

## Reading the evidence

Trace anchors prove control reached the relevant ROM path; they do not by
themselves prove the final screen looked right. Use both the coverage file and
the final PNG/GIF for display or graph claims. This distinction matters for
`GRAPHDFS`, where `_ILine` and `_IPoint` coverage only proves drawing routines
ran, while the final frame proves the graph-screen topology is visible.

For parser and calling-convention claims, prefer resolved coverage plus a narrow
routine trace. For example, the BASIC subprogram case uses the private
`38:6910` -> `38:6914` -> `38:778F` body-evaluator path after the top-level
homescreen parse has already seeded parser RAM. That is why the negative
ASM-to-BASIC probes in [TI-BASIC programming patterns](sub-tibasic-programming.md)
are kept as probes rather than fixtures: they reach useful ROM paths, but they
do not display the target BASIC program.

## Related pages

- [TI-BASIC programs](sub-tibasic.md) explains the parser, statement evaluator,
  control flow, display commands, `Asm(`, and `prgmNAME`.
- [TI-BASIC programming patterns](sub-tibasic-programming.md) turns the traces
  into performance and calling-convention guidance.
- [TI-BASIC `For(` optional paren trap](sub-tibasic-for-paren.md) is a focused
  trace study of one parser-performance edge case.
