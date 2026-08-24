# TI-OS reverse-engineering TODOs for resident language runtimes

These questions came out of auditing `ti84-forth`, but the answers are useful to
shells, interpreters, compilers, debuggers, and other long-running assembly
programs. Keep measured behavior separated by calculator model, ASIC revision,
OS version, and launch path. Prefer a ROM/disassembly anchor plus a reproducible
TilEm trace; items involving 48 KiB versus 128 KiB hardware also need real-calculator
confirmation.

Continue with [`followup-todos.md`](followup-todos.md) after this checklist. It
covers broader TI-OS, hardware, tooling, and documentation work that is not
specific to a resident language runtime.

Status updated 2026-08-24 on branch `siraben/resident-runtime-research`.
Checked items have a reproducible answer for the stated OS 2.55MP/source scope.
Unchecked items still require the named trace, fixture, original source, or
physical-hardware evidence; they are not silently treated as complete.

## Assembly-program launch and the real RAM budget

- [x] Trace the complete `Asm(`/`AsmPrgm` launch path from the source program
  variable to the executable copy at `userMem` (`0x9D95`). Record every
  `_InsertMem`, `_DelMem`, pointer fixup, and cleanup action.
- [x] Determine the exact largest payload accepted by TI-OS, including whether
  the `BB 6D` token bytes and the variable's two-byte size field count toward
  the conventional 8,811-byte `0x9D95-0xBFFF` limit.
- [ ] Capture `FPS`, `OPS`, `pTemp`, `progPtr`, `symTable`, hardware `SP`, and
  `_MemChk` immediately before launch, at the first instruction at `0x9D95`,
  during a nested bcall, and immediately after return.
- [ ] Repeat for an unarchived program, an archived program launched by each
  supported OS path, `_ExecAsm`, and a shell launcher. Quantify when TI-OS needs
  both the variable and an execution copy in RAM.
- [x] Establish how much stack headroom exists above the VAT during execution
  and what, if anything, detects collision between the Z80 stack and OS data.

Suggested fixtures: payloads of 8,808 through 8,814 bytes; a payload that calls
`_MemChk`; and guard patterns around the source variable, execution copy, FPS,
OPS, VAT, and stack.

Completed results are folded into
[`docs/memory-management.md`](docs/memory-management.md) and detailed in
[`docs/sub-resident-programs.md`](docs/sub-resident-programs.md). The compiled
path caps its internal size at `0x2000`, including `BB 6D` but excluding the
size word; it copies two bytes beyond that size-described data. `_MemChk` never
reads `SP`, so TI-OS supplies no stack-collision detector. Timed pointer
snapshots, `_ExecAsm`, archived-launch variants, and common shell traces remain
open.

## Scratch-RAM clobber matrix

- [ ] Build a bcall-by-buffer clobber matrix for the commonly advertised
  scratch areas: OP1-OP6 (`0x8478...`), `textShadow` (`0x8508`, 128 bytes),
  `iMathPtr*`, `saveSScreen` (`0x86EC`, 768 bytes), `statVars` (`0x8A3A`, 531
  bytes), table/solver workspace around `0x91DC-0x9301`, `plotSScreen`
  (`0x9340`, 768 bytes), and `appBackUpScreen` (`0x9872`, 768 bytes).
- [ ] Exercise `_GetKey`, `_GetCSC`, `_PutS`, `_VPutS`, screen clears, graph
  routines, `_ChkFindSym`, variable creation/deletion, `_Arc_Unarc`, link/USB
  handling, error unwinding, APD, context changes, and app launch/exit.
- [ ] Verify the WikiTI rule that `saveSScreen` is safe after `_DisableApd`,
  including whether `_GetKey` or an ON-key interrupt can still initiate a path
  that overwrites it.
- [ ] Verify the `statVars` requirements (`_DelRes`, no statistics use, and the
  MirageOS interrupt caveat) under direct TI-OS launch and common shells.
- [x] Identify which ranges remain stable for the entire lifetime of a program
  that continues to use ordinary display, keyboard, VAT, and archive bcalls.

The output should be a machine-readable table as well as a reader-facing page;
"not touched in one trace" must not be promoted to "safe" without broader
coverage.

