# The bcall mechanism

`bcall` is how the OS spans 1 MiB with a 64 KiB CPU: a routine on any page calls a routine on any other page without knowing where it physically lives.

## The call site

```z80
RST 28h          ; opcode 0xEF
.dw  <bcall_id>   ; 2-byte little-endian ID immediately after
```

`rst 28h` is a 1-byte Z80 `call 0028h`. So the return address pushed on the stack points at the 2-byte ID. The dispatcher reads the ID *through the return address*, then fixes the return to skip those 2 bytes — i.e. execution resumes at `call_site + 3`. [confirmed] (modeled in Ghidra by setting each `rst 28h`'s fall-through to `+3` and typing the ID as a word.)

## The dispatcher — `bcall_dispatcher` @ `ram:2a2f` [confirmed]

The dispatcher at `ram:2A2F`–`ram:2A97` performs these steps. [confirmed]

1. Read the 2-byte ID `dw` from the caller's return address.
2. Decode the ID's high bits: `bit15`/`bit14` select the address class; the low bits form the table offset.
3. Bank the bcall table page into slot A (via the helper at `ram:181c`, which sets `port_mapBankA`).
4. Read the 3-byte table entry: target address (2) + target page (1).
5. Bank the target page into slot A. A zero page byte keeps the caller's bank-A mapping for a fixed-page target (`ram:2A8B`–`ram:2A90`).
6. Restore the input registers and enter the target with `RET`. Its normal return reaches `ram:2B41`, which restores the saved bank-A selector, then resumes the caller at `+3`.

## The jump table — flash page `0x3B` [confirmed]

- Located at the start of physical flash page `0x3B` (file offset `0x3B*0x4000 = 0xEC000`).
- **3-byte entries**: `addr_lo, addr_hi, page`. IDs step by 3 from `0x4000`, so entry for ID *X* is at table offset `X-0x4000`.
- The resolver scores all 64 pages by plausible target addresses; page `0x3B` scores highest. The dispatcher independently selects it at `ram:2A5E`–`ram:2A6D`. The 645 checked rows resolve from ROM bytes; 623 IDs also appear in the SDK equates and 22 have project-inferred names. This is mapping evidence, not runtime coverage of every body.
- Validation: known bcalls land exactly where expected — `_PutS`→`01:5C39`, `_GetKey`→`06:491E`, `_ClrLCDFull`→`01:60E4`, `_GetCSC`→`00:04B2`, `_CreateReal`→`00:10B8`.

`tools/symbols/bcall_targets.txt` holds 645 resolved main-table bcall rows.
The retail boot table has 87 populated entries. `tools/symbols/bcalls8x_targets.txt`
holds the 83 rows with official SDK names; four populated slots have only
project-inferred names in the [bcall index](bcall-index.md#retail-boot-0x8xxx-bcalls).
`tools/ti84re/rom/resolve_bcalls.py` emits the official-name rows when page `3F` has
the retail prefix. It does not hash the companion USB payload; validate the
complete image using [provenance](provenance.md) before using those targets.
A BootFree or unknown prefix leaves diagnostic comments instead.
`tools/ghidra/ApplyBcalls.java` disassembles and names the confirmed bodies.
`tools/ghidra/BcallEvidenceStudy.java` then provides a read-only listing, reference,
and decompiler dump for a selected set of IDs. For example:

```sh
nix develop -c ghidra-analyzeHeadless "$PWD" ti84 \
  -process -noanalysis -readOnly -scriptPath tools/ghidra \
  -postScript BcallEvidenceStudy.java tools/symbols/bcall_targets.txt \
  /tmp/bcall-evidence.txt 4030 4ED6 50C8
```

## Jump-table ID ranges

The dispatcher (`bcall_dispatcher`) decodes the ID's top two bits to pick the table page: bit 15 set → page-byte `0x7F` (masked `& 0x3F` → page `0x3F`); bit 14 set → `0x7B` (→ page `0x3B`); with *neither* bit set it falls through to `lookup_bcall_table_page` (`ram:2ADA`). The two tables real bcall IDs use:
- `0x4000`–`0x7FFF` (bit 14 set): the main table on flash page `0x3B`, entry at offset `ID − 0x4000` (645 byte-resolved rows: 623 IDs also present in the included SDK equates and 22 project-inferred names).
- `0x8xxx` (bit 15 set): the retail boot table is on physical page `3F`, indexed by `ID & 0x7FFF`. Its real entries occupy IDs `0x8018`–`0x80D2` and `0x80E4`–`0x8129`; bytes `3F:40D5`–`3F:40E3` between those ranges are executable dispatch-stub bytes, not five table entries. `D84PBE1.8Xv` supplies the retail page `3F`; `D84PBE2.8Xv` supplies the companion USB boot support page `2F`. Most entries resolve to `3F:addr`; USB entries such as `_AttemptUSBOSReceive` (`80E4`) and `_InitUSB` (`8108`) resolve to `2F:addr`. `tools/ti84re/rom/resolve_bcalls.py` refuses to emit these targets from a BootFree-substituted page. [confirmed]

Both resolved table formats are 3-byte entries: target address (little endian) plus page byte masked with `& 0x3F`.

## RST shortcuts (fast inlined bcalls) [confirmed]

Five of the RST vectors are 1-byte fast paths for the hottest routines (each `JP`s to its page-0 handler, which is also reachable as a bcall — the table maps the same address). `rst 28h` is the bcall dispatcher itself (not a shortcut, and `ram:2A2F` is not a bcall target); it is listed here only to complete the vector set:

| Opcode | Vector → target | Routine |
|--------|-----------------|---------|
| `rst 08h` | `0008→1A2F` | `_OP1ToOP2` (copy FP reg) |
| `rst 10h` | `0010→0E65` | `_FindSym` (VAT lookup) |
| `rst 18h` | `0018→155C` | `_PushRealO1` (push OP1 to FPS) |
| `rst 20h` | `0020→1B01` | `_Mov9ToOP1` (copy 9 bytes → OP1) |
| `rst 28h` | `0028→2A2F` | bcall dispatcher |
| `rst 30h` | `0030→229E` | `_FPAdd` (float add) |

All six match the documented TI-83+/84+ RST assignments — strong cross-confirmation of the table resolution.

## bjump — the sibling mechanism (OS-internal cross-page calls)

Besides bcalls, the OS calls *its own* cross-page routines via `bjump`. Its
encoding is:

```z80
CALL cross_page_jump ; = CALL ram:2B09
.dw addr
.db page
```

`cross_page_jump` reads the stacked descriptor address through an `SP`-relative
load at `ram:2B0E`–`ram:2B14`. It replaces that frame with the saved bank-A
selector and constructs a target/restore frame at `ram:2B15`–`ram:2B26`.
On this TI-84 Plus, the page byte is masked with `0x3F` when port `0x21`
bits 0–1 are zero (`ram:2B32`–`ram:2B3B`). It restores the input registers
and enters the target with `RET`. [confirmed]

The target's normal `RET` enters `ram:2B41`, restores bank A, and returns
through the enclosing routine's return address. Execution does not resume
after the inline descriptor. This is a tail-jump, so a trampoline needs no
separate `RET` after its six-byte encoding. [confirmed]

The fixed Flash page-0 range `ram:3B01`–`ram:3D0A` contains 87 packed
six-byte trampolines. `ram:3D0B` begins a separate `CALL ram:2B49` table.
Calls to `ram:3Bxx` execute the Flash bytes directly; the `ram` prefix is
Ghidra's address-space name. `tools/symbols/bjumps.txt` lists every entry's
target, and `tools/ghidra/RamRoutines.java` marks the descriptors as data.
[confirmed]

Example: `_PutMap`'s glyph blitter is reached via the trampoline at `ram:3B3D → 07:4588`.

**Inline bjumps.** Besides this trampoline table, the three-line bjump encoding
above appears in packed dispatch tables and inside OS routines. The target returns
to the bjump caller, so `cross_page_jump` consumes the three inline descriptor
bytes as a non-returning tail-jump. `tools/ghidra/FixInlineBjumps.java` runs before and
after the scripts that seed parser handlers and reviewed function entries. Each
pass marks every disassembled inline site, including the 87 trampoline-table
entries. Raw byte matches outside disassembled code are not counted. [confirmed]

## Limitations

- Keep the BootFree guard in place when regenerating from emulator-derived ROM images.
- Some bcalls are *thunks*: e.g. `_FindSym`'s page-0 entry uses `cross_page_jump` to reach the real body on page 0x07.
