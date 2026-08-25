# Physical-probe assembly sources

This directory contains the calculator-side sources described in
`docs/hardware-probes.md` and indexed individually in
`docs/needed-probes/calculator-readable.md`.

Build every transfer file with:

```sh
probe_parent=$(mktemp -d /tmp/ti84-physical-probes.XXXXXX)
nix develop -c python tools/build_hardware_probes.py \
  --output-dir "$probe_parent/build"
```

`common.inc` owns the stable `JP start` displacement and `HWP1` AppVar-copy
routine. Do not add convenience display code to that include: changing its
size shifts every probe entry and invalidates exact-emulator runners and
artifact hashes. A probe that displays a completion message must do so after
state restoration and AppVar creation.

`display.inc` implements every probe's post-cleanup display. It prints a
labeled decimal CRC-16/CCITT-FALSE code over the complete AppVar-resident
`HWP1` frame. The host decoder reports the same code for comparison. The
display and key bcalls run only when interrupts were enabled on entry.

Execution-fetch probes create their AppVar before the guarded fetch. A normal
return updates the resident outcome and prints its CRC. A protection reset
cannot reach the display path; export the pending AppVar after recovery.

The SPASM-ng workflow was cross-checked against
[`siraben/ti84-forth`](https://github.com/siraben/ti84-forth): both use a Nix
build environment, direct assembly at user RAM, and explicit register/stack
discipline around OS calls. This suite intentionally retains its existing
`.org $9D95`, initial `JP $9DB5`, tokenized `AsmPrgm`, and versioned AppVar
contract rather than adopting TI-84 Forth's different container entry.

The source-to-artifact contract is checked by
`tools/test_build_hardware_probes.py`. The documentation coverage is checked
by `tools/test_needed_probe_docs.py`.

`rtc-rollover.asm` is the only probe that may wait several minutes. It keeps
interrupts enabled until current-time port `0x45` reaches `0xFF`, then masks
interrupts across the final rollover window. It never writes the RTC block.
