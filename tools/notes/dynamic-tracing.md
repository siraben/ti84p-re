# Dynamic tracing with headless TilEm

Static RE (Ghidra) tells you what *could* run. A headless emulator tells you
what *did* run, with real register and memory state. This guide drives the
TI-84 Plus OS under a headless build of [TilEm](https://github.com/siraben/tilem-headless),
captures an instruction trace, and maps every executed address back onto this
repo's Ghidra model (`page_NN:addr`) and a flat `tools/rom.bin` offset.

The resolver between TilEm's trace and the static model is
[`tools/ti84re/trace/resolve.py`](../ti84re/trace/resolve.py).

## Why this is non-trivial

TilEm records only the logical 16-bit PC of each instruction. On the 84+, the
upper three 16 KiB windows can be banked flash or RAM (see
[docs/paging.md](../../docs/paging.md)). A logical PC like `0x412c` is ambiguous
until the mapping ports are known. The resolver recovers the mapping by
replaying the `OUT` instructions in the trace:

- `OUT (n),A` — TilEm sets `WZ = (A<<8) | n`, so port = `WZ & 0xFF`, value = `WZ >> 8`.
- Port 4 bit 0 selects paired or independent mapping. In paired mode, port 6
  selects the even/odd pair at `0x4000` and `0x8000`, and port 7 selects the
  `0xC000` window. In independent mode, ports 6, 7, and 5 select the three
  windows respectively.
- Ports 6/7 use bit 7 as the RAM selector. With bit 7 clear, low six bits select
  flash (`0x7F` maps as flash page `3F`); with bit 7 set, low three bits select
  RAM (`0x83` maps as RAM page `83`). Port 5 always selects RAM by low three bits.
- Port `0x27` forces a configurable range at the top of the `0xC000` window to
  RAM page `80`. Port `0x28` does the same at the bottom of the `0x8000` window
  for RAM page `81`.

The resolver maps an `OUT` instruction with the pre-write state that fetched
that instruction. It applies the new port value only to later instructions.
It recognizes `OUT (n),A`, `OUT (C),r`, and `OUT (C),0`. TLMT v2 does not store
the memory byte emitted by `OUTI`, `OUTD`, `OTIR`, or `OTDR`; if one targets a
mapping port, the resolver marks that port unknown until a later recoverable
write establishes its value.

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
whole-line comment only — a trailing `# …` after a command is parsed as a
(bad) hold-time. Full key-name list is in `tilem-headless/headless/script.c`.

### Trace storage and analysis cost

TLMT is a binary record stream. Capture writes 48-byte instruction records,
6-byte memory-write records, and 9-byte key events through a 1 MiB buffered
stream rather than formatting one log line per instruction. A full trace still
grows linearly with executed instructions, so keep scenarios short and use
`--trace-backtrace` when only the events before a failure matter.

The reusable `hardware_trace.iter_resolved_executions` iterator resolves the
mapping and decodes optional I/O during one sequential read. Consumers can
aggregate counters and selected events without retaining the instruction
stream. For example, the retail boot validator stops at `3F:422B`:

```sh
python3 -m ti84re.boot.describe_hardware trace /tmp/b.trace
```

On the saved one-second reset trace, it consumes 134,851 of 269,645
instructions, retains 35 matching output events plus counters, and emits three
summary lines. Add `--json` before `trace` for machine-readable output. It does
not generate a per-instruction text log. [confirmed]

For exact-address coverage, `hardware_trace.count_resolved_trace_points`
replays mapping changes without constructing instruction or execution objects.
On a 1,753,851-instruction reset/idle trace, the targeted scan takes 5.57
seconds versus 17.78 seconds through the general object iterator, about 3.2×
faster. Its retained state is one mapper and a counter whose size depends on
the requested point set, not the trace length. The input remains about 83 MiB
because TLMT stores one 48-byte record per instruction. That audit retained no
hit keys. The general iterator remains appropriate when a consumer needs
register or I/O state from every yielded instruction. [confirmed]

## 3. Resolve the trace to Ghidra addresses

```sh
# first N instructions, with the proven TilEm reset mapping, symbol names,
# and flat ROM offsets
python3 -m ti84re.trace.resolve /tmp/b.trace --initial-mapping ti84p-reset \
  --print 40 --names tools/symbols/names.txt

# walk ONE routine's execution (with live registers) inside a multi-million-
# instruction trace: filter --print by space and a logical-address window, and
# page through it with --print-from. E.g. step through _LnX (02:6EFD) computing
# ln(2):
python3 -m ti84re.trace.resolve /tmp/b.trace --print 200 \
  --initial-mapping ti84p-reset \
  --only-space page_02 --only-addr 6efd-6ff0 --names tools/symbols/names.txt
python3 -m ti84re.trace.resolve /tmp/b.trace --print 200 --print-from 200 \
  --initial-mapping ti84p-reset \
  --only-space page_02 --only-addr 6efd-6ff0 --names tools/symbols/names.txt   # next page

# every mapping write (ports 4–7, 0x27, and 0x28)
python3 -m ti84re.trace.resolve /tmp/b.trace --initial-mapping ti84p-reset \
  --page-switches

# decoded I/O on selected hexadecimal ports and inclusive ranges;
# skip 200 matching events and print the next 100
python3 -m ti84re.trace.resolve /tmp/b.trace --initial-mapping ti84p-reset \
  --names tools/symbols/names.txt --io-ports 10-13,2f \
  --io-from 200 --io-count 100

# injected key events, named and aligned to instruction clocks
python3 -m ti84re.trace.resolve /tmp/b.trace --initial-mapping ti84p-reset \
  --names tools/symbols/names.txt --key-events

# restrict both key and decoded-I/O output to an inclusive trace-clock window
python3 -m ti84re.trace.resolve /tmp/b.trace --initial-mapping ti84p-reset \
  --names tools/symbols/names.txt --key-events --io-ports 01,03-04 \
  --event-clock 93285080-93450000

# physical RAM page writes
python3 -m ti84re.trace.analyze_ram_page /tmp/b.trace \
  --initial-mapping ti84p-reset --page 0x83

# arbitrary resolved writes, filtered by logical target and writing PCs
python3 -m ti84re.trace.analyze_memory_writes /tmp/b.trace --logical 0x8000 \
  --pc ram:8149 --pc ram:816B --target-kind ram --json

# visits to several exact resolved addresses, with registers and trace clocks
python3 -m ti84re.trace.analyze_points /tmp/b.trace \
  --point page_3C:7733 --point page_3C:7cfb

# filter a copied-worker entry and count its source pointers; --where is
# repeatable, and both visits and summaries support --json
python3 -m ti84re.trace.analyze_points /tmp/b.trace --point ram:8100 \
  --opcode 0xE6 --where 'DE<0x8000' --summary-register HL

# AMD command-shaped CPU writes, physical targets, and compact program runs
python3 -m ti84re.flash.analyze_trace /tmp/b.trace \
  --clock 321347460-344829074 --timeline

# group byte-program commands by the copied worker's terminal reset, or emit JSON
python3 -m ti84re.flash.analyze_trace /tmp/b.trace --invocations
python3 -m ti84re.flash.analyze_trace /tmp/b.trace --json

# coverage: distinct executed addresses + hit counts
python3 -m ti84re.trace.resolve /tmp/b.trace --initial-mapping ti84p-reset \
  --coverage --sort count --names tools/symbols/names.txt

# function-level coverage (roll hits up to the nearest-preceding name),
# optionally restricted to one address space:
python3 -m ti84re.trace.resolve /tmp/b.trace --initial-mapping ti84p-reset \
  --funcs --only-space page_39 --sort count --names tools/symbols/names.txt
```

TilEm's TLMT records identify CPU writes to mapped Flash. They do not encode
whether the ASIC gate or Flash device accepted a write. `analyze_flash_trace.py`
therefore reports command-shaped write attempts. Check port-`0x14`/port-`0x02`
state and final array data before treating a decoded sequence as a completed
program or erase.

`--trace-range all` is required for paging to work — it captures page 0 and the
banked windows. TLMT v2 does not store the mapping at the first record. Without
an explicit initial state, the resolver emits `page_??:` and warns that paged
coverage is incomplete until enough mapping writes appear.

`--io-ports` accepts comma-separated hexadecimal bytes and inclusive ranges.
The resolver decodes immediate and `(C)` forms of `IN` and `OUT`, prints the
resolved instruction address and clock, and uses `tools/symbols/names.txt` when
`--names` is supplied. Register and immediate transfers retain their byte
value. TLMT v2 does not retain the memory byte used by `INI`, `IND`, `INIR`,
`INDR`, `OUTI`, `OUTD`, `OTIR`, or `OTDR`, so block-I/O events report the value
as `unknown`. `--io-from` and `--io-count` window the matching I/O events
without changing coverage or ordinary `--print` output.

`--key-events` prints TLMT v2 key-event records with the injected key name,
press/release state, trace clock, and the current resolved PC. These are emulator
input events, not port-`0x01` reads. `--event-clock START[-END]` accepts decimal
or `0x`-prefixed 32-bit bounds and filters both `--key-events` and `--io-ports`
output. It does not change mapping replay, coverage, or ordinary `--print`
output.

For a full trace captured with `--model ti84p --reset`, use
`--initial-mapping ti84p-reset` only when the first traced instruction is the
reset entry at `0x8000`. The resolver warns if this preset is used when the
first traced PC differs. TilEm's `x4_reset()` initializes port 4 to `0x07`,
ports 6/7 to `0x3F`, and ports `0x27`/`0x28` to zero; a new calculator
initializes port 5 to zero. Paired mode therefore maps flash page `3E` at
`0x4000` and page `3F` at both `0x8000` and `0xC000`. These values describe the
TilEm `x4` model, not ROM-internal state.

For any other starting state, pass the values at the first record explicitly
with `--initial-port4`, `--initial-port5`, `--initial-port6`,
`--initial-port7`, `--initial-port27`, and `--initial-port28`. Do not apply the
reset preset to a wrapped ring trace: its oldest retained record normally
occurs long after reset.

Memory-write records precede the instruction record that generated them. The
RAM-page analyzer retains those writes until the following instruction record
so its event and top-PC output names the writing instruction.

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

python3 -m ti84re.trace.resolve /tmp/a.trace --initial-mapping ti84p-reset \
  --coverage --sort addr --names tools/symbols/names.txt > /tmp/cov_a.txt
python3 -m ti84re.trace.resolve /tmp/b.trace --initial-mapping ti84p-reset \
  --coverage --sort addr --names tools/symbols/names.txt > /tmp/cov_b.txt
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
python3 -m ti84re.tibasic.samples --write-dir tools/tibasic-samples
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
| `gcflash` | archive two real variables, retire one, accept `GarbageCollect`, and exercise the Flash GC state machine |
| `asmret` | `AsmPrgm` body containing `C9` (`RET`) |
| `asmcall` | BASIC wrapper that runs `Asm(prgmASMRET)` between two `Disp` calls |
| `asmsig` | `AsmPrgm` body that sets `Ans=1` with `_OP1Set1` + `_StoAns` |
| `asmbridge` + `asmsig` + `zzbasic` | cooperative ASM-directed BASIC callback through `If Ans` |
| `asmval` + `asmreturn` | `AsmPrgm` stores `Ans=2`; BASIC reads it, adds `3`, and displays `5` |
| `asmfind` + `zzfind` + `zzbasic` | `AsmPrgm` builds `OP1={ProgObj,"ZZBASIC"}`, reaches `findsym_scan`, and returns without running `ZZBASIC` |
| `asmparse` + `zzparse` + `zzbasic` | same OP1 setup, but `_ParseInpLastEnt` ends at `ERR:INVALID` instead of running `ZZBASIC` |
| `asmformula` + `zzformula` + `zzbasic` | same OP1 setup, but `_Find_Parse_Formula` ends at `ERR:UNDEFINED` instead of running `ZZBASIC` |
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
python3 -m ti84re.trace.resolve /tmp/tibasic.trace \
  --initial-mapping ti84p-reset --funcs \
  --only-space page_38 --sort count --names tools/symbols/names.txt
```

The generated fixtures also have a repeatable smoke runner. It executes selected
programs, extracts the last GIF frame to PNG, resolves coverage, checks trace
anchors, and deletes the large binary trace unless `--keep-trace` is set:

```sh
python3 -m ti84re.tibasic.smoke --tilem "$TILEM" --rom tools/rom.bin \
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
appear. `ASMFIND` checks the wrapper's `BEFORE`, `AFTER`, and `Done` lines plus
a bounded low-pixel region where an unexpected third line would appear.
`ASMPARSE` checks the `ERR:INVALID`, `1:Quit`, and `2:Goto` error-screen
regions. `ASMFORM` checks the matching `ERR:UNDEFINED`, `1:Quit`, and `2:Goto`
regions.

### Backtrace ring (break on exit / crash)

`--trace-backtrace FILE` keeps the most recent instructions in a RAM ring and
writes them at exit — use it when you care about what led *up to* a failure.
TLMT v2 does not identify a trace as a ring or save the port state at the oldest
retained record. Pass `--ring` so the resolver checks whether retained mapping
writes recover all windows:

```sh
$TILEM --headless --rom tools/rom.bin --model ti84p --normal-speed --reset \
  --macro tools/macros/home-2plus3.macro \
  --trace-backtrace /tmp/bt.bin --trace-range all --trace-backtrace-limit 67108864
python3 -m ti84re.trace.resolve /tmp/bt.bin --ring --print 60 --names tools/symbols/names.txt
```

If the warning appears, paged addresses remain `page_??:` until the required
port writes occur. Supply the six `--initial-portN` values only when another
trace or debugger snapshot establishes them at the ring's oldest record.
Current TilEm backtrace files retain whole records. `--resync` is available for
older or damaged traces with unknown bytes, but it cannot prove record alignment
because TLMT v2 has no per-record checksum or framing marker.

### Stop conditions

The upstream decoder `tilem-headless/tools/tilem_trace.py` adds control-flow
and stack analysis on the same trace files: `--print-flow` (call/ret/jump
events), `--stop-on-ret-underflow`, `--stop-on-sp-underflow`, `--step`
(interactive). Use it alongside the resolver when you need call-stack reasoning
rather than paged-address resolution.


### Guarded fixtures and pinned emulator probes

The longer recipes live in their own notes:

- [Flash fixtures](flash-fixtures.md) — cross-page Flash programming,
  execution-protection boundaries, guarded Flash-worker probes, and
  Flash-command replay with GC restart.
- [Pinned emulator probes](emulator-probes.md) — direct-core TilEm probes,
  guarded MAME probes, the Wabbitemu headless adapter, and the jsTIfied
  source profile.

## 5. Cross-referencing with Ghidra

- `ram:XXXX` → open that address directly (page 0 / RAM).
- `page_NN:XXXX` → the `page_NN` overlay block in the Ghidra project; `XXXX` is
  the `4000`-window address. The same `(page,addr)` is what bcalls/bjumps
  resolve to (see [docs/bcall-mechanism.md](../../docs/bcall-mechanism.md)).
- `rom=0x......` → byte offset into `tools/rom.bin` for raw decoding.

## Files

The tooling is organized as the `ti84re` package under `tools/`; see
[`tools/README.md`](../README.md) for the package map. The trace-side entry
points are `ti84re.trace.resolve` (trace → paged Ghidra address resolver),
`ti84re.trace.hardware` (importable resolved-execution, RAM-page, I/O, and
memory-write iterators), and the `analyze_*` and `describe_*` modules in the
subsystem packages. Headless TilEm macros live in `tools/macros/`.

## Trace format (quick reference)

`TLMT` v2: a 20-byte header + initial memory snapshot of the traced range,
then records — `0x01` instruction (logical PC, decoded opcode, clock, all Z80
registers incl. `WZ`, flags), `0x02` memory write (in-range), `0x03` key event.
Defined in `tilem-headless/headless/trace.c`.
