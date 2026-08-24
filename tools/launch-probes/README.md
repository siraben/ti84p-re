# Resident launch snapshot fixture

This fixture records heap and stack state around a compiled `Asm(` launch on a
TI-84 Plus running TI-OS 2.55MP. It uses an unarchived `ProgObj` with compiled
marker `BB 6D`.

The payload reacquires `prgmRTSNAP` through `_ChkFindSym` and writes four
records into reserved bytes in the source variable. The launcher moves that
source during `_InsertMem`; lookup therefore tests the same relocation that a
resident runtime must handle. Records 2 and 3 bracket a payload call to
`_MemChk`.

The trace analyzer independently replays TLMT v2 memory-write records. It
reports the state at `_ExecutePrgm` entry, the first payload instruction, the
nested `_MemChk`, the payload `RET`, cleanup entry, and return from cleanup.

## Build and run

Set `TILEM` to the patched headless TilEm binary described in
[`tools/dynamic-tracing.md`](../dynamic-tracing.md).

```sh
nix develop -c spasm -E -I tools \
  tools/launch-probes/runtime_snapshot.asm /tmp/runtime_snapshot.bin

nix develop -c python3 tools/launch-probes/build_runtime_snapshot.py \
  /tmp/runtime_snapshot.bin /tmp/runtime-snapshot-fixture

"$TILEM" --headless --rom tools/rom.bin --model ti84p --normal-speed --reset \
  --macro tools/launch-probes/run-runtime-snapshot.macro \
  --trace /tmp/runtime-snapshot.trace --trace-range all \
  /tmp/runtime-snapshot-fixture/AACALL.8xp \
  /tmp/runtime-snapshot-fixture/RTSNAP.8xp

nix develop -c python3 tools/launch-probes/decode_runtime_snapshot.py \
  /tmp/runtime-snapshot.ram

nix develop -c python3 tools/launch-probes/analyze_launch_trace.py \
  /tmp/runtime-snapshot.trace

nix develop -c python3 tools/launch-probes/analyze_launch_trace.py \
  /tmp/runtime-snapshot.trace --rom tools/rom.bin --json
```

The reference payload is 373 bytes, so the compiled program's internal size is
`0x0177`: two marker bytes plus the payload.

## Reference result

The four source-variable records agree:

```text
fpBase=0xA15F FPS=0xA171 OPBase=0xFCCE OPS=0xFCBA
pTemp=0xFCCE progPtr=0xFD34 symTable=0xFE66
SP=0xFFC9 MemChk=0x5B4A
```

The first record is the payload-entry state. Records 2 and 3 bracket the nested
`_MemChk`; record 4 is immediately before the payload's final `RET`.
[confirmed]

The TLMT replay supplies the missing pre-launch and OS-cleanup checkpoints.
Its output is the authoritative timed result because it applies every traced
RAM write to the trace's initial logical-memory snapshot. [confirmed]

The machine-readable reference rows are stored in
`tools/data/resident-launch-snapshot.csv`. The trace and ROM SHA-256 values in
that file bind the compact observation to the uncommitted copyrighted ROM and
large raw trace. [confirmed]

| Checkpoint | `FPS` | `OPS` | `pTemp` | `progPtr` | `symTable` | `SP` | `_MemChk` |
|---|---:|---:|---:|---:|---:|---:|---:|
| `_ExecutePrgm` entry | `0x9FFA` | `0xFCBA` | `0xFCCE` | `0xFD34` | `0xFE66` | `0xFFD7` | `0x5CC1` |
| first payload instruction | `0xA171` | `0xFCBA` | `0xFCCE` | `0xFD34` | `0xFE66` | `0xFFC9` | `0x5B4A` |
| nested `_MemChk` | `0xA171` | `0xFCBA` | `0xFCCE` | `0xFD34` | `0xFE66` | `0xFFC3` | `0x5B4A` |
| immediately after payload `RET` | `0xA171` | `0xFCBA` | `0xFCCE` | `0xFD34` | `0xFE66` | `0xFFCB` | `0x5B4A` |
| cleanup entry | `0xA171` | `0xFCBA` | `0xFCCE` | `0xFD34` | `0xFE66` | `0xFFD7` | `0x5B4A` |
| cleanup return | `0x9FFA` | `0xFCBA` | `0xFCCE` | `0xFD34` | `0xFE66` | `0xFFD9` | `0x5CC1` |

`fpBase` moves from `0x9FE8` to `0xA15F` for the resident copy and returns to
`0x9FE8` during cleanup. `OPBase` stays `0xFCCE`; `symTable` stays `0xFE66`.
The changes to `FPS`, `fpBase`, and `_MemChk` are exactly the internal size
`0x0177`. [confirmed]

The macro's later RAM dump occurs after the TI-BASIC command loop runs its own
cleanup. It is useful for checking persisted source records, but it is not the
immediate post-launch checkpoint. [confirmed]

This fixture does not measure an archived launch, `_ExecAsm`, a shell loader,
or a physical calculator. [confirmed]
