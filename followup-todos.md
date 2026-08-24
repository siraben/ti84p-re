# Additional TI-OS reverse-engineering TODOs

This checklist extends [`todos.md`](todos.md) beyond resident-language runtime
questions. It targets reusable TI-OS knowledge, model differences, tooling,
dynamic verification, and documentation gaps. Record evidence separately for
the ROM, emulator, public documentation, and physical calculators.

## Build and provenance baseline

- [ ] Add a generated manifest containing the ROM SHA-256, OS version, model,
  ASIC revision, boot-page hashes, include-file version, Ghidra version, and
  analysis-script revisions for every result set.
- [ ] Record which local ROM components produced `tools/rom.bin`, including the
  page ranges supplied by each input file.
- [ ] Add a command that rejects traces and generated tables whose provenance
  does not match the current ROM manifest.
- [ ] Compare the BootFree and retail boot pages. List every routine, table, and
  reset path that differs or is unavailable in one image.
- [ ] Produce a reproducible database-health report: loaded pages, undefined
  bytes, overlapping instructions, unresolved cross-page jumps, function
  coverage, and symbols without typed storage.
- [ ] Detect generated documentation that embeds stale addresses after a ROM or
  symbol-table change.

## Calculator and ASIC behavior matrix

- [ ] Create one model matrix for TI-83+, TI-83+SE, early TI-84+, later 48 KiB
  TI-84+, TI-84+SE, Pocket variants, and TI-Nspire 84+ keypad emulation.
- [ ] Record ports `0x02`, `0x03`, `0x04`, `0x05`–`0x07`, `0x0E`–`0x0F`,
  `0x15`, `0x20`–`0x29`, and speed/timing ports after reset and after TI-OS
  initialization on each model.
- [ ] Determine which ASIC ID tests the OS uses and map each branch to a named
  hardware feature or workaround.
- [ ] Identify hardware behaviors that TilEm models approximately or omits:
  execution protection, Flash unlock, LCD delay, USB, timers, ON-key wake,
  memory aliasing, and power loss.
- [ ] Build physical-calculator probes that report only non-destructive model
  data and can export results as normal calculator variables.
- [ ] Separate selector aliasing from physical RAM size. Hash all candidate RAM
  pages after unique patterns, reset, APD, and OS activity.
- [ ] Verify whether TI-Nspire 84+ keypad emulation matches any physical ASIC for
  ports, protected execution, interrupts, and archive behavior.

## Reset, boot, and power transitions

- [ ] Trace cold boot, warm reset, RAM clear, ON-key wake, APD power-down, APD
  wake, battery removal, and OS installation as separate state transitions.
- [ ] Record which RAM ranges, ports, Flash settings, clock state, hooks, and
  certificate data survive each transition.
- [ ] Resolve every caller of `ram_reset_wipe` and classify the reason for the
  reset: user command, error recovery, protection fault, low power, or boot.
- [ ] Determine how the OS distinguishes a protection-triggered reset from an
  ordinary RAM clear, if it distinguishes them at all.
- [ ] Trace `_PutAway`, `_AppInit`, context teardown, and APD cleanup for the
  home screen, editors, graph screen, and Flash Apps.
- [ ] Test interrupted archive writes and garbage collection under emulator
  fault injection. Repeat safe cases on physical hardware without risking user
  data.
- [ ] Document the minimum RAM and port state required to re-enter TI-OS after a
  third-party program changes paging, interrupt mode, speed, or LCD state.

## Bcall ABI contracts

- [ ] Generate a machine-readable ABI table for every public bcall: inputs,
  outputs, destroyed registers, flags, RAM globals read or written, bank
  changes, allocations, errors, and interrupt assumptions.
- [ ] Distinguish the bcall ID from the routine body page and address throughout
  the generated table.
- [ ] Compare official SDK register contracts with static dataflow and dynamic
  sentinel tests. Flag narrower or broader clobbers.
- [ ] Identify bcalls that rely on undocumented preconditions in `IY`, OP1–OP6,
  parser state, context flags, or bank A.
- [ ] Trace error exits separately from normal returns. Record whether an error
  bypasses register restoration, page restoration, or temporary allocation
  cleanup.
- [ ] Find tail-call bcalls and bjump wrappers whose apparent ABI belongs to a
  different implementation body.
- [ ] Test nested bcalls from RAM programs, Flash Apps, interrupt handlers, and
  error handlers. Mark interfaces that are not reentrant.
- [ ] Add minimal positive and negative fixtures for high-impact memory,
  archive, display, keyboard, and parser bcalls.

## Cross-page call machinery

