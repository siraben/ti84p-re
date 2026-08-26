# TI-84 Plus OS — Reverse engineering

An evidence-indexed technical reference for TI-84 Plus OS 2.55MP. The wiki
documents ROM behavior, hardware interfaces, emulator differences, and the
remaining unknowns for readers working on emulation, interoperability, or Z80
software analysis. This repository contains the reproducible Ghidra build,
derived symbol data, and reverse-engineering notes. It does not contain the
copyrighted ROM image or the regenerable Ghidra database.

Read the rendered wiki: <https://siraben.github.io/ti84p-re/>

## What's here

```text
docs/                  reverse-engineering notes, one file per subsystem (the rendered wiki)
tools/                 build pipeline (Ghidra headless scripts) + derived symbol tables
.codex/skills/         repository writing and review guidance
flake.nix · book.toml  mdBook build/serve + vendored KaTeX/Mermaid/pseudocode assets
```

The ROM and Ghidra project (`*.gpr`/`*.rep`) are gitignored. Put the three pinned local inputs under `tools/roms/`, then run `python3 tools/assemble_local_rom.py --check` to validate them without writing or `python3 tools/assemble_local_rom.py` to create `tools/rom.bin` plus the 16 KiB page-0 slice at `tools/ti84_page00.bin`. The validator decodes the two TI AppVar containers, checks their internal lengths and checksums, and requires the exact hashes recorded in `tools/rom_signatures.py`.

Generate a result manifest with `nix develop -c python3
tools/rom_provenance.py manifest --rom tools/rom.bin`; use its `verify`
subcommand to reject CSV or JSON evidence produced from a different ROM. The
[provenance page](docs/provenance.md) distinguishes the canonical retail image
from the BootFree runtime-trace variant and records the reproducible Ghidra
database-health audit.

## Browse the wiki

