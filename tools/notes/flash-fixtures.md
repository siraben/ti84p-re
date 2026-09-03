# Flash fixtures under headless TilEm

Guarded fixtures that exercise Flash programming, execution protection, the
retail Flash workers, and archive garbage collection. They build on the trace
recipe in [dynamic-tracing.md](dynamic-tracing.md); every fixture is
hash-guarded and built by a `ti84re` module, so no binary is checked in.

## Cross-page Flash-programming fixture

`build_ti_program.py` generates large storage fixtures without checking binary
files into the repository. The following pair sorts `AARCHIVE` before
`ZBIGDATA`; the macro then selects the second program in the memory manager and
archives it without executing its deliberately repetitive body:

```sh
python3 -m ti84re.tifiles.build_program /tmp/AARCHIVE.8xp \
  --name AARCHIVE --body-size 1 --fill-byte 0x3F --json
python3 -m ti84re.tifiles.build_program /tmp/ZBIGDATA.8xp \
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
python3 -m ti84re.flash.analyze_trace /tmp/writeflash-cross.trace --invocations
python3 -m ti84re.flash.analyze_trace /tmp/writeflash-cross.trace --json
python3 -m ti84re.trace.analyze_points /tmp/writeflash-cross.trace \
  --point ram:811B --point ram:8122 --point ram:8124 \
  --clock 230976500-230976650 --json
```

The recorded run contains one 17,002-command invocation from physical
`0x20013` (`08:4013`) through `0x2427C` (`09:427C`). It is contiguous, crosses
one page, and resets at the final target. At the boundary, `ram:811B` reads
page `0x08`, `ram:8122` outputs page `0x09`, and `ram:8124` has changed `DE`
from `0x8000` to `0x4000`. Clock values depend on the complete run and macro
timing; use the invocation report to narrow the point query after recapture.

## Execution-protection boundary fixture

`execution_protection_fixture.py` builds exact-ROM copies with a six-byte
marker at `pp:7FF0`, validates the 75-byte assembly probe, and classifies a
trace from its call, target-fetch, follow-up, return, and reset records. The
default CLI run covers both sides of the boot bounds `08`–`29`:

```sh
probe_parent=$(mktemp -d)
nix develop -c python3 -m ti84re.hardware.run_execution_protection_probe \
  --tilem "$TILEM" --output-dir "$probe_parent/run" --json
```

