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

`tools/bcall_targets.txt` holds **607** historical resolved bcall rows: 596 main `0x4xxx` entries plus 11 `0x8xxx` extended candidates. The 596 main entries are live-confirmed in the current Ghidra/MCP DB; the 11 extended page-0x3F candidates remain ROM-scan artifacts until the live DB exposes matching functions. `tools/ApplyBcalls.java` disassembles & names the confirmed bodies it can resolve.

## Jump-table ID ranges

The dispatcher's ID decode (`bcall_dispatcher`) selects one of **two** tables by the ID's top bits:
- **`0x4xxx`–`0x7FFF`** (bit 14 set): the main table on **flash page 0x3B**, entry at offset `ID − 0x4000` (596 live-confirmed bcalls: 535 from the `.inc` + 61 RE-named).
- **`0x8xxx`** (bit 15 set): historical scripts decoded 11 TI-84+-era extended candidates from a page-0x3F table, but the current live Ghidra/MCP DB does not expose functions at the claimed page-0x3F targets such as `_FindFirstCertificateField` `3F:4448` or `_GetBootVer` `3F:531E`. Treat these entries as **unverified ROM-scan output**, not live-confirmed bcalls, until the DB/load model is reconciled.

Both table formats are 3-byte entries (addr LE + page, page masked `& 0x3F`); only the main page-0x3B table is MCP-confirmed end to end.

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

There is a trampoline table in the page-0 address range **`0x3B01–0x3D0B`**: **87 packed 6-byte entries**, each a bjump to a hot OS routine on another page. The static Ghidra DB models it in the page-0/ROM address space; the old "RAM-resident" wording is a runtime-copy hypothesis and is not MCP-confirmed. Code invokes a routine by `CALL 0x3Bxx` into the table. `tools/bjumps.txt` lists every entry's `(offset → page:addr)`; `tools/RamRoutines.java` marks the inline `.dw/.db` as data and comments each target.

Example: `_PutMap`'s glyph blitter is reached via the trampoline at `0x3B3D → page_07:4588`.

**Inline bjumps:** besides the trampoline table, `CALL cross_page_jump; .dw; .db` appears *inline* throughout the OS (e.g. transcendentals: `_EToX` = `fp_clear_guard(); bjump`). Because `cross_page_jump` consumes the 3 inline bytes and tail-jumps (the target returns to the bjump's caller), the bytes after must be data and the call is non-returning. `tools/FixInlineBjumps.java` marks all **280** such sites, which substantially improved OS-wide disassembly coverage.

## Limitations / TODO
- Reconcile the historical `0x8xxx`/page-0x3F bcall scan with the live Ghidra/MCP DB; the claimed page-0x3F bodies are not currently functions.
- Some bcalls are *thunks*: e.g. `_FindSym`'s page-0 entry uses `cross_page_jump` to reach the real body on page 0x07.
