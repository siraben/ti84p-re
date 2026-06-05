# TI-84 Plus OS — Reverse Engineering

A reproducible Ghidra reverse-engineering project for the **TI-84 Plus** calculator OS (**version 2.55MP**), a Zilog **Z80** system. This repo contains the build scripts, derived symbol data, and reverse-engineering notes — **not** the ROM image (copyrighted) or the Ghidra database (regenerable).

## What's here

```
tools/   build pipeline (Ghidra headless scripts) + derived symbol tables
docs/    reverse-engineering notes, one file per subsystem
```

The ROM (`ti84plus.rom`) and the Ghidra project (`*.gpr`/`*.rep`) are gitignored. Put the ROM at `tools/rom.bin` (and a 16 KiB page-0 slice at `tools/ti84_page00.bin`) and run the build.

## Browse the wiki

The `docs/` are also a rendered **[mdBook](https://rust-lang.github.io/mdBook/) wiki** (sidebar nav + full-text search):

```sh
nix run            # live server at http://127.0.0.1:3000
nix build          # static HTML → ./result  (deploy anywhere)
nix develop        # shell with mdbook
```

## Build

Requires Ghidra 12.1 + JDK 21. With Ghidra **closed**:

```sh
tools/build.sh        # ~10s; rebuilds ~/Documents/ti84-re/ti84.gpr
```

The pipeline (`build.sh`):
1. `resolve_bcalls.py` — resolve both bcall jump tables (0x4xxx→page 0x3B, 0x8xxx→page 0x3F) + the bjump trampoline table from the ROM
2. `BuildTI84Full.java` — load all 64 flash pages (page 0 + overlays `page_01..3F`), RAM/IO blocks, symbols from `ti83plus.inc`, BCD-float detection, `rst 28h` fix-ups
3. `ApplyBcalls.java` — disassemble & name all 596 bcall routines at their real `(page,addr)`
4. `DeepenPass.java` — flow analysis + name remaining bcall sites
5. `RamRoutines.java` — mark the page-0 bjump trampoline table (87 cross-page vectors)
6. `ApplyBjumpTargets.java` — disassemble the hot routines those trampolines point to
7. `FixInlineBjumps.java` — fix all 280 inline `CALL cross_page_jump` tail-jumps
8. `ParserTable.java` — the page-0x38 parser handler dispatch
9. `RenameFns.java` — apply ~1600 accumulated names (`names.txt`) — gets to 100%
10. `BuildTypes.java` — TI-OS enums/structs/typed regions

Then open `ti84.gpr` in Ghidra (the GhidraMCP plugin exposes it to Claude over `:8080`).

## Current state

| Metric | Value |
|--------|-------|
| Functions | **2413** (**2413 named — 100%**) |
| bcall routines named | **535 / 535** |
| bjump sites resolved | 280 (incl. 87-entry trampoline table) |
| parser handlers | 84 (page 0x38 dispatch table) |
| Defined data (strings/floats/typed) | 618 |
| Flash pages loaded | 64 (1 MiB) |
| Docs | 26 (15 core 00–13/99 + 10 subsystem deep-dives + this) |

## Architecture in one paragraph

A Z80 (64 KiB address space) with hardware **paging** maps flash page 0 at `0000` (the kernel: RST vectors, the bcall dispatcher, FP/VAT/memory core) and swaps other 16 KiB flash pages into `4000` on demand. Code reaches routines on other pages via **bcalls** (`rst 28h` + a 2-byte ID resolved through a jump table on flash page `0x3B`). The OS is a single-tasking **context** machine: a main event loop runs the active context's handlers, switching contexts by key. All arithmetic flows through a 9-byte **BCD floating-point** engine (OP1–OP6); named objects live in the **VAT**; TI-BASIC is stored as 1/2-byte **tokens** executed by the parser on page `0x38`.

## Documentation index

| Doc | Subsystem |
|-----|-----------|
| [00](docs/00-system-overview.md) | System overview & the four pillars |
| [01](docs/01-memory-map.md) | Address space, ports, RAM layout |
| [02](docs/02-paging.md) | Flash/RAM banking |
| [03](docs/03-bcall-mechanism.md) | `rst 28h` system calls + jump table (page 0x3B) |
| [04](docs/04-interrupts.md) | IM1 ISR, timers, APD, ON key |
| [05](docs/05-variables-vat.md) | Variable Allocation Table & object types |
| [06](docs/06-floating-point.md) | BCD float format, OP registers, `_FPAdd` |
| [07](docs/07-tokenizer-basic.md) | Tokens & the parser (page 0x38) |
| [08](docs/08-display-lcd.md) | LCD driver, fonts, screen buffers |
| [09](docs/09-keyboard-link.md) | Keypad scan & link protocol |
| [10](docs/10-subsystem-map.md) | bcall API surface, system through-line |
| [11](docs/11-boot-contexts-errors.md) | Boot, the context system, `_JError`/`onSP` |
| [12](docs/12-memory-management.md) | RAM heap, VAT, Flash archive & GC |
| [13](docs/13-flash-page-map.md) | What each of the 64 flash pages holds |
| [99](docs/99-open-questions.md) | Future-work roadmap |

**Subsystem deep-dives** (from parallel multi-agent RE): `sub-calculation`, `sub-graphing`, `sub-tibasic`, `sub-vat-archive`, `sub-apps-mem-settings`, `sub-statistics`, `sub-matrix-list`, `sub-solver-numeric`, `sub-table-yvars`, `sub-link-transfer`.

## Notes
- `ti83plus.inc` is TI's 2001-era equates file (from [siraben/ti84-forth](https://github.com/siraben/ti84-forth)); the `0x8xxx` 84+-era bcalls it lacks are resolved via the page-0x3F table and RE-named in `tools/ti84plus_extra.inc`.
- ~1600 function names beyond the official bcalls are **RE-inferred** from behavior (callees, RAM/port touches) — accurate in aggregate, but a specific low-level helper's name is a best-effort guess; flagged by snake_case (vs the `_CamelCase` official TI bcalls).
- Confidence flags in the docs: **[confirmed]** (seen in disassembly), **[standard]** (matches documented TI architecture), **[hypothesis]** (inferred).