The command refuses to reuse an output directory and never changes its source
ROM. It emits a patched ROM copy, machine-code program, BASIC runner, complete
trace, emulator log, and hashes for pages `07`, `08`, `29`, and `2A`. The
classifier requires `07` and `2A` to return and `08` and `29` to enter the
reset stub without reaching the marker's second instruction. See
[Execution protection](../../docs/execution-protection.md#guarded-tilem-boundary-trace)
for the recorded clocks and identities.

## RAM execution-protection fixtures

`execution_protection_fixture.py` also validates RAM targets, packages TilEm
program pairs, patches the boot mode immediate, and classifies physical-page
fetches. The TilEm CLI changes only `3F:41D6` for modes 1–3. Its self-installing
probe writes and reads back the six-byte target through data accesses before
the guarded call:

```sh
ram_probe_parent=$(mktemp -d)
nix develop -c python3 -m ti84re.emulators.tilem.run_ram_execution_probe \
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
nix develop -c python3 -m ti84re.emulators.wabbitemu.run_ram_execution_probe \
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

## Guarded Flash-worker fixtures

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

### Entry-return probe

`EMUWFENT` checks the unmodified `_WriteFlashUnsafe` entry signature and then
captures `AF` after four no-write paths: safe page `3E`, unsafe page `3F`, zero
length on page `3D`, and a direct call from RAM. It saves and restores port
`0x06` plus the incoming interrupt state.

```sh
fixture_dir=$(mktemp -d /tmp/writeflash-entry-fixture.XXXXXX)
nix develop -c python3 -m ti84re.flash.build_emulator_fixture \
  --fixture entry-returns \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-writeflash-entry.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/writeflash-entry.trace --trace-range all \
  "$fixture_dir/AWRUNENT.8xp" "$fixture_dir/EMUWFENT.8xp"

python3 -m ti84re.flash.analyze_trace /tmp/writeflash-entry.trace --json
python3 -m ti84re.trace.analyze_points /tmp/writeflash-entry.trace \
  --point ram:9DC5 --point ram:9DD8 \
  --point ram:9DEB --point ram:9DFF --json
```

The validated run contains no CPU write attempts targeting mapped Flash. The
four result points hold `AF=0x3E42`, `0x3F42`, `0x3DBB`, and `0xA591`,
respectively. The fixture ROM SHA-256 equals the source ROM SHA-256; the
manifest reports `"rom_modified": false`.

### Byte-entry return probe

`EMUWBENT` verifies the 16 wrapper bytes from `3F:4C9A` through `3F:4CA9` on
the unmodified ROM. It exercises safe page `3E`, safe page `3F`, unsafe page
`3F`, and a direct `_WriteAByte` call from RAM. Every path returns before
worker launch. The fixture saves and restores the original `OP1` byte.

```sh
fixture_dir=$(mktemp -d /tmp/writeabyte-entry-fixture.XXXXXX)
nix develop -c python3 -m ti84re.flash.build_emulator_fixture \
  --fixture byte-entry-returns \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-writeabyte-entry.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/writeabyte-entry.trace --trace-range all \
  "$fixture_dir/AWBENTRY.8xp" "$fixture_dir/EMUWBENT.8xp"

python3 -m ti84re.flash.analyze_trace /tmp/writeabyte-entry.trace --json
python3 -m ti84re.trace.analyze_points /tmp/writeabyte-entry.trace \
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

### Locked byte-program no-op probe

`EMULOCK` verifies the `_WriteAByte` wrapper and protected page-`3C` lock
wrapper on the unmodified ROM. It requires source byte `0x50` at `3D:7FFF`,
calls the lock wrapper, and aborts unless port `0x02` bit 2 is clear. It then
requests `0x40`, captures the worker result, and rereads the target and status
port. The fixture restores the original `OP1` byte.

```sh
fixture_dir=$(mktemp -d /tmp/writeabyte-locked-fixture.XXXXXX)
nix develop -c python3 -m ti84re.flash.build_emulator_fixture \
  --fixture locked-byte-noop \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-writeabyte-locked.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/writeabyte-locked.trace --trace-range all \
  "$fixture_dir/ALOCKED.8xp" "$fixture_dir/EMULOCK.8xp"

python3 -m ti84re.flash.analyze_trace \
  /tmp/writeabyte-locked.trace --events --invocations --json
python3 -m ti84re.trace.analyze_points /tmp/writeabyte-locked.trace \
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

### Erase-entry probe

`EMUERENT` verifies the unmodified entry bytes for `_EraseFlashPage`,
`_EraseFlash`, and `_EraseCertificateSector`. It captures the page-`3E` guard,
the direct-call guard, and an invalid certificate address. None can launch an
erase worker.

```sh
fixture_dir=$(mktemp -d /tmp/eraseflash-entry-fixture.XXXXXX)
nix develop -c python3 -m ti84re.flash.build_emulator_fixture \
  --fixture erase-entry-returns \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-eraseflash-entry.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/eraseflash-entry.trace --trace-range all \
  "$fixture_dir/AERUNENT.8xp" "$fixture_dir/EMUERENT.8xp"

python3 -m ti84re.flash.analyze_trace /tmp/eraseflash-entry.trace --json
python3 -m ti84re.trace.analyze_points /tmp/eraseflash-entry.trace \
  --point ram:9DCD --point ram:9DE2 --point ram:9DF6 --json
```

The validated run contains no CPU write attempts targeting mapped Flash. The
three result points hold `AF=0x3E42`, `0xA591`, and `0xA545`, respectively.
The last value is the fixture's seeded caller value, preserved by the
certificate wrapper. Its manifest reports `"rom_modified": false`.

### Certificate-erase success probe

`EMUCERAS` checks the patched unlock-wrapper signature, seeds caller
`AF=0xA545`, and invokes `_EraseCertificateSector` for `HL=0x4000`. It rereads
the first byte while Flash remains unlocked, then relocks and restores the
incoming interrupt state. The operation affects only the copied ROM image.

```sh
fixture_dir=$(mktemp -d /tmp/certificate-erase-fixture.XXXXXX)
nix develop -c python3 -m ti84re.flash.build_emulator_fixture \
  --fixture certificate-erase-success \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-certificate-erase-patched.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/certificate-erase.trace --trace-range all \
  "$fixture_dir/ACERASE.8xp" "$fixture_dir/EMUCERAS.8xp"

python3 -m ti84re.flash.analyze_trace \
  /tmp/certificate-erase.trace --events --timeline
python3 -m ti84re.trace.analyze_points /tmp/certificate-erase.trace \
  --point ram:8138 --summary-register AF --json
python3 -m ti84re.trace.analyze_points /tmp/certificate-erase.trace \
  --point ram:8143 --point ram:8151 --point page_3F:4E55 \
  --point ram:9DBA --point ram:9DC3 --json
```

The trace decodes one sector erase at physical `0xF8000`. Its 24,497 target
reads contain three `0x00`/`0x44` pairs, 12,245 `0x08`/`0x4C` pairs, and one
final `0xFF`. The worker returns `A=0`, Z; the wrapper-visible result remains
the seeded `AF=0xA545`; and the original `0x00` target byte reads back as
`0xFF`.

### Erase-busy range probe

`EMUERANG` checks the patched unlock-wrapper signature and issues
`AA 55 80 AA 55 30` directly for `3E:4000`. After DQ3 reports active erase,
it samples both ends of the selected sector, the adjacent and preceding
sectors, the boot sector, and distant page `08`. It waits for DQ7 before
capturing final array values and relocking Flash.

```sh
fixture_dir=$(mktemp -d /tmp/erase-busy-range-fixture.XXXXXX)
nix develop -c python3 -m ti84re.flash.build_emulator_fixture \
  --fixture erase-busy-range \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-eraseflash-range-patched.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/erase-busy-range.trace --trace-range all \
  "$fixture_dir/AERANGE.8xp" "$fixture_dir/EMUERANG.8xp"

python3 -m ti84re.flash.analyze_trace \
  /tmp/erase-busy-range.trace --events --timeline
python3 -m ti84re.trace.analyze_points /tmp/erase-busy-range.trace \
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

### Low-source boundary probe

`EMULOW` verifies fixed source bytes `4D 50` at `00:0068`, the first 16 bytes
of the block worker at `3F:4CCA`, and the protected lock wrapper at `3C:66D5`.
It calls that wrapper and aborts unless port `0x02` bit 2 reports Flash locked.
It then calls `_WriteFlashUnsafe` with `A=0x3D`, `DE=0x7FFF`, `BC=2`, and
`HL=0x0068`. The fixture saves and restores RAM `0x8000`, `(IY+0x25)`, port
`0x06`, and the incoming interrupt state. Its ROM is unmodified.

```sh
fixture_dir=$(mktemp -d /tmp/writeflash-low-source.XXXXXX)
nix develop -c python3 -m ti84re.flash.build_emulator_fixture \
  --fixture low-source-cross \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-writeflash-low-source.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/writeflash-low-source.trace --trace-range all \
  "$fixture_dir/ALOWSRC.8xp" "$fixture_dir/EMULOW.8xp"

python3 -m ti84re.flash.analyze_trace \
  /tmp/writeflash-low-source.trace --events --invocations --json
python3 -m ti84re.trace.analyze_memory_writes /tmp/writeflash-low-source.trace \
  --logical 0x8000 --pc ram:8149 --pc ram:816B \
  --target-kind ram --clock 187318000-187320000 --json
python3 -m ti84re.trace.analyze_points /tmp/writeflash-low-source.trace \
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

### Page-3E skip probe

`EMUWF3E` checks all eight patched bytes before calling the wrapper. It exits
without unlocking Flash on an unmodified ROM. `AWRUN3E` is the BASIC
`Asm(prgmEMUWF3E)` launcher and sorts first in the program menu. Build and run
the fixture only under emulation:

```sh
fixture_dir=$(mktemp -d /tmp/writeflash-fixture.XXXXXX)
nix develop -c python3 -m ti84re.flash.build_emulator_fixture \
  --fixture page-3e-cross \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-writeflash-3e-patched.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/writeflash-3e-cross.trace --trace-range all \
  "$fixture_dir/AWRUN3E.8xp" "$fixture_dir/EMUWF3E.8xp"

python3 -m ti84re.flash.analyze_trace \
  /tmp/writeflash-3e-cross.trace --events --invocations
python3 -m ti84re.trace.analyze_points /tmp/writeflash-3e-cross.trace \
  --point ram:811B --point ram:811D --point ram:811E \
  --point ram:8120 --point ram:8122 --point ram:8124 --json
```

The validated TilEm run produced byte-program commands at physical `0xF7FFF`
and `0xF4000`, followed by the worker reset at `0xF4000`. `ram:8122` was not
executed. `flash_trace.py` labels the resulting physical-address jump
`same-page-window-wrap`. This is emulator evidence for the ROM branch, not a
physical-calculator result.

### Illegal-program probe

`EMUWFERR` checks the same patched-ROM signature, then requests `0xD0` over the
stored `0x50` at `3D:7FFF`. This forces TilEm's illegal `0→1` program state.
The fixture captures returned `AF`, rereads the target byte, relocks Flash, and
restores the incoming interrupt state.

```sh
fixture_dir=$(mktemp -d /tmp/writeflash-error-fixture.XXXXXX)
nix develop -c python3 -m ti84re.flash.build_emulator_fixture \
  --fixture program-error \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-writeflash-error-patched.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/writeflash-program-error.trace --trace-range all \
  "$fixture_dir/AWRUNERR.8xp" "$fixture_dir/EMUWFERR.8xp"

python3 -m ti84re.flash.analyze_trace \
  /tmp/writeflash-program-error.trace --events --invocations
python3 -m ti84re.trace.analyze_points /tmp/writeflash-program-error.trace \
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

### Internal certificate-program failure probe

`EMUCFAIL` verifies the patched unlock wrapper plus the head and tail of the
129-byte page-`3D` program worker. After unlocking, it requires stored `0x00`
at `3E:4000`, copies the worker from `3D:730A` to `0x8100`, and directly calls
it with port `0x06` set to page zero. The requested `0x80` forces TilEm's
illegal `0→1` state. This fixture tests the copied worker's return tail, not the
outer caller at `3D:4332`.

```sh
fixture_dir=$(mktemp -d /tmp/certificate-program-error.XXXXXX)
nix develop -c python3 -m ti84re.flash.build_emulator_fixture \
  --fixture certificate-program-error \
  --rom tools/rom.bin --output-dir "$fixture_dir"

TILEM=~/Git/tilem-headless/result/bin/tilem2
$TILEM --headless \
  --rom "$fixture_dir/ti84plus-certificate-program-error-patched.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/run-first-program.macro \
  --trace /tmp/certificate-program-error.trace --trace-range all \
  "$fixture_dir/ACFAIL.8xp" "$fixture_dir/EMUCFAIL.8xp"

python3 -m ti84re.flash.analyze_trace \
  /tmp/certificate-program-error.trace --invocations --json
python3 -m ti84re.trace.analyze_points /tmp/certificate-program-error.trace \
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

## Flash command replay and GC restart

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
python3 -m ti84re.flash.replay_trace /tmp/tibasic-smoke/gcflash.trace \
  --rom tools/rom.bin --output-dir "$replay_dir" \
  --phase 0xFF --phase 0xFE --phase 0xE0 \
  --accept-command-shapes --json
```

Controlled archive-sector topologies use a separate reusable builder. It
requires the pinned source identity and records every synthetic header byte;
later journal transitions still require an unmodified-ROM trace:

```sh
python3 -m ti84re.flash.build_gc_layout \
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
python3 -m ti84re.flash.build_archive_fixture \
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
python3 -m ti84re.flash.replay_trace /tmp/gcf0-seed.trace \
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
python3 -m ti84re.trace.analyze_points /tmp/gc-restart-ff.trace \
  --point page_3C:7bc7 --point page_3C:7c1f \
  --point page_3C:7c43 --point page_3C:7cfb \
  --point page_3C:7d30
python3 -m ti84re.flash.analyze_trace /tmp/gc-restart-ff.trace --timeline
```

The same CLI can replay a complete recovery trace over its interrupted input.
Pass the exact input hash reported by the phase-snapshot command:

```sh
python3 -m ti84re.flash.replay_trace /tmp/gc-restart-ff.trace \
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
