# Evidence audit coverage

This audit covers the 55 wiki content pages, their shared address catalogs,
and the supporting tools implicated by the reviewed claims. The base revision
is `b887b8f8`. Raw checks use the canonical retail OS 2.55MP image with SHA-256
`7d9a7d96d89fc552ebee6afdbdd011fdc6047be9c16d308245dff07eb1f7bd6d`.

The tables record review scope and evidence sources. A reviewed page is not a
claim that every routine has been executed or every remaining hypothesis
resolved. Source-token values, numeric dispatch selectors, inferred names,
ROM behavior, emulator results, and physical-hardware behavior remain separate.

## Shared architecture and provenance

| Page | Checked evidence |
|---|---|
| [System overview](../../docs/system-overview.md) | Machine/image identity, subsystem links, RAM-revision evidence boundaries |
| [Subsystem map](../../docs/subsystem-map.md) | Representative SDK names and body mappings; removed unsupported keyword-bucket counts |
| [Memory map](../../docs/memory-map.md) | Fixed/banked windows, RAM equates and typed regions; `onSP` write at `ram:0BE9` |
| [Flash page map](../../docs/flash-page-map.md) | All 64 page contents, 42 erased pages, per-page main-table row counts |
| [The bcall mechanism](../../docs/bcall-mechanism.md) | Complete dispatcher/restore sequence at `ram:2A2F`–`ram:2B48`, RST targets and trampoline descriptors |
| [bcall index](../../docs/bcall-index.md) | All 732 rows against raw table triples and separate name inputs; community-use CSV counts and source/runtime limits |
| [Conventions and evidence](../../docs/conventions.md) | Address-space meaning, name provenance, resolver guards and runtime-coverage wording |
| [Glossary](../../docs/glossary.md) | RAM symbols and cross-page consistency, including `errSP` versus `onSP` |
| [Build and evidence provenance](../../docs/provenance.md) | Image/component hashes, database-health report totals, community-inventory totals, manifest and artifact-verifier behavior |
| [Open questions](../../docs/open-questions.md) | Reconciled TABLE, matrix, MathPrint, statistics and assembly-launch claims with subsystem evidence |

`ti84re.wiki.audit_rom_claims` independently decodes table bytes without
regenerating the checked catalogs. It checks 645 main mappings, 83 SDK-named
boot mappings, four inferred boot mappings, 87 bjump descriptors, six RST
vectors, 19 per-page row counts, blank-page ranges, and the version string.
Its tests change names, targets, row counts and formatting to check that
catalog drift is detected. It does not prove the named routines' semantics.

The provenance digest includes maintained scripts and symbol/probe inputs in
their current subdirectories. CSV validation requires a valid hash on each
row; JSON validation checks every declared identity and permits report-level
provenance. These checks establish identity consistency, not the truth of an
analysis conclusion.

## Hardware and boot

| Page | Checked evidence |
|---|---|
| [ASIC status, identity, protection, and GPIO](../../docs/asic-status-gpio.md) | Complete I/O census, battery/GPIO paths, asymmetric port read/write meanings |
| [Boot hardware](../../docs/boot-hardware.md) | Ordered 35-write manifest, protected-write sequences, dormant diagnostic |
| [Bus timing](../../docs/bus-timing.md) | Timing profiles, LCD delay assumptions, probe setup and cleanup |
| [Clock, timers, and power](../../docs/clock-timers-power.md) | Timer API, RTC read sequence, retail port-`2D` initialization |
| [Execution protection](../../docs/execution-protection.md) | Protected-write wrappers, model predicates and fetch-probe preconditions |
| [Hardware probes](../../docs/hardware-probes.md) | All 21 programs assembled; frames, decoder comparisons, battery normalization and execution-probe mapping assumptions |
| [Interrupts](../../docs/interrupts.md) | IM1 status and acknowledgement semantics, emulator/physical distinctions |
| [Keyboard and link](../../docs/keyboard-link.md) | Keypad and transfer entry points and byte paths |
| [Keypad and ON-key hardware](../../docs/keypad-on-hardware.md) | Active-low scan and separate ON/status behavior |
| [LCD hardware](../../docs/lcd-hardware.md) | Busy and capture loops, destination branch, diagnostic evidence |
| [Two-wire link hardware](../../docs/link-port-hardware.md) | Raw lines versus assist FIFO, differential-audio evidence limits |
| [MD5 hardware](../../docs/md5-hardware.md) | Round operand order, original/working state, feed-forward and result-read sequence |
| [Paging](../../docs/paging.md) | Paired-to-independent reset transition and window aliases |
| [RAM pages](../../docs/ram-pages.md) | Page-83 capture/history anchors and paired-window trace notation |
| [Retail boot](../../docs/retail-boot.md) | Reset instruction boundaries, page-0 Flash markers and boot API mappings |
| [USB ASIC and link assist](../../docs/sub-usb-asic.md) | Assist I/O addresses versus native USB transport, conditional flags and distinct timeout exits |
| [Display and LCD](../../docs/display-lcd.md) | Drawing entry points and `_SaveDisp` caller-selected destination at `39:5DFF` |

