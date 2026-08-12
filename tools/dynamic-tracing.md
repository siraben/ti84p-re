# Dynamic tracing with headless TilEm

Static RE (Ghidra) tells you what *could* run. A headless emulator tells you
what *did* run, with real register and memory state. This guide drives the
TI-84 Plus OS under a headless build of [TilEm](https://github.com/siraben/tilem-headless),
captures an instruction trace, and maps every executed address back onto this
repo's Ghidra model (`page_NN:addr`) and a flat `tools/rom.bin` offset.

The resolver between TilEm's trace and the static model is
[`tools/tilem_trace_resolve.py`](tilem_trace_resolve.py).

## Why this is non-trivial

TilEm records only the logical 16-bit PC of each instruction. On the 84+, the
upper three 16 KiB windows can be banked flash or RAM (see
[docs/paging.md](../docs/paging.md)). A logical PC like `0x412c` is ambiguous
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
python tools/describe_boot_hardware.py trace /tmp/b.trace
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
tools/tilem_trace_resolve.py /tmp/b.trace --initial-mapping ti84p-reset \
  --print 40 --names tools/names.txt

# walk ONE routine's execution (with live registers) inside a multi-million-
# instruction trace: filter --print by space and a logical-address window, and
# page through it with --print-from. E.g. step through _LnX (02:6EFD) computing
# ln(2):
tools/tilem_trace_resolve.py /tmp/b.trace --print 200 \
  --initial-mapping ti84p-reset \
  --only-space page_02 --only-addr 6efd-6ff0 --names tools/names.txt
tools/tilem_trace_resolve.py /tmp/b.trace --print 200 --print-from 200 \
  --initial-mapping ti84p-reset \
  --only-space page_02 --only-addr 6efd-6ff0 --names tools/names.txt   # next page

# every mapping write (ports 4–7, 0x27, and 0x28)
tools/tilem_trace_resolve.py /tmp/b.trace --initial-mapping ti84p-reset \
  --page-switches

# decoded I/O on selected hexadecimal ports and inclusive ranges;
# skip 200 matching events and print the next 100
tools/tilem_trace_resolve.py /tmp/b.trace --initial-mapping ti84p-reset \
  --names tools/names.txt --io-ports 10-13,2f \
  --io-from 200 --io-count 100

# injected key events, named and aligned to instruction clocks
tools/tilem_trace_resolve.py /tmp/b.trace --initial-mapping ti84p-reset \
  --names tools/names.txt --key-events

# restrict both key and decoded-I/O output to an inclusive trace-clock window
tools/tilem_trace_resolve.py /tmp/b.trace --initial-mapping ti84p-reset \
  --names tools/names.txt --key-events --io-ports 01,03-04 \
  --event-clock 93285080-93450000

# physical RAM page writes
tools/analyze_ram_page_trace.py /tmp/b.trace \
  --initial-mapping ti84p-reset --page 0x83

# arbitrary resolved writes, filtered by logical target and writing PCs
tools/analyze_memory_writes.py /tmp/b.trace --logical 0x8000 \
  --pc ram:8149 --pc ram:816B --target-kind ram --json

# visits to several exact resolved addresses, with registers and trace clocks
tools/analyze_trace_points.py /tmp/b.trace \
  --point page_3C:7733 --point page_3C:7cfb

# filter a copied-worker entry and count its source pointers; --where is
# repeatable, and both visits and summaries support --json
tools/analyze_trace_points.py /tmp/b.trace --point ram:8100 \
  --opcode 0xE6 --where 'DE<0x8000' --summary-register HL

# AMD command-shaped CPU writes, physical targets, and compact program runs
tools/analyze_flash_trace.py /tmp/b.trace \
  --clock 321347460-344829074 --timeline

# group byte-program commands by the copied worker's terminal reset, or emit JSON
tools/analyze_flash_trace.py /tmp/b.trace --invocations
tools/analyze_flash_trace.py /tmp/b.trace --json

# coverage: distinct executed addresses + hit counts
tools/tilem_trace_resolve.py /tmp/b.trace --initial-mapping ti84p-reset \
  --coverage --sort count --names tools/names.txt

# function-level coverage (roll hits up to the nearest-preceding name),
# optionally restricted to one address space:
tools/tilem_trace_resolve.py /tmp/b.trace --initial-mapping ti84p-reset \
  --funcs --only-space page_39 --sort count --names tools/names.txt
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
resolved instruction address and clock, and uses `tools/names.txt` when
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

tools/tilem_trace_resolve.py /tmp/a.trace --initial-mapping ti84p-reset \
  --coverage --sort addr --names tools/names.txt > /tmp/cov_a.txt
tools/tilem_trace_resolve.py /tmp/b.trace --initial-mapping ti84p-reset \
  --coverage --sort addr --names tools/names.txt > /tmp/cov_b.txt
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
tools/tilem_trace_resolve.py /tmp/tibasic.trace \
  --initial-mapping ti84p-reset --funcs \
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
appear. `ASMFIND` checks the wrapper's `BEFORE`, `AFTER`, and `Done` lines plus
a bounded low-pixel region where an unexpected third line would appear.
`ASMPARSE` checks the `ERR:INVALID`, `1:Quit`, and `2:Goto` error-screen
regions. `ASMFORM` checks the matching `ERR:UNDEFINED`, `1:Quit`, and `2:Goto`
regions.

### Cross-page Flash-programming fixture

`build_ti_program.py` generates large storage fixtures without checking binary
files into the repository. The following pair sorts `AARCHIVE` before
`ZBIGDATA`; the macro then selects the second program in the memory manager and
archives it without executing its deliberately repetitive body:

```sh
python tools/build_ti_program.py /tmp/AARCHIVE.8xp \
  --name AARCHIVE --body-size 1 --fill-byte 0x3F --json
python tools/build_ti_program.py /tmp/ZBIGDATA.8xp \
  --name ZBIGDATA --body-size 17000 --json

$TILEM --headless --rom tools/rom.bin --model ti84p --normal-speed --reset \
  --macro tools/macros/archive-second-program.macro \
  --trace /tmp/writeflash-cross.trace --trace-range all \
  /tmp/AARCHIVE.8xp /tmp/ZBIGDATA.8xp
```

This requires the same headless file-loading support described above. Load
exactly these two unarchived programs: the macro opens **MEM** > **Mem Mgmt/Del**
> **Prgm**, moves to the second entry, and presses **ENTER**. Decode the worker
invocations and then inspect the three copied-worker instructions around the
single boundary event:

```sh
python tools/analyze_flash_trace.py /tmp/writeflash-cross.trace --invocations
python tools/analyze_flash_trace.py /tmp/writeflash-cross.trace --json
python tools/analyze_trace_points.py /tmp/writeflash-cross.trace \
  --point ram:811B --point ram:8122 --point ram:8124 \
  --clock 230976500-230976650 --json
```

The recorded run contains one 17,002-command invocation from physical
`0x20013` (`08:4013`) through `0x2427C` (`09:427C`). It is contiguous, crosses
one page, and resets at the final target. At the boundary, `ram:811B` reads
page `0x08`, `ram:8122` outputs page `0x09`, and `ram:8124` has changed `DE`
from `0x8000` to `0x4000`. Clock values depend on the complete run and macro
timing; use the invocation report to narrow the point query after recapture.

### Execution-protection boundary fixture

`execution_protection_fixture.py` builds exact-ROM copies with a six-byte
marker at `pp:7FF0`, validates the 75-byte assembly probe, and classifies a
trace from its call, target-fetch, follow-up, return, and reset records. The
default CLI run covers both sides of the boot bounds `08`–`29`:

```sh
probe_parent=$(mktemp -d)
nix develop -c python tools/run_execution_protection_probe.py \
  --tilem "$TILEM" --output-dir "$probe_parent/run" --json
```

The command refuses to reuse an output directory and never changes its source
ROM. It emits a patched ROM copy, machine-code program, BASIC runner, complete
trace, emulator log, and hashes for pages `07`, `08`, `29`, and `2A`. The
classifier requires `07` and `2A` to return and `08` and `29` to enter the
reset stub without reaching the marker's second instruction. See
[Execution protection](../docs/execution-protection.md#guarded-tilem-boundary-trace)
for the recorded clocks and identities.

### RAM execution-protection fixtures

`execution_protection_fixture.py` also validates RAM targets, packages TilEm
program pairs, patches the boot mode immediate, and classifies physical-page
fetches. The TilEm CLI changes only `3F:41D6` for modes 1–3. Its self-installing
probe writes and reads back the six-byte target through data accesses before
the guarded call:

```sh
ram_probe_parent=$(mktemp -d)
nix develop -c python tools/run_tilem_ram_execution_probe.py \
  --tilem "$TILEM" --output-dir "$ram_probe_parent/run" --json
```

The default run covers page-2 chunk 0 and chunk 1 in modes 0 and 1, plus the
mode-1 page-5 and page-6 repetitions. It rejects any control-flow result or
restricted-RAM warning count that disagrees with the pinned TilEm predicate.
Each output directory contains the mode-specific ROM, assembly program, BASIC
launcher, emulator log, complete trace, and hash-complete manifest. Complete
traces are about 200 MB each.

The native Wabbitemu CLI uses direct core injection after the retail boot has
established and relocked the baseline registers:

```sh
wabbit_ram_parent=$(mktemp -d)
nix develop -c python tools/run_wabbitemu_ram_execution_probe.py \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_ram_parent/run" --json
```

Its default 18 targets cover modes 0–3, odd-page shortcuts, the complete upper
chunk, the next denied chunk, and the mode-1 disagreements. Custom
`--lower-chunk`, `--upper-chunk`, and repeatable
`--target MODE:PHYSICAL_PAGE:PAGE_OFFSET` arguments expose other cases. The
runner checks the boot snapshot, configured 16-bit bounds, source and target
mappings, markers, visits, resets, expected predicate, and all input hashes.
Both launch methods remain emulator evidence, not physical ASIC measurements.

### Guarded Flash-worker fixtures

`build_flash_emulator_fixture.py` creates a fixture copy of the exact local OS
2.55MP image and two program files. It refuses a ROM whose SHA-256 is not
`7d9a7d96d89fc552ebee6afdbdd011fdc6047be9c16d308245dff07eb1f7bd6d`.
Fixtures that need accepted Flash commands change eight bytes at physical
`0xF3068`, the tail of the page-`3C` protected unlock wrapper, from
`F1 CD B9 2B CD D5 66 C9` to `F1 C9 00 00 00 00 00 00`. The
`_WriteFlashUnsafe` body and copied worker remain unchanged. Entry-return,
locked-write, and low-source fixtures use an unmodified ROM copy.

The builder selects named probes through `--fixture`. `page-3e-cross` remains
the default; `program-error` exercises the worker's DQ5 failure path, and
`entry-returns` captures early guards without unlocking Flash. The
`byte-entry-returns` fixture captures `_WriteAByteSafe` and `_WriteAByte`
wrapper side effects on no-worker paths. `locked-byte-noop` shows the worker's
DQ7 result while the ASIC gate remains locked. `low-source-cross` follows the
worker's fixed-ROM source branch across logical `0x7FFF` into RAM.
`erase-entry-returns` does the same for the erase APIs. The
`certificate-erase-success` fixture exercises a complete 8 KiB erase on a
patched ROM copy. `erase-busy-range` samples selected and unselected Flash
regions during an active erase. Fixture metadata, optional patching,
validation, and TI link-file packaging live in
`flash_emulator_fixture.py`; the CLI only assembles the selected source and
writes its artifacts.

#### Entry-return probe

`EMUWFENT` checks the unmodified `_WriteFlashUnsafe` entry signature and then
captures `AF` after four no-write paths: safe page `3E`, unsafe page `3F`, zero
length on page `3D`, and a direct call from RAM. It saves and restores port
`0x06` plus the incoming interrupt state.

```sh
fixture_dir=$(mktemp -d /tmp/writeflash-entry-fixture.XXXXXX)
nix develop -c python tools/build_flash_emulator_fixture.py \
  --fixture entry-returns \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-writeflash-entry.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/writeflash-entry.trace --trace-range all \
  "$fixture_dir/AWRUNENT.8xp" "$fixture_dir/EMUWFENT.8xp"

python tools/analyze_flash_trace.py /tmp/writeflash-entry.trace --json
python tools/analyze_trace_points.py /tmp/writeflash-entry.trace \
  --point ram:9DC5 --point ram:9DD8 \
  --point ram:9DEB --point ram:9DFF --json
```

The validated run contains no CPU write attempts targeting mapped Flash. The
four result points hold `AF=0x3E42`, `0x3F42`, `0x3DBB`, and `0xA591`,
respectively. The fixture ROM SHA-256 equals the source ROM SHA-256; the
manifest reports `"rom_modified": false`.

#### Byte-entry return probe

`EMUWBENT` verifies the 16 wrapper bytes from `3F:4C9A` through `3F:4CA9` on
the unmodified ROM. It exercises safe page `3E`, safe page `3F`, unsafe page
`3F`, and a direct `_WriteAByte` call from RAM. Every path returns before
worker launch. The fixture saves and restores the original `OP1` byte.

```sh
fixture_dir=$(mktemp -d /tmp/writeabyte-entry-fixture.XXXXXX)
nix develop -c python tools/build_flash_emulator_fixture.py \
  --fixture byte-entry-returns \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-writeabyte-entry.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/writeabyte-entry.trace --trace-range all \
  "$fixture_dir/AWBENTRY.8xp" "$fixture_dir/EMUWBENT.8xp"

python tools/analyze_flash_trace.py /tmp/writeabyte-entry.trace --json
python tools/analyze_trace_points.py /tmp/writeabyte-entry.trace \
  --point ram:9DD1 --point ram:9DE4 \
  --point ram:9DF5 --point ram:9E08 \
  --point ram:9E19 --point ram:9E2C \
  --point ram:9E42 --point ram:9E55 --json
```

The trace contains zero CPU write attempts targeting mapped Flash. The safe
page-`3E` result keeps the input `BC=0x2233`, `DE=0x4455`, `HL=0x6677`, and
sentinel `OP1=0x11`. The other three paths return with `BC=1`, `HL=0x8478`,
and `OP1` equal to the input `B`. Their `AF` results are `0x3F42`, `0x3F42`,
and `0xA591`.

#### Locked byte-program no-op probe

`EMULOCK` verifies the `_WriteAByte` wrapper and protected page-`3C` lock
wrapper on the unmodified ROM. It requires source byte `0x50` at `3D:7FFF`,
calls the lock wrapper, and aborts unless port `0x02` bit 2 is clear. It then
requests `0x40`, captures the worker result, and rereads the target and status
port. The fixture restores the original `OP1` byte.

```sh
fixture_dir=$(mktemp -d /tmp/writeabyte-locked-fixture.XXXXXX)
nix develop -c python tools/build_flash_emulator_fixture.py \
  --fixture locked-byte-noop \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-writeabyte-locked.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/writeabyte-locked.trace --trace-range all \
  "$fixture_dir/ALOCKED.8xp" "$fixture_dir/EMULOCK.8xp"

python tools/analyze_flash_trace.py \
  /tmp/writeabyte-locked.trace --events --invocations --json
python tools/analyze_trace_points.py /tmp/writeabyte-locked.trace \
  --point ram:9DDC --point ram:8149 --point ram:814D \
  --point ram:816B --point ram:9DF0 --point ram:9E03 \
  --point ram:9E0D --point ram:9E12 --json
```

Port `0x02` is `0xE3` before and after the call, so TilEm's Flash-unlocked bit
stays clear. The command decoder finds five CPU write attempts, shaped as one
byte program and one reset, but TLMT does not encode ASIC acceptance. The
worker reads `0x50`, sees DQ7 agree with requested `0x40`, and returns
`AF=0x0044`, Z. `BC=0`, `DE=0x8000`, `HL=0x8479`, and `OP1=0x40`; the final
array byte remains `0x50`.

#### Erase-entry probe

`EMUERENT` verifies the unmodified entry bytes for `_EraseFlashPage`,
`_EraseFlash`, and `_EraseCertificateSector`. It captures the page-`3E` guard,
the direct-call guard, and an invalid certificate address. None can launch an
erase worker.

```sh
fixture_dir=$(mktemp -d /tmp/eraseflash-entry-fixture.XXXXXX)
nix develop -c python tools/build_flash_emulator_fixture.py \
  --fixture erase-entry-returns \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-eraseflash-entry.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/eraseflash-entry.trace --trace-range all \
  "$fixture_dir/AERUNENT.8xp" "$fixture_dir/EMUERENT.8xp"

python tools/analyze_flash_trace.py /tmp/eraseflash-entry.trace --json
python tools/analyze_trace_points.py /tmp/eraseflash-entry.trace \
  --point ram:9DCD --point ram:9DE2 --point ram:9DF6 --json
```

The validated run contains no CPU write attempts targeting mapped Flash. The
three result points hold `AF=0x3E42`, `0xA591`, and `0xA545`, respectively.
The last value is the fixture's seeded caller value, preserved by the
certificate wrapper. Its manifest reports `"rom_modified": false`.

#### Certificate-erase success probe

`EMUCERAS` checks the patched unlock-wrapper signature, seeds caller
`AF=0xA545`, and invokes `_EraseCertificateSector` for `HL=0x4000`. It rereads
the first byte while Flash remains unlocked, then relocks and restores the
incoming interrupt state. The operation affects only the copied ROM image.

```sh
fixture_dir=$(mktemp -d /tmp/certificate-erase-fixture.XXXXXX)
nix develop -c python tools/build_flash_emulator_fixture.py \
  --fixture certificate-erase-success \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-certificate-erase-patched.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/certificate-erase.trace --trace-range all \
  "$fixture_dir/ACERASE.8xp" "$fixture_dir/EMUCERAS.8xp"

python tools/analyze_flash_trace.py \
  /tmp/certificate-erase.trace --events --timeline
python tools/analyze_trace_points.py /tmp/certificate-erase.trace \
  --point ram:8138 --summary-register AF --json
python tools/analyze_trace_points.py /tmp/certificate-erase.trace \
  --point ram:8143 --point ram:8151 --point page_3F:4E55 \
  --point ram:9DBA --point ram:9DC3 --json
```

The trace decodes one sector erase at physical `0xF8000`. Its 24,497 target
reads contain three `0x00`/`0x44` pairs, 12,245 `0x08`/`0x4C` pairs, and one
final `0xFF`. The worker returns `A=0`, Z; the wrapper-visible result remains
the seeded `AF=0xA545`; and the original `0x00` target byte reads back as
`0xFF`.

#### Erase-busy range probe

`EMUERANG` checks the patched unlock-wrapper signature and issues
`AA 55 80 AA 55 30` directly for `3E:4000`. After DQ3 reports active erase,
it samples both ends of the selected sector, the adjacent and preceding
sectors, the boot sector, and distant page `08`. It waits for DQ7 before
capturing final array values and relocking Flash.

```sh
fixture_dir=$(mktemp -d /tmp/erase-busy-range-fixture.XXXXXX)
nix develop -c python tools/build_flash_emulator_fixture.py \
  --fixture erase-busy-range \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-eraseflash-range-patched.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/erase-busy-range.trace --trace-range all \
  "$fixture_dir/AERANGE.8xp" "$fixture_dir/EMUERANG.8xp"

python tools/analyze_flash_trace.py \
  /tmp/erase-busy-range.trace --events --timeline
python tools/analyze_trace_points.py /tmp/erase-busy-range.trace \
  --point ram:9DF5 --point ram:9DFB --point ram:9E01 \
  --point ram:9E0B --point ram:9E15 --point ram:9E1F \
  --point ram:9E2D --point ram:9E33 --point ram:9E39 \
  --point ram:9E43 --point ram:9E4D --point ram:9E57 --json
```

The trace decodes one erase of physical `0xF8000`–`0xF9FFF`. Busy samples are
`0x08`, `0x4C`, `0x08`, `0x4C`, `0x08`, and `0x4C` in the order above. Final
samples are `0xFF`, `0xFF`, `0xFF`, `0x50`, `0x3E`, and `0xFF`. TilEm returns
busy status even for the distant page-`08` read and emits one off-range
warning. These results describe pinned TilEm; physical read scope remains
unmeasured.

#### Low-source boundary probe

`EMULOW` verifies fixed source bytes `4D 50` at `00:0068`, the first 16 bytes
of the block worker at `3F:4CCA`, and the protected lock wrapper at `3C:66D5`.
It calls that wrapper and aborts unless port `0x02` bit 2 reports Flash locked.
It then calls `_WriteFlashUnsafe` with `A=0x3D`, `DE=0x7FFF`, `BC=2`, and
`HL=0x0068`. The fixture saves and restores RAM `0x8000`, `(IY+0x25)`, port
`0x06`, and the incoming interrupt state. Its ROM is unmodified.

```sh
fixture_dir=$(mktemp -d /tmp/writeflash-low-source.XXXXXX)
nix develop -c python tools/build_flash_emulator_fixture.py \
  --fixture low-source-cross \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-writeflash-low-source.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/writeflash-low-source.trace --trace-range all \
  "$fixture_dir/ALOWSRC.8xp" "$fixture_dir/EMULOW.8xp"

python tools/analyze_flash_trace.py \
  /tmp/writeflash-low-source.trace --events --invocations --json
python tools/analyze_memory_writes.py /tmp/writeflash-low-source.trace \
  --logical 0x8000 --pc ram:8149 --pc ram:816B \
  --target-kind ram --clock 187318000-187320000 --json
python tools/analyze_trace_points.py /tmp/writeflash-low-source.trace \
  --point ram:8149 --point ram:816B --point ram:9E11 \
  --point ram:9E21 --point ram:9E2E --point ram:9E36 \
  --point ram:9E3C --clock 187318000-187320000 --json
```

At `ram:8149`, the first `LDI` attempts to program `0x4D` at `3D:7FFF`; the
locked target remains `0x50`. The second `LDI` at the same copied-worker PC
writes `0x50` to RAM `0x8000`. The terminal reset at `ram:816B` writes `0xF0`
to that RAM address. The bcall returns with `AF=0x0044`, `BC=0`, `DE=0x8001`,
and `HL=0x006A`; `(IY+0x25).1` is set, and port `0x02` reads `0xE3`. The
fixture's machine-code SHA-256 is
`bb8159803d67bbfdc354d523db7dbe72e02bf4469a89c79d2c7d033dd660074e`.
These are pinned TilEm and unmodified-ROM results, not physical-device tests.

#### Page-3E skip probe

`EMUWF3E` checks all eight patched bytes before calling the wrapper. It exits
without unlocking Flash on an unmodified ROM. `AWRUN3E` is the BASIC
`Asm(prgmEMUWF3E)` launcher and sorts first in the program menu. Build and run
the fixture only under emulation:

```sh
fixture_dir=$(mktemp -d /tmp/writeflash-fixture.XXXXXX)
nix develop -c python tools/build_flash_emulator_fixture.py \
  --fixture page-3e-cross \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-writeflash-3e-patched.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/writeflash-3e-cross.trace --trace-range all \
  "$fixture_dir/AWRUN3E.8xp" "$fixture_dir/EMUWF3E.8xp"

python tools/analyze_flash_trace.py \
  /tmp/writeflash-3e-cross.trace --events --invocations
python tools/analyze_trace_points.py /tmp/writeflash-3e-cross.trace \
  --point ram:811B --point ram:811D --point ram:811E \
  --point ram:8120 --point ram:8122 --point ram:8124 --json
```

The validated TilEm run produced byte-program commands at physical `0xF7FFF`
and `0xF4000`, followed by the worker reset at `0xF4000`. `ram:8122` was not
executed. `flash_trace.py` labels the resulting physical-address jump
`same-page-window-wrap`. This is emulator evidence for the ROM branch, not a
physical-calculator result.

#### Illegal-program probe

`EMUWFERR` checks the same patched-ROM signature, then requests `0xD0` over the
stored `0x50` at `3D:7FFF`. This forces TilEm's illegal `0→1` program state.
The fixture captures returned `AF`, rereads the target byte, relocks Flash, and
restores the incoming interrupt state.

```sh
fixture_dir=$(mktemp -d /tmp/writeflash-error-fixture.XXXXXX)
nix develop -c python tools/build_flash_emulator_fixture.py \
  --fixture program-error \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-writeflash-error-patched.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/writeflash-program-error.trace --trace-range all \
  "$fixture_dir/AWRUNERR.8xp" "$fixture_dir/EMUWFERR.8xp"

python tools/analyze_flash_trace.py \
  /tmp/writeflash-program-error.trace --events --invocations
python tools/analyze_trace_points.py /tmp/writeflash-program-error.trace \
  --point ram:814D --point ram:8155 --point ram:8159 \
  --point ram:815D --point ram:8175 --point ram:817A \
  --point ram:9DBE --point ram:9DC7 --json
```

The validated run decodes one byte-program command at physical `0xF7FFF` and
one reset from failure-tail PC `ram:8175`. The structured invocation report
labels it `worker_outcome: "failure"`. Poll reads return `0x00`, `0x60`, then
`0x20`; the bcall returns `AF=0x3F2C`, and the final target read returns
`0x50`. These values describe pinned TilEm and the OS worker. They do not
establish physical-device failure timing or status values.

Pinned Wabbitemu returns `0x20` for the first read of this pair and clears its
error flag. The ROM worker tests DQ5 in that same `0x20` byte, then performs one
final read. The final `0x50` leaves DQ7 different from requested `0xD0`, so the
worker takes its failure tail. The guarded native worker probe below captures
this path. It is not a hardware result.

#### Internal certificate-program failure probe

`EMUCFAIL` verifies the patched unlock wrapper plus the head and tail of the
129-byte page-`3D` program worker. After unlocking, it requires stored `0x00`
at `3E:4000`, copies the worker from `3D:730A` to `0x8100`, and directly calls
it with port `0x06` set to page zero. The requested `0x80` forces TilEm's
illegal `0→1` state. This fixture tests the copied worker's return tail, not the
outer caller at `3D:4332`.

```sh
fixture_dir=$(mktemp -d /tmp/certificate-program-error.XXXXXX)
nix develop -c python tools/build_flash_emulator_fixture.py \
  --fixture certificate-program-error \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-certificate-program-error-patched.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/certificate-program-error.trace --trace-range all \
  "$fixture_dir/ACFAIL.8xp" "$fixture_dir/EMUCFAIL.8xp"

python tools/analyze_flash_trace.py \
  /tmp/certificate-program-error.trace --invocations --json
python tools/analyze_trace_points.py /tmp/certificate-program-error.trace \
  --point ram:8154 --point ram:815B --point ram:8160 \
  --point ram:817B --point ram:9E06 --point ram:9E16 \
  --point ram:9E1F --json
```

The fixture machine-code SHA-256 is
`34fc6b71a0015cbcb13578a30ec195883a187ee43b234d6ab671d00275824429`.
The trace decodes one byte-program attempt at physical `0xF8000` and one reset
from `ram:817B`, classified as `certificate-failure`. Poll reads return
`0x00`, `0x60`, and `0x20`. The worker returns `AF=0x0044`, Z, with `BC=0`,
`DE=0x4000`, and `HL=0x9E63`. Port `0x06` is zero after return, and the target
still reads `0x00`. These values describe the ROM worker under pinned TilEm;
they do not establish physical status timing.

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
| `ASMFIND.8xp` + `ZZFIND.8xp` + `ZZBASIC.8xp` | ASM-side lookup returns to wrapper: `BEFORE`, `AFTER`, then `Done`; `ZZBASIC` does not display `CALLED` | payload executes at `ram:9D95`, builds `OP1={ProgObj,"ZZBASIC"}`, bcalls `_ChkFindSym`, reaches `findsym_scan`, and returns to BASIC wrapper `_Disp` |
| `ASMPARSE.8xp` + `ZZPARSE.8xp` + `ZZBASIC.8xp` | final screen is `ERR:INVALID`, `1:Quit`, `2:Goto`; `ZZBASIC` does not display `CALLED` | payload executes at `ram:9D95`, builds `OP1={ProgObj,"ZZBASIC"}`, bcalls `_ParseInpLastEnt`, then reaches `_ParseInp`, `parseinp_find_setup`, `findsym_scan`, `parse_init`, and `eval_stmt_entry` before the error screen |
| `ASMFORM.8xp` + `ZZFORM.8xp` + `ZZBASIC.8xp` | final screen is `ERR:UNDEFINED`, `1:Quit`, `2:Goto`; `ZZBASIC` does not display `CALLED` | payload executes at `ram:9D95`, builds `OP1={ProgObj,"ZZBASIC"}`, bcalls `_Find_Parse_Formula`, reaches `parse_init_findsym`, `findsym_scan`, and `eval_stmt_entry`, then stops at the error screen |
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

ASM-to-BASIC probe boundary: `ASMFIND`/`ZZFIND` is the generated positive
fixture for ASM-side VAT lookup. It proves `_ChkFindSym` can locate
`prgmZZBASIC` from an `AsmPrgm` payload and return to BASIC; it also proves that
lookup alone does not run the target BASIC body. `ASMFORM`/`ZZFORM` is the
generated `_Find_Parse_Formula` (`4AF2`) negative fixture. It enters
`_Find_Parse_Formula` (`38:758A`), reaches parser/find setup, and ends at
`ERR:UNDEFINED`; the target BASIC program body does not run.

`_ParseInpLastEnt` negative fixture (2026-06-07): `ASMPARSE`/`ZZPARSE` builds
`OP1={ProgObj,"ZZBASIC"}` and bcalls `_ParseInpLastEnt` (`4B07`, target
`38:5984`). It reaches `_ParseInpLastEnt`, `_ParseInp` (`38:5987`),
`parseinp_find_setup` (`38:5B2B`), `findsym_scan`, `parse_init`, and
`eval_stmt_entry`, but the final screen is `ERR:INVALID` / `1:Quit` / `2:Goto`;
it never displays `CALLED`. This supports the static reading that `_ParseInp`
variants expect a live parser/FPS stack frame, not just an OP1 program name
from an arbitrary `AsmPrgm`.

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

### Flash command replay and GC restart

`flash_replay.py` applies accepted byte-program commands with the NOR
`old & requested` rule and erases the top-boot sector selected by each erase
command. `replay_flash_trace.py` is the guarded CLI. It requires an expected
source-ROM hash, rejects unresolved or unmatched writes and non-successful OS
program-worker outcomes, refuses existing outputs by default, and reports both
input and output hashes.

TLMT records CPU write attempts, not the ASIC gate or Flash device's acceptance
decision. The CLI therefore refuses to write an image until
`--accept-command-shapes` explicitly acknowledges that boundary. Establish
acceptance from the surrounding trace before using this option. The `GCFLASH`
fixture has successful worker resets, no unmatched writes, and later reads of
the resulting archive state.

Materialize every active phase reached by that trace:

```sh
replay_dir=$(mktemp -d /tmp/ti84-gc-replay.XXXXXX)
python tools/replay_flash_trace.py /tmp/tibasic-smoke/gcflash.trace \
  --rom tools/rom.bin --output-dir "$replay_dir" \
  --phase 0xFF --phase 0xFE --phase 0xE0 \
  --accept-command-shapes --json
```

Controlled archive-sector topologies use a separate reusable builder. It
requires the pinned source identity and records every synthetic header byte;
later journal transitions still require an unmodified-ROM trace:

```sh
python tools/build_gc_layout.py \
  --output /tmp/gc-controlled.rom \
  --sector-header 0x08=0xFE \
  --sector-header 0x28=0xF0 \
  --json
```

The record-authentic phase-`0xF0` path uses a fresh-sector constructor rather
than controlled header bytes. It serializes the observed OS record fields,
requires erased 64 KiB sectors, and places each generated program in first-fit
order. This command reproduces the UI-generated input hash
`389ed80fe8635740f855c7b8ffec6312a5182027dd0605e8a6e2b094c8481452`:

```sh
python tools/build_archive_fixture.py \
  --rom tools/rom.bin --output /tmp/gcf0-seed.rom \
  --sector 0x20000 --sector 0x30000 \
  --program ZBIGDATA=17000 --program YBIGDAT2=17000 \
  --program XBIGDAT3=17000 --program WBIGDAT4=17000 \
  --program VBIGDAT5=17000 --program UBIGDAT6=17000 \
  --program TBIGFILL=14454 --program SBIGFILL=14454 --json

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless --rom /tmp/gcf0-seed.rom \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program-gcflash.macro \
  --trace /tmp/gcf0-seed.trace --trace-range all \
  tools/tibasic-samples/GCFLASH.8xp

phase_dir=$(mktemp -d /tmp/gcf0-phase.XXXXXX)
python tools/replay_flash_trace.py /tmp/gcf0-seed.trace \
  --rom /tmp/gcf0-seed.rom \
  --expected-rom-sha256 \
    389ed80fe8635740f855c7b8ffec6312a5182027dd0605e8a6e2b094c8481452 \
  --output-dir "$phase_dir" --phase 0xF0 \
  --accept-command-shapes --json
```

The recaptured trace can have different clocks while the phase image remains
byte-identical. Its required SHA-256 is
`df49d6ec77483e33944fdbcee969084fc065b01a4e44327f83246a9de363fcb2`.

The phase-`0xFF` snapshot is taken after the new certificate half's base byte
becomes `0x00`, not when the still-inactive half first receives an `0xFF`
master byte. This prevents an idle or incomplete certificate half from being
misclassified as an active interruption journal.

Cold-boot each image with fresh RAM and collect a full trace:

```sh
TILEM=~/Git/tilem-headless/result/bin/tilem2
for phase in ff fe e0; do
  "$TILEM" --headless --rom "$replay_dir/gc-phase-$phase.rom" \
    --model ti84p --normal-speed --reset \
    --macro tools/macros/boot-recovery.macro \
    --trace "/tmp/gc-restart-$phase.trace" --trace-range all
done
```

Check the dispatcher paths and recovery command timelines:

```sh
python tools/analyze_trace_points.py /tmp/gc-restart-ff.trace \
  --point page_3C:7bc7 --point page_3C:7c1f \
  --point page_3C:7c43 --point page_3C:7cfb \
  --point page_3C:7d30
python tools/analyze_flash_trace.py /tmp/gc-restart-ff.trace --timeline
```

The same CLI can replay a complete recovery trace over its interrupted input.
Pass the exact input hash reported by the phase-snapshot command:

```sh
python tools/replay_flash_trace.py /tmp/gc-restart-ff.trace \
  --rom "$replay_dir/gc-phase-ff.rom" \
  --expected-rom-sha256 \
    4e484ad4b99f07a333ae3845ee795b36cb6181e9a829261b2d52ff7931ac8f05 \
  --output /tmp/gc-recovered-ff.rom --accept-command-shapes
```

Repeat for each phase, then compare the recovered images with a complete replay
of the uninterrupted trace. Exact equality checks the complete Flash array,
including archive records, sector headers, and both certificate halves. It is
stronger than checking only the phase byte or dispatcher coverage. This method
tests interruption after a completed command; it does not synthesize a partial
program pulse or an erase cut during the busy interval.

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
tools/tilem_trace_resolve.py /tmp/bt.bin --ring --print 60 --names tools/names.txt
```

If the warning appears, paged addresses remain `page_??:` until the required
port writes occur. Supply the six `--initial-portN` values only when another
trace or debugger snapshot establishes them at the ring's oldest record.
Current TilEm backtrace files retain whole records. `--resync` is available for
older or damaged traces with unknown bytes, but it cannot prove record alignment
because TLMT v2 has no per-record checksum or framing marker.

### Pinned TilEm direct-core probes

`tilem_core.py` supplies clean-source validation, source enumeration, compiler
construction, hashing, and captured native execution. `tilem_probe_support.c`
supplies the allocation and diagnostic callbacks needed to link small probes
against the complete core. Each builder requires the clean commit and Git tree
before it compiles any source. Use the repository's locked Nixpkgs revision
when `cc` is unavailable.

#### Reset and execution exception

```sh
tilem_reset_tmp=$(mktemp -d /tmp/ti84-tilem-reset.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_reset_tmp/tilem"
git -C "$tilem_reset_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python tools/build_tilem_reset_probe.py \
  --source "$tilem_reset_tmp/tilem" \
  --output "$tilem_reset_tmp/tilem-reset-probe" --json

tilem_reset_parent=$(mktemp -d /tmp/ti84-tilem-reset-report.XXXXXX)
python tools/run_tilem_reset_probe.py \
  --binary "$tilem_reset_tmp/tilem-reset-probe" \
  --expected-binary-sha256 \
    ab0a862b1fbb7f8a09a075fbd0ec61ebb0bab84d12d2a9c2a650813476cc7e5a \
  --output-dir "$tilem_reset_parent/run" --json
```

The source guard requires commit
`f56ad637d0524ee841dd381be6ecbaf5b8975600`, tree
`58316afe35d69e69353f0f743698144153051d4a`, and an unmodified tracked
worktree. The probe seeds all reset components directly. It checks eight reset
groups, nine retained groups, exact TI-84 Plus mapper and register defaults,
and one restricted Flash instruction. That instruction writes a byte to mapped
RAM before TilEm handles its pending exception and performs the full reset.
The manifest labels this initialized-core scope; no TI-OS instruction or
physical reset executes.

#### Flash command and status matrix

The Flash probe uses the same guarded source and shared support. It calls the
core's physical-address Flash entry points against synthetic memory. It checks
the command lock, reset, unsupported commands, fast mode, legal and illegal
programming, status toggles, timer deadlines, sector boundaries, and both
protection-override groups:

```sh
tilem_flash_tmp=$(mktemp -d /tmp/ti84-tilem-flash.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_flash_tmp/tilem"
git -C "$tilem_flash_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python tools/build_tilem_flash_probe.py \
  --source "$tilem_flash_tmp/tilem" \
  --output "$tilem_flash_tmp/tilem-flash-probe" --json

tilem_flash_parent=$(mktemp -d /tmp/ti84-tilem-flash-report.XXXXXX)
python tools/run_tilem_flash_probe.py \
  --binary "$tilem_flash_tmp/tilem-flash-probe" \
  --expected-binary-sha256 \
    31f8e15a348d15f876f103b8452340484893987e458023fd913280365db5c51d \
  --output-dir "$tilem_flash_parent/run" --json
```

The scheduler converts TilEm's 7 µs program, 50 µs erase-window, and 200 ms
erase inputs to 42, 300, and 1,200,000 clocks at the reset speed. The probe
reads each status phase and directly invokes the registered Flash callback to
advance between phases. It does not execute the retail ROM or a physical
command.

#### Legacy interrupt matrix

The interrupt probe uses the same source guard and shared support. Its Python
oracle reuses the immutable TilEm state in `interrupt_controller.py`. The C
adapter calls the registered port and periodic-timer handlers, keypad and link
entry points, programmable-timer expiry, and full reset:

```sh
tilem_interrupt_tmp=$(mktemp -d /tmp/ti84-tilem-interrupt.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_interrupt_tmp/tilem"
git -C "$tilem_interrupt_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python tools/build_tilem_interrupt_probe.py \
  --source "$tilem_interrupt_tmp/tilem" \
  --output "$tilem_interrupt_tmp/tilem-interrupt-probe" --json

tilem_interrupt_parent=$(mktemp -d /tmp/ti84-tilem-interrupt-report.XXXXXX)
python tools/run_tilem_interrupt_probe.py \
  --binary "$tilem_interrupt_tmp/tilem-interrupt-probe" \
  --expected-binary-sha256 \
    23037df0fee48b3ec15656aae80b6181d97211e8eec325c2be81eef02b1ff840 \
  --output-dir "$tilem_interrupt_parent/run" --json
```

The native matrix checks full port-`0x03` readback; clear-on-zero behavior at
ports `0x02` and `0x03`; ON press and release edges; the three standard-timer
callbacks; current intervals and four selected periods; external link
transitions; programmable-timer completion and CPU requests in halted and
running states; and reset ordering. It exposes TilEm's stored
port-`0x03 = 0x0B` with an internally disabled ON interrupt immediately after
reset. A prior bit-3 write also remains in the internal power policy despite
the reset readback. Writing `0x0B` through the port handler synchronizes both
fields.

Two isolated runs produce identical canonical native JSON with SHA-256
`1c1209e9c3f625b07c42288c21e9a5dbadddb38f12aee995c1fbc8daf1f8e8ad`.
The manifest labels the initialized-core scope. It does not execute TI-OS or
measure interrupt voltage, physical timing, low-power domains, or reset
retention.

#### Battery comparator matrix

`battery_hardware.py` encodes the byte-verified `_Chk_Batt_Level` decision
tree and TilEm's four threshold constants. The native adapter sweeps the
emulator's 0.1 V battery field and reads every port-`0x04` selector through the
TI-84 Plus port-`0x02` handler:

```sh
tilem_battery_tmp=$(mktemp -d /tmp/ti84-tilem-battery.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_battery_tmp/tilem"
git -C "$tilem_battery_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python tools/build_tilem_battery_probe.py \
  --source "$tilem_battery_tmp/tilem" \
  --output "$tilem_battery_tmp/tilem-battery-probe" --json

tilem_battery_parent=$(mktemp -d /tmp/ti84-tilem-battery-report.XXXXXX)
python tools/run_tilem_battery_probe.py \
  --binary "$tilem_battery_tmp/tilem-battery-probe" \
  --expected-binary-sha256 \
    47008d660c7ea3e88c07df3d41d5c3e34c51d49850a806d5d2e37d5ca6214029 \
  --output-dir "$tilem_battery_parent/run" --json
```

The guarded run observes masks `0`, `1`, `5`, `7`, and `F` across 3.0–4.5 V.
The shared ROM model maps them to levels 0, 1, 3, 3, and 4. This pins level 2
as unreachable under TilEm's threshold ordering. The manifest labels this as
initialized-core emulator behavior, not a measured calculator voltage.

#### Programmable timer and RTC matrix

`tilem_timer.py` derives source periods and expiry outcomes from the reusable
timer model, then adds pinned scheduling, readback, reset, and RTC edge values.
The C adapter replaces `time()` only inside the probe executable, making every
RTC transition and byte-level rollover deterministic:

```sh
tilem_timer_tmp=$(mktemp -d /tmp/ti84-tilem-timer.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_timer_tmp/tilem"
git -C "$tilem_timer_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python tools/build_tilem_timer_probe.py \
  --source "$tilem_timer_tmp/tilem" \
  --output "$tilem_timer_tmp/tilem-timer-probe" --json

tilem_timer_parent=$(mktemp -d /tmp/ti84-tilem-timer-report.XXXXXX)
python tools/run_tilem_timer_probe.py \
  --binary "$tilem_timer_tmp/tilem-timer-probe" \
  --expected-binary-sha256 \
    fa665079fac1ace807930be8a3836385f6821ee9994c6454039b8ca85bb75d77 \
  --output-dir "$tilem_timer_parent/run" --json
```

The probe checks all crystal and CPU divisor selections, three off-family
values, three port-`0x2F` values under source `0xC0`, mode masking, counter
zero, completion, overflow, interrupt generation, acknowledgement, all three
status mappings, source-write retention, and the unacknowledged non-loop
restart period. The RTC cases commit, advance, freeze, re-enable, reset, and
force a rollover between individual current-register reads.

Two isolated runs produce identical canonical native JSON with SHA-256
`0da06edc402dfb14945d28577f212face4c04c22b3b6ffc3e283a70e0ecb4aa5`.
The manifest identifies the substituted time source and initialized-core
scope. The run does not execute the OS, measure the host clock, or establish
physical divisor, power, rollover, or reset behavior.

#### Keypad and ON-edge matrix

`tilem_keypad.py` derives ordered matrix cases from the reusable model in
`keypad_hardware.py`. The C adapter uses the initialized core's keypad API and
TI-84 Plus port handlers. It checks transitive closure, all eight rows, exact
group-byte storage, ordinary scancode bounds, duplicate events, the separate
ON path, both enabled ON edges, and keypad reset:

```sh
tilem_keypad_tmp=$(mktemp -d /tmp/ti84-tilem-keypad.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_keypad_tmp/tilem"
git -C "$tilem_keypad_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python tools/build_tilem_keypad_probe.py \
  --source "$tilem_keypad_tmp/tilem" \
  --output "$tilem_keypad_tmp/tilem-keypad-probe" --json

tilem_keypad_parent=$(mktemp -d /tmp/ti84-tilem-keypad-report.XXXXXX)
python tools/run_tilem_keypad_probe.py \
  --binary "$tilem_keypad_tmp/tilem-keypad-probe" \
  --expected-binary-sha256 \
    9553bdafadf042dd9af634221b52b8795b572d0c047f839e119dabc957063323 \
  --output-dir "$tilem_keypad_parent/run" --json
```

The ordered reads are `FF`, `FE`, `FF`, `FE`, `FC`, `F8`, `7F`, `FC`, and
`FE`. They cover an unselected matrix, one selected key, an unselected key,
same-column keys, a rectangle, a transitive chain, column 7, all selected
groups, and row 7. Two isolated builds produce the same binary. Their
canonical native JSON has SHA-256
`1f75a4010773a7c8a108d62239cb937e02aa029affa55263906688eb73ba536c`.
The run does not execute the OS or measure electrical settling, switch bounce,
physical ghosting, or ASIC ON edges.

#### MD5-assist edge matrix

`tilem_md5.py` checks an ordered native report against the shared arithmetic
and edge oracle in `md5_hardware.py`. The C adapter calls the TI-84 Plus port
handlers directly. It covers partial and fifth operand writes, control masks,
undefined operand reads, mid-read mutation, modeled clock cost, and full reset:

```sh
tilem_md5_tmp=$(mktemp -d /tmp/ti84-tilem-md5.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_md5_tmp/tilem"
git -C "$tilem_md5_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python tools/build_tilem_md5_probe.py \
  --source "$tilem_md5_tmp/tilem" \
  --output "$tilem_md5_tmp/tilem-md5-probe" --json

tilem_md5_parent=$(mktemp -d /tmp/ti84-tilem-md5-report.XXXXXX)
python tools/run_tilem_md5_probe.py \
  --binary "$tilem_md5_tmp/tilem-md5-probe" \
  --expected-binary-sha256 \
    b461e9720e0c304b26ab95ca814943eddfba670dd7bd1e41b48d53a0f8c689c5 \
  --output-dir "$tilem_md5_parent/run" --json
```

The partial-write results are `11000000`, `33221100`, `44332211`, and
`55443322`. Raw `FF` control writes store shift 31 and mode 3. Mutating `A`
after reading the low result byte assembles `343F97B4` from old result
`D6D117B4` and new result `343F9701`. Two isolated builds produce binary
SHA-256 `b461e9720e0c304b26ab95ca814943eddfba670dd7bd1e41b48d53a0f8c689c5`.
Their canonical native JSON has SHA-256
`97921226800da92b585b6d16a390355c157bf9aa5976fe47d183e87bbcbad1b8`.

The zero-shift cases exercise a nonportable shift-by-32 expression in TilEm's
C source. The manifest therefore scopes these observations to the locked
compiler and exact binary. The run does not execute TI-OS or establish any
physical ASIC behavior.

#### Raw link and assist matrix

`tilem_link.py` validates raw line reads, link-activity interrupts, assist
ports, byte transfers, status acknowledgement, reset retention, and modeled
clock cost against the reusable source model in `link_port.py`. The C adapter
calls the registered TI-84 Plus port handlers and link state machine directly:

```sh
tilem_link_tmp=$(mktemp -d /tmp/ti84-tilem-link.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_link_tmp/tilem"
git -C "$tilem_link_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python tools/build_tilem_link_probe.py \
  --source "$tilem_link_tmp/tilem" \
  --output "$tilem_link_tmp/tilem-link-probe" --json

tilem_link_parent=$(mktemp -d /tmp/ti84-tilem-link-report.XXXXXX)
python tools/run_tilem_link_probe.py \
  --binary "$tilem_link_tmp/tilem-link-probe" \
  --expected-binary-sha256 \
    b878d9be860a92da72c5712e82a4c2974fb3cad125e078e61f8444172b887896 \
  --output-dir "$tilem_link_parent/run" --json
```

The raw truth table is `03 02 01 00`, `12 12 10 10`, `21 20 21 20`, and
`30 30 30 30`. A peer-line transition asserts the enabled activity interrupt.
The disabled assist status is `0x20`; idle-ready is `0x22`; receive completion
is `0x31` before the `0xA5` data read and `0x20` afterward. Illegal both-low
input produces `0x64`; the first status read clears the interrupt but leaves
`0x60`. Reset retains the four auxiliary write registers and external line
state while clearing active assist fields. Direct calls add zero modeled CPU
clocks.

Two isolated builds produce binary SHA-256
`b878d9be860a92da72c5712e82a4c2974fb3cad125e078e61f8444172b887896`.
Their canonical native JSON has SHA-256
`7f649da90850ef5c00bd2472f1cc9772eb6f50b75ed462fc7527bbd7c6a7ce59`.
The manifest limits the result to pinned initialized-core TilEm behavior. The
run does not execute TI-OS, exercise a virtual-cable lifecycle, measure
electrical timing, or establish physical reset retention.

### Pinned MAME Flash probe

`mame_runtime.py` provides shared MAME identity, configuration, isolated
headless-environment, command, process, logging, and manifest helpers. Its
guarded probe operation validates the executable, ROM, and Lua script before
creating the runtime tree. `mame_trace.py` reuses the lower-level library for
I/O traces. The Flash-specific parser and oracle are in
`mame_flash.py`; `run_mame_flash_probe.py` is the guarded CLI. The independent
sector and chip-erase types, parser, and image oracle are in
`mame_flash_erase.py`. `mame_flash_gate.py` provides the typed CPU-visible gate
report and complete-image oracle; `run_mame_flash_gate_probe.py` is its guarded
CLI.

The CLI requires a caller-supplied executable SHA-256 and MAME 0.287. It also
requires the exact local OS 2.55MP ROM. It places the ROM, configuration,
NVRAM, and snapshots under a new output directory, retains standard output and
standard error, and writes a manifest with every input and result identity.
Run the packaged MAME through Nix when it is not installed globally:

```sh
mame_flash_parent=$(mktemp -d /tmp/ti84-mame-flash.XXXXXX)
nix shell nixpkgs#mame --command python tools/run_mame_flash_probe.py \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_flash_parent/run" --json
```

The Lua adapter writes and reads the `ti84pv3` machine's mapped `:membank0`
Flash interface. It checks autoselect, reset, CFI, unlock bypass, legal and
illegal byte programming, one 8 KiB top-sector erase, the incorrect 64 KiB
busy-read range, and timer completion. The Python oracle compares all reported
fields with the pinned MAME source model. It also compares the complete saved
1 MiB Flash array with its own mutation model and requires output SHA-256
`1dc4eec678252588df24118e96603b6c80806b8b9ea8e0e12b2169ac6aae3935`.
The adapter does not execute a TI-OS Flash routine or a physical command.

The gate adapter maps Flash page `08` into CPU program space, reads gate status
through I/O port `0x02`, and changes port `0x14` between AMD command phases. It
programs the same byte with a complete command while locked, a locked-to-
unlocked transition, and an unlocked-to-locked transition. All three commands
take effect, with final byte `20`; the complete saved image must have SHA-256
`2fd21a6b139a641d40a71a0e68df492e4555e79c6f1cf44858b4dcfd9158bbeb`:

```sh
mame_gate_parent=$(mktemp -d /tmp/ti84-mame-gate.XXXXXX)
nix shell nixpkgs#mame --command python tools/run_mame_flash_gate_probe.py \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_gate_parent/run" --json
```

The locked, unlocked, and relocked status reads are `C3`, `C7`, and `C3`.
CPU-mapped and direct-device reads agree after each command. This confirms the
MAME driver's missing write gate through its CPU and I/O spaces, but says
nothing about the physical ASIC.

`run_mame_flash_erase_probe.py` uses a separate runtime tree. It seeds each
selected sector and adjacent probe through byte-program commands, waits for
array reads before advancing, and then chip-erases the isolated image. A
periodic callback observes chip completion because erasing boot Flash stops
the calculator driver from producing frame callbacks. The final image must be
exactly one MiB of `FF` with SHA-256
`f5fb04aa5b882706b9309e885f19477261336ef76a150c3b4d3489dfac3953ec`:

```sh
mame_erase_parent=$(mktemp -d /tmp/ti84-mame-erase.XXXXXX)
nix shell nixpkgs#mame --command python tools/run_mame_flash_erase_probe.py \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_erase_parent/run" --json
```

The native report pins sector completion frames `50`, `75`, `88`, `101`, and
`126`. Chip erase starts at emulated second 2 and exposes array data at second
18. The report oracle also verifies selected mutation ranges, fixed 64 KiB busy
ranges, stale chip-erase status scope, and every boundary byte. This remains
MAME behavior rather than TI-OS or physical evidence.

### Pinned MAME MD5-port probe

`mame_md5.py` parses the native port report and calculates the expected first
padded-`"abc"` result with the independent arithmetic model in
`md5_hardware.py`. `run_mame_md5_probe.py` uses the shared guarded MAME runtime:

```sh
mame_md5_parent=$(mktemp -d /tmp/ti84-mame-md5.XXXXXX)
nix shell nixpkgs#mame --command python tools/run_mame_md5_probe.py \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_md5_parent/run" --json
```

The Lua adapter reads ports `0x18`–`0x1F`, writes a distinct value to every
port, reads them again, and issues the complete 30-access transaction used by
the first MD5 step. Initial, post-pattern, and post-transaction reads are eight
zero bytes. The result is `0x00000000`; the independent expected result is
`0xD6D117B4`. Two isolated runs produce identical parsed reports. This is
CPU-I/O-space evidence for MAME 0.287's absent MD5 block, not retail-ROM or
physical-hardware evidence.

### Pinned MAME raw-link probe

`mame_link.py` parses raw-write, connector-output, peer-input, and assist-port
cases. Its oracle derives the expected values from `link_port.py` rather than
duplicating the PCR and connector formulas. Run it through the shared guarded
MAME runtime:

```sh
mame_link_parent=$(mktemp -d /tmp/ti84-mame-link.XXXXXX)
nix shell nixpkgs#mame --command python tools/run_mame_link_probe.py \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_link_parent/run" --json
```

The Lua adapter issues writes `00`, `01`, `02`, `03`, `14`, `28`, and `3C`
through CPU I/O space. It records port-`0x00` readback and the link-port
device's saved tip/ring output fields after each write. It also injects all
four peer pull-low masks through the corresponding saved input fields. Normal
writes produce reads `03`, `12`, `21`, and `30` while releasing both modeled
connector outputs. The peer reads are `03`, `02`, `01`, and `00`.

Port `0x02` returns `C3`. Ports `0x08`–`0x0D` return six zero bytes before and
after patterned writes. Two isolated runs produce identical parsed reports.
This validates MAME's internal CPU, PCR, and connector-facing state. It does
not execute a TI-OS transfer, attach an optional MAME link device, or measure
physical electrical behavior.

### Pinned MAME keypad probe

`mame_keypad.py` parses the ordered live-input matrix and checks it against the
MAME branch of the reusable model in `keypad_hardware.py`. The guarded CLI uses
the shared MAME runtime:

```sh
mame_keypad_parent=$(mktemp -d /tmp/ti84-mame-keypad.XXXXXX)
nix shell nixpkgs#mame --command python tools/run_mame_keypad_probe.py \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_keypad_parent/run" --json
```

The Lua adapter resolves group masks from MAME's `:BIT0`–`:BIT7` live input
fields. Forced input values cross one video-frame update before the adapter
writes and reads port `0x01` through the main CPU I/O space. The ordered reads
are `FF`, `FF`, `FE`, `FF`, `FF`, `FE`, `7F`, and `FD` for the release-byte,
bit-7-only, single-key, unselected-key, same-column, rectangle, column-7, and
all-selected cases. The same-column `FF` result directly confirms MAME's XOR
cancellation. The rectangle `FE` result confirms that MAME does not apply
TilEm or Wabbitemu matrix closure.

Two isolated runs produce byte-identical native reports with SHA-256
`f684472b1f139b649245f54d140190bd5f91bf2508aa9e4764ddc0ce88079477`.
This validates MAME 0.287's live input fields and keypad handlers. It does not
execute the TI-OS scanner or measure electrical settling, bounce, or a physical
matrix.

### Pinned MAME legacy-interrupt probe

`mame_interrupt.py` parses shared status reads, mask writes, ON transitions,
standard-timer latches, and reset retention. Its oracle uses the immutable MAME
state model in `interrupt_controller.py`. Run it through the shared guarded
runtime:

```sh
mame_interrupt_parent=$(mktemp -d /tmp/ti84-mame-interrupt.XXXXXX)
nix shell nixpkgs#mame --command python tools/run_mame_interrupt_probe.py \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_interrupt_parent/run" --json
```

The Lua adapter parks the Z80 in `DI` RAM, disables programmable timers, and
uses only CPU-I/O-space accesses for the legacy controller. Ports `0x03` and
`0x04` both read `08` after each mask write in `00 01 02 04 08 10 FF`.
Writing `07` to port `0x02`, then applying port-`0x03` masks `01 06 FF 00`,
produces status `09 0E 0F 08`.

The live ON sequence produces `00 00 08 01 09 08` for masked press,
held-button enable, release, enabled press, enabled release, and
acknowledgement. One frame with timer 1, timer 2, or both enabled produces
`0A`, `0C`, or `0E`. Soft reset retains seeded status `0F`; after direct status
clear, the retained masks regenerate timer status `0E`, and a new ON press
produces `07`.

Two isolated runs produce identical canonical parsed native JSON with SHA-256
`bb4b38d444692b5136d96264fa3acf9fe95ef2f6a1879ab72e9a2ad8077c1def`.
This is MAME legacy-interrupt, input-sampling, scheduler, and reset evidence.
It does not establish physical interrupt edges, timer rates, acknowledgement,
link wake, low power, or reset retention.

### Pinned MAME timer and RTC probe

`mame_timer.py` parses the complete timer, status, auxiliary-port, and RTC-port
report. Its oracle derives source divisors and expiry polarity from
`timer_hardware.py`. Run it through the shared guarded MAME runtime:

```sh
mame_timer_parent=$(mktemp -d /tmp/ti84-mame-timer.XXXXXX)
nix shell nixpkgs#mame --command python tools/run_mame_timer_probe.py \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_timer_parent/run" --json
```

The Lua adapter maps page-0 RAM at `0xC000` and parks the Z80 in `DI; JR $`.
It then drives ports through the CPU I/O space while MAME's scheduler advances.
Sources `01`, `41`, and `81` each reduce counter `FF` to `EA` during one 20 ms
frame. This is 21 decrements: the initial zero-delay callback plus 20 periods
at 1,024 Hz. The run also records idle counter zero, source-zero disable,
mode-bit masking, inverted interrupt polarity, loop self-clearing, and a mode
write that clears completion for all three timers.

Ports `0x2D`–`0x2F` and `0x40`–`0x48` return zero before and after patterned
writes. Two isolated runs produce byte-identical native reports with SHA-256
`5aab56b737495fef9c953522e1a3eee47d3e96637bc8266ce6258ff10d3e2c26`.
This is MAME 0.287 callback and mapping evidence. It does not execute the TI-OS
timer API or measure physical crystal, RTC, interrupt, or low-power behavior.

### Pinned MAME LCD-controller probe

`mame_lcd.py` parses controller fields, status, pointer walks, read-latch
values, 6-bit packing, and ASIC-port coverage. Its oracle reuses the MAME
profile and pointer/latch models in `lcd_controller.py`:

```sh
mame_lcd_parent=$(mktemp -d /tmp/ti84-mame-lcd.XXXXXX)
nix shell nixpkgs#mame --command python tools/run_mame_lcd_probe.py \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_lcd_parent/run" --json
```

The Lua adapter parks the Z80 in page-0 RAM. It reads the untouched controller
startup state, then seeds named save items between independent cases. All
controller transfers use the mirrored CPU I/O ports. The run verifies status
`43` at reset, permanent busy-clear status, command decoding, ports `0x12` and
`0x13`, four writes across backing indices 14–17, safe direct indices 15 and
31, the `00 12 34` dummy-read sequence, and `FD 50` from two 6-bit writes.

Port `0x02` returns `C3`. Ports `0x29`–`0x2F` return zero before and after
patterned writes. Two isolated runs produce byte-identical native reports with
SHA-256 `d6930650a96383710be7ebb772675b5a494cba2450827b12a535c963fa464bfc`.
The adapter deliberately omits row 63, column 31 because the source computes
index 976 outside the 960-byte C++ array. This is MAME behavior, not physical
controller or ASIC evidence.

### Pinned MAME ASIC-control probe

`mame_asic.py` combines the reusable ASIC-control and MAME timing profiles with
a typed native report. The Lua adapter drives mapped and absent ports through
the CPU I/O space, runs a fixed RAM counter at both clocks, and schedules one
soft reset:

```sh
mame_asic_parent=$(mktemp -d /tmp/ti84-mame-asic.XXXXXX)
nix shell nixpkgs#mame --command python tools/run_mame_asic_probe.py \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_asic_parent/run" --json
```

Port-`0x14` writes `00 01 02 3F 40 FF` produce port-`0x02` reads
`C3 C7 CB FF C3 FF`; port `0x14` always reads zero. Port `0x20` retains every
raw byte in `00 01 02 03 FF`. The 50-T-state loop advances 12,000 times in
100 ms at write zero and 30,000 times after write one, matching the source's
6 MHz and 15 MHz clocks.

Port `0x21` accepts writes with the gate closed and reads `value & 0x0F`.
Ports `0x22`–`0x2F` and `0x39`–`0x3A` discard patterned writes. Across
`0x4A`–`0x5B`, only constant reads `0x55 = 0x1F` and `0x56 = 0x00` are mapped.
A soft reset returns to `PC = 0x0000` while retaining gate one, raw speed
`0x03`, and port-`0x21 = 0x0B` from write `0xAB`.

Two isolated runs produce identical canonical parsed native JSON with SHA-256
`bbf6c3c8f05a43daa854f404401aa4d7cd8ed89599c00a2c211541e0416eb3e5`.
This is MAME 0.287 control and reset evidence. It does not establish physical
battery, protection, clock, GPIO, USB, or warm-reset behavior.

### Pinned MAME memory-mapper probe

`mame_mapper.py` parses five fresh-machine reports and checks them against the
MAME profile in `memory_mapper.py`. A fresh process is required for each
fixed-page case because the TI-84 Plus driver does not register `m_booting` as
a saved item. Run the complete guarded matrix through the shared runtime:

```sh
mame_mapper_parent=$(mktemp -d /tmp/ti84-mame-mapper.XXXXXX)
nix shell nixpkgs#mame --command python tools/run_mame_mapper_probe.py \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_mapper_parent/run" --json
```

One case reads the untouched reset map through Lua. Lua CPU-program-space
reads carry normal read side effects in this build, so its A read changes the
fixed prefix from page `3F`'s `3E 07` to page `00`'s `DB 02`. Three other
cases execute `LD A,(nn)` from seeded RAM. Independent B leaves page `3F`
fixed; A and paired B select fixed page `00`. The mapping case verifies the
six-bit Flash mask, port-`0x05`'s three-bit mask, adjacent paired pages, and
safe RAM selectors through `0x86`.

Ports `0x0E`, `0x0F`, `0x27`, and `0x28` return zero after patterned writes.
Seeded markers show that reads and writes continue through the underlying B
and C banks. A fetched program returns marker `22` from RAM page 2 rather than
candidate overlay marker `11` from RAM page 1. Selector `0x87` is deliberately
not executed because MAME maps only seven 16 KiB RAM pages.

Two isolated matrices produce identical canonical parsed native JSON with
SHA-256 `6466b5eecedb20332e915337b9e5007a4704af48fc45c26c6ffca1b613910967`.
This is MAME 0.287 mapper evidence. It does not establish physical overlay,
RAM-decoder, or boot-latch behavior.

### Pinned Wabbitemu headless adapter

The repository carries a minimal native adapter rather than a fork of
Wabbitemu. Download and verify the pinned codeload archive, then build through
the guarded CLI. Use `nix develop -c` when `g++` is not installed globally:

```sh
wabbit_tmp=$(mktemp -d /tmp/ti84-wabbitemu.XXXXXX)
curl -L \
  https://codeload.github.com/sputt/wabbitemu/tar.gz/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422 \
  -o "$wabbit_tmp/wabbitemu.tar.gz"
printf '%s  %s\n' \
  e65e20f5b45dbf5312e92a2619e3fbc0dfe228d4464134753fdc4930b7d12ac4 \
  "$wabbit_tmp/wabbitemu.tar.gz" | sha256sum -c -
tar -xzf "$wabbit_tmp/wabbitemu.tar.gz" -C "$wabbit_tmp"
nix develop -c python tools/build_wabbitemu_headless.py \
  --source "$wabbit_tmp/wabbitemu-48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422" \
  --output "$wabbit_tmp/wabbitemu-headless" --json
```

The builder additionally checks the extracted 334-file path-and-content hash
`a8a4f97fc7952770bed317b4a477f80345894da38d14fad8f0bf0ee60aae71ba`
and the translation-unit hashes. It compiles Wabbitemu's TI-84 Plus CPU and
hardware core directly. The adapter removes an MSVC-only `__pragma` construct
at preprocessing time and stubs callbacks used only by the GUI debugger and
disabled audio; it does not patch CPU, Flash, memory, device, keypad,
interrupt, or LCD behavior.

The same binary has an explicit guarded execution-probe mode. The Python CLI
builds exact-ROM fixtures through the shared library, waits for the retail boot
to establish and relock all five protection registers, and then injects the
validated 75-byte probe into physical RAM page 1:

```sh
wabbit_probe_parent=$(mktemp -d)
nix develop -c python tools/run_wabbitemu_execution_probe.py \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_probe_parent/run" --json
```

The default page set is `07`, `08`, `09`, `29`, and `2A`. Page `09` separates
Wabbitemu's lower-exclusive Flash predicate from TilEm's inclusive predicate.
The native adapter verifies the marker bytes in the fixture ROM and the
complete logical RAM copy before setting `PC=0x9D95`. Its violation callback
records the event and invokes Wabbitemu's normal `CPU_reset` function. This is
an emulator-core injection, not an OS/UI execution path or physical-hardware
result. The CLI rejects unexpected bounds, mappings, marker values, control
flow, resets, hashes, and classifications.

The binary also exposes a direct Flash byte-program probe. This mode initializes
the core, unlocks its in-memory ASIC gate, and sends `AA 55 A0` plus the target
write through `CPU_mem_write`. It reads the target twice through
`CPU_mem_read`. The guarded CLI requires the exact OS 2.55MP image. It checks
the native report against fixed launch expectations and the independent source
model in `flash_hardware.py`:

```sh
wabbit_program_parent=$(mktemp -d /tmp/ti84-wabbit-program.XXXXXX)
python tools/run_wabbitemu_flash_program_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_program_parent/run" --json
```

The default matrix covers three legal requests and four illegal `0→1`
requests, including both initial DQ6 states for one pair. The repeatable
`--case INITIAL:REQUESTED[:TOGGLE]` option replaces the default matrix. The
manifest records the complete native fields plus the ROM and binary hashes.
This mode tests initialized Wabbitemu command-state behavior. It does not run
the retail ROM worker and provides no physical-device or timing evidence.

Run the guarded command-family matrix separately:

```sh
wabbit_command_parent=$(mktemp -d /tmp/ti84-wabbit-command.XXXXXX)
python tools/run_wabbitemu_flash_command_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_command_parent/run" --json
```

This mode checks autoselect, reset from autoselect and a partial unlock,
repeated fast programming and exit, one ordinary 64 KiB sector erase, and chip
erase through the native core interfaces. It also verifies that a CFI query
and an erase-suspend/resume attempt create no command state or array mutation.
The sector case seeds its complete expected range plus both adjacent boundary
bytes. The chip case counts the complete array and seeds the last boot-page
byte. All mutations remain in Wabbitemu's allocated Flash array; the source ROM
file is read-only input. The guarded CLI rejects every unexpected state,
identifier, range, mutation count, hash, and T-state count.

Run the guarded retail-worker matrix separately:

```sh
wabbit_worker_parent=$(mktemp -d /tmp/ti84-wabbit-worker.XXXXXX)
python tools/run_wabbitemu_flash_worker_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_worker_parent/run" --json
```

This mode boots the exact ROM and injects only `rst 28h`, bcall ID `8087h`,
`HALT`, and one source byte into RAM page 1. It sets the documented ABI
registers and directly opens Wabbitemu's in-memory Flash gate. The retail bcall
copies its original worker from `3F:4CCA` and runs it at `0x8100`. The default
matrix covers legal success, illegal lower-bit false success, illegal DQ7
failure with both stored DQ5 states, and both initial DQ6 states. It does not
exercise the protected unlock sequence, an OS/UI caller, or physical Flash.

#### Retail Flash bcall usage probe

The programmer-facing examples have a separate assembled probe. The reusable
`flash_bcall_examples.py` library assembles the fixture, parses the native
report, and checks bcall visits, copied-worker entries, return values, scratch
state, array bytes, `_FlashToRam` copies, the port-`0x23` value, and IFF2. The
CLI requires the exact OS 2.55MP ROM and refuses to reuse an output directory:

```sh
python tools/check_executable_snippets.py --json

wabbit_bcall_parent=$(mktemp -d /tmp/ti84-wabbit-bcalls.XXXXXX)
nix develop -c python tools/run_wabbitemu_flash_bcall_probe.py \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_bcall_parent/run" --json
```

The 2026-08-10 run assembled 264 bytes, booted the retail ROM for 134,845 CPU
steps, and completed the injected probe in 4,346 steps. It visited every public
modifying Flash entry plus `_SetFlashLowerBound`. The shared
`_WriteFlashUnsafe`, `_WriteAByte`, and `_EraseFlash` bodies ran four, two, and
three times as their wrappers converged. Seven `_FlashToRam` calls brought the
RAM-worker-entry count to 14.

Both block writes, both byte writes, `_EraseFlashPage`, and `_EraseFlash`
returned `AF=0x0044`. The safe block stored `A5 5A` at `08:4100`; the unsafe
block stored `3C C3` at `3E:4100`. The byte entries stored `FC` at `08:4102`
and `F8` at `3E:4102`. The page, raw, and certificate erases produced `FF` at
`0C:4000`, `10:4567`, and `3E:6001`. All seven array results matched their
readback buffers. `_EraseCertificateSector` preserved seeded `AF=0xA545` for
`HL=0x6001`; `OP1=0xF8`, the context scratch bit was clear, port `0x23` held
`0x2A`, and IFF2 was clear after `_SetFlashLowerBound`.

The assembly-source SHA-256 was
`ba91fa8a4d1d7c816b742a426dbb0216f927ec209f368534a13748d4683b42e7`,
the machine-code SHA-256 was
`8f9ca5975c418871ba831c3536cba6e7e4f9f368520e1ad37650ef9c54d9249c`,
and the rebuilt adapter SHA-256 was
`6dec9c4f4a87466a27baa5e5e4fc90c644506d0a90baa9278d17407b9bc9dd36`.
The runner directly opens only Wabbitemu's in-memory gate and seeds disposable
array bytes. This is exact retail-ROM execution under a pinned emulator, not a
test of the protected unlock sequence, OS allocation or journaling, power loss,
timing, or physical Flash.

Run the guarded Wabbitemu MD5 edge probe through the same binary:

```sh
wabbit_md5_parent=$(mktemp -d /tmp/ti84-wabbit-md5.XXXXXX)
python tools/run_wabbitemu_md5_edge_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_md5_parent/run" --json
```

This direct-core mode reads the fresh operand and result ports, writes one,
three, four, and five bytes to one sliding operand, sends high control bits,
and mutates an operand between result-byte reads. The reusable oracle checks
every result with `md5_assist_value`. This is initialized Wabbitemu device
behavior, not retail-ROM execution, physical ASIC behavior, or timing
evidence.

Run the guarded keypad and ON-edge probe through the same binary:

```sh
wabbit_keypad_parent=$(mktemp -d /tmp/ti84-wabbit-keypad.XXXXXX)
python tools/run_wabbitemu_keypad_edge_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_keypad_parent/run" --json
```

This initialized-core mode checks a single key, same-column keys in two
selected rows, a three-key rectangle, a transitive chain, and ignored row 7.
It also reads port `0x04` around ON press, acknowledgement while held, release,
and a second press. The probe invokes Wabbitemu's standard-interrupt device
callback at explicit observation points and advances no T-states. Its results
therefore establish emulator state transitions, not TI-OS execution, physical
electrical behavior, or timing.

Run the guarded programmable-timer and RTC edge probe through the same binary:

```sh
wabbit_timer_parent=$(mktemp -d /tmp/ti84-wabbit-timer.XXXXXX)
python tools/run_wabbitemu_timer_edge_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_timer_parent/run" --json
```

This initialized-core mode advances Wabbitemu's emulated crystal ticks,
T-states, and elapsed seconds explicitly. It compares crystal and CPU catch-up,
expires a zero counter, acknowledges completion, observes the interrupt line
during and after `HALT`, and commits, advances, and freezes the RTC. The
reusable oracle derives source divisors and expiry fields from
`timer_hardware.py`. This is emulator state-machine evidence rather than
TI-OS execution, host timing, or physical ASIC behavior.

Run the assembled programmable-timer physical discriminator through the shared
injected-program runner:

```sh
wabbit_timer_physical_parent=$(mktemp -d /tmp/ti84-wabbit-timer-physical.XXXXXX)
python tools/run_wabbitemu_timer_physical_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --expected-binary-sha256 \
    3acb6a18280f9c42d6fe324188eab73f87280ee70b973e1251fcfa50f54fb14e \
  --output-dir "$wabbit_timer_physical_parent/run" --json
```

This mode boots the retail OS, injects the exact `HWTMR` image into logical
user RAM, and stops before `_CreateAppVar`. It verifies the probe ID, frame
length, Wabbitemu-specific timer classifications, and complete guarded-state
restoration. The same native runner handles `HWPFX`; its shared injection,
execution-limit, stop-address, frame, and violation-reset checks avoid a second
probe-specific control path. The retained manifest identifies the ROM, binary,
machine code, runtime counters, decoded frame, and evidence scope. No result
from a physical calculator is implied.

Run the controlled retail USB boot paths through the same binary:

```sh
wabbit_usb_rom_parent=$(mktemp -d /tmp/ti84-wabbit-usb-rom.XXXXXX)
python tools/run_wabbitemu_usb_rom_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --expected-binary-sha256 \
    3acb6a18280f9c42d6fe324188eab73f87280ee70b973e1251fcfa50f54fb14e \
  --output-dir "$wabbit_usb_rom_parent/run" --json
```

This mode boots the retail ROM and uses short RAM-resident bcall harnesses for
`_InitUSB` and `_AttemptUSBOSReceive`. Controlled handlers replace only the
USB controller and endpoint ports. Four constant-memory summaries report
success, handshake timeout, frame timeout, and event-`0x40` dispatch. The
runner retains counters and at most 128 port writes per case instead of an
instruction log. It also compares the complete Flash image and stops before
endpoint payload handling. The result is controlled ROM-execution evidence,
not connected-device, PHY, or physical-calculator evidence.

Continue into the installer record dispatcher with exact scripted endpoint
packets:

```sh
wabbit_usb_receive_parent=$(mktemp -d /tmp/ti84-wabbit-usb-receive.XXXXXX)
nix develop -c python tools/run_wabbitemu_usb_receive_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --expected-binary-sha256 \
    3acb6a18280f9c42d6fe324188eab73f87280ee70b973e1251fcfa50f54fb14e \
  --output-dir "$wabbit_usb_receive_parent/run" --json
```

This constant-memory mode validates the ROM's type-`0x04` request, the host
type-`0x05` acknowledgement, service `0x0005`, page `0x3E`, record dispatch,
page rejection, error cleanup, and the complete unchanged Flash array. It
seeds the already-displayed progress page immediately before
`_DisplayOSProgress` to isolate the downstream rejection; the manifest records
that intervention. The adapter retains three received packets, two transmitted
packets, fixed boundary counters, and the final state instead of a textual
instruction log.

## Pinning jsTIfied source behavior

The Cemetech project page identifies jsTIfied, but the reusable profile checks
the deployed JavaScript itself. Download and verify the exact `20170706a`
artifact with:

```sh
nix develop -c curl -L \
  'https://www.cemetech.net/projects/jstified/jstified_compressed.js?20170706a' \
  -o /tmp/jstified_compressed.js
nix develop -c env PYTHONPATH=tools python \
  tools/describe_jstified_hardware.py /tmp/jstified_compressed.js --json
```

`tools/jstified_hardware.py` requires size 297,128 and SHA-256
`c7325a38f976f64eaa34182da17d838fe4831eece4650b92d5db710cf7a8fc5b`,
then verifies source fingerprints for Flash commands, mapping, execution
protection, timers, LCD, link assist, and fixed USB reads. Its feature profile
is source evidence for a fourth emulator. The readable GitHub mirror at commit
`56246a1181f90123a843ea17eb9e0f2fcda65113` aids review but is explicitly not
treated as byte-identical to the deployed artifact.

Run the guarded ASIC-control edge probe through the same binary:

```sh
wabbit_asic_parent=$(mktemp -d /tmp/ti84-wabbit-asic.XXXXXX)
python tools/run_wabbitemu_asic_edge_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_asic_parent/run" --json
```

This initialized-core mode reads port `0x02` across the in-memory Flash gate,
changes Wabbitemu's RAM revision for port `0x15`, and checks port `0x21` while
locked and directly unlocked. It reports both port-`0x21` readback and the
internal Flash-group and RAM-execution fields, making the readback defect
observable. It also distinguishes absent port `0x39` from the byte latch at
port `0x3A`. This is emulator state evidence, not a retail protected-byte
sequence or physical battery, identity, protection, or GPIO evidence.

Run the guarded protected-boundary port probe through the same binary:

```sh
wabbit_protected_port_parent=$(mktemp -d /tmp/ti84-wabbit-protected-port.XXXXXX)
python tools/run_wabbitemu_protection_port_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_protected_port_parent/run" --json
```

This initialized-core mode checks registration and the shared locked-write
gate at ports `0x22`–`0x26`. After opening the emulator's in-memory gate, it
checks low-byte preservation, port-`0x24` high-field clearing, and the
`0x3F`/`0x40`/`0x41`/`0xFF` RAM-bound wrap matrix. Its reusable oracle is
backed by `execution_protection.py`. Direct lock and high-field changes isolate
the registered handlers; they do not execute the retail protected-byte
sequence, fetch through the resulting bounds, or measure physical behavior.

Run the guarded LCD-controller and bus-timing edge probe through the same
binary:

```sh
wabbit_lcd_parent=$(mktemp -d /tmp/ti84-wabbit-lcd.XXXXXX)
python tools/run_wabbitemu_lcd_edge_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_lcd_parent/run" --json
```

This initialized-core mode checks the fixed controller guard at 59 and 60
T-states, an early rejected write, hidden-column increment and alias behavior,
the data-read latch, absent ports `0x12` and `0x13`, and the reset-status
`word_len` defect. It also checks the strict 240-T-state ready boundary,
read-versus-write timestamp policy, active LCD instruction delay, all six
memory-wait fields, and default speed clamp. The reusable oracle derives the
expected pointer, latch, ready, wait, and speed results from
`lcd_controller.py` and `bus_timing.py`. This is Wabbitemu state-machine
evidence, not TI-OS execution, host timing, or physical LCD/ASIC behavior.

Run the guarded CPU-speed and delay-register edge probe through the same
binary:

```sh
wabbit_speed_parent=$(mktemp -d /tmp/ti84-wabbit-speed.XXXXXX)
python tools/run_wabbitemu_speed_edge_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_speed_parent/run" --json
```

This initialized-core mode checks reset readback, the default 6/15 MHz speed
clamp, the internally enabled 20/25 MHz modes, raw readback across ports
`0x29`–`0x2F`, and all four Flash/RAM wait-gate combinations. It also verifies
that Wabbitemu's generic port-`0x2D` latch does not change its timer, LCD,
`HALT`, interrupt, frequency, or T-state state. The reusable oracle derives
speed and wait fields from `bus_timing.py`. Directly setting
`timer_version = 1` represents front-end configuration, not a calculator port.
This is emulator-handler evidence, not TI-OS execution, electrical timing, or
physical low-power behavior.

Run the guarded standard-interrupt and low-power edge probe through the same
binary:

```sh
wabbit_interrupt_parent=$(mktemp -d /tmp/ti84-wabbit-interrupt.XXXXXX)
python tools/run_wabbitemu_interrupt_edge_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_interrupt_parent/run" --json
```

This initialized-core mode checks full port-`0x03` readback, ON-latch
acknowledgement, all four standard-timer rates, the strict timer-expiry edge,
port-`0x03` and port-`0x02` timer catch-up, programmable completion bits, and
Wabbitemu's LCD-based low-power approximation. Its reusable oracle derives
mask and status fields from `interrupt_controller.py`. This is emulator
state-machine evidence, not TI-OS execution, host timing, physical interrupt
edges, or ASIC power-domain behavior.

Run the guarded raw-link and link-assist edge probe through the same binary:

```sh
wabbit_link_parent=$(mktemp -d /tmp/ti84-wabbit-link.XXXXXX)
python tools/run_wabbitemu_link_edge_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_link_parent/run" --json
```

This initialized-core mode checks all 16 local/peer raw-line combinations,
high write-bit masking, raw transition interrupt omission, assist port
coverage, idle-ready, one complete `0xA5` send and receive, data-register
acknowledgement, and seeded-error read-to-clear behavior. The reusable oracle
derives the raw matrix, LSB-first byte order, and status fields from
`link_port.py`. It does not run TI-OS, exercise virtual-cable lifecycle code,
or measure electrical levels and timing.

Run the guarded Fake USB edge probe through the same binary:

```sh
wabbit_usb_parent=$(mktemp -d /tmp/ti84-wabbit-usb.XXXXXX)
python tools/run_wabbitemu_usb_edge_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_usb_parent/run" --json
```

This initialized-core mode checks mapped and absent ports, reset reads and
internal fields, event-mask storage, mask-independent and repeatable line
events, the active-low interrupt-summary matrix, and the protocol-enable and
device-address latches. Direct field seeding isolates the port-`0x4A` and
port-`0x4D` handler arithmetic that registered ports cannot otherwise reach.
The reusable oracle in `wabbitemu_usb_probe.py` derives every expected value
from `usb_hardware.py`. This is pinned Wabbitemu handler evidence, not TI-OS
execution, a connected endpoint transaction, or physical USB behavior.

Run the guarded memory-mapper edge probe through the same binary:

```sh
wabbit_mapper_parent=$(mktemp -d /tmp/ti84-wabbit-mapper.XXXXXX)
python tools/run_wabbitemu_mapper_edge_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_mapper_parent/run" --json
```

This initialized-core mode checks mapper-port registration, reset mapping,
the fixed-page opcode handoff, raw selector storage versus visible readback,
the even-page paired expression, and both forced-RAM ranges. Seeded backing
bytes distinguish boundary reads, low-level write destinations, and fetched
NOP versus HALT bytes in independent and paired modes. The reusable oracle in
`wabbitemu_mapper_probe.py` derives the expected mappings from
`memory_mapper.py`. This is pinned emulator routing evidence, not TI-OS
execution, Flash command acceptance, or physical ASIC behavior.

Run the guarded reset-retention probe through the rebuilt binary:

```sh
wabbit_reset_parent=$(mktemp -d /tmp/ti84-wabbit-reset.XXXXXX)
python tools/run_wabbitemu_reset_retention_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --expected-binary-sha256 \
    386be74e738f2a0f9ad17f12bae4cd44994b5a73835ab10d488c7b8232afd87e \
  --output-dir "$wabbit_reset_parent/run" --json
```

This mode seeds state directly, calls `CPU_reset`, performs the frontend's
`CPU_reset` plus LCD-reset sequence, and triggers two execution violations.
The reusable source model in `wabbitemu_reset.py` separates cleared, rebuilt,
and retained fields. Its oracle checks all 14 retained component groups, the
TI-84 Plus reset mapping, LCD-visible frontend state, and the program/error
Flash-state paths through the remainder of `CPU_step`. The CLI guards the exact
ROM and native-binary hashes. It does not run TI-OS reset code or measure
physical reset and power-loss retention.

Run one replayed image with an input-identity guard and a separate output:

```sh
python tools/run_wabbitemu_headless.py "$replay_dir/gc-phase-ff.rom" \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output "$wabbit_tmp/gc-recovered-ff.rom" \
  --expected-input-sha256 \
    4e484ad4b99f07a333ae3845ee795b36cb6181e9a829261b2d52ff7931ac8f05 \
  --expected-output-sha256 \
    8c857701d7da118d5c5f4c240ee21af91a10b95539059e74fb5e423368a683f9 \
  --expect-gate-write '3F:4163:01:1>0' \
  --expect-gate-write '3F:4221:00:0>1' \
  --expect-gate-write '3D:60A6:01:1>0' \
  --expect-gate-write '3D:5CEF:00:0>1' \
  --require-retail-flash-path \
  --json
```

The runner starts with fresh RAM, models the ON press/release used by the TilEm
recovery macro, samples the entire Flash array while executing, and reports
the known page-`0x3C` recovery points it executes. The repeated gate-write
options require the complete ordered list, including the boot-page pair and
the recovery unlock/relock pair. `--require-retail-flash-path` requires an
accepted unlock and relock, matching `_WriteFlashUnsafe` and byte-identical
copied-worker entry counts, at least one program write per worker, one success
tail per worker, and no failure tail. Settling means ten identical samples one
million instructions apart after at least 20 million instructions; it is not
a physical timing claim. Compare the reported complete output hash, not only
the phase byte.

The recovery path begins at the startup call at `00:0D73`. Its bjump stub
enters `3D:6098`, whose protected bytes unlock at `3D:60A6`. The wrapper calls
the `00:2BAD` bjump stub to reach `3C:7BC7`, then jumps to the shared page-`3D`
lock sequence after recovery returns. The native report represents each gate
write and lock transition as typed JSON fields. It also reports separate
counts for public write/erase bcalls, exact block-worker entries, data writes,
and success/failure reset tails.

The reconstructed phase-`0xF0` image executes the `3C:7CE3` branch and settles
after 20,000,000 instructions. Its output SHA-256 is
`39113ee67921340b8817e35576a8f8fda467122af7713b099f399512d65d9bc3`.
Capture and replay the matching TilEm recovery before comparing complete
outputs:

```sh
$TILEM --headless --rom "$phase_dir/gc-phase-f0.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/boot-recovery.macro \
  --trace /tmp/gcf0-restart.trace --trace-range all

python tools/replay_flash_trace.py /tmp/gcf0-restart.trace \
  --rom "$phase_dir/gc-phase-f0.rom" \
  --expected-rom-sha256 \
    df49d6ec77483e33944fdbcee969084fc065b01a4e44327f83246a9de363fcb2 \
  --output /tmp/gcf0-recovered-tilem.rom \
  --accept-command-shapes --json

python tools/run_wabbitemu_headless.py "$phase_dir/gc-phase-f0.rom" \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output "$wabbit_tmp/gc-recovered-f0.rom" \
  --expected-input-sha256 \
    df49d6ec77483e33944fdbcee969084fc065b01a4e44327f83246a9de363fcb2 \
  --json

python tools/compare_flash_images.py \
  "$wabbit_tmp/gc-recovered-f0.rom" /tmp/gcf0-recovered-tilem.rom \
  --expected-left-sha256 \
    39113ee67921340b8817e35576a8f8fda467122af7713b099f399512d65d9bc3 \
  --expected-right-sha256 \
    39113ee67921340b8817e35576a8f8fda467122af7713b099f399512d65d9bc3 \
  --expect-equal --json
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
  resolve to (see [docs/bcall-mechanism.md](../docs/bcall-mechanism.md)).
- `rom=0x......` → byte offset into `tools/rom.bin` for raw decoding.

## Files

- [`tilem_trace_resolve.py`](tilem_trace_resolve.py) — trace → paged Ghidra address resolver.
- [`hardware_trace.py`](hardware_trace.py) — importable one-pass resolved-execution, physical-RAM-page, I/O-event, and memory-write iterators, plus constant-memory point counting.
- [`describe_boot_hardware.py`](describe_boot_hardware.py) — constant-memory retail-boot timing and ordered-I/O trace validator.
- [`analyze_trace_points.py`](analyze_trace_points.py) — resolved-address visits, opcode/register filters, register-frequency summaries, and JSON reports.
- [`analyze_ram_page_trace.py`](analyze_ram_page_trace.py) — trace memory writes → physical RAM page ranges.
- [`analyze_memory_writes.py`](analyze_memory_writes.py) — arbitrary resolved memory-write filters by logical target, writing PC, target kind, clock, and JSON output.
- [`flash_trace.py`](flash_trace.py) — importable AMD command-shape decoder for CPU write attempts, including physical-address transition classification.
- [`analyze_flash_trace.py`](analyze_flash_trace.py) — command-shaped write summaries, worker-invocation grouping, event filters, compact timelines, and JSON reports with explicit acceptance semantics.
- [`flash_replay.py`](flash_replay.py) — accepted-command replay, NOR programming, top-boot erasure, active-certificate selection, and GC phase snapshots.
- [`replay_flash_trace.py`](replay_flash_trace.py) — guarded CLI for complete replay and interrupted GC images with source/output hashes.
- [`tilem_core.py`](tilem_core.py) — reusable pinned-source validator, complete source enumerator, build command, hashing, and native-process capture.
- [`tilem_probe_support.c`](tilem_probe_support.c) and [`tilem_probe_support.h`](tilem_probe_support.h) — shared allocation, diagnostics, and TI-84 Plus core construction for direct probes.
- [`tilem_reset_probe.c`](tilem_reset_probe.c) — direct-core TilEm reset and forbidden-opcode side-effect adapter.
- [`tilem_reset.py`](tilem_reset.py) — typed reset report parser, disposition model, and oracle.
- [`build_tilem_reset_probe.py`](build_tilem_reset_probe.py) — clean-commit and Git-tree guarded TilEm reset-probe compiler CLI.
- [`run_tilem_reset_probe.py`](run_tilem_reset_probe.py) — exact-binary guarded TilEm reset and execution-exception CLI.
- [`tilem_flash_probe.c`](tilem_flash_probe.c) — direct-core command, status, timer, and erase-geometry adapter.
- [`tilem_flash.py`](tilem_flash.py) — typed Flash report parser and pinned-source oracle.
- [`build_tilem_flash_probe.py`](build_tilem_flash_probe.py) — shared-core, clean-source guarded Flash-probe compiler CLI.
- [`run_tilem_flash_probe.py`](run_tilem_flash_probe.py) — exact-binary guarded Flash command/status CLI.
- [`tilem_interrupt_probe.c`](tilem_interrupt_probe.c) — direct-core legacy interrupt, acknowledgement, callback, link, programmable-timer, and reset adapter.
- [`tilem_interrupt.py`](tilem_interrupt.py) — typed interrupt report parser and oracle backed by the reusable state model.
- [`build_tilem_interrupt_probe.py`](build_tilem_interrupt_probe.py) — clean-source guarded TilEm interrupt-probe compiler CLI.
- [`run_tilem_interrupt_probe.py`](run_tilem_interrupt_probe.py) — exact-binary guarded legacy-interrupt CLI.
- [`battery_hardware.py`](battery_hardware.py) — ROM battery-level tree, TilEm threshold regions, and raw comparator queries.
- [`describe_battery_hardware.py`](describe_battery_hardware.py) — text and JSON battery-model CLI.
- [`hardware-probes/battery-level.asm`](hardware-probes/battery-level.asm) and [`hardware-probes/battery-raw.asm`](hardware-probes/battery-raw.asm) — restoring physical probes for OS-visible levels and per-selector comparator masks.
- [`hardware-probes/link-raw.asm`](hardware-probes/link-raw.asm) — disconnected-port truth-table and instruction-spaced settling probe with release-to-idle cleanup.
- [`hardware-probes/keypad-settle.asm`](hardware-probes/keypad-settle.asm) — held-key and chord matrix-settling probe with eight group writes and four instruction gaps.
- [`hardware-probes/bus-timing.asm`](hardware-probes/bus-timing.asm) — guarded six-class Flash/RAM wait-state matrix using idle programmable timer 2.
- [`hardware-probes/prefix-m1.asm`](hardware-probes/prefix-m1.asm) — guarded RAM-M1 matrix for ordinary, prefixed, repeated-prefix, and indexed-CB instructions.
- [`hardware-probes/timer-physical.asm`](hardware-probes/timer-physical.asm) — guarded divisor, mode-3-prescaler, counter-zero, and expiry-status matrix.
- [`prefix_fetch_models.py`](prefix_fetch_models.py) and [`describe_prefix_fetch_models.py`](describe_prefix_fetch_models.py) — hash-guarded TilEm/Wabbitemu prefix-fetch comparison library and CLI.
- [`run_wabbitemu_prefix_m1_probe.py`](run_wabbitemu_prefix_m1_probe.py) — exact-ROM and exact-binary guarded execution of the assembled prefix-M1 probe through its cleanup boundary.
- [`run_wabbitemu_timer_physical_probe.py`](run_wabbitemu_timer_physical_probe.py) — exact-ROM and exact-binary guarded execution of the assembled timer discriminator through its cleanup boundary.
- [`tilem_battery_probe.c`](tilem_battery_probe.c) — direct-core voltage and selector sweep adapter.
- [`tilem_battery.py`](tilem_battery.py) — typed battery report parser and shared-model oracle.
- [`build_tilem_battery_probe.py`](build_tilem_battery_probe.py) — clean-source guarded battery-probe compiler CLI.
- [`run_tilem_battery_probe.py`](run_tilem_battery_probe.py) — exact-binary guarded battery-comparator CLI.
- [`tilem_timer_probe.c`](tilem_timer_probe.c) — direct-core programmable-timer and deterministic RTC adapter.
- [`tilem_timer.py`](tilem_timer.py) — typed timer/RTC report parser and oracle backed by reusable timing models.
- [`build_tilem_timer_probe.py`](build_tilem_timer_probe.py) — clean-source guarded TilEm timer-probe compiler CLI.
- [`run_tilem_timer_probe.py`](run_tilem_timer_probe.py) — exact-binary guarded programmable-timer and RTC CLI.
- [`tilem_keypad_probe.c`](tilem_keypad_probe.c) — direct-core keypad matrix, scancode, ON-edge, and reset adapter.
- [`tilem_keypad.py`](tilem_keypad.py) — typed keypad report parser and oracle backed by the reusable matrix model.
- [`build_tilem_keypad_probe.py`](build_tilem_keypad_probe.py) — clean-source guarded TilEm keypad-probe compiler CLI.
- [`run_tilem_keypad_probe.py`](run_tilem_keypad_probe.py) — exact-binary guarded keypad and ON-edge CLI.
- [`tilem_md5_probe.c`](tilem_md5_probe.c) — direct-core sliding-register, control-mask, read-mutation, clock, and reset adapter.
- [`tilem_md5.py`](tilem_md5.py) — typed MD5 report parser and oracle backed by the reusable arithmetic model.
- [`build_tilem_md5_probe.py`](build_tilem_md5_probe.py) — clean-source guarded TilEm MD5-probe compiler CLI.
- [`run_tilem_md5_probe.py`](run_tilem_md5_probe.py) — exact-binary guarded MD5-assist edge CLI.
- [`mame_runtime.py`](mame_runtime.py) — reusable MAME identity, guarded input validation, isolated runtime, command, logging, process, and manifest helpers.
- [`mame_trace.py`](mame_trace.py) — reusable I/O-trace configuration layered on the shared MAME runtime.
- [`mame_flash_probe.lua`](mame_flash_probe.lua) — mapped MAME Flash command, status, erase-range, and timer adapter.
- [`mame_flash.py`](mame_flash.py) — typed MAME Flash report parser, pinned-source oracle, and complete-image model.
- [`run_mame_flash_probe.py`](run_mame_flash_probe.py) — exact-ROM and exact-MAME guarded Flash CLI with retained logs, NVRAM, and manifest.
- [`mame_flash_gate_probe.lua`](mame_flash_gate_probe.lua) — CPU-mapped Flash command adapter with port-`0x14` transitions and port-`0x02` status reads.
- [`mame_flash_gate.py`](mame_flash_gate.py) — typed MAME gate-report parser, pinned-source oracle, and complete-image model.
- [`run_mame_flash_gate_probe.py`](run_mame_flash_gate_probe.py) — exact-ROM and exact-MAME guarded CPU-visible Flash-gate CLI.
- [`mame_flash_erase_probe.lua`](mame_flash_erase_probe.lua) — mapped five-sector geometry, fixed busy-range, chip-erase, and timer adapter.
- [`mame_flash_erase.py`](mame_flash_erase.py) — typed sector/chip report oracle and all-`FF` complete-image validator.
- [`run_mame_flash_erase_probe.py`](run_mame_flash_erase_probe.py) — guarded isolated erase-matrix CLI with retained logs, NVRAM, and manifest.
- [`mame_md5_probe.lua`](mame_md5_probe.lua) — CPU-I/O-space port-coverage and known MD5-step adapter for MAME.
- [`mame_md5.py`](mame_md5.py) — typed MAME MD5 report parser and pinned-map oracle backed by independent arithmetic.
- [`run_mame_md5_probe.py`](run_mame_md5_probe.py) — exact-ROM and exact-MAME guarded MD5-port CLI with retained logs and manifest.
- [`mame_link_probe.lua`](mame_link_probe.lua) — CPU-I/O-space raw-link, connector-output, peer-input, and assist-port adapter for MAME.
- [`mame_link.py`](mame_link.py) — typed MAME link report parser and pinned-source oracle backed by the reusable link model.
- [`run_mame_link_probe.py`](run_mame_link_probe.py) — exact-ROM and exact-MAME guarded raw-link CLI with retained logs and manifest.
- [`mame_keypad_probe.lua`](mame_keypad_probe.lua) — frame-latched live-input group/column and CPU-I/O-space keypad adapter for MAME.
- [`mame_keypad.py`](mame_keypad.py) — typed MAME keypad report parser and pinned-source oracle backed by the reusable matrix model.
- [`run_mame_keypad_probe.py`](run_mame_keypad_probe.py) — exact-ROM and exact-MAME guarded keypad-matrix CLI with retained logs and manifest.
- [`mame_interrupt_probe.lua`](mame_interrupt_probe.lua) — parked-CPU legacy status, mask, live ON, standard-timer, and soft-reset adapter for MAME.
- [`mame_interrupt.py`](mame_interrupt.py) — typed MAME legacy-interrupt report parser and oracle backed by the reusable interrupt state model.
- [`run_mame_interrupt_probe.py`](run_mame_interrupt_probe.py) — exact-ROM and exact-MAME guarded interrupt-controller CLI with retained logs and manifest.
- [`mame_timer_probe.lua`](mame_timer_probe.lua) — parked-CPU programmable-timer, status, auxiliary-port, and absent-RTC adapter for MAME.
- [`mame_timer.py`](mame_timer.py) — typed MAME timer report parser and oracle backed by the reusable timing and expiry models.
- [`run_mame_timer_probe.py`](run_mame_timer_probe.py) — exact-ROM and exact-MAME guarded timer/RTC CLI with retained logs and manifest.
- [`mame_lcd_probe.lua`](mame_lcd_probe.lua) — parked-CPU controller-state, mirrored-port, safe hidden-column, latch, packing, and missing-wait adapter for MAME.
- [`mame_lcd.py`](mame_lcd.py) — typed MAME LCD report parser and oracle backed by the reusable status, pointer, and latch models.
- [`run_mame_lcd_probe.py`](run_mame_lcd_probe.py) — exact-ROM and exact-MAME guarded LCD-controller CLI with retained logs and manifest.
- [`mame_asic_probe.lua`](mame_asic_probe.lua) — CPU-I/O-space status, gate, speed, protection/GPIO/USB coverage, clock-loop, and soft-reset adapter for MAME.
- [`mame_asic.py`](mame_asic.py) — typed MAME ASIC report parser and oracle backed by the reusable control and timing profiles.
- [`run_mame_asic_probe.py`](run_mame_asic_probe.py) — exact-ROM and exact-MAME guarded ASIC-control CLI with retained logs and manifest.
- [`mame_mapper_probe.lua`](mame_mapper_probe.lua) — fresh-process reset latch, selector, paired-bank, overlay-routing, and fetched-marker adapter for MAME.
- [`mame_mapper.py`](mame_mapper.py) — typed MAME mapper report parser and oracle backed by the reusable mapper profile and pinned ROM prefixes.
- [`run_mame_mapper_probe.py`](run_mame_mapper_probe.py) — exact-ROM and exact-MAME guarded five-case mapper CLI with retained logs and manifest.
- [`wabbitemu_headless.cpp`](wabbitemu_headless.cpp) — minimal Linux adapter, wake scheduler, Flash sampler, protected-gate observer, exact copied-worker matcher, recovery-point recorder, and guarded execution, reset, Flash, retail-worker, MD5, keypad, timer, ASIC-control, LCD/bus, shared assembled-program injection, direct-entry LCD-diagnostic, speed/delay, interrupt, link, and compact scripted USB-receive probe modes for the pinned Wabbitemu core.
- [`wabbitemu_headless.py`](wabbitemu_headless.py) — reusable pinned-source validation, build command, recovery and probe runners, typed gate/report parsing, shared assembled-program execution, retail-path validation, and image hashing.
- [`wabbitemu_flash_probe.py`](wabbitemu_flash_probe.py) — shared Flash case parser plus command-family, byte-program, and retail-worker report oracles.
- [`build_wabbitemu_headless.py`](build_wabbitemu_headless.py) — guarded compiler CLI for the exact pinned source tree.
- [`run_wabbitemu_headless.py`](run_wabbitemu_headless.py) — guarded cold-boot CLI with input/output hashes, exact gate-write expectations, retail Flash-path validation, and JSON coverage.
- [`run_wabbitemu_execution_probe.py`](run_wabbitemu_execution_probe.py) — exact-ROM boundary-fixture CLI with expected-predicate, register, mapping, marker, reset, and hash checks.
- [`run_wabbitemu_ram_execution_probe.py`](run_wabbitemu_ram_execution_probe.py) — guarded all-mode RAM target matrix with custom bound and target support.
- [`run_wabbitemu_flash_program_probe.py`](run_wabbitemu_flash_program_probe.py) — guarded native byte-program matrix with source-model, report-field, ROM, and binary checks.
- [`run_wabbitemu_flash_command_probe.py`](run_wabbitemu_flash_command_probe.py) — guarded native autoselect, reset, fast-program, erase, and unsupported-command matrix with complete mutation-range checks.
- [`run_wabbitemu_flash_worker_probe.py`](run_wabbitemu_flash_worker_probe.py) — guarded retail-ROM `_WriteFlashUnsafe` matrix with copied-worker path, register, poll-read, reset-tail, and hash checks.
- [`run_wabbitemu_prefix_m1_probe.py`](run_wabbitemu_prefix_m1_probe.py) — exact-ROM and exact-binary guarded assembled timing-probe CLI with decoded model discrimination and restoration checks.
- [`run_wabbitemu_timer_physical_probe.py`](run_wabbitemu_timer_physical_probe.py) — exact-ROM and exact-binary guarded assembled timer-probe CLI with decoded model discrimination and restoration checks.
- [`wabbitemu_usb_receive.py`](wabbitemu_usb_receive.py) — exact transport-frame decoder and retail installer-record execution oracle.
- [`run_wabbitemu_usb_receive_probe.py`](run_wabbitemu_usb_receive_probe.py) — exact-ROM and exact-binary guarded scripted USB-receive CLI with a retained JSON manifest.
- [`jstified_hardware.py`](jstified_hardware.py) — pinned deployed-artifact identity, source fingerprints, provenance, and fourth-emulator hardware feature profile.
- [`describe_jstified_hardware.py`](describe_jstified_hardware.py) — hash-guarded text and JSON jsTIfied source-profile CLI.
- [`emulator-probes/flash-bcall-usage.asm`](emulator-probes/flash-bcall-usage.asm) — assembled programmer-facing `_WriteFlash`, `_WriteAByteSafe`, `_EraseFlashPage`, `_SetFlashLowerBound`, and `_FlashToRam` usage fixture.
- [`flash_bcall_examples.py`](flash_bcall_examples.py) — reusable assembly, typed native-report parsing, and bcall/result/readback oracle.
- [`run_wabbitemu_flash_bcall_probe.py`](run_wabbitemu_flash_bcall_probe.py) — exact-ROM guarded executable-example CLI with source, machine-code, adapter, and result hashes.
- [`wabbitemu_md5_probe.py`](wabbitemu_md5_probe.py) — reusable native MD5 edge-report oracle backed by the independent arithmetic model.
- [`run_wabbitemu_md5_edge_probe.py`](run_wabbitemu_md5_edge_probe.py) — guarded native MD5 sliding-register, control-mask, undefined-read, and read-time-recalculation CLI.
- [`wabbitemu_keypad_probe.py`](wabbitemu_keypad_probe.py) — reusable native keypad and ON-edge report oracle backed by the pinned matrix model.
- [`run_wabbitemu_keypad_edge_probe.py`](run_wabbitemu_keypad_edge_probe.py) — guarded native matrix-topology, row-7, ON-latch, held-key, and release-rearming CLI.
- [`wabbitemu_timer_probe.py`](wabbitemu_timer_probe.py) — reusable native programmable-timer and RTC report oracle backed by the pinned comparison model.
- [`run_wabbitemu_timer_edge_probe.py`](run_wabbitemu_timer_edge_probe.py) — guarded native catch-up, zero-counter, acknowledgement, HALT-line, and RTC-freeze CLI.
- [`wabbitemu_asic_probe.py`](wabbitemu_asic_probe.py) — reusable native status, identity, protection, and GPIO report oracle backed by the ASIC-control model.
- [`run_wabbitemu_asic_edge_probe.py`](run_wabbitemu_asic_edge_probe.py) — guarded native port-`0x02`, port-`0x15`, protected port-`0x21`, and GPIO-map CLI.
- [`wabbitemu_protection_port_probe.py`](wabbitemu_protection_port_probe.py) — reusable native port-`0x22`–`0x26` gate, high-field, and RAM-wrap oracle backed by the execution-protection model.
- [`run_wabbitemu_protection_port_probe.py`](run_wabbitemu_protection_port_probe.py) — guarded native protected-boundary registration, readback, port-`0x24`, and 16-bit storage CLI.
- [`wabbitemu_reset.py`](wabbitemu_reset.py) — reusable low-level, frontend, and execution-violation reset disposition model and native-report oracle.
- [`run_wabbitemu_reset_retention_probe.py`](run_wabbitemu_reset_retention_probe.py) — exact-ROM and exact-binary guarded reset-retention CLI with direct-seeding scope labels.
- [`wabbitemu_lcd_probe.py`](wabbitemu_lcd_probe.py) — reusable native LCD and bus-timing report oracle backed by the pointer, latch, timing-register, and implementation models.
- [`run_wabbitemu_lcd_edge_probe.py`](run_wabbitemu_lcd_edge_probe.py) — guarded native controller-guard, hidden-column, latch, port-map, ASIC-ready, wait-field, and speed-clamp CLI.
- [`wabbitemu_lcd_diagnostic_probe.py`](wabbitemu_lcd_diagnostic_probe.py) — reusable oracle for compact direct-entry execution of retail page-`3F` LCD helpers.
- [`run_wabbitemu_lcd_diagnostic_probe.py`](run_wabbitemu_lcd_diagnostic_probe.py) — exact-ROM guarded LCD-helper CLI with transfer counts, visible-screen hashes, contrast state, and an explicit unreachable-path scope label.
- [`wabbitemu_speed_probe.py`](wabbitemu_speed_probe.py) — reusable native CPU-speed, delay-latch, wait-gate, and port-`0x2D` report oracle backed by the bus-timing implementation model.
- [`run_wabbitemu_speed_edge_probe.py`](run_wabbitemu_speed_edge_probe.py) — guarded native default/internal speed matrix, raw-latch, wait-gate, and port-`0x2D` side-effect CLI.
- [`wabbitemu_interrupt_probe.py`](wabbitemu_interrupt_probe.py) — reusable native standard-interrupt and low-power oracle backed by exact mask, status, and Wabbitemu rate models.
- [`run_wabbitemu_interrupt_edge_probe.py`](run_wabbitemu_interrupt_edge_probe.py) — guarded native mask, ON-latch, standard-timer, acknowledgement, completion, and low-power CLI.
- [`wabbitemu_link_probe.py`](wabbitemu_link_probe.py) — reusable native raw-link and assist oracle backed by the link truth table, byte order, port map, and assist-status model.
- [`run_wabbitemu_link_edge_probe.py`](run_wabbitemu_link_edge_probe.py) — guarded native raw matrix, assist send/receive, interrupt, acknowledgement, and error-status CLI.
- [`run_tilem_ram_execution_probe.py`](run_tilem_ram_execution_probe.py) — exact-ROM, mode-patched TilEm RAM boundary and repetition runner.
- [`gc_layout.py`](gc_layout.py) — reusable validation and construction for explicit synthetic archive-sector headers.
- [`build_gc_layout.py`](build_gc_layout.py) — hash-guarded CLI that reports every controlled layout mutation.
- [`archive_fixture.py`](archive_fixture.py) — exact archive-record serialization and fresh erased-sector first-fit placement.
- [`build_archive_fixture.py`](build_archive_fixture.py) — guarded deterministic program-layout CLI with source and output hashes.
- [`flash_image_compare.py`](flash_image_compare.py) — byte-complete image hashes, difference ranges, and physical-page counts.
- [`compare_flash_images.py`](compare_flash_images.py) — identity-guarded complete-image comparison CLI.
- [`gc_journal.py`](gc_journal.py) — byte-verified GC journal fields, phase transitions, sector-state indexing, and state-changing trace-event extraction.
- [`analyze_gc_journal.py`](analyze_gc_journal.py) — static GC journal reports with optional TilEm trace correlation and JSON output.
- [`flash_emulator_fixture.py`](flash_emulator_fixture.py) — reusable exact-ROM, optional-patch, probe-validation, and TI packaging contracts for named Flash fixtures.
- [`build_flash_emulator_fixture.py`](build_flash_emulator_fixture.py) — thin CLI that assembles a named probe and writes its ROM copy, assembly program, BASIC launcher, and JSON manifest.
- [`ti_program.py`](ti_program.py) — importable tokenized-program, `AsmPrgm`, `Asm(` launcher, and deterministic body builders.
- [`build_ti_program.py`](build_ti_program.py) — JSON-capable `.8xp` fixture builder.
- [`z80_disassembly.py`](z80_disassembly.py) — reusable `z80dasm` parser and paged-ROM literal and call-target helpers.
- [`analyze_rom_literals.py`](analyze_rom_literals.py) — all-page immediate-value candidates with optional nearby call/jump sinks.
- [`rom_calls.py`](rom_calls.py) — reusable direct `CALL`/`JP`, raw bcall, inline cross-page bjump, and bjump-stub caller reports with inferred target spaces and marked instruction context.
- [`analyze_rom_calls.py`](analyze_rom_calls.py) — thin CLI over `rom_calls.py` with source- and target-page filters plus text and JSON output.
- [`execution_protection_fixture.py`](execution_protection_fixture.py) — exact-ROM marker patching, guarded probe validation, TI program packaging, and protected-fetch trace classification.
- [`run_execution_protection_probe.py`](run_execution_protection_probe.py) — four-boundary TilEm runner with source, fixture, machine-code, and trace hashes.
- [`error_table.py`](error_table.py) — reusable decoder for raw `_JError` codes and the page-`07` message-pointer table.
- [`describe_error.py`](describe_error.py) — text and JSON reports for the message selected by one or more raw error codes.
- [`z80_io.py`](z80_io.py) — reusable immediate-port access decoding for static ROM disassembly.
- [`analyze_rom_io.py`](analyze_rom_io.py) — selected-page or all-ROM static I/O-access inventory, inclusive port ranges, instruction context, and summaries.
- [`asic_control.py`](asic_control.py) — reusable ASIC-status, identity, protection-mode, GPIO, generic immediate-port consumer, and raw-opcode coverage decoding.
- [`describe_asic_control.py`](describe_asic_control.py) — JSON-capable ASIC-control report with complete-ROM port-`0x02`, port-`0x21`, and GPIO audits plus arbitrary `--audit-port` scans.
- [`ram_topology.py`](ram_topology.py) — reusable ordered-pattern decoder for independent, shared, partial, and invalid RAM-selector alias observations.
- [`describe_ram_topology.py`](describe_ram_topology.py) — JSON-capable decoder and backing-assignment simulator for `HWPRAM` results.
- [`tibasic_smoke.py`](tibasic_smoke.py) — generated TI-BASIC fixture runner with
  trace-anchor checks and final-frame visual checks.
- [`macros/home-2plus3.macro`](macros/home-2plus3.macro) — power on, dismiss splash, evaluate `2+3`.
- [`macros/graph-y1-x2.macro`](macros/graph-y1-x2.macro) — power on, enter `Y1=X^2`, and graph it.
- [`macros/boot-idle.macro`](macros/boot-idle.macro) — baseline for coverage diffs.
- [`macros/boot-recovery.macro`](macros/boot-recovery.macro) — cold-boot a replayed Flash image with fresh RAM and allow archive-GC recovery to finish.
- [`macros/power-cycle.macro`](macros/power-cycle.macro) — enter low power with **[2nd]**+**ON**, wait in the `ram:0A5C` HALT loop, and wake with **ON**; see [Clock, timers, and power](../docs/clock-timers-power.md).
- [`macros/archive-second-program.macro`](macros/archive-second-program.macro) — archive the second of exactly two loaded programs through the memory-manager UI.
- [`macros/run-first-program-factorial5.macro`](macros/run-first-program-factorial5.macro) —
  launch the first TI-BASIC program and answer `5` at `Prompt N`.
- `macros/mathprint-{power,fraction,fnint,integral-fraction}.macro` — render
  `X²`, `1/2`, a filled integral, and an integral with a nested fraction to
  instrument the page `0x39` MathPrint engine (worked example in
  [docs/sub-equation-display.md](../docs/sub-equation-display.md), "Filled and nested-integrand traces").
- `macros/{ln2,exp1,sin1,fpsub}.macro` — known-input runs (`ln(2)`, `e¹`, `sin(1)`,
  `5−2`) that drive the FP/transcendental algorithms in
  [docs/floating-point.md](../docs/floating-point.md) for instruction-level
  pseudocode verification (walk a routine with `--print --only-space --only-addr`).
- `macros/solver-sqrt2.macro` — drives the Equation Solver to solve `X²−2=0`→√2,
  confirming the root-finder pseudocode in
  [docs/sub-solver-numeric.md](../docs/sub-solver-numeric.md).

For example, inventory the page-`0x35` controller block with two instructions
of context on each side:

```sh
nix develop -c python tools/analyze_rom_io.py --page 0x35 --before 2 --after 2 0x80-0xA2
```

This output is a linear-disassembly candidate list. Confirm control flow before
treating an apparent access as code because ROM data can decode as `IN` or
`OUT` instructions.

The call-reference CLI applies the same rule. Direct targets are logical
addresses, so filter the physical source page when auditing a same-page helper;
raw bcall matching instead checks the complete `EF low high` byte sequence.
Both modes can emit stable JSON records with a marked context window:

```sh
nix develop -c python tools/analyze_rom_calls.py \
  --page 0x3D --before 3 --after 4 --json 0x45E7
nix develop -c python tools/analyze_rom_calls.py \
  --bcall --before 3 --after 4 --json 0x8024
nix develop -c python tools/analyze_rom_calls.py \
  --bjump --before 3 --after 4 --json 3D:6098
```

## Trace format (quick reference)

`TLMT` v2: a 20-byte header + initial memory snapshot of the traced range,
then records — `0x01` instruction (logical PC, decoded opcode, clock, all Z80
registers incl. `WZ`, flags), `0x02` memory write (in-range), `0x03` key event.
Defined in `tilem-headless/headless/trace.c`.