- [ ] Decode the complete `rst 28h` dispatcher, main bcall table, retail boot
  bcall table, bjump trampoline table, and inline cross-page tail-jump format.
- [ ] Record the exact bank-A save/restore mechanism and its behavior under
  nested calls.
- [ ] Determine whether any dispatcher path depends on interrupts being enabled
  or on a writable stack frame at a fixed depth.
- [ ] Verify every generated bcall target against raw page bytes, not only
  Ghidra control flow.
- [ ] Identify banked routines reached through function pointers rather than
  bcall or bjump tables.
- [ ] Trace calls that page RAM into bank A or bank C and determine whether the
  generic dispatcher restores the caller's mapping.
- [ ] Add a bank-aware call graph export that joins page overlays without
  merging unrelated logical addresses.

## Interrupts, timers, and asynchronous writes

- [ ] Decode the full IM 1 handler and identify every timer, ON-key, link, USB,
  APD, and clock branch.
- [ ] Map interrupt-owned RAM fields and buffers. Record which writes can occur
  while a foreground assembly program waits in `_GetKey`.
- [ ] Determine which interrupt sources remain enabled after `DI`, which events
  latch for later delivery, and which hardware state can still change.
- [ ] Measure timer cadence at 6 MHz and 15 MHz under each documented timer-port
  configuration.
- [ ] Trace APD countdown initialization, suppression, power-down, wake, and
  screen restoration.
- [ ] Verify the ON-key error/break path while the OS is inside a bcall, parser
  recursion, archive operation, or app context.
- [ ] Identify interrupt handlers installed by common shells and hooks. Record
  chaining rules and failure behavior when one handler does not preserve state.
- [ ] Add an emulator facility that injects a selected interrupt at a precise
  instruction count for reproducible race tests.

## Error contexts and unwinding

- [ ] Decode the error-context stack layout, `onSP`, error codes, saved pages,
  and saved application/context state.
- [ ] Trace `_JError`, `_PushErrorHandler`, `_PopErrorHandler`, `Quit`, `Goto`,
  and forced context teardown.
- [ ] Determine which allocations and temporary variables the OS cleans up when
  control leaves through an error rather than a normal return.
- [ ] Record how `SP`, `IX`, `IY`, interrupt mode, and paging are restored for
  errors raised in RAM, Flash, parser code, and interrupts.
- [ ] Test nested error handlers and errors raised while formatting the original
  error message.
- [ ] Identify error paths that intentionally reset the calculator instead of
  returning to a context.
- [ ] Add guard fixtures around the hardware stack and error-context frames to
  measure maximum depth and corruption behavior.

## RAM allocator and pointer-fixup coverage

- [ ] Decode the allocator's complete pointer-fixup list for `_InsertMem`,
  `_DelMem`, variable creation, variable deletion, archive, and unarchive.
- [ ] Identify pointers that the allocator does not know about: third-party
  globals, cached application pointers, parser-local pointers, and interrupt
  buffers.
- [ ] Test insertion and deletion at the bottom, middle, and top of user RAM.
  Record movement direction and overlap handling.
- [ ] Determine the exact conditions under which FPS or OPS storage moves rather
  than only its boundary pointer changing.
- [ ] Trace `_EnoughMem`, `_MemChk`, and allocation failure into the error
  subsystem. Pin size-field and VAT-entry overhead for every variable type.
- [ ] Find all ROM code that writes `FPS`, `OPS`, `pTemp`, `progPtr`, or
  `symTable` outside the main allocator.
- [ ] Add a relocation-fuzz fixture with several variables and sentinels around
  every allocator boundary.

## VAT and variable-format edge cases

- [ ] Generate byte-level layouts for every RAM and archived variable type,
  including version bytes, flags, name encodings, formulas, and size fields.
- [ ] Test zero-length, maximum-length, hidden, locked, protected, malformed,
  and unsupported-version variables.
- [ ] Resolve the ordering rules for VAT entries and the separate program,
  AppVar, and system-variable search paths.
- [ ] Determine how duplicate or malformed names are handled when created by
  direct memory manipulation or link transfer.
- [ ] Trace variable rename, lock, archive, unarchive, and delete across every
  context that exposes them.
- [ ] Verify which variable pointers remain valid after edits that change size
  but do not create a new VAT entry.
- [ ] Document how tokenized names differ from ASCII names and where the OS
  compares tokens, bytes, or display strings.

## Archive and garbage collection

- [ ] Decode archive-sector headers, object headers, deleted-object markers,
  free-space accounting, and garbage-collection state.
- [ ] Determine object placement rules near 16 KiB page boundaries and Flash
  sector boundaries.
