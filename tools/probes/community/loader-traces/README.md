# Community loader traces

These fixtures exercise the identified RUNCOUNT 16, Plasma 1.4, and TSE
1.5/1.6 releases without running any program from the archives on the host.
`build.py` reads calculator link files, checks their release hashes, and writes
only `.8xp`/`.8xg` inputs. `scan_trace.c` streams large TLMT v2 traces and
attributes the relevant writes to calculator-side instruction addresses.

Run the tools from the repository root inside the development shell:

```sh
nix develop -c python3 tools/probes/community/loader-traces/build.py \
  --extracted "$COMMUNITY_ARCHIVE/extracted" \
  --out-dir /tmp/community-loader-fixtures
nix develop -c cc -O2 -Wall -Wextra -Werror \
  -o /tmp/community-loader-scan \
  tools/probes/community/loader-traces/scan_trace.c
```

The recorded traces used the `siraben/tilem-headless` commit
`d1bdc58dd321ae462a701e556fcb62bb925a78b1`. Its headless branch needed the
same command-line file-loading call as the GUI branch before the macro began;
otherwise every calculator link argument was silently ignored. The trace
binary with that local fix has SHA-256
`b8ee505483c79732a4ca21efb8b904de0792477795f6fc717874dcd5addaed09`.
The local build also supplies a typed `GifEncode` prototype and corrects the
zero-argument `tilem_macro_new` call so the pinned source builds with the Nix
shell's compiler. A trace is invalid for these fixtures unless its calculator
arguments were loaded before the macro.

Example captures are:

```sh
TILEM=/path/to/patched/tilem2
ROM=tools/rom.bin
OUT=/tmp/community-loader-traces
mkdir -p "$OUT"

"$TILEM" --headless --rom "$ROM" --model ti84p --normal-speed --reset \
  --macro tools/probes/community/loader-traces/runcount.macro \
  --trace "$OUT/runcount-ram.trace" --trace-range all \
  /tmp/community-loader-fixtures/ACOUNT.8xp \
  /tmp/community-loader-fixtures/RUNCOUNT.8xp

"$TILEM" --headless --rom "$ROM" --model ti84p --normal-speed --reset \
  --macro tools/probes/launch-fixtures/run-first.macro \
  --trace "$OUT/tse-archive.trace" --trace-range all \
  /tmp/community-loader-fixtures/tse-archive-A.8xp \
  /tmp/community-loader-fixtures/tse-archive-LOADTSE.8xp \
  /tmp/community-loader-fixtures/tse-archive-TSEKRNL.8xp \
  /tmp/community-loader-fixtures/tse-archive-TSELIBS.8xp

/tmp/community-loader-scan "$OUT/runcount-ram.trace"
/tmp/community-loader-scan "$OUT/tse-archive.trace"
```

The RAM TSE case passes the original `TSE.8xg` instead. The archived RUNCOUNT
case substitutes `RUNCOUNT-archived.8xp`. The Plasma context case passes
`APLASMA.8xp` and `PLASMA.8xp` with `plasma-context.macro`.

`tools/data/community-loader-traces.csv` pins the ROM, fixtures, macros, trace
hashes, and scanner counts. Raw traces are intentionally not committed.

## Boundaries

- RUNCOUNT's unarchived direct `Asm(` path executes twice and stores `1`, then
  `2`, to the named RAM source. The archived fixture never reaches
  `ram:9D95`; it therefore supplies a refusal/non-execution observation, not an
  archived-source store observation.
- Both TSE `LOADTSE` paths reach the packaged kernel at `ram:9872`. Each run
  copies 531 bytes to `saferam2` (`0x8A3A`) from a packaged library with only
  388 code bytes after the loader's five-byte skip. The trace records all 143
  writes beyond that code extent in both RAM and archived paths.
- Plasma reaches its release entry, but the deterministic macro neither enters
  the protected Ion client nor reaches the copied hook's `4030h` call at
  `ram:9881`. `_newContext` at `ram:077E` is consequently interaction-blocked,
  not dynamically confirmed.

The numeric bcall scan found only Plasma's `4F66h` (`_SetGetKeyHook`) and
`4030h` (`_newContext`). Both IDs already have those names in `tools/symbols/bcalls.txt`;
no absent or misnamed loader bcall was found.
