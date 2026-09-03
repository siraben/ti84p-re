# Resident allocation probe

This fixture exercises the TI-OS variable and gap allocators while a compiled
program remains at `userMem`. It targets a TI-84 Plus running OS 2.55MP.

The payload creates and deletes a 32-byte AppVar and ordinary program. It then
opens a 16-byte gap immediately below its own source variable, reacquires the
source through `_ChkFindSym`, closes the gap, and reacquires it again. A final
AppVar consumes all memory reported by `_MemChk` after accounting for its
two-byte size word and VAT entry.

## Build and run

Set `SPASM` to SPASM-ng with `ti83plus.inc` in its include directory. Set
`TILEM` to the patched headless TilEm described in
[`tools/notes/dynamic-tracing.md`](../../notes/dynamic-tracing.md).

```sh
nix develop -c "$SPASM" -L -E -I path/to/spasm-ng/inc \
  tools/probes/allocation/resident-allocation.asm \
  /tmp/resident-allocation.bin

nix develop -c python3 tools/probes/allocation/build.py \
  /tmp/resident-allocation.bin /tmp/resident-allocation-fixture

"$TILEM" --headless --rom tools/rom.bin --model ti84p --normal-speed \
  --reset --macro tools/probes/allocation/run.macro \
  --trace /tmp/resident-allocation.trace --trace-range all \
  /tmp/resident-allocation-fixture/AACALL.8xp \
  /tmp/resident-allocation-fixture/ALPROBE.8xp

nix develop -c python3 tools/probes/allocation/analyze.py \
  /tmp/resident-allocation.trace /tmp/resident-allocation.lab \
  tools/data/resident-allocation.csv --rom tools/rom.bin
```

The analyzer replays TLMT memory writes, samples registers when `PC_REG`
reaches each post-operation label, verifies the source-variable pointer
movement, and checks an unchanged guard in the execution copy. It also requires
coverage of `_CreateAppVar`, `_CreateProg`, `_InsertMem`, `_DelMem`,
`_EnoughMem`, and `_DelVar` during the resident interval.

## Reference result

On a reset calculator containing only the wrapper and probe link variables, the
249-byte compiled object enters with `_MemChk=0x5C44`. Creating either
32-byte object moves `FPS` upward by 34 bytes and the VAT-side pointers downward
by 12 bytes. Deletion restores every recorded heap pointer. [confirmed]

The 16-byte gap moves the source data pointer from `0x9F2B` to `0x9F3B`.
Closing it restores `0x9F2B`. The execution guard and logical checkpoint
addresses remain unchanged. [confirmed]

For the five-character `ALMAX` AppVar, the creator needs 14 bytes beyond the
requested payload: a two-byte size word and a 12-byte VAT entry. A request of
`0x5C36` from `0x5C44` free bytes succeeds and leaves `_MemChk=0`; deletion
restores `0x5C44`. A raw `_EnoughMem(0x5C37)` succeeds because `_EnoughMem`
does not add creator overhead. The create preflight at `ram:0FF0` adds that
overhead before its own `_EnoughMem` call. [confirmed]

The reference run is emulator evidence, not a physical-calculator measurement.
It does not cover shell move-loaders, Flash Apps, archived launch paths, or a
representative user-variable population. [confirmed]

The run uses TilEm x4 and the BootFree 11.259 complete image with SHA-256
`dbb47afae091ab36f9abe74e32083013fbeff3d7e0516bbf5d1abf4ee57adc09`.
The allocator bytes on Flash page `0x00` are identical to the canonical retail
analysis image, but the measurement does not establish retail-boot state.
[confirmed]
