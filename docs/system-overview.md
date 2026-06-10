# TI-84 Plus OS — Reverse-engineering notes: system overview

Target: `ti84plus.rom` (1 MiB flash dump). OS self-identifies as 2.55MP. CPU: Zilog Z80 (16-bit address bus, 64 KiB logical space) with hardware flash/RAM paging. Ghidra project: `ti84.gpr` (rebuild: `tools/build.sh`).

> Confidence is flagged: [confirmed] = verified in disassembly/decompiler; [standard] = matches documented TI-83+/84+ architecture and is consistent with the disassembly; [hypothesis] = inferred, not yet verified.

## The big picture

The TI-84+ is a Z80 machine that can only see 64 KiB at once, but has 1 MiB of flash and 128 KiB of RAM. It bridges that gap with a 4-slot paging scheme and a system-call ("bcall") mechanism that lets code on one 16 KiB flash page call routines on any other page. The OS is a single-tasking monitor: a boot/kernel core on flash `page 0` (always mapped low), a large body of OS routines spread across the other flash pages and reached via bcalls, and a fixed RAM region holding the system state (flags, floating-point registers, display buffers, the variable table).

Everything the user interacts with — the homescreen, TI-BASIC programs, graphing, the catalog — is built on four pillars:

1. **Paging + bcalls** — how code and data beyond 64 KiB are reached. (see [paging.md](paging.md), [bcall-mechanism.md](bcall-mechanism.md))
2. **The floating-point engine** — 9-byte BCD reals/complex in the OP1–OP6 registers; all math flows through these. ([floating-point.md](floating-point.md))
3. **The variable system (VAT)** — named objects (reals, lists, matrices, strings, programs, appvars…) catalogued in the Variable Allocation Table. ([variables-vat.md](variables-vat.md))
4. **The tokenizer/parser** — TI-BASIC is stored as 1- and 2-byte tokens; the parser executes them. ([tokenizer-basic.md](tokenizer-basic.md))

Around those sit the I/O subsystems: the IM1 interrupt that drives timing/APD/cursor/ON-key ([interrupts.md](interrupts.md)), the LCD driver, the keypad scanner, and the link port.

## Subsystem index

Each row maps a documentation page to the subsystem it covers and its analysis status.

| Doc | Subsystem |
|-----|-----------|
| [memory-map.md](memory-map.md) | Address space, ports, RAM layout |
| [paging.md](paging.md) | Flash/RAM banking (ports 6/7) |
| [bcall-mechanism.md](bcall-mechanism.md) | rst 28h system calls + jump table |
| [interrupts.md](interrupts.md) | IM1 ISR, timers, APD, ON key |
| [variables-vat.md](variables-vat.md) | Variable Allocation Table, object types |
| [floating-point.md](floating-point.md) | BCD float format, OP registers |
| [tokenizer-basic.md](tokenizer-basic.md) | Token tables, parser/interpreter |
| [display-lcd.md](display-lcd.md) | LCD ports, screen buffers |
| [keyboard-link.md](keyboard-link.md) | Keypad scan, link protocol |
| [subsystem-map.md](subsystem-map.md) | bcall API surface, system through-line |
| [boot-contexts-errors.md](boot-contexts-errors.md) | Boot, context system, _JError/onSP |
| [memory-management.md](memory-management.md) | RAM heap, VAT/userMem, Flash archive/GC |
| [flash-page-map.md](flash-page-map.md) | What each of the 64 flash pages contains |
| [ram-pages.md](ram-pages.md) | RAM page selectors, page `83`, and restore rules |
| [open-questions.md](open-questions.md) | Prioritized future-work roadmap |
| [sub-calculation.md](sub-calculation.md) | Calculation engine: FP ops, transcendentals, formatting, errors |
| [sub-graphing.md](sub-graphing.md) | Graphing: window vars, coord↔pixel, draw primitives, Y= eval |
| [sub-tibasic.md](sub-tibasic.md) | TI-BASIC: program execution, control flow, I/O commands |
| [sub-tibasic-tracing.md](sub-tibasic-tracing.md) | TI-BASIC fixture traces, smoke runner, coverage anchors |
| [sub-vat-archive.md](sub-vat-archive.md) | Variables, Sto/Rcl, Archive/Unarchive, Flash GC |
| [sub-apps-mem-settings.md](sub-apps-mem-settings.md) | Apps find/launch, RAM-reset, MODE/format flags |
| [sub-statistics.md](sub-statistics.md) | STAT: 1/2-var, regressions, statVars |
| [sub-matrix-list.md](sub-matrix-list.md) | Matrix/list element access, Gauss-Jordan inverse/det, matmul |
| [sub-solver-numeric.md](sub-solver-numeric.md) | Solver root-finder, nDeriv/fnInt, TVM finance |
| [sub-table-yvars.md](sub-table-yvars.md) | TABLE generation/cache, Y= equation vars |
| [sub-equation-display.md](sub-equation-display.md) | Equation display / MathPrint layout (page 0x39 `eqdisp_*`) |
| [sub-link-transfer.md](sub-link-transfer.md) | Link protocol: byte/packet/var-transfer (page 0x3C) |
| [sub-usb-asic.md](sub-usb-asic.md) | USB ASIC/link-assist ports and OS transport selection |

(The `sub-*` docs are deep dives covering user-facing functionality and I/O internals: calculation, graphing, TI-BASIC, VAT/archive, apps, stats, matrices, solver, table, equation display, link, and USB/link assist.)

New to these notes? Start with [Conventions & Methodology](conventions.md) (how to read the addresses and confidence flags) and the [Glossary](glossary.md); the [bcall Index](bcall-index.md) is the full alphabetical system-call reference.

The main `0x4xxx` bcall table and the retail boot bcall table (`0x8xxx`, from the local complete ROM) both carry TI-OS types. Most boot bcall bodies are on page `3F`; USB boot routines such as `_AttemptUSBOSReceive`, `_ReceiveOS_USB`, `_InitUSB`, and `_KillUSB` are on page `2F`. Rebuild: `tools/build.sh`.
