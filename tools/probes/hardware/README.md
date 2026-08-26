# Physical-probe assembly sources

This directory contains the calculator-side sources described in
`docs/hardware-probes.md` and indexed individually in
`docs/needed-probes/calculator-readable.md`.

Build every transfer file with:

```sh
probe_parent=$(mktemp -d /tmp/ti84-physical-probes.XXXXXX)
nix develop -c python3 -m ti84re.hardware.build_probes \
  --output-dir "$probe_parent/build"
```

`common.inc` owns the stable `JP start` displacement and `HWP1` AppVar-copy
routine. Do not add convenience display code to that include: changing its
size shifts every probe entry and invalidates exact-emulator runners and
artifact hashes. A probe that displays a completion message must do so after
state restoration and AppVar creation.

`display.inc` implements every probe's post-cleanup display. It first prints a
labeled decimal CRC-16/CCITT-FALSE code over the complete AppVar-resident
`HWP1` frame. It then uses `_VPutMap` to page through a reversible `HWPZ1`
encoding in fixed small-font cells. The encoding contains the frame length,
CRC, and deterministic escape-run compression of every frame byte. The host
decoder reports the decimal code and compact text for comparison. All display
and key bcalls run only when interrupts were enabled on entry.

The decimal number identifies a visible run; the compact text can reconstruct
the frame but does not replace the original exported AppVar. The decoder
retains the complete frame and reports SHA-256 identities for the frame and
AppVar. `tools/ti84re/hardware/physical_probe_evidence.py` binds those bytes to the exact build
manifest and required physical metadata.

Execution-fetch probes create their AppVar before the guarded fetch. A normal
return updates the resident outcome and prints its CRC and compact frame code.
A protection reset cannot reach either display path; export the pending AppVar
after recovery.

`lcd-controller.asm` is a transferable visible-cell probe. It rejects saved
columns outside command range `0x20`–`0x2B` and never writes a hidden column.
Its only data value is the byte already read from the guarded visible cell.
It verifies that byte after the same-value write and restores it again.

`lcd-hidden-lab.asm` is a separate laboratory artifact. It is excluded from
the default build. Its builder requires a matching backup file and SHA-256,
an identified controller or test unit, recovery notes, an expected ASIC byte,
and a literal risk acknowledgement. Unknown controller aliasing can still
reach a cell outside the saved set, so this artifact belongs only on an
identified, repairable test calculator.

The SPASM-ng workflow was cross-checked against
[`siraben/ti84-forth`](https://github.com/siraben/ti84-forth): both use a Nix
build environment, direct assembly at user RAM, and explicit register/stack
discipline around OS calls. This suite intentionally retains its existing
`.org $9D95`, initial `JP $9DB5`, tokenized `AsmPrgm`, and versioned AppVar
contract rather than adopting TI-84 Forth's different container entry.

The source-to-artifact contract is checked by
`tools/tests/hardware/test_build_hardware_probes.py`. The documentation coverage is checked
by `tools/tests/wiki/test_needed_probe_docs.py`.

The tracked `HWPMAP` emulator record can be checked against the assembly and
runner sources without changing it:

```sh
python3 -m ti84re.hardware.mapper_probe_evidence \
  --check tools/oracles/hardware/mapper-overlays-emulators.json
```

To regenerate that record, first build `HWPMAP` and collect fresh manifests
from both exact-image backends and the guarded MAME mapper adapter. Keep every
runner's output outside the repository, then pass the four manifests to:

```sh
python3 -m ti84re.hardware.mapper_probe_evidence \
  --build-manifest /tmp/hwp-build/manifest.json \
  --tilem-manifest /tmp/hwp-tilem/manifest.json \
  --wabbitemu-manifest /tmp/hwp-wabbitemu/manifest.json \
  --mame-manifest /tmp/hwp-mame/manifest.json \
  --output tools/oracles/hardware/mapper-overlays-emulators.json
```

The generator rejects machine-image mismatches, nonzero outcomes, failed
marker or port restoration, a mismatched displayed decimal code, and an
unexpected ROM or emulator revision. It records MAME's Lua result as a direct
handler profile and labels exact `HWPMAP` execution unsupported.

`rtc-rollover.asm` is the only probe that may wait several minutes. It keeps
interrupts enabled until current-time port `0x45` reaches `0xFF`, then masks
interrupts across the final rollover window. It never writes the RTC block.