The `docs/` are also a rendered [mdBook](https://rust-lang.github.io/mdBook/) wiki (sidebar nav + full-text search):

```sh
nix run            # live server at http://127.0.0.1:3000
nix build          # static HTML → ./result  (deploy anywhere)
nix develop        # shell with mdbook
```

## Build

Requires Ghidra 12.1 + JDK 21. The Nix development shell provides both. With
Ghidra *closed*:

```sh
nix develop -c tools/build.sh   # rebuilds ti84.gpr
```

`tools/build.sh` also discovers Homebrew and upstream Ghidra installations. Set
`GHIDRA_ANALYZE_HEADLESS` when the launcher is installed in another location.

The pipeline (`build.sh`):

1. `resolve_bcalls.py` — resolve the main bcall jump table (`0x4xxx`→page `0x3B`), the retail boot bcall table (`0x8xxx`→pages `0x3F`/`0x2F` when present), and the bjump trampoline table from the ROM
2. `BuildTI84Full.java` — load all 64 flash pages (page 0 + overlays `page_01..3F`), RAM/IO blocks, symbols from `ti83plus.inc`, BCD-float detection, `rst 28h` fix-ups
3. `ApplyBcalls.java` — disassemble and name the resolved main and retail boot bcall routines at their real `(page,addr)`
4. `DeepenPass.java` — flow analysis + name remaining bcall sites
5. `RamRoutines.java` — mark the page-0 bjump trampoline table (87 cross-page vectors)
6. `ApplyBjumpTargets.java` — disassemble the hot routines those trampolines point to
7. `FixInlineBjumps.java` — fix the currently disassembled inline `CALL cross_page_jump` tail-jumps
8. `ParserTable.java` — the page-0x38 parser handler dispatch
9. `RenameFns.java` — apply the accumulated function names in `names.txt`
10. `BuildTypes.java` — TI-OS enums, structures, and typed regions
11. `ApplyLabels.java` — apply reviewed ROM-data and internal-entry labels from `labels.txt`
12. `ApplyOffsetRefs.java` — render reviewed structure-field references from `poffsets.txt`
13. `FixInlineBjumps.java` — repeat the fix-up after seeded code and checked metadata are installed
14. `ApplyOffsetRefs.java` — restore or verify the reviewed offsets after final flow analysis
15. `RenameVars.java` — apply reviewed local-variable names from `varnames.txt`

Then open `ti84.gpr` in Ghidra for interactive analysis.

## Current state

| Metric | Value |
|--------|-------|
| Functions | rebuilt from the local ROM by `tools/build.sh` |
| bcall routines named | 728 total: 645 main-table bcalls + 83 retail boot-table bcalls |
| bjump sites modeled | every disassembled inline `CALL cross_page_jump` site; the total includes the 87-entry trampoline table |
| parser handlers | 84 (page 0x38 dispatch table) |
| Defined data (strings/floats/typed) | 618 |
| Flash pages loaded | 64 (1 MiB) |
| Docs | 57 rendered content pages |

The checked [database-health report](tools/data/database-health.json) records
coverage and concrete cleanup locations for the current BootFree-derived
database. Regenerate it with the read-only command on the
[provenance page](docs/provenance.md); its ROM hash prevents those results from
being confused with the canonical retail database.

## Architecture in one paragraph

A Z80 with a 64 KiB address space maps Flash page `00` at `0x0000` and swaps other 16 KiB Flash pages into `0x4000` on demand. Page `00` contains the RST vectors, bcall dispatcher, floating-point core, VAT, and memory services. Bcalls reach other pages through `rst 28h` plus a 2-byte ID resolved through the jump table on page `3B`. The OS is a single-tasking context machine: its main loop runs the active context's handlers and changes contexts in response to keys. Arithmetic uses a 9-byte BCD floating-point engine, named objects live in the VAT, and the parser on page `38` executes TI-BASIC stored as one- or two-byte tokens.

## Suggested starting points

The rendered wiki sidebar contains the complete page list. These pages provide
the shortest paths into the main kinds of material:

| Page | Subsystem |
|------|-----------|
| [System overview](docs/system-overview.md) | The four pillars and the system through-line |
| [Memory map](docs/memory-map.md) | Address space, ports, RAM layout |
| [Paging](docs/paging.md) | Flash/RAM banking |
| [The bcall mechanism](docs/bcall-mechanism.md) | `rst 28h` system calls + jump table (page 0x3B) |
| [Interrupts](docs/interrupts.md) | IM1 ISR, timers, APD, ON key |
| [Clock, timers, and power](docs/clock-timers-power.md) | Clock domains, timer API, RTC, APD cadence, shutdown, and TilEm fidelity |
| [MD5 accelerator and boot API](docs/md5-hardware.md) | ASIC round operation, streaming digest bcalls, descriptors, traces, and signature transformation |
| [Variables and the VAT](docs/variables-vat.md) | Variable Allocation Table and object types |
| [Floating-point](docs/floating-point.md) | BCD float format, OP registers, `_FPAdd` |
| [Tokenizer and TI-BASIC tokens](docs/tokenizer-basic.md) | Tokens and the parser (page `0x38`) |
| [Display and LCD](docs/display-lcd.md) | LCD driver, fonts, screen buffers |
| [Keyboard and link](docs/keyboard-link.md) | Key input and wired-transfer overview |
| [Keypad and ON-key hardware](docs/keypad-on-hardware.md) | Matrix timing, ghosting, debounce, repeat, ON interrupts, and wake |
| [Subsystem map](docs/subsystem-map.md) | bcall API surface, system through-line |
| [Boot, contexts, and errors](docs/boot-contexts-errors.md) | Boot, the context system, `_JError`, and `onSP` |
| [Memory management](docs/memory-management.md) | RAM heap, VAT, Flash archive, and garbage collection |
| [Flash memory](docs/flash-memory.md) | Flash geometry, ASIC protection, program and erase bcalls, and archive traces |
| [Flash page map](docs/flash-page-map.md) | What each of the 64 flash pages holds |
| [RAM pages](docs/ram-pages.md) | RAM page selectors, page `83`, and restore rules |
| [Open questions](docs/open-questions.md) | Future-work roadmap |

Subsystem deep dives cover calculation, graphing, TI-BASIC, VAT and archive
handling, apps, statistics, matrices and lists, numerical solvers, tables,
MathPrint, link transfer, and the USB/link-assist hardware.

Reference pages include the [glossary](docs/glossary.md), [conventions and evidence](docs/conventions.md), [bcall index](docs/bcall-index.md), and [two-byte token tables](docs/token-tables.md).

## Contributing

The repository [writing standard](.codex/skills/ti84-re-writing/SKILL.md) defines prose structure, sentence-case headings, address notation, confidence flags, function naming, and mdBook mechanics. [Conventions and evidence](docs/conventions.md) explains the reader-facing notation. Check static claims against the generated Ghidra database and raw `tools/rom.bin` bytes; cross-page trampolines can leave otherwise valid routines undefined during automatic analysis. For dynamic evidence, run the ROM under headless TilEm and map coverage differences back to the `page_NN:addr` model with [the tracing guide](tools/dynamic-tracing.md). Run `nix build` before committing to validate math, diagrams, assets, and local links.

## Legal

Independent reverse-engineering notes for interoperability and education. No
copyrighted TI ROM image or OS code is included — the local ROM inputs are
gitignored and must be supplied separately. `ti83plus.inc` is TI's
freely-distributed equates file (the full 2007 TI-83 Plus SDK include, as hosted
on WikiTI). All trademarks belong to Texas Instruments; this project is not
affiliated with or endorsed by TI.

## Evidence limits

- `ti83plus.inc` is the full 2007 TI-83 Plus SDK equates file hosted on WikiTI. It defines the TI-84 Plus-era `0x8xxx` boot bcall IDs. With the validated local ROM assembled from `ti84plus_patched.rom`, `D84PBE1.8Xv`, and `D84PBE2.8Xv`, those entries resolve through retail page `3F`; the USB boot routines land on page `2F`. These files have exact, reproducible identities, but their acquisition history does not establish a physical-calculator capture.
- About 1,600 function names beyond the official bcalls are inferred from behavior, including callees and RAM or port accesses. A specific low-level helper name remains a best-effort interpretation; `snake_case` distinguishes inferred names from official `_CamelCase` TI names.
- Confidence flags in the docs: [confirmed] (direct ROM or labeled-trace evidence), [standard] (documented TI architecture consistent with the ROM), and [hypothesis] (an inference that remains open).
