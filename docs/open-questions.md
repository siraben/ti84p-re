# Open questions and roadmap

The major ROM and hardware subsystems are mapped well enough to support focused
follow-up work. This page records the audit boundary and the evidence needed to
resolve the remaining behavior. Detailed reconstructions and emulator
comparisons remain on the subsystem pages linked below.

## Static-analysis work

### Symbol types

The Ghidra model assigns `TIKeyCode` to `kbdKey`, `kbdGetKy`, and `keyExtend`
(`0x8444`–`0x8446`), and `TIError` to `errNo` (`0x86DD`). `TIVarType` remains
on `curType` and `varType`. `stat_calc_command` remains inside the typed
`SystemFlags` span. [confirmed]

### Floating-point table semantics

The `_SinCosRad` recurrence is mechanically reconstructed. Phase 1 extracts one
redundant BCD digit per row of `02:7201` by non-restoring modulo-1 subtraction
or addition of the row aligned at $10^{-(k+1)}$. Phase 2 builds
$b_0\cdot\prod_k(1+10^{-2k})^{\lfloor(11-d_k)/2\rfloor}$ from the digits. The
row values approach $1 - s^2/3$ for the aligned scale $s = 10^{-(k+1)}$, but
they do not reduce to a clean rotation identity. This suggests tuned or
truncated constants. [confirmed]