The initial machine-readable matrix is
`tools/data/scratch-ram-observations.csv`; its analyzer is
`tools/analyze_scratch_trace.py`. Results and conditional ownership are folded
into [`docs/memory-management.md`](docs/memory-management.md),
[`docs/ram-pages.md`](docs/ram-pages.md), and
[`docs/sub-resident-scratch.md`](docs/sub-resident-scratch.md). No advertised
range is stable while every requested subsystem remains available. The
isolated bcall matrix and the `saveSScreen`/`statVars` guard experiment remain
unchecked because the first guard launch reached TI-OS Error before executing
the fixture.

## RAM execution protection across hardware revisions

- [ ] Record the reset and TI-OS values of ports `0x21`, `0x25`, and `0x26` on
  TI-83+SE, early 128 KiB TI-84+/SE, later 48 KiB TI-84+/SE, and relevant ASIC
  revisions. Confirm the inclusive upper-limit behavior documented for port
  `0x26`.
- [ ] Determine precisely whether protection is checked against the selected
  page number, the aliased physical RAM page, the CPU address, or a combination
  on 48 KiB models where selectors `0x82-0x87` alias one physical page.
- [ ] Reproduce and document Crabcake's page-`0x80`/page-`0x83` swap, Fullrene's
  execution-limit method, and zStart's `Execute >C000` option. For each, record
  supported models, required privilege/unlock path, interrupt assumptions,
  failure mode, and whether all ports and page contents are restored on exit
  and error.
- [ ] Test an instruction fetch, operand read, stack access, and DMA/block copy
  at the same protected addresses. Confirm that non-executable RAM remains safe
  for threaded bytecode or data even when native instruction fetch resets the
  calculator.

Do not recommend globally disabling execution protection until reset/exception
cleanup has been proven. A reset that preserves an unsafe port configuration is
a particularly important case.

The emulator, ROM, and original-source boundary is now documented in
[`docs/paging.md`](docs/paging.md) and
[`docs/execution-protection.md`](docs/execution-protection.md), with observations
in `tools/data/execution-protection-observations.csv`. Crabcake and zStart are
source-confirmed; Fullrene, physical alias/protection behavior, reset values by
ASIC, and fetch-versus-data hardware tests remain unchecked.

## Extra RAM pages while TI-OS remains resident

- [ ] Extend the page-`0x83` traces to cover `_GetKey` waiting, APD, ON-key
  handling, USB/link transfer, variable receive, archive GC, graphing, table,
  statistics, program editing, app launch, and error dialogs.
- [ ] Determine which page-`0x83` ranges can be borrowed during a long-running
  assembly program and which OS calls may asynchronously or synchronously
  overwrite them.
- [ ] On 128 KiB hardware, probe pages `0x84-0x87` for OS and third-party use.
  On 48 KiB hardware, confirm aliasing and treat them as one page.
- [x] Document a save/map/restore protocol for borrowing a RAM page through
  bank A (`0x4000-0x7FFF`) without breaking bcalls, including port `0x06` and
  port `0x0E` state, interrupts, and nested page-changing calls.
- [x] Determine whether a bcall always restores the caller's bank-A mapping or
  whether specific calls assume the normal TI-OS page and leave a different
  mapping behind.

The protocol and dispatcher result are folded into
[`docs/ram-pages.md`](docs/ram-pages.md) and
[`docs/sub-resident-scratch.md`](docs/sub-resident-scratch.md). The page-zero
dispatcher restores port `0x06` on ordinary return, but removes a borrowed
bank-A mapping during the call and cannot promise caller cleanup after an OS
error. Long-path page-`0x83` coverage and 48/128 KiB physical probes remain
open.

## VAT allocation and stable large buffers

- [ ] Trace `_CreateAppVar`, `_CreateProg`, `_InsertMem`, `_DelMem`,
  `_EnoughMem`, and `_DelVar` while an assembly program is resident at
  `0x9D95`. Record which live pointers TI-OS fixes and whether an execution copy
  can ever move.
- [x] Establish a safe protocol for allocating a large dictionary/workspace in
  a RAM AppVar. List every operation that can relocate it and how a runtime can
  reacquire or relocate internal absolute pointers afterward.
- [ ] Measure the maximum contiguous allocation available under a normal
  `Asm(` launch, a shell move-loader, and a Flash App, starting from a clean RAM
  state and with representative user variables present.
