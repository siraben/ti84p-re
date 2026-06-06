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
- Port 6 selects the `4000` window (bank A); port 7 selects the `8000` window (bank B).
- A page value `0x00–0x3F` is flash (64 pages = 1 MiB); other values are RAM
  (e.g. the 84+'s `0x80/0x81` RAM-mode value).

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

# every bank switch (port 6 / port 7 writes)
tools/tilem_trace_resolve.py /tmp/b.trace --page-switches

# coverage: distinct executed addresses + hit counts
tools/tilem_trace_resolve.py /tmp/b.trace --coverage --sort count --names tools/names.txt
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
- [`macros/home-2plus3.macro`](macros/home-2plus3.macro) — power on, dismiss splash, evaluate `2+3`.
- [`macros/boot-idle.macro`](macros/boot-idle.macro) — baseline for coverage diffs.

## Trace format (quick reference)

`TLMT` v2: a 20-byte header + initial memory snapshot of the traced range,
then records — `0x01` instruction (logical PC, decoded opcode, clock, all Z80
registers incl. `WZ`, flags), `0x02` memory write (in-range), `0x03` key event.
Defined in `tilem-headless/headless/trace.c`.