A separate pass compared 342 address-annotated instructions with ROM
disassembly. The hardware model/probe tests and ROM I/O, boot-manifest,
protected-write, and LCD-diagnostic analyzers support their declared scopes.
No physical calculator was exercised.

The Bad Apple injector now verifies the retail image, patches the actual
protected-register immediates, preserves USB boot page `2F`, and loads source
pages downward from `2E` through `08`. Tests cover identity rejection, distinct
page contents, USB preservation, and input aliases. Historical playback counts
do not validate this corrected partial-image fixture; a fresh emulator capture
remains necessary before assigning it playback results.

## Storage, launch, and transfer

| Page | Checked evidence |
|---|---|
| [Boot, contexts, and errors](../../docs/boot-contexts-errors.md) | Reset `35:719F`, context checkpoint `ram:0BE9`, error frames `ram:27BB`–`ram:2800` |
| [Flash memory](../../docs/flash-memory.md) | Model predicate `ram:1837`, worker selection `3D:5247`, command stores, certificate and GC analyzers |
| [Flash emulator comparison](../../docs/flash-emulator-comparison.md) | Worker signatures and checked journal/certificate artifacts; historical emulator evidence boundaries |
| [Flash bcall guide](../../docs/flash-bcall-guide.md) | Protected wrapper register preservation, copier `3D:6763`–`3D:678A`, zero-count boundary |
| [Memory management](../../docs/memory-management.md) | Allocation helpers `ram:0F0C`–`ram:1080`, inclusive `_MemChk`, archive discriminator |
| [Variables and VAT](../../docs/variables-vat.md) | Name/type/page layout, named-list limit, creator branches `ram:1002`–`ram:1080` |
| [VAT and archive](../../docs/sub-vat-archive.md) | Lookup bounds, mirror save/restore, `07:6171`–`07:628A`, archive-header skip and unarchive copy/retirement |
| [Apps, memory, and settings](../../docs/sub-apps-mem-settings.md) | RAM reset, mode predicate flags, 15 local App-header binaries |
| [Link transfer](../../docs/sub-link-transfer.md) | Request/receive `3C:4DD2` and `3C:4763`, separate send `3C:58ED`, staging `3C:6AB1` |
| [Resident scratch](../../docs/sub-resident-scratch.md) | Scratch lifetime statements and cited source/data manifests; unmeasured paths remain qualified |
| [Resident programs](../../docs/sub-resident-programs.md) | Launch markers and limits `07:5717`–`07:5855`, archived pointer/header semantics `3D:6625`, copier bounds |

Flash, link and community test suites passed during this review. The ROM
certificate-rebuild, GC-journal, command-store, worker-descriptor and link-staging
analyzers were also run. Committed community-source and trace tables were
checked as historical artifacts; their absent archives and raw traces were not
reconstructed or relabeled as newly reproduced results.

## Language, arithmetic, and display layout

