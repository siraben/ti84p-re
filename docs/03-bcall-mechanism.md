# 03 — The bcall system-call mechanism

This is the heart of how the OS spans 1 MiB with a 64 KiB CPU. A routine on any page calls a routine on any other page by **bcall** without knowing where it physically lives.

## The call site

```z80
rst 28h          ; opcode 0xEF
.dw  <bcall_id>   ; 2-byte little-endian ID immediately after
```

`rst 28h` is a 1-byte Z80 `call 0028h`. So the return address pushed on the stack points at the 2-byte ID. The dispatcher reads the ID *through the return address*, then fixes the return to skip those 2 bytes — i.e. execution resumes at `call_site + 3`. **[confirmed]** (modeled in Ghidra by setting each `rst 28h`'s fall-through to `+3` and typing the ID as a word.)

## The dispatcher — `bcall_dispatcher` @ `ram:2a2f` [confirmed]

From the decompiler:
1. Read the 2-byte ID `dw` from the caller's return address.
2. Decode the ID's high bits: `bit15`/`bit14` select the address class; the low bits form the **table offset**.
3. Bank the **bcall table page** into slot A (via the helper at `ram:181c`, which sets `port_mapBankA`).
4. Read the 3-byte table entry: **target address (2)** + **target page (1)**.
5. Bank the target page into slot A (`port_mapBankA = page`), save the previous page.
6. `call` the target. On return, restore the previous page and resume the caller at `+3`.

## The jump table — flash page **0x3B** [confirmed]

- Located at the start of physical flash **page 0x3B** (file offset `0x3B*0x4000 = 0xEC000`).
- **3-byte entries**: `addr_lo, addr_hi, page`. IDs step by 3 from `0x4000`, so entry for ID *X* is at table offset `X-0x4000`.
- Resolution method (`tools/` Python): scored all 64 pages by how many of the 535 named .inc IDs produced a valid `(addr∈4000..7FFF or page-0, page<0x40)` entry — in this page-selection heuristic page `0x3B` scored **447/535** (a conservative validity filter used only to pick the table), the runner-up only 124. Once `0x3B` is selected and applied, all 535 `.inc` IDs plus 61 RE-named entries (596 total) resolve and are live-confirmed.
- Validation: known bcalls land exactly where expected — `_PutS`→`01:5C39`, `_GetKey`→`06:491E`, `_ClrLCDFull`→`01:60E4`, `_GetCSC`→`00:04B2`, `_CreateReal`→`00:10B8`.

`tools/bcall_targets.txt` holds **596** resolved main-table bcall rows. `tools/bcalls8x_targets.txt` holds **83** retail boot-table rows when the local ROM has the retail page `3F` and USB support page `2F` installed. `tools/ApplyBcalls.java` disassembles and names the confirmed bodies it can resolve.

## Jump-table ID ranges

The dispatcher's ID decode (`bcall_dispatcher`) selects one of **two** tables by the ID's top bits:
- **`0x4xxx`–`0x7FFF`** (bit 14 set): the main table on **flash page 0x3B**, entry at offset `ID − 0x4000` (596 live-confirmed bcalls: 535 from the `.inc` + 61 RE-named).
- **`0x8xxx`** (bit 15 set): the retail boot table is on physical page `3F`, indexed by `ID & 0x7FFF`. `D84PBE1.8Xv` supplies the retail page `3F`; `D84PBE2.8Xv` supplies the companion USB boot support page `2F`. Most entries resolve to `3F:addr`; USB entries such as `_AttemptUSBOSReceive` (`80E4`) and `_InitUSB` (`8108`) resolve to `2F:addr`. `tools/resolve_bcalls.py` refuses to emit these targets from a BootFree-substituted page. **[confirmed]**

Both resolved table formats are 3-byte entries: target address (little endian) plus page byte masked with `& 0x3F`.

## RST shortcuts (fast inlined bcalls) [confirmed]

The other RST vectors are 1-byte fast paths for the hottest routines (each `JP`s to its page-0 handler, which is also reachable as a bcall — the table maps the same address):

| Opcode | Vector → target | Routine |
|--------|-----------------|---------|
| `rst 08h` | `0008→1A2F` | `_OP1ToOP2` (copy FP reg) |
| `rst 10h` | `0010→0E65` | `_FindSym` (VAT lookup) |
| `rst 18h` | `0018→155C` | `_PushRealO1` (push OP1 to FPS) |
| `rst 20h` | `0020→1B01` | `_Mov9ToOP1` (copy 9 bytes → OP1) |
| `rst 28h` | `0028→2A2F` | **bcall dispatcher** |
| `rst 30h` | `0030→229E` | `_FPAdd` (float add) |

All six match the documented TI-83+/84+ RST assignments — strong cross-confirmation of the table resolution.

## bjump — the sibling mechanism (OS-internal cross-page calls)

Besides bcalls, the OS calls *its own* cross-page routines via **bjump**: `CALL cross_page_jump` (`= CALL 0x2b09`) followed inline by `.dw addr; .db page`. `cross_page_jump` pops the return address, reads the 2-byte target + 1-byte page from it, banks the page (`& 0x3F`), and jumps. The target's `RET` returns to *the bjump's caller*, so it behaves like a call that consumes the 3 inline bytes.

There is a trampoline table in the page-0 address range **`0x3B01–0x3D0B`**: **87 packed 6-byte entries**, each a bjump to a hot OS routine on another page. The static Ghidra DB models it in the page-0/ROM address space; whether the table is copied to RAM at runtime is a hypothesis, not MCP-confirmed. Code invokes a routine by `CALL 0x3Bxx` into the table. `tools/bjumps.txt` lists every entry's `(offset → page:addr)`; `tools/RamRoutines.java` marks the inline `.dw/.db` as data and comments each target.

Example: `_PutMap`'s glyph blitter is reached via the trampoline at `0x3B3D → page_07:4588`.

**Inline bjumps:** besides the trampoline table, `CALL cross_page_jump; .dw; .db` appears *inline* throughout the OS (e.g. transcendentals: `_EToX` = `fp_clear_guard(); bjump`). Because `cross_page_jump` consumes the 3 inline bytes and tail-jumps (the target returns to the bjump's caller), the bytes after must be data and the call is non-returning. `tools/FixInlineBjumps.java` marks all **355** such sites in the complete local ROM, which substantially improved OS-wide disassembly coverage.

## Limitations / TODO
- Keep the BootFree guard in place when regenerating from emulator-derived ROM images.
- Some bcalls are *thunks*: e.g. `_FindSym`'s page-0 entry uses `cross_page_jump` to reach the real body on page 0x07.
