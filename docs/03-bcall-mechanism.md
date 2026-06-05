# 03 — The bcall System-Call Mechanism

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
- Resolution method (`tools/` Python): scored all 64 pages by how many of the 535 named .inc IDs produced a valid `(addr∈4000..7FFF or page-0, page<0x40)` entry — page `0x3B` scored **447/535**, the runner-up only 124.
- Validation: known bcalls land exactly where expected — `_PutS`→`01:5C39`, `_GetKey`→`06:491E`, `_ClrLCDFull`→`01:60E4`, `_GetCSC`→`00:04B2`, `_CreateReal`→`00:10B8`.

`tools/bcall_targets.txt` holds all **607** resolved bcalls (596 in the main 0x4xxx table + 11 extended). 289 targets live on page 0 (kernel), 318 on banked pages. `tools/ApplyBcalls.java` disassembles & names each.

## Two jump tables — by ID range [confirmed]

The dispatcher's ID decode (`bcall_dispatcher`) selects one of **two** tables by the ID's top bits:
- **`0x4xxx`–`0x7FFF`** (bit 14 set): the main table on **flash page 0x3B**, entry at offset `ID − 0x4000` (this is the 596 documented bcalls — 535 from the `.inc` + 61 RE-named).
- **`0x8xxx`** (bit 15 set): a **second table on flash page 0x3F** (the boot page), entry at offset `ID & 0x7FFF`. These are the **TI-84+-era extended bcalls** (absent from the 2001 `.inc`) — their targets are routines on page 0x3F (record/cert scanning, paging setup; e.g. `_xb_RecordFind` `8027h`→`3F:4448`). 11 appear in OS 2.55MP; cataloged in `tools/ti84plus_extra.inc` and `bcalls8x_targets.txt`.

Both tables use 3-byte entries (addr LE + page, page masked `& 0x3F`).

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

Besides bcalls, the OS calls *its own* cross-page routines via **bjump**: `CALL cross_page_jump` (`= CALL 0x2b09`) followed inline by `.dw addr; .db page`. `cross_page_jump` pops the return address, reads the 2-byte target + 1-byte page from it, banks the page (`& 0x3F`), and jumps — the target's `RET` returns to *the bjump's caller* (so it behaves like a call that consumes the 3 inline bytes).

There is a **RAM-resident trampoline table** on page 0 at **`0x3B01–0x3D0B`**: **87 packed 6-byte entries**, each a bjump to a hot OS routine on another page. Boot copies this region into RAM (so it runs fast and lets `cross_page_jump` itself be RAM-resident). Code invokes a routine by `CALL 0x3Bxx` into the table. `tools/bjumps.txt` lists every entry's `(offset → page:addr)`; `tools/RamRoutines.java` marks the inline `.dw/.db` as data and comments each target.

Example: `_PutMap`'s glyph blitter is reached via the trampoline at `0x3B3D → page_07:4588`.

**Inline bjumps:** besides the trampoline table, `CALL cross_page_jump; .dw; .db` appears *inline* throughout the OS (e.g. transcendentals: `_EToX` = `fp_clear_guard(); bjump`). Because `cross_page_jump` consumes the 3 inline bytes and tail-jumps (the target returns to the bjump's caller), the bytes after must be data and the call is non-returning. `tools/FixInlineBjumps.java` marks all **280** such sites, which substantially improved OS-wide disassembly coverage.

## Limitations / TODO
- The 2001-era `ti83plus.inc` lacks the `0x8xxx` TI-84+ bcall IDs; these are now **resolved** via the second table on page 0x3F (see *Two jump tables* above) and named in `tools/ti84plus_extra.inc`.
- Some bcalls are *thunks*: e.g. `_FindSym`'s page-0 entry just `thunk_FUN_ram_2b09()` — a page-switch trampoline to the real body. Worth tracing `thunk_FUN_ram_2b09` (the common cross-page jumper) next.