- [ ] Trace archive reads that cross a page boundary through direct mapping,
  `_FlashToRam`, parser access, and link transmission.
- [ ] Record every pointer and VAT field updated by archive garbage collection.
- [ ] Test recovery from an interrupted archive, unarchive, delete, and garbage
  collection at each erase/program phase in an emulator copy.
- [ ] Quantify Flash writes caused by common workflows and shell writeback.
- [ ] Identify OS checks for low battery, certificate state, Flash lock, and
  available contiguous archive space before a write.
- [ ] Add an archive visualizer that correlates physical sectors, VAT entries,
  deleted objects, and free spans.

## Keyboard and input stack

- [ ] Trace the full `_GetCSC` matrix scan and map raw codes across all supported
  calculator keyboards.
- [ ] Decode `_GetKey`'s 2nd, ALPHA, alpha-lock, repeat, mode-key, context-key,
  and link-command state machine.
- [ ] Determine which key paths call active-context handlers rather than return
  a code directly to the caller.
- [ ] Measure key-repeat timing and differences between 6 MHz and 15 MHz modes.
- [ ] Trace ON-key behavior separately from matrix keys, including break and
  wake behavior.
- [ ] Resolve keyboard behavior with headphones or link hardware attached.
- [ ] Build a generated table joining raw scan codes, cooked key codes, token
  values, display strings, and context-specific aliases.

## Display, text, and MathPrint state

- [ ] Map all LCD buffers, shadows, cursor fields, pen coordinates, font state,
  inverse/scroll flags, and dirty-region fields.
- [ ] Trace large-font and small-font rendering from token or character input to
  LCD writes.
- [ ] Identify routines that use `plotSScreen`, `saveSScreen`,
  `appBackUpScreen`, `textShadow`, or page-`0x83` display storage.
- [ ] Decode MathPrint entry-history allocation, rendering, scrolling, and
  invalidation around `numLastEntries` at `0x8E29`.
- [ ] Determine which screen state `_GetKey`, errors, APD, app changes, and graph
  contexts save and restore.
- [ ] Compare LCD delay and busy-flag behavior across hardware revisions.
- [ ] Add pixel-accurate screenshot tests for fonts, clipping, scrolling,
  inverse text, graph-buffer copies, and context restoration.

## Parser and TI-BASIC execution

- [ ] Complete the page-`0x38` handler-table map with token names, grammar role,
  input cursor changes, outputs, errors, and called subsystems.
- [ ] Recover the recursive-descent precedence structure as a typed graph rather
  than a flat function list.
- [ ] Trace program calls, `Return`, `Stop`, `Goto`, `Lbl`, loops, and block
  matching through nested programs and error exits.
- [ ] Determine exact parser refill behavior for RAM, archived, protected, and
  shell-launched programs.
- [ ] Map parser temporaries on FPS, OPS, hardware stack, and fixed RAM.
- [ ] Fuzz token streams with truncation, invalid two-byte tokens, malformed
  numbers, and unmatched control structures in an emulator snapshot.
- [ ] Generate executable fixtures from the token table and compare observed
  handler coverage with the documented dispatch map.

## Link and USB state machines

- [ ] Decode the serial link send/receive state machines, timeouts, checksums,
  retries, and error exits.
- [ ] Trace silent link activity while `_GetKey` waits on the home screen and in
  editor contexts.
- [ ] Map every USB buffer on RAM page `0x83` and the ownership transitions
  between foreground code, interrupts, and boot routines.
- [ ] Record page mappings and interrupt state during variable receive, OS
  receive, certificate transfer, and direct USB operations.
- [ ] Test aborted transfer cleanup at each protocol state.
- [ ] Compare SilverLink, direct serial link, and USB paths for variable-format
  validation and archive placement.
- [ ] Build packet-level traces that link external traffic to ROM routines and
  RAM-buffer mutations.

## Apps, hooks, and contexts

- [ ] Decode Flash App discovery, validation, header parsing, page assignment,
  launch, context installation, and exit.
- [ ] Determine which App header fields TI-OS validates and which fields are
  advisory metadata.
- [ ] Trace parser, raw-key, home-screen, app-change, catalog, and menu hooks.
- [ ] Document hook chaining, ownership, persistence across RAM clears, and
  behavior when an installed App is deleted.
- [ ] Identify fixed RAM and AppVar state used by Doors CS, MirageOS, zStart,
  Omnicalc, and other common extensions.
- [ ] Compare direct TI-OS launch with shell launch for registers, pages,
  interrupts, scratch RAM, source-variable handling, and writeback.
