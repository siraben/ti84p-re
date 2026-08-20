# Open questions and roadmap

The major ROM and hardware subsystems are mapped well enough to support focused
follow-up work. This page lists only unresolved behavior and the evidence needed
to resolve it. Completed reconstructions and emulator comparisons remain on the
subsystem pages linked below.

## Static-analysis work

### Symbol types

Apply `TIKeyCode`, `TIError`, and `TIVarType` to scalar operands in the handlers
that consume them. Keep the changes scoped to operands whose domains are already
established.

### Floating-point table semantics

The `_SinCosRad` range reduction and table-driven recurrence are byte-pinned.
The exact rotation identity represented by each row at `02:7201` and `02:7281`
is still unknown. [confirmed]

Reduce the rows to their mathematical identities and reconcile them with the
recurrence in [Floating point](floating-point.md#_sincosrad-sine-and-cosine-in-radians-02733e-confirmed).

### Graph raster details

Find a natural flag state that routes `Circle(` through `_DrawCirc2`, then
compare its 60 emitted segments with the statically decoded schedule. Separately,
find and trace a natural caller of `_GrphCirc`, adding a direct-call interval
boundary to the current `_CircCmd` trace reducer. Extend the function-mode
traces to thick, shade, animate, and dotted styles; `Xres>1`; multiple selected
equations; and polar, parametric, and sequence modes. The coordinate rounding,
two ordinary function witnesses, and the clear-flag page-33 Circle path are pinned in
[Graphing](sub-graphing.md#evidence-summary-and-open-items).

### TABLE evaluation

Trace the per-row `_StoX` call and each selected-Y evaluation in the page-`05`
fill loop. The Depend:Ask prompt path and the `TblRng` special case in
`_Find_Parse_Formula` also need end-to-end traces. See [Table and Y= variables](sub-table-yvars.md#evidence-summary-and-open-items).

### Statistics command families

Locate and decode the DISTR numerical cores and each STAT-TEST handler that
writes `PStat` through `SStat`. Complete the byte trace of `3A:6845`–`3A:6891`,
where the regression path derives `r` and `r²`. See [Statistics](sub-statistics.md#remaining-questions).

### MathPrint runtime paths

Existing traces cover a filled integral and an integral containing a stacked
fraction. Both reach `39:4CA4`, but neither reaches the static compositor entry
at `39:5167`. [confirmed]

Find an expression and cursor state that selects `39:5167`, then trace the
row-step and saved-operand callees at `39:5949`, `39:5B10`, and `39:5B1D`. A
MathPrint-side witness must continue through `39:59E0` or `39:59F9` to
`_FindAlphaUp` or `_FindAlphaDn`. Arbitrary VAT sequences and the two extension
bytes in the page-`07` 11-byte OP scratch registers also remain open. See
[Equation display](sub-equation-display.md#from-live-editor-state-to-settled-drawing).

### Matrix and list paths

Explain why plain `augment(` calls the partial-pivoting engine at `02:4663`.
Locate the `randM(` cell-fill path and the separate `rref(`/`ref(` driver. Finish
the collection and element-load traces for `seq(`, `SortA(`, and `SortD(`. See
[Matrices and lists](sub-matrix-list.md#resolved-behavior-and-remaining-questions).

### Parser and archive residuals

Map the FPS loop-frame bytes used by `For(`, `While`, and `Repeat`. Recover the
`Asm(`/`AsmPrgm` setup before the traced `ram:9D95` payload handoff. Find a
direct assembly-to-TI-BASIC program-call entry beyond VAT lookup and the
cooperative `Ans` callback. Trace the group-archive member walk after
`_Arc_Unarc` rejects type `0x17`.

## Physical-hardware work

The emulator pages distinguish ROM behavior from TilEm, Wabbitemu, and MAME
behavior. The items below require calculator measurements; emulator agreement
does not close them.

### Flash commands and interrupted collection

The Flash workers, top-boot geometry, archive-sector rotation,
certificate-sector journal, and all six ROM-written collector phases are
reconstructed. Cold TilEm and pinned Wabbitemu restart tests cover each phase,
but do not establish physical timing or power-loss guarantees. [confirmed]

On physical calculators:

- measure legal and illegal `0→1` programming, DQ toggle cadence, program and
  erase durations, erase suspend, and busy reads at all four top-boot boundaries;
- force DQ5 failure with `DE` first in Flash and then in restoring scratch RAM
  to test the worker's undocumented reset write; and
- cut power at each phase boundary and during active program and erase commands.

The reconstructed paths and emulator results are in [Flash memory](flash-memory.md)
and [Variables, archive and unarchive](sub-vat-archive.md#flash-garbage-collector-confirmed).

### Two-wire link and USB

Determine why the legacy backup path normalizes the restored system-flags word
at `0x89F0` to `0x0063`. The destination, section bounds, checksum coverage, and
affected indexed bits are pinned; the unresolved question is whether the value
is a canonical post-restore state or a compatibility state. [confirmed]

On physical calculators:

- measure port-`0x00` pull-ups, thresholds, rise times, both CPU-speed timeout
  durations, and the both-low pulse's voltage and duration;
- run the read-only USB snapshot on identified TA2 and TA3 units, connected and
  disconnected, before testing ports `0x49`, `0x51`, and `0x52`;
- test the FDRC-family register hypothesis, port `0x4B`, and the port-`0x4F`/`0x50`
  setup sequence;
- capture port-`0x5A` presentation traffic to test the proposed two-byte
  endpoint-2 LCD packets and host-mode dependency; and
- exercise endpoint payload transfer and the connected boot receive path.

The prepared [raw two-wire link probe](hardware-probes.md#raw-two-wire-link-probe)
measures digital settling but not analog voltage or pull-up behavior. See
[Two-wire link port hardware](link-port-hardware.md#resolved-findings-and-open-hardware-tests),
[Link transfer](sub-link-transfer.md#open-items), and
[USB ASIC and link assist](sub-usb-asic.md#limits).

### MD5 accelerator

Run the [MD5 edge probe](hardware-probes.md#md5-edge-probe) on TA2 and TA3 units.
Add reset-retention and I/O wait-state measurements. The valid 64-step path,
boot API, TilEm and Wabbitemu models, and MAME's missing port block are already
reconciled in [MD5 accelerator and boot API](md5-hardware.md).

### Memory-mapper overlays

Determine whether ports `0x27` and `0x28` remain active in paired mode, whether
the `0xFB64` cutoff exists in the ASIC, and whether forced
[execution-protection overlays](execution-protection.md#mapping-and-forced-overlays)
follow the underlying window or a forced RAM page. The boot transition, selector
modes, and emulator differences are in [Paging](paging.md).

### Bus timing and LCD controller

On TA2 and TA3 controller revisions:

- measure every port-`0x2E` access class, CPU-speed readback, and actual clock
  frequency;
- characterize port-`0x2D` low-power behavior and the port-`0x2F` mode-3 timer
  prescaler;
- measure LCD read-versus-write ready timing and controller-specific minimum
  delays; and
- test hidden-column bounds and status-read pointer behavior.

Use the [memory-bus timing probe](hardware-probes.md#memory-bus-timing-probe),
[prefix-M1 probe](hardware-probes.md#prefix-m1-timing-probe), and
[programmable-timer probe](hardware-probes.md#programmable-timer-physical-probe).
The established decode and emulator differences are in
[Bus timing and wait states](bus-timing.md) and
[LCD controller and display bus](lcd-hardware.md).

### ASIC identity, RAM, protection, and GPIO

Run the [battery-level probe](hardware-probes.md#battery-level-probe) and
[raw battery-selector probe](hardware-probes.md#raw-battery-selector-probe)
through upward and downward voltage sweeps on TA1, TA2, and TA3 units. Correlate
the [RAM alias probe](hardware-probes.md#ram-alias-probe) results and port-`0x15`
byte with PCB date and ASIC marking rather than assuming that a TA label fixes
RAM capacity.

Also test protected-register readback and high-value behavior, violation and
warm/cold reset behavior, the [execution-fetch suite](hardware-probes.md#execution-protection-fetch-probes),
port-`0x39` direction polarity, and port-`0x3A` electrical signals. See
[ASIC status, identity, protection, and GPIO](asic-status-gpio.md) and
[Execution protection](execution-protection.md).

### Timers, keypad, and interrupts

On TA2 and TA3 units:

- distinguish timer divisors `33`/`328`/`3277` from the emulator values
  `32`/`327`/`3276`;
- test the port-`0x2F` prescaler, counter zero, first- versus second-expiry
  status bit 2, programmable-timer `HALT` behavior, disabled RTC reads, and
  rollover coherence;
- run the [keypad settling probe](hardware-probes.md#keypad-settling-probe) with
  worst-case chords, then measure switch bounce and ON-key edges separately;
- determine which ON and link transitions wake low power; and
- test whether simultaneous legacy requests are coalesced by the port-`0x03`
  clear-on-zero sequence and which timer configurations wake `HALT`.

See [Clock, timers, and power](clock-timers-power.md),
[Keypad and ON-key hardware](keypad-on-hardware.md#resolved-findings-and-open-hardware-tests),
and [Interrupts](interrupts.md#emulator-comparison).

## Closed audit boundary

The ROM-wide I/O census is complete. It classifies all 35 aligned
non-descriptor immediate candidates and all 37 register/block-I/O opcode pairs;
no unresolved immediate or computed-`C` candidate remains. [confirmed]

## Reproduction paths

Static work can extend the headless pipeline in `tools/` and rebuild with
`tools/build.sh`. Regions the decompiler leaves unanalyzed should be reduced
from raw bytes and reconciled with the generated database. Hardware work should
use the restoring probes in [Hardware probes](hardware-probes.md) and record the
calculator revision, PCB date, and ASIC marking with each result.