Remaining: the closed-form interpretation of the phase-1 digit map — which
function of the reduced argument the digit string represents, and how phase 3
combines it with the phase-2 product and the residual to assemble the result.
A second traced input (e.g. `sin(0.5)`, digits `3,9,9,3,8,4,4,2`, residual
$3.81\times10^{-9}$) is available to constrain the fit. See
[Floating point](floating-point.md#_sincosrad-sine-and-cosine-in-radians-02733e-confirmed).

### Graph raster details

Find a natural flag state that routes `Circle(` through `_DrawCirc2`, then
compare its 60 emitted segments with the statically decoded schedule. Separately,
find and trace a natural caller of `_GrphCirc`, adding a direct-call interval
boundary to the current `_CircCmd` trace reducer. Extend the function-mode
traces to thick, shade, animate, and dotted styles; `Xres>1`; multiple selected
equations; and polar, parametric, and sequence modes. The coordinate rounding,
two ordinary function witnesses, and the clear-flag page-33 Circle path are
pinned in [Graphing](sub-graphing.md#evidence-summary-and-open-items).

### TABLE evaluation

Driver `05:6205` loops over seven visible rows and calls bcall ID `4741h` →
`35:7C7C` for each row. The `_ParseInp` region executes once per row; `_StoX`
does not execute during the fill. The Ask-mode bodies are also decoded.
`Indpnt=Ask` prompts through the editor at `05:7303`, with an OPS continuation
at `05:7329`, and finalizes the row through the value-cache shift at `05:6032`.
`Depend=Ask` evaluates one requested cell through `05:637C`, with an OPS
continuation at `05:644E`. Both mode tests honor an override check at `05:74BE`.
The `TblRng` validation at `38:72DA` and `38:7260` reduces to parse-boundary
checking: the range variable must be followed by a legal statement delimiter.
[confirmed]

No remaining items for this subsystem.

### Statistics command families

The regression `r`/`r²` cluster is byte-pinned: `3A:6845`–`3A:6891` forms
`r = num/den`, stores it to `Corr` (`_Sto_StatVar` id `0x12`), accumulates a
column-weighted residual sum over the augmented matrix, and — when the
denominator is nonzero — stores `r²` (id `0x35`, slot `0x8C05`) or `R²`
(id `0x36`, slot `0x8C0E`). [confirmed]

The STAT-TESTS engine occupies `3A:4A00`–`3A:7E60`. A raw operand scan finds
about 50 candidate `PStat`–`SStat` references in that window. Byte-pinned
evidence includes a T-Test output stage at `3A:5500` that stores `TStat` (id
`0x24`), the Zelen–Severo normal-tail coefficient table at
`3A:554F`–`3A:5584`, and the test-editor descriptor tables at
`3A:7D00`–`3A:7E60`. The `normalcdf(` evaluation reaches the page-`39`
floating-point core at `39:4A02`–`39:4F5B` and its helpers. [confirmed]

Remaining: the per-test entry addresses (the parser's execution dispatch into
the page-`3A` engine — the page-`38` table is parse-side only), the
menu-slot mapping of the `3A:7DF4` pointer array, and the algorithm identity
of the page-`39` core. See [Statistics](sub-statistics.md#remaining-questions).

### MathPrint runtime paths

The action byte entering `eqdisp_layout_main` (`39:4F9A`) is a raw TI key code:
`kLeft` opens the backward-walk path (`CP 2` at `39:5048`) and `kAlphaDown`
opens window advance (`CP 8` at `39:507C`), which loops `CALL 39:5167`. The
`kAlphaUp`/`kAlphaDown` codes come from a translator at `39:53A1` — get-key
variant bcall ID `4A68h`, compare against `0xFB`, state byte `0x8446` selects up
vs down. In-slot character scrolling bypasses `eqdisp_layout_main` entirely, as
does nested-template insertion. [confirmed]

Remaining: make get-key return `0xFB` inside a template editor state — neither
sequential ALPHA-then-arrow keystrokes nor overlapping press/release chords do.
Once it does, `39:5167`, its callees `39:5949`/`39:5B10`/`39:5B1D`, and the
saved-operand dispatch through `39:59E0`/`39:59F9` to `_FindAlphaUp`/
`_FindAlphaDn` become traceable; arbitrary VAT sequences and the two extension
bytes in the page-`07` 11-byte OP scratch registers also remain open. See
[Equation display](sub-mathprint-editor.md#from-live-editor-state-to-settled-drawing).

### Matrix and list paths

Plain `augment(` enters the partial-pivoting engine at `02:4663` but never
eliminates: the `0x91` branch sets carry (`02:6361 SCF`, restored by the
`POP AF` at `02:6378`), and the engine gates its elimination body on that flag
(<code>46DA POP AF</code><br><code>JR C,46EF</code>). The elimination pass belongs to the statistics
regression path, which enters the same dispatcher through `3A:6398`. [confirmed]

The `randM(` fill is decoded: `02:5CC1`–`02:5CE6` computes `int(19·rand)−9` per
cell, drawing from `_Random` (`36:7DC9`) through the page 0 banked-call stub
at `ram:392D`. The `ref(` driver dispatches at `02:609A` via bcall ID `4B85h`
→ `35:7995`; the `rref(` executor runs through bcall ID `4B88h` → `02:7C23`
from page-38 stubs at `38:514F`/`38:5157`; `SortA(`/`SortD(` share one body at
`02:652F` with direction discriminators `0x0E`/`0x10`. The `seq(` collection is
traced per element: entry `37:6E87`, expression eval through the standard
parser, element append via `02:69BC` → `37:4260`–`37:4285`, list growth via page-`07`
VAT routines, final `_CreateRList` through `37:70DC`. [confirmed]

No remaining items for this subsystem.

### Parser and archive residuals

The `Asm(`/`AsmPrgm` setup before the `ram:9D95` payload handoff is
byte-pinned at `07:5762`–`57D4`: `_ChkFindSym`, size checks against `0x2000`,
`_InsertMem` growth of `userMem`, `LDIR` payload copy, USB port-`0x20` state
save, cleanup handler `0x5800`, and the `07:57FD` jump to `0x9D95`. The entry
gate compares the second body byte to `6D` (`07:5772`, `FE 6D`), while working
fixtures emit `AsmPrgm` as `BB 6C` and still reach the payload — reconciling
the gate byte remains open. [confirmed]

Remaining: the meaning of the loop-record state word (it varies per fixture:
`0012h` in one trace, `0007h` in another) and the per-iteration split between
`parse_end_ops_record` re-entry and direct continuation jumps for `While`/
`Repeat`. The record shapes themselves are pinned: all three loops share the
5-byte form `00 | continuation word | state word`, with `For(` continuations
`38:5836`/`38:587D` and the `While`/`Repeat` runtime continuation `38:57E7`.
[confirmed]

Also open: a direct assembly-to-TI-BASIC program-call entry beyond VAT lookup
and the cooperative `Ans` callback. The generated `ZZRUN` negative probe
resolves `prgmOO`, sets the observed parser interval, and enters `38:6910`, but
the carry-guarded run terminates at `_ErrSyntax` (`ram:2700`) with the cursor
inside the target body. An 80-byte layout of the same probe ended at
`_ErrArgument` (`ram:2711`), so the terminal error depends on state outside the
copied name and cursor interval. The remaining gap is the native caller's
stack, error-handler, FPS/OPS, and run-state setup around that private entry.
[confirmed]

The group receive path is resolved. Receiving a `.8xg` stores each member as an
individual variable through the standard link variable-receive loop; no
`0x17` object or page-`07` guard is involved. A mixed group confirms that the
receiver honors the archive attribute per member. `HELLO` lands on Flash page
`08`, while `FACTOR` remains in RAM. Invoking the archived program takes the
page-byte guard to `ERR:ARCHIVED`. See
[Variables, archive and unarchive](sub-vat-archive.md#resolved-behavior-and-open-items).
[confirmed]

## Resident-runtime experiments

The compiled `Asm(` launcher, its `0x2000` internal-size cap, pointer repair,
archived lookup, scratch-buffer observations, and normal bank-A bcall restore
are documented. The following cases remain unresolved:

- Repeat the completed direct, unarchived compiled-launch heap snapshot under
  `_ExecAsm`, archived OS paths, and shell paths with boundary-size programs.
- Isolate scratch-buffer writes by bcall. Complete a successful
  `_DisableApd`/`_DelRes` guard run through `_GetKey`, ON-key handling, an OS
  error, APD, archive collection, link/USB, and shell interrupts.
- Run RAM-selector `0x83` guards through editor, graph, table, statistics, App,
  archive-GC, and transfer contexts. Probe selectors `0x84`–`0x87` on
  identified 48 KiB and 128 KiB calculators.
- Measure execution-protection ports and reset behavior on each ASIC. Recover
  Fullrene from an original artifact and test instruction fetch, operand read,
  stack access, and block copy at the same physical addresses.
- Repeat the direct-`Asm(` maximum-AppVar measurement with representative VAT
  states. Measure the same limit under shell move loaders and one- and
  multi-page Flash Apps.
- Force Flash-page, sector, and garbage-collection crossings while streaming an
  archived object. Reacquire its VAT result after each moving operation.
- Run one instrumented self-modifying payload under Ion, MirageOS, Doors CS, and
  zStart. Record peak RAM, self-lookup bytes, normal/error/forced-exit writeback,
  interrupt state, page selectors, and scratch restoration.
- Interrupt a two-slot AppVar update at each create, write, archive,
  garbage-collection, and delete boundary. Verify that startup selects the last
  committed generation.

## Physical-hardware work

The emulator pages distinguish ROM behavior from TilEm, Wabbitemu, and MAME
behavior. The items below require calculator measurements; emulator agreement
does not close them.

### Flash commands and interrupted collection

The Flash workers, top-boot geometry, archive-sector rotation,
certificate-sector journal, and all six ROM-written collector phases are
reconstructed. Cold TilEm and pinned Wabbitemu restart tests cover each phase,
but do not establish physical timing or power-loss guarantees. [confirmed]

A separate guarded Wabbitemu fixture exercises the failed stack preflight at
`ram:02BF`, its reset transfer, and the illegal-DQ7 worker failure. It prints
numeric status `0`, verifies zero source-image changes, and confines the worker
case to allocated byte `0x20100`. Wabbitemu has no program-busy interval, so
this does not close the physical interruption question. [confirmed] for pinned
Wabbitemu; [hypothesis] for physical behavior.

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
modes, and emulator differences are in [Paging](paging.md). Run the guarded
[mapper-overlay probe](hardware-probes.md#mapper-overlay-probe) on identified
TA2 and TA3 units.

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
The [LCD-controller probe](hardware-probes.md#lcd-controller-probe) covers the
digital ready and visible-cell cases without issuing analog or power commands.
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
  status bit 2, and programmable-timer `HALT` behavior;
- run the [RTC rollover probe](hardware-probes.md#rtc-rollover-coherence-probe),
  then test disabled RTC reads and the larger `0x00FFFFFF` → `0x01000000`
  carry with a separately guarded mutating artifact;
- run the [keypad settling probe](hardware-probes.md#keypad-settling-probe) with
  worst-case chords, then measure switch bounce and ON-key edges separately;
- determine which ON and link transitions wake low power; and
- test whether simultaneous legacy requests are coalesced by the port-`0x03`
  clear-on-zero sequence and which timer configurations wake `HALT`.

See [Clock, timers, and power](clock-timers-power.md),
[Keypad and ON-key hardware](keypad-on-hardware.md#resolved-findings-and-open-hardware-tests),
and [Interrupts](interrupts.md#emulator-comparison).
Use the guarded [interrupt wake
probe](hardware-probes.md#interrupt-halt-probe) for the programmable-versus-
watchdog discriminator; ON, link, and electrical edge cases remain separate.

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