| Page | Checked evidence |
|---|---|
| [Floating point](../../docs/floating-point.md) | OP layout and helper flags, 39 literal coefficient rows byte-compared with ROM, near-one log branch, corrected trig product index and recurrence boundaries |
| [Calculation](../../docs/sub-calculation.md) | `_Int`, `_RndGuard`, sign/zero guards, reciprocal and error-frame semantics |
| [Tokenizer](../../docs/tokenizer-basic.md) | Token widths, parser tables, ROM string extraction and bounded parser tests |
| [Token tables](../../docs/token-tables.md) | 492 catalog rows and their external/model-filtered provenance; not a ROM-completeness claim |
| [TI-BASIC](../../docs/sub-tibasic.md) | Normalized `BB` selectors, divisor operand, record shapes and checked parser coverage |
| [TI-BASIC programming](../../docs/sub-tibasic-programming.md) | Control-flow and performance claims against interpreter/fixture evidence |
| [For parentheses](../../docs/sub-tibasic-for-paren.md) | Paired fixture reports, temporary-buffer sequence and remaining causal gap |
| [TI-BASIC examples](../../docs/sub-tibasic-examples.md) | Graph versus pixel coordinates, redraw limits, illustrative digit-array bounds and scoped fixture observations |
| [TI-BASIC tracing](../../docs/sub-tibasic-tracing.md) | Reducer artifacts and finite coverage/error claims |
| [Graphing](../../docs/sub-graphing.md) | Indexed pointer base, circle/regraph models, raw-coordinate differential checks |
| [Matrices and lists](../../docs/sub-matrix-list.md) | `38:6FB2` normalization, row-reduction modes, cumulative helpers, determinant mode-byte parity and inverse-only permutation updates; full factorization recurrence remains open |
| [Numerical solver](../../docs/sub-solver-numeric.md) | Actual calculus/root call edges, default constants, centered quotient, counter/error paths; unproven algorithm names removed |
| [Statistics](../../docs/sub-statistics.md) | Source tokens versus selectors, common stat-variable resolver, `TStat` store at `3A:54D9`, separate normal upper-tail body at `3A:54FD`, conditional logarithm mask, and MathPrint contamination of interactive coverage |
| [TABLE and Y-variables](../../docs/sub-table-yvars.md) | Cache/base-pointer helpers, copies at `05:601E`/`05:6026` and shift at `05:6032`, expression-stack bcall, and limits of evaluator/scroll observations |
| [Equation display](../../docs/sub-equation-display.md) | Structural records, action/cell distinctions, numeric versus rendering call paths |
| [MathPrint editor](../../docs/sub-mathprint-editor.md) | Editor claims against ROM anchors, settled record/framebuffer oracles and renderer artifacts |
| [MathPrint validation](../../docs/sub-mathprint-validation.md) | Corpus, extraction, saturation and differential-test scope |

`ti84re.tibasic.analyze_numeric_dispatch` records 25 raw instruction anchors
and 11 table triples independently of inferred Ghidra names. This identifies
`fnInt(` at `07:6365`, `nDeriv(` at `02:6AF3`, and the normalized row-reduction
dispatch, real versus complex power entries, and selected numeric-helper
contracts; it does not prove complete numerical algorithms. The associated
coefficient regression compares all 39 documented rows with the raw ROM.

MathPrint font, token and layout exports were compared byte-for-byte with
the web artifacts. Graph-coordinate checks include 220,000 raw OP1 differential
cases. These checks validate the compared artifacts and models; they do not
substitute for a fresh native trace of every editor or numerical path.

## Reproduction and limits

From the repository root:

```sh
nix develop -c python3 -m ti84re.wiki.audit_rom_claims
nix develop -c python3 -m ti84re.tibasic.analyze_numeric_dispatch
nix develop -c python3 -m unittest discover -s tools/tests -t tools
nix build --no-link
git diff --check
```

The full Python suite requires the original pinned base-ROM and AppVar
containers under `tools/roms/`. They are absent in this audit environment, so
`tests.rom.test_rom_assembly.RomAssemblyTests.setUpClass` cannot run. The
assembled canonical ROM is available and hash-verified. Optional tests that
require absent raw traces also cannot supply fresh replay evidence.

Remaining research includes physical timing and reset behavior, full DISTR and
finance caller graphs, the integration rule, TABLE evaluation details, loop
state-word meaning, and the unresolved editor transitions named in the wiki.
Those limits remain explicit rather than inheriting confirmation from a
plausible name, a visited address, or a passing model test.
