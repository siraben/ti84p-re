# 12 — Memory Management (RAM heap & Flash archive)

How the OS allocates the ~24 KiB of user RAM between variables, temporaries, the FP stack, and the program being run — and how it offloads variables to Flash ("archive").

## The RAM heap [confirmed pointers, standard layout]

The dynamic region runs from `userMem` (`0x9D95`) up to `symTable` (`0xFE66`). Two structures grow toward each other with **free RAM** in the middle:

```
0xFE66  symTable ┐  ← VAT (variable names + metadata) grows DOWNWARD
                 │     each entry: type, data ptr/page, name (see 05-variables-vat.md)
   (free RAM)    │
                 │
   user data  ───┘  ← variable contents grow UPWARD
0x9D95  userMem
```

Boundary/work pointers (clustered at `0x9820–0x983A`) [confirmed addrs]:

| Ptr | Addr | Role |
|-----|------|------|
| `tempMem` | 9820 | base of the temporary area |
| `fpBase` | 9822 | floating-point stack base |
| `FPS` | 9824 | FP stack pointer (grows; `_PushReal`/`_PopReal`) |
| `OPBase` | 9826 | base of OP/symbol scratch |
| `pTemp` | 982E | temp-variable pointer |
| `progPtr` | 9830 | currently-executing program pointer |
| `pagedBuf` | 983A | paged scratch buffer |

So free RAM = (gap between the upward data heap and the downward VAT). When a variable grows/shrinks, everything above it shifts.

## Core allocation primitives [confirmed]

- `_InsertMem` (`00:0F81`) — open a gap of N bytes at HL by shifting all memory above it up (helper `FUN_ram_1398` is the block move); fails with `E_Memory` if it would collide with the VAT.
- `_DelMem` (`00:1368`) — the inverse: close a gap, shifting memory down.
- `_EnoughMem` (`00:0FA6`) — ensure N free bytes; if short, it walks the temp/scratch entries (9-byte stride from `pTemp` down to `OPBase`) and `_DelVar`s reclaimable temporaries to make room. **[confirmed]**
- `_MemChk` (`00:0E20`) — compute current free RAM.

Every `_CreateXxx` (see `05`) ultimately calls `_InsertMem` to carve space, then registers the variable in the VAT.

## Flash archive [confirmed location]

To save scarce RAM, variables can be **archived** to Flash. The archive code lives on **flash page 0x07**:
- `_Arc_Unarc` (`07:6248`) — move OP1's variable between RAM and the Flash archive (toggles the archive bit, then relocates the data and rewrites the VAT entry's page to the Flash page).
- `_FlashToRam` (`07:5017`) — copy archived data back into RAM.
- `_CleanAll` (`07:52CF`) — **garbage-collect** the archive: archived vars are appended to Flash (which can't be overwritten in place), so deleting an archived var just marks it dead; when the archive Flash fills, `_CleanAll` rewrites the live vars to fresh sectors and erases the old ones. This is the **"Garbage Collecting…"** screen (string on page 1). **[confirmed routine; mechanism standard]**

Flash is written/erased a sector at a time via low-level routines (RAM-resident, since you can't execute from Flash while erasing it) — the boot stub copies these to RAM. *To confirm: the sector erase/write primitives and the archive sector map.*

## TODO
- Pin the exact VAT walk in `_FindSym` and the temp-var entry format used by `_EnoughMem`.
- Trace `_CleanAll` to document the archive sector layout and the Flash write/erase RAM routines.
