# TI-84 Plus OS — Reverse-Engineering Notes: System overview

Target: `ti84plus.rom` (1 MiB flash dump). OS self-identifies as **2.55MP**. CPU: Zilog **Z80** (16-bit address bus, 64 KiB logical space) with hardware flash/RAM **paging**. Ghidra project: `~/Documents/ti84-re/ti84.gpr` (rebuild: `tools/build.sh`).

> These are living notes written during RE. Confidence is flagged: **[confirmed]** = verified in disassembly/decompiler; **[standard]** = matches documented TI-83+/84+ architecture and is consistent with the disassembly; **[hypothesis]** = inferred, not yet verified.

## The big picture

The TI-84+ is a Z80 machine that can only see 64 KiB at once, but has 1 MiB of flash and 128 KiB of RAM. It bridges that gap with a **4-slot paging scheme** and a **system-call ("bcall") mechanism** that lets code on one 16 KiB flash page call routines on any other page. The OS is a single-tasking monitor: a boot/kernel core on flash **page 0** (always mapped low), a large body of OS routines spread across the other flash pages and reached via bcalls, and a fixed RAM region holding the system state (flags, floating-point registers, display buffers, the variable table).

Everything the user interacts with — the homescreen, TI-BASIC programs, graphing, the catalog — is built on four pillars:

1. **Paging + bcalls** — how code and data beyond 64 KiB are reached. (see [02-paging.md](02-paging.md), [03-bcall-mechanism.md](03-bcall-mechanism.md))
2. **The floating-point engine** — 9-byte BCD reals/complex in the OP1–OP6 registers; all math flows through these. ([06-floating-point.md](06-floating-point.md))
3. **The variable system (VAT)** — named objects (reals, lists, matrices, strings, programs, appvars…) catalogued in the Variable Allocation Table. ([05-variables-vat.md](05-variables-vat.md))
4. **The tokenizer/parser** — TI-BASIC is stored as 1- and 2-byte tokens; the parser executes them. ([07-tokenizer-basic.md](07-tokenizer-basic.md))

Around those sit the I/O subsystems: the **IM1 interrupt** that drives timing/APD/cursor/ON-key ([04-interrupts.md](04-interrupts.md)), the **LCD driver**, the **keypad scanner**, and the **link port**.

## Subsystem index

Each row maps a documentation page to the subsystem it covers and its analysis status.

| Doc | Subsystem | Status |
|-----|-----------|--------|
| [01-memory-map.md](01-memory-map.md) | Address space, ports, RAM layout | ✅ |
| [02-paging.md](02-paging.md) | Flash/RAM banking (ports 6/7) | ✅ |
| [03-bcall-mechanism.md](03-bcall-mechanism.md) | rst 28h system calls + jump table | ✅ |
| [04-interrupts.md](04-interrupts.md) | IM1 ISR, timers, APD, ON key | ✅ |
| [05-variables-vat.md](05-variables-vat.md) | Variable Allocation Table, object types | ✅ |
| [06-floating-point.md](06-floating-point.md) | BCD float format, OP registers | ✅ |
| [07-tokenizer-basic.md](07-tokenizer-basic.md) | Token tables, parser/interpreter | ✅ |
| [08-display-lcd.md](08-display-lcd.md) | LCD ports, screen buffers | ✅ |
| [09-keyboard-link.md](09-keyboard-link.md) | Keypad scan, link protocol | ✅ |
| [10-subsystem-map.md](10-subsystem-map.md) | bcall API surface, system through-line | ✅ |
| [11-boot-contexts-errors.md](11-boot-contexts-errors.md) | Boot, context system, _JError/onSP | ✅ |
| [12-memory-management.md](12-memory-management.md) | RAM heap, VAT/userMem, Flash archive/GC | ✅ |
| [13-flash-page-map.md](13-flash-page-map.md) | What each of the 64 flash pages contains | ✅ |
| [99-open-questions.md](99-open-questions.md) | Prioritized future-work roadmap | ✅ |
| [sub-calculation.md](sub-calculation.md) | Calculation engine: FP ops, transcendentals, formatting, errors | ✅ |
| [sub-graphing.md](sub-graphing.md) | Graphing: window vars, coord↔pixel, draw primitives, Y= eval | ✅ |
| [sub-tibasic.md](sub-tibasic.md) | TI-BASIC: program execution, control flow, I/O commands | ✅ |
| [sub-vat-archive.md](sub-vat-archive.md) | Variables, Sto/Rcl, Archive/Unarchive, Flash GC | ✅ |
| [sub-apps-mem-settings.md](sub-apps-mem-settings.md) | Apps find/launch, RAM-reset, MODE/format flags | ✅ |
| [sub-statistics.md](sub-statistics.md) | STAT: 1/2-var, regressions, statVars | ✅ |
| [sub-matrix-list.md](sub-matrix-list.md) | Matrix/list element access, Gauss-Jordan inverse/det, matmul | ✅ |
| [sub-solver-numeric.md](sub-solver-numeric.md) | Solver root-finder, nDeriv/fnInt, TVM finance | ✅ |
| [sub-table-yvars.md](sub-table-yvars.md) | TABLE generation/cache, Y= equation vars | ✅ |
| [sub-equation-display.md](sub-equation-display.md) | Equation display / MathPrint layout (page 0x39 `eqdisp_*`) | ✅ |
| [sub-link-transfer.md](sub-link-transfer.md) | Link protocol: byte/packet/var-transfer (page 0x3C) | ✅ |

(The `sub-*` docs are deep dives covering user-facing functionality: calculation, graphing, TI-BASIC, VAT/archive, apps, stats, matrices, solver, table, and link.)

New to these notes? Start with [Conventions & Methodology](conventions.md) (how to read the addresses and confidence flags) and the [Glossary](glossary.md); the [bcall Index](bcall-index.md) is the full alphabetical system-call reference.

Database state: **2413 functions (100% named)**, the main `0x4xxx` bcall table resolved, TI-OS types applied. The older `0x8xxx`/page-0x3F bcall scan output is not present as functions in the current live Ghidra/MCP DB and needs reconciliation. Rebuild: `tools/build.sh`.

## Key anchors found so far

- Reset entry `reset` @ `ram:0000` **[confirmed]**
- bcall dispatcher `bcall_dispatcher` @ `ram:2a2f` (RST 28h) **[confirmed]**
- IM1 interrupt dispatcher `int_dispatch_sources` @ `ram:006f` (via RST 38h through the `ram:006d` shadow-register prologue; older notes call this `isr_im1`) **[confirmed]**
- System flags base `flags` @ `0x89F0` (IY-indexed), typed `SystemFlags` **[confirmed]**
- FP registers `OP1`–`OP6` @ `0x8478`+ **[standard]**
- 126 BCD float constants ROM-wide incl. π/180, 180/π **[ROM-scan result; not directly verifiable through the current MCP byte interface]**
