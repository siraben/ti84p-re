# Glossary

This glossary defines the TI-specific terms and key RAM symbols used throughout
the wiki.

## Core concepts

| Term | Meaning |
|------|---------|
| **bcall** | "branch call" — the OS system-call mechanism: `rst 28h` + a 2-byte ID, dispatched through a jump table to a routine on any flash page. See [The bcall Mechanism](bcall-mechanism.md). |
| **bjump** | OS-internal cross-page *jump*: `CALL cross_page_jump; .dw addr; .db page` (a tail-jump). The sibling of bcall for the OS's own use. |
| **RST shortcut** | A 1-byte `rst NN` vector that fast-paths a hot routine (`rst 10h`=`_FindSym`, `rst 30h`=`_FPAdd`, `rst 28h`=the bcall dispatcher). |
| **context** | The active "mode" (homescreen, Y= editor, graph, an app…). A block of handler vectors at `cxMain` (`0x858D`); the main loop runs the current context's handlers. See [Boot, Contexts & Errors](boot-contexts-errors.md). |
| **paging / banking** | The Z80 sees 64 KiB; ports 6/7 swap which 16 KiB flash/RAM page is visible in the two middle slots. See [Paging](paging.md). |
| **APD** | Auto Power Down — the standard-timer-driven idle shutoff. See [Clock, timers, and power](clock-timers-power.md). |
| **RTC** | Real-time clock — a 32-bit seconds counter with an epoch of 1 January 1997, exposed through ports `0x40`–`0x48`. |
| **programmable timer** | One of three independent source/mode/counter blocks at ports `0x30`–`0x38`; distinct from the two standard interrupt timers. |
| **MathPrint** | The 2D "pretty-print" rendering of expressions; on this OS the engine is on page 0x39. |

## Floating point

| Term | Meaning |
|------|---------|
| **BCD** | Binary-Coded Decimal — numbers stored as decimal digits (2 per byte), the format of all TI floats. |
| `TIFloat` | The 9-byte float: 1 type/sign byte, 1 biased exponent, 7 bytes = 14 BCD mantissa digits. See [Floating-Point Engine](floating-point.md). |
| `OP1`–`OP6` | The six 11-byte floating-point accumulator registers in RAM at `0x8478`+. `OP1` is the primary accumulator; binary ops use `OP1`+`OP2`, result in `OP1`. |
| **FPS** | Floating-Point Stack — a software stack (pointer at `0x9824`) for spilling OP registers during nested evaluation. |
| **guard digits** | The 2 extra mantissa bytes past the 9-byte number (`OP1EXT`/`OP2EXT`), used for rounding during math. |

## Variables & memory

| Term | Meaning |
|------|---------|
| **VAT** | Variable Allocation Table — the RAM catalog of every named object, growing *down* from `symTable` (`0xFE66`). See [Variables & the VAT](variables-vat.md). |
| **object type** | The 1-byte type tag of a variable (`RealObj`=0, `ListObj`=1, `ProgObj`=5, `AppVarObj`=0x15…), modeled as the `TIVarType` enum. |
| **archive** | Variables relocated to Flash to save RAM; the VAT entry's page byte then points into Flash. See [Variables, archive & unarchive](sub-vat-archive.md) and [Flash memory](flash-memory.md). |
| **Flash page** | A 16 KiB ASIC paging unit selected through port `0x06`. It is not necessarily an erase sector; ordinary sectors span four pages. See [Flash memory](flash-memory.md). |
| **Flash sector** | The smallest physical region restored to `0xFF` by one sector-erase operation. The one-megabyte top-boot chip uses 64 KiB ordinary sectors and 32/8/8/16 KiB sectors at the top. |
| **garbage collection** | Compacting the Flash archive in physical sector units. `archive_gc_collect` at `3C:7733` copies live records, erases reclaimed sectors, and journals its phase in the inactive half of page `3E`. See [Variables, archive & unarchive](sub-vat-archive.md#7-flash-garbage-collector-confirmed). |
| **RAM heap** | The dynamic region from `userMem` (`0x9D95`) up to the VAT; managed by `_InsertMem`/`_DelMem`. See [Memory Management](memory-management.md). |

## Registers & RAM symbols

| Symbol | Addr | Meaning |
|--------|------|---------|
| `IY` | (reg) | Held at `flags` (`0x89F0`) almost everywhere, so `(IY+off)` indexes the `SystemFlags` bitfield. |
| `flags` | 0x89F0 | The IY-indexed system flag area (`SystemFlags` struct). |
| `OP1` | 0x8478 | Primary FP accumulator. |
| `FPS` | 0x9824 | Floating-point stack pointer. |
| `onSP` | 0x85BC | SP saved at context/parse start; `_JError` unwinds to it (try/catch). |
| `symTable` | 0xFE66 | Top of RAM; the VAT grows down from here. |
| `kbdScanCode` | 0x843F | Last keypad scan code (filled by the ISR, read by `_GetCSC`). |
| `plotSScreen` | 0x9340 | The 768-byte graph/display buffer (96×64). |
| `parsePtr` / `parseEnd` | 0x965D / 0x965F | The TI-BASIC parser's token-stream cursor. |

## Conventions

- **Addresses**: written `pp:addr` where `pp` is the flash page (`00`–`3F`) — e.g. `3D:6745`. Page 0 (the always-mapped kernel) is also written `ram:addr` since Ghidra keeps it in the `ram` space. A bare `0x….` with no page is a RAM/data address. See [Conventions](conventions.md).
- **bcall IDs vs addresses**: a bcall has both an *ID* (the 2-byte value after `rst 28h`, e.g. `_FlashToRam` = `5017h`) and a *body address* (`3D:6745`). The ID is not an address.
- **Confidence flags**: `[confirmed]` (seen in disassembly), `[standard]` (matches documented TI-83+/84+ behavior), `[hypothesis]` (inferred). See [Conventions](conventions.md).
- **Function names**: official TI bcalls are `_CamelCase` (`_FindSym`); RE-inferred names are `snake_case` (`findsym_scan`).