- [ ] Test context switching while an App owns temporary variables, custom
  interrupts, or non-default page mappings.

## Performance and timing

- [ ] Add instruction-count and wall-clock benchmarks for bcalls, parser
  operations, rendering, allocation, archive access, and page switching.
- [ ] Separate CPU-frequency effects from Flash wait states, LCD delays, and
  timer configuration.
- [ ] Identify ROM routines with hardware-specific fast and slow paths.
- [ ] Measure interrupt latency and maximum interrupt-disabled spans in archive,
  USB, display, and memory routines.
- [ ] Profile hot cross-page call paths and quantify dispatcher overhead.
- [ ] Record timings in a machine-readable format keyed by ROM hash and hardware
  profile.

## Dynamic-tracing infrastructure

- [ ] Extend trace records with active mappings for banks A, B, and C at every
  instruction without requiring post-hoc inference from truncated traces.
- [ ] Record physical RAM-page reads and writes as well as logical addresses.
- [ ] Add watch ranges, register predicates, bcall entry/exit events, interrupt
  events, and error-context events.
- [ ] Support deterministic checkpoint, restore, and event injection from a
  macro or command-line scenario.
- [ ] Add differential traces between two ROMs, hardware profiles, or input
  sequences, aligned by named routine rather than raw instruction number.
- [ ] Generate function coverage by overlay, call edge, bcall, and parser
  handler.
- [ ] Detect writes whose logical address remains the same while the physical
  RAM page changes.
- [ ] Store compact trace indexes so multi-gigabyte traces do not require a full
  scan for every query.

## Static-analysis improvements

- [ ] Type all fixed RAM globals and arrays referenced by more than one
  subsystem.
- [ ] Propagate bcall ABI types into callers without treating cross-page
  trampolines as ordinary same-page functions.
- [ ] Detect inline data after calls, restart vectors, and page-local dispatch
  tables that Ghidra may disassemble as code.
- [ ] Add scripts that compare raw disassembly, Ghidra instructions, and
  generated function boundaries.
- [ ] Recover function-pointer tables and annotate their page provenance.
- [ ] Identify shared code tails and prevent duplicated pseudo-functions from
  producing conflicting names.
- [ ] Export a stable symbol format consumed by trace tools, docs generators,
  and external emulators.

## Regression corpus and result format

- [ ] Define one scenario manifest format with ROM identity, calculator model,
  initial variables, key/link events, expected screen, expected RAM signatures,
  and expected coverage anchors.
- [ ] Add positive, negative, boundary, and interrupted-operation cases for each
  documented subsystem.
- [ ] Preserve before/after RAM-page hashes and selected byte ranges for every
  state-mutating fixture.
- [ ] Separate emulator-only destructive tests from physical-hardware-safe
  probes.
- [ ] Store expected failures where the OS intentionally rejects malformed data
  or unsupported hardware.
- [ ] Run the corpus against multiple OS releases and generate a behavioral
  difference report.
- [ ] Add a small reproducible seed corpus for parser, VAT, archive, and link
  fuzzing.

## Documentation reconciliation

- [ ] Add an evidence index mapping each `[confirmed]` claim to a ROM address,
  trace fixture, generated table, or byte decode.
- [ ] Add model and OS applicability boxes to pages whose behavior changes by
  hardware revision.
- [ ] Audit every use of “safe RAM,” “unused page,” “fixed,” “always,” and
  “preserved” against interrupts, contexts, APD, shells, and errors.
- [ ] Distinguish logical addresses, physical RAM pages, Flash pages, Ghidra
  overlays, and bcall IDs in every table.
- [ ] Link each unresolved `[hypothesis]` to a concrete fixture or TODO that can
  resolve it.
- [ ] Generate RAM-map and Flash-page-map tables from typed symbols where
  possible, then flag handwritten discrepancies.
- [ ] Add a “known emulator differences” page with one reproducible probe per
  difference.
- [ ] Ensure every generated artifact records its source command and can be
  reproduced inside the Nix environment.

## Follow-up deliverables

- [ ] Publish a hardware/OS behavior matrix with confidence and provenance per
  cell.
- [ ] Publish the machine-readable bcall ABI and RAM-clobber databases.
- [ ] Publish a bank-aware call graph and parser-handler graph.
- [ ] Publish allocator, VAT, archive, context, and interrupt state diagrams.
- [ ] Publish a trace-backed list of memory regions safe under named, explicit
  operating conditions.
- [ ] Publish the reusable fixture corpus and scenario runner.
- [ ] Fold resolved results into the subsystem pages and remove completed items
  from this follow-up list.