- [ ] Confirm maximum variable payload sizes and the behavior of allocation
  requests that approach the VAT, FPS/OPS, or hardware-stack boundaries.

The completed AppVar handle protocol is in
[`docs/sub-resident-programs.md`](docs/sub-resident-programs.md): retain the
name and offsets, reacquire with `_ChkFindSym` after moving calls, and never
expect `_InsertMem`/`_DelMem` to repair arbitrary runtime pointers. Allocation
traces and clean/representative maximum-size measurements remain open.

## Archived data and source streaming

- [x] Document `_ChkFindSym`'s archived result as a complete contract: `B` page
  value, `DE` offset, required bank mapping, and pointer validity across bcalls.
- [x] Compare direct page mapping, `_FlashToRam`, and unarchive-then-read for a
  streaming interpreter. Identify which approach permits source or dictionary
  images larger than free RAM and which calls can trigger archive GC.
- [ ] Build fixtures whose source crosses a 16 KiB Flash page or archive-sector
  boundary, including variables moved by garbage collection.
- [ ] Verify whether protected programs and ordinary programs differ anywhere
  after VAT lookup other than type checking.

The result contract and streaming comparison are folded into
[`docs/memory-management.md`](docs/memory-management.md) and
[`docs/sub-resident-programs.md`](docs/sub-resident-programs.md). Boundary-
crossing and forced-GC fixtures, plus the protected-type comparison, remain
open.

## Shell loaders and writeback semantics

- [ ] Trace Ion, MirageOS, Doors CS, and zStart launchers with the same payload.
  Classify each as copy, move/delete/recreate, swap, or direct archived
  execution, and measure its RAM overhead.
- [ ] For Doors CS's graph-buffer chunk swap and similar loaders, verify what a
  self-modifying program writes back, how archived originals are handled, and
  what happens on an error or forced exit.
- [ ] Determine whether a program can reliably find its original variable while
  running under each launcher. This matters to runtimes that persist modified
  state into their own program object.
- [ ] Record shell-owned interrupts and scratch ranges that differ from direct
  TI-OS launch.

Original Ion, MirageOS, Doors CS, and zStart artifacts are now classified in
[`docs/sub-shell-loaders.md`](docs/sub-shell-loaders.md) and
`tools/data/shell-loader-observations.csv`, and the existing resident-program
overview links to the comparison. These checklist items remain unchecked
because their wording requires a common dynamic payload and measured peak RAM,
self-lookup, writeback, and abnormal-exit traces under all four shells.

## Flash Apps as resident runtimes

- [ ] Measure the RAM available to a one-page and multi-page Flash App and
  confirm whether the full `0x9D95-0xBFFF` executable region can be dedicated to
  generated code while the kernel executes at `0x4000-0x7FFF`.
- [x] Document cross-page App calls, app-relative data, OS bcalls that reject
  Flash-resident pointers, error handlers, and the required app cleanup path.
- [ ] Trace persistent AppVar load/save/archive flows suitable for a language
  dictionary, including recovery from a partially written image.
- [x] Produce a minimal SPASM-built unsigned/developer-key Flash App fixture so
  future experiments do not need to rediscover header, page, and signing rules.

RPN83P is a useful real-world comparison: it places a large OS-hosted runtime in
multiple Flash pages and stores mutable state in AppVars.

The architecture, RPN83P source anchors, cleanup lifecycle, and non-atomic
AppVar warning are folded into
[`docs/sub-apps-mem-settings.md`](docs/sub-apps-mem-settings.md) and
[`docs/sub-flash-app-runtime.md`](docs/sub-flash-app-runtime.md). The SPASM
fixture is `tools/flash-apps/minimal_flash_app.asm`; its 668-byte reference
build and developer-key header are verified. RAM-budget and reset-during-save
measurements remain open.

## Reproducible deliverables

- [ ] Add TilEm macros and trace analyzers for all scenarios above.
- [ ] Store results with calculator model, ASIC ID, OS version, launch method,
  relevant ports, and before/after hashes of every RAM page.
- [x] Cross-check community techniques against their original source releases
  rather than relying only on forum summaries.
- [x] Fold confirmed conclusions into `docs/memory-management.md`,
  `docs/ram-pages.md`, `docs/paging.md`, and `docs/open-questions.md`; retain
  unresolved or hardware-only claims here.
