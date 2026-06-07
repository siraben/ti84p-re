# Dynamic tracing with headless TilEm

Static RE (Ghidra) tells you what *could* run. A headless emulator tells you
what *did* run, with real register and memory state. This guide drives the
TI-84 Plus OS under a headless build of [TilEm](https://github.com/siraben/tilem-headless),
captures an instruction trace, and maps every executed address back onto this
repo's Ghidra model (`page_NN:addr`) and a flat `tools/rom.bin` offset.

The bridge between TilEm's trace and our static model is
[`tools/tilem_trace_resolve.py`](tilem_trace_resolve.py).

## Why this is non-trivial

TilEm records only the **logical 16-bit PC** of each instruction. On the
84+, `4000–7FFF` and `8000–BFFF` are banked flash/RAM windows (see
[docs/02-paging.md](../docs/02-paging.md)), so a logical PC like `0x412c` is
ambiguous until you know which page ports 6/7 had selected. The resolver
recovers banking by replaying the OUT instructions in the trace itself:

- `OUT (n),A` — TilEm sets `WZ = (A<<8) | n`, so **port = `WZ & 0xFF`, value = `WZ >> 8`**.
- Port 5 selects the high RAM `C000` window (bank C), port 6 selects the `4000`
  window (bank A), and port 7 selects the `8000` window (bank B).
- Ports 6/7 use bit 7 as the RAM selector. With bit 7 clear, low six bits select
  flash (`0x7F` maps as flash page `3F`); with bit 7 set, low three bits select
  RAM (`0x83` maps as RAM page `83`). Port 5 always selects RAM by low three bits.

It then maps each PC to a Ghidra address that matches `BuildTI84Full.java`'s
overlay layout: page 0 → `ram:XXXX`, banked flash → `page_NN:XXXX` (overlay
based at `0x4000`), RAM → `ram:XXXX`.

## 1. Build TilEm (Nix)

```sh
git clone https://github.com/siraben/tilem-headless ~/Git/tilem-headless   # if needed
cd ~/Git/tilem-headless
nix build .#tilem          # -> ./result/bin/tilem2  (the GUI binary; --headless works headless)
```

`tilem2 --help` lists the headless options (`--trace`, `--trace-range`,
`--trace-backtrace`, `--macro`, `--headless-record`, …).

## 2. Run the ROM headless (the working recipe)

Put your ROM at `tools/rom.bin` (same image the Ghidra build uses). Then:

```sh
TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless --rom tools/rom.bin --model ti84p --normal-speed --reset \
  --macro tools/macros/home-2plus3.macro \
  --headless-record /tmp/calc.gif \
  --trace /tmp/b.trace --trace-range all
```

Three gotchas that will otherwise waste your time:

- **Use `--normal-speed`, not `--full-speed`, for anything interactive.**
  `wait Ns` counts *wall-clock* seconds but at full speed runs *minutes* of
  emulated time per wall-second — the OS hits Auto-Power-Down (a permanent
  `HALT` with interrupts off) long before your keys land. Full speed is fine
  for *non-interactive* tracing (boot, a fixed delay).
- **Press `ON` first, and dismiss the splash.** A cold `--reset` boot powers
  up off; `key ON` wakes it, then it shows `TI-84 Plus 2.55MP / RAM cleared /
  PRESS ALPHA F1–F4…`, which a keypress dismisses to the home screen.
- **Record a GIF to see the screen.** A single `--headless-screenshot` /
  `screenshot` often catches a blank LCD-refresh phase and saves an all-white
  PNG even though the calc is fine. `--headless-record FILE.gif` is reliable;
  pull a frame with Pillow if you need a still.

Macro syntax is one command per line (`wait`, `key NAME [hold T]`,
`press`/`release`, `type`, `screenshot`, `memdump`); `#`/`//` start a
**whole-line** comment only — a trailing `# …` after a command is parsed as a
(bad) hold-time. Full key-name list is in `tilem-headless/headless/script.c`.

## 3. Resolve the trace to Ghidra addresses

```sh
# first N instructions, with symbol names from names.txt and flat ROM offsets
tools/tilem_trace_resolve.py /tmp/b.trace --print 40 --names tools/names.txt

# walk ONE routine's execution (with live registers) inside a multi-million-
# instruction trace: filter --print by space and a logical-address window, and
# page through it with --print-from. E.g. step through _LnX (02:6EFD) computing
# ln(2):
tools/tilem_trace_resolve.py /tmp/b.trace --print 200 \
  --only-space page_02 --only-addr 6efd-6ff0 --names tools/names.txt
tools/tilem_trace_resolve.py /tmp/b.trace --print 200 --print-from 200 \
  --only-space page_02 --only-addr 6efd-6ff0 --names tools/names.txt   # next page

# every bank switch (port 5 / port 6 / port 7 writes)
tools/tilem_trace_resolve.py /tmp/b.trace --page-switches

# physical RAM page writes, after replaying port 5/6/7 page selection
tools/analyze_ram_page_trace.py /tmp/b.trace --page 0x83

# coverage: distinct executed addresses + hit counts
tools/tilem_trace_resolve.py /tmp/b.trace --coverage --sort count --names tools/names.txt

# function-level coverage (roll hits up to the nearest-preceding name),
# optionally restricted to one address space:
tools/tilem_trace_resolve.py /tmp/b.trace --funcs --only-space page_39 \
  --sort count --names tools/names.txt
```

`--trace-range all` is required for paging to work — it captures page-0 and the
banked windows. A `page_??:` prefix means a bankable PC was hit before the
first OUT set that port (only the first few boot instructions).

Output carries a flat `rom=0x......` offset for flash addresses, so you can
sanity-check against the raw image, e.g.:

```sh
z80dasm -a -t -g 0x4000 -S <(dd if=tools/rom.bin bs=1 skip=$((0x3F*0x4000)) count=$((0x4000))) | less
```

## 4. "Breakpoints" and isolating a code path

Headless TilEm has no interactive breakpoints, but these patterns cover the
same ground:

### Coverage diff (the workhorse)

Run the action and a baseline that differs by *only* the step of interest, then
subtract the address sets. Everything left is that step's code. Example —
isolating the `2+3` evaluation against an idle baseline
([`boot-idle.macro`](macros/boot-idle.macro) vs
[`home-2plus3.macro`](macros/home-2plus3.macro)):

```sh
$TILEM --headless --rom tools/rom.bin --model ti84p --normal-speed --reset \
  --macro tools/macros/boot-idle.macro  --trace /tmp/a.trace --trace-range all
$TILEM --headless --rom tools/rom.bin --model ti84p --normal-speed --reset \
  --macro tools/macros/home-2plus3.macro --trace /tmp/b.trace --trace-range all

tools/tilem_trace_resolve.py /tmp/a.trace --coverage --sort addr --names tools/names.txt > /tmp/cov_a.txt
tools/tilem_trace_resolve.py /tmp/b.trace --coverage --sort addr --names tools/names.txt > /tmp/cov_b.txt
comm -13 <(awk '{print $2}' /tmp/cov_a.txt | sort) <(awk '{print $2}' /tmp/cov_b.txt | sort)
```

That diff cleanly surfaces the parser on page `0x38` (`eval_expr_inner`,
`eval_stmt_entry`, `parse_refill`, `digit_accum2`, `fps_push_word2`, …) and the
BCD-float formatting on page `0x06` (`_FormReal`, `fmt_digit`,
`fmt_decimal_point`) plus the page-0 FP helpers — i.e. exactly the
parser/float pillars the static docs describe.

### Stored TI-BASIC programs

The sample programs in [`tools/tibasic-samples/`](tibasic-samples/) are generated
from token bodies by:

```sh
tools/tibasic_samples.py --write-dir tools/tibasic-samples
```

Each sample has:

- `NAME.bas` — readable TI-BASIC source.
- `NAME.tok` — ASCII hex text for the raw bytes after the `ProgObj` two-byte
  size word.
- `PRGMNAME.8xp` — a TI-83+/84+ link file containing `[size][token bytes]`.

They cover:

| Sample | Purpose |
|--------|---------|
| `hello` | `ClrHome`, `Disp`, string scanning, newline/display completion |
| `factorial` | `Prompt`, stores, `For(`/`End`, FP multiply, loop `parsePtr` reseed |
| `data` | list literal, `L1`/`L2` 2-byte names, `SortA(`, `cumSum(`, `sum(` |
| `asmret` | `AsmPrgm` body containing `C9` (`RET`) |
| `asmcall` | BASIC wrapper that runs `Asm(prgmASMRET)` between two `Disp` calls |
| `asmsig` | `AsmPrgm` body that sets `Ans=1` with `_OP1Set1` + `_StoAns` |
| `asmbridge` + `asmsig` + `zzbasic` | cooperative ASM-directed BASIC callback through `If Ans` |
| `asmval` + `asmreturn` | `AsmPrgm` stores `Ans=2`; BASIC reads it, adds `3`, and displays `5` |
| `animtext` | `ClrHome`, `For(`/`End`, `Output(` text placement, `Disp` |
| `graphviz` | `ClrDraw`, `Line(`, `Circle(`, `Text(`, `DispGraph` |
| `graphdfs` | graph-buffer node/edge visualization for the DFS sample |
| `graphlist` | list-driven edge/node coordinate visualization for the DFS sample |
| `callsub` + `subrt` | BASIC `prgmNAME` call, shared variable return, `Return` |
| `callabi` + `abisub` | BASIC subprogram ABI across `Ans`, scalar `A`, and list `L1` |
| `callstop` + `stopsub` | BASIC `prgmNAME` call where callee `Stop` terminates the caller chain |
| `bigadd` | list-digit arbitrary-precision addition, list indexing/stores, carry |
| `bigmul` | list-digit arbitrary-precision multiplication, nested loops, carry |
| `dfs` | list-backed DFS stack, `While`, nested `If`/`Then`, list stores |

The current upstream headless TilEm runner does not silently load `.8xp` files
before executing a macro. The validation traces below used a local TilEm patch
that schedules command-line files with `tilem_link_send_file()` before the
headless macro starts. Without that patch, load the chosen program into a clean
calculator RAM image with the editor, GUI send-file path, or another link-file
tool, then run `tools/macros/run-first-program.macro`.

With the patched runner:

```sh
TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless --rom tools/rom.bin --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --headless-record /tmp/tibasic.gif \
  --trace /tmp/tibasic.trace --trace-range all \
  tools/tibasic-samples/HELLO.8xp
tools/tilem_trace_resolve.py /tmp/tibasic.trace --funcs \
  --only-space page_38 --sort count --names tools/names.txt
```

The generated fixtures also have a repeatable smoke runner. It executes selected
programs, extracts the last GIF frame to PNG, resolves coverage, checks trace
anchors, and deletes the large binary trace unless `--keep-trace` is set:

```sh
tools/tibasic_smoke.py --tilem "$TILEM" --rom tools/rom.bin \
  --case animtext --case graphviz --case graphdfs \
  --out-dir /tmp/tibasic-smoke-visual
```

For the visualization cases, the smoke runner also thresholds the final frame
and compares it with the first recorded frame. `ANIMTXT`, `GRAPHV`,
`GRAPHDFS`, and `GRAPHLST` must end with at least 100, 100, 200, and 200 dark
pixels respectively, and must change by at least the same number of pixels from
first to final frame. `ANIMTXT` must also produce at least five distinct
captured frames, so a static final screen cannot pass as an animation. The
runner then checks named crop regions, including `GRAPHV` label, axes, and
circle arcs, plus `GRAPHDFS`/`GRAPHLST` node and edge regions. The 2026-06-07
run measured 212, 619, 466, and 466 dark pixels, with matching first-to-final
pixel changes.
The text/list fixtures use the same region mechanism for final-screen output:
`HELLO`, `FACTOR`, `DATA`, `ASMCALL`, `ASMBRIDG`, `CALLSUB`, `BIGADD`,
`BIGMUL`, and `DFS` check the displayed lines or numeric/list result regions,
while `ASMRTN` and `ABICALL` check their rendered scalar/list/`Ans` outputs.
`CALLSTOP` also checks the `BEFORE`, `STOP`, and `Done` lines, plus a bounded
low-pixel region where the caller's skipped `AFTER` line would otherwise
appear.

Keep only one test program in RAM when using `run-first-program.macro`; it opens
`PRGM`, selects the first `EXEC` entry, and presses `ENTER`. For `factorial`,
use a variant that enters `5` at the prompt. For the `Asm(` smoke test, load both
`ASMCALL.8xp` and `ASMRET.8xp`; `ASMCALL` sorts before `ASMRET` and is selected
as the first executable program. `ASMRET` contains only `AsmPrgm` plus the hex
byte `C9`, so the Z80 payload returns immediately to the BASIC interpreter. The
wrapper uses the program-name token `0x5F` for the displayed `prgm` prefix.

Validated outputs/traces (2026-06-06/07, OS 2.55MP, `tools/rom.bin`):

| Program(s) | Screen result | Trace anchors |
|------------|---------------|---------------|
| `HELLO.8xp` | `HELLO, WORLD` then `Done` | page `0x38` parser (`eval_stmt_entry`, `parse_refill`, `parse_advance`) and `_Disp` at `37:51D3` |
| `FACTOR.8xp` with prompt input `5` | `N=5`, result `120`, then `Done` | `eval_stmt_entry`, loop parsing, `_FPMult` at `ram:238B`, `_Disp` |
| `DATA.8xp` | sorted `{1 1 3 4 5}`, cumulative `{1 2 5 9 14}`, sum `14`, then `Done` | list token handling (`resolve_2byte_var2`, `chk_list_type`, `store_list_elem*`, `list_fold_dispatch`) and `_Disp` |
| `ASMCALL.8xp` + `ASMRET.8xp` | `BEFORE`, `AFTER`, then `Done` | `Asm(` handler parses `prgmASMRET`, bcalls `_ExecutePrgm`, jumps through `07:57B4`; payload executes `ram:9D95 op=0xC9` and returns to BASIC |
| `ASMBRIDG.8xp` + `ASMSIG.8xp` + `ZZBASIC.8xp` | `BEFORE`, `CALLED`, `AFTER`, then `Done` | `Asm(` runs the `ASMSIG` payload at `ram:9D95`; payload calls `_OP1Set1` (`00:1B38`) and `_StoAns` (`38:6251`); BASIC evaluates `If Ans` via `_AnsName` and calls `prgmZZBASIC` through the normal `38:6910`/`38:6914`/`38:778F` body path |
| `ASMRTN.8xp` + `ASMVAL.8xp` | ASM stores `Ans=2`; BASIC computes and displays `5`, then `Done` | `ram:9D95`, `_OP1Set2` (`00:1B50`), `_StoAns` (`38:6251`), `_AnsName`, `_FPAdd`, `_Disp` |
| `ANIMTXT.8xp` | row of `X` characters, `DONE`, then `Done` | page-38 parser/loop paths, `_OutputExpr` (`03:4AF2`), `_Disp`, LCD text routines |
| `GRAPHV.8xp` | graph screen with `DFS`, axes, a circle, and diagonal line | `_GrBufClr`, `_StoSysTok`, `_ILine` (`04:4029`), `graph_pixel_op`, `_IPoint`, `_PDspGrph` (`04:7904`) |
| `GRAPHDFS.8xp` | graph screen with four labeled nodes and edges `1-2`, `1-3`, `2-4` | `_ILine` (`04:4029`), `graph_pixel_op`, `_IPoint`, `_PDspGrph` (`04:7904`), `_StoSysTok`, small-font glyph paths, `_RestoreDisp`, `eval_stmt_entry` |
| `GRAPHLST.8xp` | list-driven graph screen with four labeled nodes and edges `1-2`, `1-3`, `2-4` | list indexing/recall (`list_var_index`, `_GetLToOP1`), `_ILine`, `_IPoint`, `_PDspGrph`, `_StoSysTok` |
| `CALLSUB.8xp` + `SUBRT.8xp` | `SUB`, `1`, then `Done` | initial launch parse through `_ParseInpLastEnt`/`_ParseInp`, then BASIC subprogram body path through `stmt_eval_body_entry` (`38:6910`), `38:6914` -> `eval_eqn_recursive` (`38:778F`), shared `A` store/recall, `_Disp`, `Return` to caller |
| `ABICALL.8xp` + `ABISUB.8xp` | displays `11`, `{2 4 9}`, `11`, then `Done` | BASIC subprogram body path, `_AnsName`, list element read/store paths, shared scalar/list state, `Return` to caller |
| `CALLSTOP.8xp` + `STOPSUB.8xp` | displays `BEFORE`, `STOP`, then `Done`; the caller's `AFTER` line is absent | BASIC subprogram body path through `stmt_eval_body_entry` and `call_eval_eqn_recursive`; `_Disp` renders the caller pre-call and callee text; final-frame region check rejects an `AFTER`-sized caller continuation |
| `BIGADD.8xp` | `L3` digits begin `{0 1 1 1 1 ...}`, carry line `1`, then `Done` | list indexing/stores (`list_var_index`, `_AdrLEle`, `_GetLToOP1`, `_PutToL`, `store_list_elem*`), `fnint_body`, `_FPDiv`, `_FPAdd`, `_FPSub`, `_FPMult` |
| `BIGMUL.8xp` | `L3` digits `{5 3 5 5 0}`, high digit `5`, then `Done` | nested `For(` loops, list indexing/stores (`list_var_index`, `_GetLToOP1`, `_PutToL`), carry normalization through `int(`, `_FPMult`, `_FPAdd`, `_FPSub` |
| `DFS.8xp` | traversal `1`, `3`, `2`, `4`, visited `{1 1 1 1}`, then `Done` | nested control-flow scanners (`blockmatch_end_else`, `parse_scan_tokens`), `eval_stmt_entry`, parser refill/advance, list stack reads/stores |

ASM-to-BASIC negative probes: a temporary `AsmPrgm` that builds
`OP1={ProgObj,"ZZBASIC"}` and bcalls `_ChkFindSym` (`42F1`) returns to its BASIC
wrapper, proving ASM-side VAT lookup works. The same payload changed to bcall
`_Find_Parse_Formula` (`4AF2`) enters `_Find_Parse_Formula` (`38:758A`) and ends
at `ERR:UNDEFINED`; the target BASIC program body does not run. Keep these as
investigation traces rather than generated sample fixtures because one path is
intentionally a failing probe.

`_ParseInpLastEnt` probe (2026-06-07): a temporary `AsmPrgm` that builds
`OP1={ProgObj,"ZZBASIC"}` and bcalls `_ParseInpLastEnt` (`4B07`, target
`38:5984`) reaches `_ParseInpLastEnt`, `_ParseInp` (`38:5987`),
`parseinp_find_setup` (`38:5B2B`), `findsym_scan`, `parse_init`, and
`eval_stmt_entry`, but the final screen is `ERR:INVALID` / `Goto`; it never
displays `CALLED`. This supports the static reading that `_ParseInp` variants
expect a live parser/FPS stack frame, not just an OP1 program name from an
arbitrary `AsmPrgm`.

Forced-command/edit-buffer probes (2026-06-07): a payload that calls
`_JForceCmd(kEnter)` (`402A`) enters `ram:0747` and re-enters the command loop
without returning to the wrapper's following `Disp`; the screen repeats
`BEFORE`/`Done`. A payload that calls `_PutTokString` (`4960`, target `06:46FD`)
for `prgmZZBASIC` token bytes returns to the wrapper and reaches `AFTER`, but it
only renders/inserts token text. Combining `_PutTokString` with `_JForceCmd`
hits both routines and repeats the wrapper/rendered text; `ZZBASIC` never
displays `CALLED`. The related `_rclToQueue` (`49B4`, target `06:5F29`) depends
on an existing edit buffer and `rclFlag.enableQueue`, so it is not a proven
program-call entry either.

`_ExecuteNewPrgm` probes (2026-06-07): calling `4C3C` with `OP1=ProgObj` and
`HL -> "ZZBASIC",0` enters `_ExecuteNewPrgm` (`00:265F`) and `findsym_scan`, then
ends at `ERR:SYNTAX`. Loading `ZZBASIC` as `ProtProgObj` and calling with
`OP1=06` reaches the copy/jump tail (`00:268A`, `00:268F`) but still ends at
`ERR:SYNTAX`; the target body never displays `CALLED`.

These traces include the startup link-transfer code because the patched headless
runner loads the `.8xp` files during the traced process. Use an idle/load
baseline and coverage diff if you need to isolate only interpreter execution.

### Backtrace ring (break on exit / crash)

`--trace-backtrace FILE` keeps the most recent instructions in a RAM ring and
writes them at exit — use it when you care about what led *up to* a failure.
Decode with `--resync` (the ring may start mid-record):

```sh
$TILEM --headless --rom tools/rom.bin --model ti84p --normal-speed --reset \
  --macro tools/macros/home-2plus3.macro \
  --trace-backtrace /tmp/bt.bin --trace-range all --trace-backtrace-limit 67108864
tools/tilem_trace_resolve.py /tmp/bt.bin --resync --print 60 --names tools/names.txt
```

### Stop conditions

The upstream decoder `tilem-headless/tools/tilem_trace.py` adds control-flow
and stack analysis on the same trace files: `--print-flow` (call/ret/jump
events), `--stop-on-ret-underflow`, `--stop-on-sp-underflow`, `--step`
(interactive). Use it alongside the resolver when you need call-stack reasoning
rather than paged-address resolution.

## 5. Cross-referencing with Ghidra

- `ram:XXXX` → open that address directly (page 0 / RAM).
- `page_NN:XXXX` → the `page_NN` overlay block in the Ghidra project; `XXXX` is
  the `4000`-window address. The same `(page,addr)` is what bcalls/bjumps
  resolve to (see [docs/03-bcall-mechanism.md](../docs/03-bcall-mechanism.md)).
- `rom=0x......` → byte offset into `tools/rom.bin` for raw decoding.

## Files

- [`tilem_trace_resolve.py`](tilem_trace_resolve.py) — trace → paged Ghidra address resolver.
- [`analyze_ram_page_trace.py`](analyze_ram_page_trace.py) — trace memory writes → physical RAM page ranges.
- [`tibasic_smoke.py`](tibasic_smoke.py) — generated TI-BASIC fixture runner with
  trace-anchor checks and final-frame visual checks.
- [`macros/home-2plus3.macro`](macros/home-2plus3.macro) — power on, dismiss splash, evaluate `2+3`.
- [`macros/graph-y1-x2.macro`](macros/graph-y1-x2.macro) — power on, enter `Y1=X^2`, and graph it.
- [`macros/boot-idle.macro`](macros/boot-idle.macro) — baseline for coverage diffs.
- [`macros/run-first-program-factorial5.macro`](macros/run-first-program-factorial5.macro) —
  launch the first TI-BASIC program and answer `5` at `Prompt N`.
- `macros/mathprint-{power,fraction,fnint}.macro` — render `X²` / `1/2` / `fnInt(`
  to instrument the page-`0x39` MathPrint engine (worked example in
  [docs/sub-equation-display.md](../docs/sub-equation-display.md), "Dynamic confirmation").
- `macros/{ln2,exp1,sin1,fpsub}.macro` — known-input runs (`ln(2)`, `e¹`, `sin(1)`,
  `5−2`) that drive the FP/transcendental algorithms in
  [docs/06-floating-point.md](../docs/06-floating-point.md) for instruction-level
  pseudocode verification (walk a routine with `--print --only-space --only-addr`).
- `macros/solver-sqrt2.macro` — drives the Equation Solver to solve `X²−2=0`→√2,
  confirming the root-finder pseudocode in
  [docs/sub-solver-numeric.md](../docs/sub-solver-numeric.md).

## Trace format (quick reference)

`TLMT` v2: a 20-byte header + initial memory snapshot of the traced range,
then records — `0x01` instruction (logical PC, decoded opcode, clock, all Z80
registers incl. `WZ`, flags), `0x02` memory write (in-range), `0x03` key event.
Defined in `tilem-headless/headless/trace.c`.
