# Glossary

Quick definitions for the terms and key RAM symbols used throughout this wiki.

## Core concepts

| Term | Meaning |
|------|---------|
| **bcall** | "branch call" — the OS system-call mechanism: `rst 28h` + a 2-byte ID, dispatched through a jump table to a routine on any flash page. See [The bcall Mechanism](03-bcall-mechanism.md). |
| **bjump** | OS-internal cross-page *jump*: `CALL cross_page_jump; .dw addr; .db page` (a tail-jump). The sibling of bcall for the OS's own use. |
| **RST shortcut** | A 1-byte `rst NN` vector that fast-paths a hot routine (`rst 10h`=`_FindSym`, `rst 30h`=`_FPAdd`, `rst 28h`=the bcall dispatcher). |
| **context** | The active "mode" (homescreen, Y= editor, graph, an app…). A block of handler vectors at `cxMain` (`0x858D`); the main loop runs the current context's handlers. See [Boot, Contexts & Errors](11-boot-contexts-errors.md). |
| **paging / banking** | The Z80 sees 64 KiB; ports 6/7 swap which 16 KiB flash/RAM page is visible in the two middle slots. See [Paging](02-paging.md). |
| **APD** | Auto Power Down — the timer-driven idle shutoff. |
| **MathPrint** | The 2D "pretty-print" rendering of expressions; on this OS the engine is on page 0x39. |

## Floating point

| Term | Meaning |
|------|---------|
| **BCD** | Binary-Coded Decimal — numbers stored as decimal digits (2 per byte), the format of all TI floats. |
| `TIFloat` | The 9-byte float: 1 type/sign byte, 1 biased exponent, 7 bytes = 14 BCD mantissa digits. See [Floating-Point Engine](06-floating-point.md). |
| `OP1`–`OP6` | The six 11-byte floating-point accumulator registers in RAM at `0x8478`+. `OP1` is the primary accumulator; binary ops use `OP1`+`OP2`, result in `OP1`. |
| **FPS** | Floating-Point Stack — a software stack (pointer at `0x9824`) for spilling OP registers during nested evaluation. |
| **guard digits** | The 2 extra mantissa bytes past the 9-byte number (`OP1EXT`/`OP2EXT`), used for rounding during math. |

## Variables & memory

| Term | Meaning |
|------|---------|
| **VAT** | Variable Allocation Table — the RAM catalog of every named object, growing *down* from `symTable` (`0xFE66`). See [Variables & the VAT](05-variables-vat.md). |
| **object type** | The 1-byte type tag of a variable (`RealObj`=0, `ListObj`=1, `ProgObj`=5, `AppVarObj`=0x15…), modeled as the `TIVarType` enum. |
| **archive** | Variables relocated to *flash* to save RAM; the VAT entry's page byte then points into flash. See [Variables, Archive & Unarchive](sub-vat-archive.md). |
| **garbage collection** | Compacting the archive flash when it fills ("Garbage Collecting…"). The GC-core candidate `flash_gc_relocate`@`3C:7BD0` is not a defined function in the current live DB; that name is a project-local inferred label, not a WikiTI or `ti83plus.inc` equate. |
| **RAM heap** | The dynamic region from `userMem` (`0x9D95`) up to the VAT; managed by `_InsertMem`/`_DelMem`. See [Memory Management](12-memory-management.md). |

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
