# Variables, archive & unarchive

Companion to [variables-vat.md](variables-vat.md) and [memory-management.md](memory-management.md), covering what a
program that manages memory touches: the VAT walk (`_FindSym`), variable Store/Recall, and the
Archive / UnArchive path (RAM ↔ Flash), the Flash garbage collector, and the memory checks.

Every address here is read from the raw Z80 disassembly rather than the decompiler alone, which
mis-renders the `SET b,(IY+d)` flag ops and
the cross-page `CALL 0x2b09`-style trampolines. Page numbers are the masked flash page
(`rawpage & 0x3F`); cross-page trampolines store `lo hi rawpage` in the 3 bytes after the `CALL`.

---

## 1. The arcInfo workspace and key RAM pointers [confirmed]

The archive engine keeps a 12-byte scratch block, labelled `arcInfo` (`83EEh`) in `ti83plus.inc`,
plus a saved copy `savedArcInfo` (`8406h`). `_Arc_Unarc`'s reentrant inner mover at `07:61DC`
copies the 12 bytes starting at `83F1` (the `vatPtr` field onward, not the whole `83EE` block)
into `8406` (`LD HL,83F1 / LD DE,8406 / LD BC,0C / LDIR`); the matching `07:61E8` restore candidate is an inferred label, not byte-confirmed in the disassembly.

| Addr | Field (this doc's name) | Meaning |
|------|-------------------------|---------|
| `83EE` | `arcInfo.page`  | page byte of the data (Flash page if archived; RAM marker otherwise) |
| `83EF` | `arcInfo.dataPtr` | 2-byte data address (in Flash window 0x4000–0x7FFF, or RAM) |
| `83F1` | `arcInfo.vatPtr` | pointer to the VAT entry's type byte (the symbol record) |
| `83F3` | `arcInfo.destPtr` | destination data pointer (RAM target on unarchive) |
| `83F5` | `arcInfo.dataSize` | a header/record-size component (loaded from `BC` after `CALL 0FDE`) |
| `83F7` | `arcInfo.size` | the variable's data byte count (from `_DataSize`; `614B` does `CALL 1485` → `LD (83F7),DE`) |
| `83F9` | `arcInfo.sizeFull` | size + header overhead |
| `8406` | `savedArcInfo` | 12-byte save slot for nested calls |

RAM-heap pointers used by the mem checks (cluster at `0x9820`–`0x983A`, confirmed in `.inc`):
`FPS=9824`, `OPBase=9826`, `OPS=9828` (top of the upward data heap), `pTemp=982E`,
`progPtr=9830`. The VAT grows *down* from `symTable=0xFE66`. `chkDelPtr3=981C` holds the result
pointer from the last lookup (`_Arc_Unarc` does `LD (981C),HL`) — note `981C` is `chkDelPtr3` in
`ti83plus.inc`, not `tSymPtr1` (which is `9818h`). `ramCode=8100h` is where Flash
read/write routines are copied to run (you cannot execute from a Flash page while erasing it).

---

## 2. `_FindSym` and the VAT walk [confirmed]

`_FindSym` (`00:0E65`, = `RST 10h`) is a page-0 trampoline that cross-page-jumps to the real scanner
`findsym_scan` @ `07:565F`. `_ChkFindSym` (`00:0E60`) first type-checks OP1 (`_CkOP1Real`)
then falls into FindSym.

The scanner keys off `OP1` at `8478`: `OP1.type`/`varType` and the name token at `8479` (=OP1+1),
with the 2 name bytes at `847A`/`847B`:

```z80
findsym_scan (07:565F):
  CALL FUN_ram_20d6           ; classify OP1 name
  if name-token (8479) == 0x24 (list-name token):
        scan the temp/list region: HL from progPtr(9830) down toward OPBase(9826), pTemp(982E)
  else: HL = symTable (0xFE66), scan downward to progPtr
  loop:
     A = (HL); A &= 0x1F            ; *** mask off archive flag bits in high nibble ***
     SBC HL,DE ; RET C  (ran past end → not found)
     CP (HL) against token (8479); on match check name bytes (847A/847B) at HL-1/HL-2
     else step HL -= 3 (single-char entries) / -= (6+nameLen) and continue
  on match:  B=(entry).pageByte, DE=dataPtr, A=(entry+6)=type; store type→8478
```

So each VAT entry is read high-address-first; the type byte's low 5 bits are the `TIVarType`; the
high bits flag the archive state. `_FindSym` returns: type in `A` and `8478`, data pointer in DE,
and the page byte in `B` — `B` is the discriminator: zero for an in-RAM var, nonzero for a var
whose data lives on a Flash page.

VAT entry shapes (consistent with `_CreateR*` header writes — see [variables-vat.md](variables-vat.md)):
- single-char (real/cplx/`Ln`/`[A]`/sysvars): high-address-first name token, page byte, data pointer, and type byte; `findsym_scan` reads these as page at name+1, data pointer at name+2/+3, and type at name+6.
- named (prog/appvar/group/str/equ): high-address-first name bytes/length plus the same page/data/type fields; the exact byte order is easiest to reason about relative to the matched name token rather than as a forward C struct.

For an archived entry the data address (`addrLSB/MSB`) points into the Flash window and the
page byte selects the Flash page; the VAT record itself always stays in RAM.

---

## 3. Store / Recall [standard]

**Store** `_StoOther` (`38:62A9`) and siblings (`_StoAns`, `_StoX`, `_StoY`, … `38:6251–62A3`):
- Set OP1 type = 0xFF placeholder (`62A9: LD A,FF / LD (8478),A`), parse the destination name.
- `5F45` resolves/creates the target symbol; then it copies the value. It dispatches on the
  destination name token (`849B`): list-element store (`0x2A` → bounds-checks via `_ErrDimension`),
  matrix element, etc. Ultimately a `_Create*` routine carves RAM with `_InsertMem` and the data is copied.
- A store into an archived var is not done in place; the OS unarchives first (you cannot rewrite
  Flash in place) — see the `_Arc_Unarc` direction logic in §4. [hypothesis]

**Recall** `_RclVarSym` (`38:67B1`) and `_RclVarPush` (`3A:5D07`):
- `_RclVarSym` calls `RST 10h` (`17A6`, a `_FindSym`+error-check wrapper: `RST 10h; JP C,271D`), then checks the name token (`8479`). For a list
  recall (`63`/`2A`) it sizes the data with `_DataSize` (`00:1485`) and copies it into a work buffer
  (`91E0`), using `_LdHLind` and cross-page helpers; ends `JP _OP4ToOP1`.
- `_DataSize` (`00:1485`): returns the variable's data byte-count in DE from the type byte — real=9,
  list/cplx-list read the `word count` header, matrix uses cols×rows, and named types
  (`0x15` AppVar, `0x16`, `0x17` Group) read the leading `word size`.
- The recall code does not care whether the source is RAM or Flash for *reading* — Flash is
  memory-mapped read-only into the 0x4000 window. To *use* an archived program/var that must be
  modified or executed in RAM, the OS first copies it via `_FlashToRam` (§5). [standard]

---

## 4. Archive / unarchive — `_Arc_Unarc` (`07:6248`) [confirmed]

`bcall(_Arc_Unarc)`, OP1 = the variable name. It toggles the var between RAM and
the Flash archive (the same entry point does both directions, deciding from the current state).

```z80
_Arc_Unarc (07:6248):
  SET 0,(IY+0x24)              ; flag: an archive operation is in progress
  CALL 628B                    ; validate OP1 name is an archivable class; Z⇒not allowed → JP 26E0 (local error shim; LD A,0xB2 = E_Variable, ERR:VARIABLE → _JError)
  CALL _OP1ToOP3 (1A0F)
  CALL _ChkFindSym (0E60)      ; locate the VAT entry; C ⇒ JP 271D (undefined)
  DI
  LD (981C),HL                 ; chkDelPtr3 = entry ptr
  LD A,B ; OR A ; JR Z,6272    ; B = page byte: 0 ⇒ currently in RAM, else ⇒ in Flash
      (Flash, B≠0) LD A,(HL); CP 0x17 ; Group? ⇒ JP 26E0 reject  [groups archive via a different path]
                   CALL 61F4   ; *** Flash → RAM:  unarchive ***
   6272 (RAM, B==0):  CALL 6107        ; *** RAM → Flash:  archive ***
  ... name-token-0x5D (list name, `tVarLst`) special-case via 32A9 / cross_page 05:4A6E
  LD A,(83EE); OR A; EI; RET
```

`628B` is the *archivable-name guard*: after `_CkOP1Real` it returns Z for the non-archivable
single-letter real/sysvar name tokens `0x58 0x59 0x54 0x5B 0x52 0x72 0xFC` (`CP n; RET Z` chain), so
`_Arc_Unarc`'s `JP Z,26E0` rejects them via the `26E0` shim (`LD A,0xB2` = E_Variable, ERR:VARIABLE →
`_JError`); archivable classes (lists, matrices, programs, appvars, …) return NZ and continue. (`_arc_59f1` @`07:59F1` and `_arc_5936` @`07:5936` are companion name/range
validators for the catalog archive command.)

Direction note: the `B`-page test sends an *in-RAM* var (`B==0`) to `6107` (archive) and an
*in-Flash* var (`B≠0`) to `61F4` (unarchive). `6107` is the one that programs Flash and frees the
RAM copy; `61F4` is the one that carves RAM and copies the data back out of Flash.

### 4a. RAM → Flash (archive), `6107` [confirmed]
```z80
6107:  CALL 7866 ; DI
       CALL 614B                       ; size/accounting: (83F1)=vatPtr, _DataSize→83F7;
                                       ;   616C reserves the archive-Flash slot
       CALL 2FF1 (cross_page 3D:64AA)  ; *** program the data into the archive Flash ***  (see §6)
       LD HL,(83F3) ; LD DE,(83F7) ; CALL _DelMem (1368)  ; release the old RAM copy
       RET
616C:  reads vatPtr type, AND 0x1F (clean type for the record header),
       LD HL,(83F7)+(83F5) ; ADC ; JP C,2729 (E_Invalid, 0x8F)  ; size overflow?
       reserves a Flash slot via 2FDF(3D:61AF) / 2FF7(3D:62C2)
```
The data is appended to the archive Flash (Flash cannot be overwritten in place). The VAT entry's
type byte gets its archive flag set and its data ptr/page rewritten to point into Flash; the old RAM
copy is then released (the upward data heap shrinks). `3D:64AA` is the Flash writer that lays down a
fresh archived record plus a copy of the symbol header/name and data (status marker bytes —
`0xFE`=in-progress / `0xFC`=valid / `0xF0`=deleted, with `0xFF`=erased/empty; the bit-clearing
mechanism is confirmed in §6a). `3D:64AA` is an inferred label, not byte-confirmed in the disassembly; the
`flash_write_record` name for it is a project-local inferred label, not a WikiTI or `ti83plus.inc`
equate. `_Chk_Batt_Low` (`00:0D07`) gates the Flash write — archiving aborts on low battery
(`61C5: CALL _Chk_Batt_Low`).

### 4b. Flash → RAM (unarchive), `61F4` [confirmed]
```z80
61F4:  LD (83EF),DE ; LD (83EE),A      ; arcInfo.dataPtr/page = source (Flash page+addr from FindSym)
       CALL 6335                       ; 6331/6335: stash vatPtr (83F1), compute dataSize (83F5) via _DataSize
       CALL 32D3                       ; size accounting
       LD A,(HL) ; CALL 146C           ; add header overhead → 83F9 (sizeFull)
       EX DE,HL ; CALL _EnoughMem(0FA6); ensure there is RAM room for the unarchived copy
                JP C,_ErrMemory(2721)
       OR 1 ; CALL 0F0C                ; carve the RAM gap (internal create-gap routine)
       LD (83F3),DE                    ; destPtr = new RAM address
       CALL 3003 (cross_page 3D:6440)  ; *** page-3D unarchive worker: copy Flash→RAM, retire the old record ***
       RET
```
The data is copied from Flash into the freshly-carved RAM gap. The VAT entry's archive flag is
cleared and its data ptr/page rewritten back to the new RAM address; the old Flash record is left
marked dead (`0xF0`, reclaimed at the next GC). `3D:6440` shares the page-3D flash-control prologue
(`OUT (0x14)`) and is an inferred label, not byte-confirmed in the disassembly.

### 4c. Errors raised on the path [confirmed]
- `2785: LD A,0x31` → `_JError` = `E_ArchFull` (0x31) "ERR:ARCHIVE FULL" (no room even after GC).
- `2729`/`272D`/`2731`: `LD A,0x8F`/`0x90`/`0x91` → E_Invalid / E_IllegalNest / E_Bound. The archive size check (`616C`) takes the `2729` (E_Invalid, `0x8F`) entry on overflow.
- `26E0`+ is a cluster of local error shims: each loads its code (`0xB2`=E_Variable, `0xB3`=E_Duplicate, `0x81`=E_Overflow, `0x82`=E_DivBy0) into `A` and enters `_JError` — not `_ErrDataType`.
- Error-name strings live at `07:6CA9`: `ARCHIVED, VERSION, ARCHIVE FULL, VARIABLE, DUPLICATE`.

---

## 5. Reading archived data — `_FlashToRam` (`3D:6745`) [confirmed]

`bcall(_FlashToRam)` (id 0x5017 → real body `3D:6745`). Copies `BC` bytes from a Flash page:addr to
a RAM destination, transparently advancing the Flash page when the read crosses the `0x8000`
window boundary:
```z80
3D:6745: mask page (AND 1F / AND 3F per port-2 model check FUN 1837/182F)
         PUSH IX ; LD IX,6761 ; CALL 678C ; POP IX ; RET
3D:678C: copies the small arg-block to ramCode, sets DE=0x8100, JP 8100  ; runs the copier from RAM
the copier (6761..678A):
   IN A,(6) saved ; OUT (6),A     ; bank A = the source Flash page into 0x4000 window
   loop LDI:  BIT 7,H → at 0x8000 wrap: IN A,(6); INC A; OUT (6),A; LD HL,0x4000  ; next page
```
Port `6` is the bank-A page-select; the read code itself runs from `ramCode (0x8100)`. This is how
an archived program/appvar is pulled back into RAM to be executed or edited. `ti83plus.inc` also
names a sibling `_FlashToRam2` (id 8054); the retail boot table maps it to `3F:4888`.

---

## 6. Low-level Flash write / erase (pages 3C/3D, port 0x14) [mixed]

The Flash program/erase primitives live on flash pages `0x3C` / `0x3D` and are invoked through
page-0 cross-page trampolines. The public bcall entry points for the byte writer are named in
`ti83plus.inc`: `_WriteAByte` (id 8021) and `_WriteAByteSafe` (id 80C6) program a single
Flash byte; `_FlashToRam2` (id 8054) is the companion Flash→RAM copy of `_FlashToRam` (§5).
The retail boot table maps those APIs to boot-page bodies (`_WriteAByte`→`3F:4C9F`,
`_WriteAByteSafe`→`3F:4C9A`, `_FlashToRam2`→`3F:4888`), which then wrap the lower-level
page-3C/3D flash machinery below. Several page-3C/3D
targets below are reached by byte trace but are inferred labels, not byte-confirmed in the disassembly;
their `flash_*` names are project-local inferred labels (not WikiTI or `ti83plus.inc` equates):

| Trampoline (RAM) | → page:addr | Role |
|------------------|-------------|------|
| `00:2FF1` | `3D:64AA` (inferred label) | Flash program record candidate |
| `00:2FDF` | `3D:61AF` (inferred label) | Flash program/erase core candidate |
| `00:2FF7` | `3D:62C2` (inferred label) | Flash free-sector scan / allocate candidate |
| `00:2FC1` | `3C:580E` | Flash command/menu entry |
| `00:2FFD` | `3C:7121` (inferred label) | Flash command dispatcher candidate |
| `00:32A9` | `05:4A6E` | complex-list special-case helper |

The program-core candidates `3D:64AA` and `3D:6440` share this unlock prologue (`3D:61AF` starts differently — `PUSH AF; PUSH HL; BIT 6,(IY+0x24)`):
```z80
RES 7,(IY+0x24) ; LD A,1 ; DI ; IM 1 ; DI ; OUT (0x14),A ; DI ; CALL FUN_ram_02bf
```
`OUT (0x14),A` toggles the Flash control port (0x14) to enable write/erase; `FUN_ram_02bf`
sets up the RAM-resident write stub (the actual byte-poke loops run from RAM at `0x8100`/`ramCode`,
because the CPU cannot fetch from a Flash chip mid-erase). `3D:6B9B`/`3D:6B6D` are bounds-checked
byte-program candidate calls (return carry → caller raises `E_ArchFull`); neither is byte-confirmed
in the disassembly. The public byte-write API for this layer is `_WriteAByte` (8021) /
`_WriteAByteSafe` (80C6), which resolve to boot-page wrappers. The free-slot scan reads sector
status bytes and sums free space to decide whether a GC is needed before a write.

### 6a. Record-status byte — the one-way bit-clearing scheme [confirmed]

The status byte is a classic AMD/Am29F *monotonic bit-clear* marker: erased Flash is all-ones
(`0xFF`), and the OS advances a record's state by *clearing* bits (program can only flip `1→0`; only
a sector erase restores `1`s). The writers are three tiny routines on page 0x3D that load an AND-mask
into `C` and then read-modify-write the status byte (`3D:7C9A: CALL flash_read_byte; AND C; …`):

| Routine | Mask in `C` | Bit cleared | State after |
|---------|-------------|-------------|-------------|
| `flash_op_fe` (`3D:7C97`) | `0xFE` | bit 0 | record in-progress (newly begun) |
| `flash_op_fd` (`3D:7C8F`) | `0xFD` | bit 1 | (intermediate / "swap" marker) |
| `flash_op_fb` (`3D:7C93`) | `0xFB` | bit 2 | (intermediate) |

Successive clears compose: the three helpers take a record `0xFF` (erased) → `0xFE` (started) →
`0xFC` (valid/complete, bits 0+1 clear). Deletion marks the record `0xF0` (deleted/dead, bits
0–3 clear) with a direct write in the delete/GC path (§7), not via those three in-progress/valid
helpers. Because only bits go `1→0`, a deleted record
can never be re-validated in place — it is reclaimed only by GC erasing the whole sector.
`flash_find_nonff` (`3D:7DEA`) confirms `0xFF` = empty: it reads the 13-byte record header and `CP 0xFF`
on each, treating an all-`0xFF` run as a free slot. (`3D:7C99` additionally folds in `AND 0xE7` and
conditional `OR 0x10`/`OR 0x08` for the swap/relocate state bits driven by `(IY+0x1A).0` and `(IY+0).2`.)

### 6b. Archive sector map / erase-block granularity [confirmed]

The physical Flash pages that form the archive pool are model-selected at runtime from the two model
bits — port 2 bit 7 (`probe_hw_model_keep_a` `00:1837`) and port 0x21 low bits (`probe_port21_keep_a` `00:182F`):

| Model test | Archive base page (`flash_page_select` `3D:726E`) | Archive top page (`flash_cmd_base` `3D:738B`) | Page mask |
|------------|-------------------------------------------------------|----------------------------------------------------|-----------|
| port 2 bit 7 clear (1 MB) | `0x15` | `0x1E` | `AND 0x1F` (32 pages) |
| port 0x21 == 0 (mid) | `0x29` | `0x3E` | `AND 0x3F` (64 pages) |
| else (2 MB) | `0x69` | `0x7E` | *no* mask (full 8-bit page; `3D:6745` skips both `AND`s) |

So on a 1 MB TI-84 Plus the user archive occupies roughly raw pages `0x15…0x1E`, and the OS pages it
into the `0x4000` window one 16 KB page at a time for both reading (`_FlashToRam`, masks `0x1F`/`0x3F`
via the same model check, `3D:6745`) and erasing. `flash_set_sector_cnt` (`3D:727D`) loads
`(base+1)` into the sector counter `0x82A3`; the erase routine `flash_erase_wait` (`3D:5ED3`, whose
loop jumps to `3D:5EF1` — `3D:5EE3` is the unrelated `_FindApp`) pages each sector to `0x4000` and
issues the chip erase command via `RST 0x28`, decrementing
`0x82A3` down toward the base page. The underlying Am29F-class chip uses 64 KB physical sectors
(= 4 × 16 KB OS pages); the OS walks/erases at 16 KB page granularity. [64 KB physical-sector figure: hypothesis]

---

## 7. Flash garbage collector — "Garbage Collecting…" [mixed]

Distinct from `_CleanAll` (RAM/FP-stack cleanup, `07:52CF`). When the archive Flash fills, dead
(unarchived/deleted) records must be reclaimed by rewriting the live records to fresh sectors and
erasing the old ones.

- The on-screen prompt string `"Garbage\0Collecting...\0"` is at `01:4126`; `"Defragmenting...\0"`
  at `01:4076`. The display front-end candidate `3C:7E0D`
  (`LD HL,0x4126 ... CALL 3E85`) is an inferred label, not byte-confirmed in the disassembly.
- GC is driven from the command dispatcher candidate `3C:7121`: `3C:71F9` = "show GC screen + relocate"
  (`CALL 7E0D` then `CALL 7219` then `CALL 7733`), `3C:720D` = relocate-only, and the archive-full
  auto-GC `3C:7204` runs `71FC` (GC) then retries the write at `7F1C`. `3C:7121` is an inferred
  label, not byte-confirmed in the disassembly.
- The relocation/erase-core candidate `3C:7BD0–7BF4`: tests a status flag, `7E6B`/`7C10` prepare the swap
  sectors (writes `0xF0` marker, sets `97A6` sector counter, `8477`), `7BE3:CALL 7E0D` shows the
  banner, `7C1F` walks live VAT/Flash entries copying each valid (`0xFC`-marked) record to the
  new sector, and `7C04` finalizes (erases the old sectors, `SET 2,(IY+0x25)`). [standard] `3C:7BD0` is
  an inferred label, not byte-confirmed in the disassembly; the `flash_gc_relocate`/`gc_show_screen` names are
  project-local inferred labels, not WikiTI or `ti83plus.inc` equates.
- GC is callable from the user catalog (`Archive`/the MEM menu "Garbage Collect?" — string at
  `01:76C9`).

So: archive = append to Flash; delete/unarchive = mark dead; when Flash fills, GC compacts. This is
the standard TI-83+/84+ behaviour, pinned to addresses here.

---

## 8. Memory checks [confirmed]

- `_MemChk` (`00:0E20`) — free RAM = `OPS(0x9828) − FPS(0x9824)`; returns 0 if the heap top
  has met the FP stack, else `count` (`INC HL` ⇒ off-by-one inclusive). `OPS` is the top of the
  upward data heap; the gap to the downward VAT is the real free RAM (see `_InsertMem` collision
  check). The decompiler's trivial 2-line view is wrong — the real routine subtracts the two
  pointers.
- `_EnoughMem` (`00:0FA6`) — ensure N free bytes; if short it walks the temp/scratch entries from
  `pTemp(982E)` down toward `OPBase(9826)` at a 9-byte stride, and `_DelVar`s any entry whose flag
  byte has bit 7 (`& 0x80`) set (a reclaimable temporary), looping until enough or exhausted. Used by
  the `_Create*` routines and by the unarchive RAM-fit check (`61F4` calls it before allocating).
- `_InsertMem` (`00:0F81`) / `_DelMem` (`00:1368`) — open / close a gap at HL by block-moving
  everything above; `_InsertMem` fails `E_Memory` if it would collide with the VAT.
- Free archive (Flash) is computed inside the Flash layer. The free-space sum is at `3D:6413`
  and the catalog "MEM" read path runs through `3C:7121`. Neither address is byte-confirmed in
  the disassembly.

---

## 9. Confident address index

| space:addr | name | what |
|------------|------|------|
| `07:6248` | `_Arc_Unarc` | archive/unarchive entry; toggles arc flag, dispatches RAM↔Flash |
| `07:628B` | `arc_chk_name` | archivable-name validator |
| `07:6107` | `arc_ram_to_flash` | RAM→Flash archive worker (programs Flash, frees old RAM) |
| `07:61F4` | `arc_flash_to_ram` | Flash→RAM unarchive worker (carves RAM, copies from Flash) |
| `07:6331` | `arc_size_setup` | stash vatPtr, compute dataSize into arcInfo |
| `07:61DC` | `arc_save_info` | save 12-byte arcInfo into savedArcInfo; `07:61E8` (restore candidate) is an inferred label, not byte-confirmed in the disassembly |
| `07:565F` | `findsym_scan` | the real `_FindSym` VAT scanner |
| `00:0E65` | `_FindSym` | RST10 trampoline → findsym_scan |
| `00:0E60` | `_ChkFindSym` | type-check OP1 then FindSym |
| `00:1485` | `_DataSize` | variable data byte-size by type |
| `38:62A9` | `_StoOther` | store value into named var |
| `38:67B1` | `_RclVarSym` | recall var by symbol |
| `3A:5D07` | `_RclVarPush` | recall var, push to FPS |
| `3D:6745` | `_FlashToRam` | copy archived data Flash→RAM (page-aware); `ti83plus.inc` sibling `_FlashToRam2` (id 8054) is named but its body is unmapped in the disassembly |
| `3D:678C` | `flash_program_buf` | live-MCP Flash programming/buffer helper |
| `3D:64AA` | `flash_write_record` (inferred label) | program an archived record to Flash candidate; not byte-confirmed in the disassembly |
| `3D:61AF` | `flash_program_core` (inferred label) | Flash program/erase core candidate; not byte-confirmed in the disassembly |
| `3D:62C2` | `flash_alloc_sector` (inferred label) | scan/allocate next free archive sector candidate; not byte-confirmed in the disassembly |
| `3D:6413` | `flash_free_scan` (inferred label) | sum free archive space / decide GC candidate; not byte-confirmed in the disassembly |
| `3D:726E` | `flash_page_select` | archive base page by model (0x15/0x29/0x69) |
| `3D:738B` | `flash_cmd_base` | archive top page by model (0x1E/0x3E/0x7E) |
| `3D:727D` | `flash_set_sector_cnt` | shared page counter `0x82A3` = base+1 |
| `3D:5ED3` | `flash_erase_wait` | erase a 16 KB archive page, wait for completion |
| `3D:7C97` / `3D:7C8F` / `3D:7C93` | `flash_op_fe/fd/fb` | clear status bit (0xFE/0xFD/0xFB AND-mask) |
| `3D:7DEA` | `flash_find_nonff` | scan 13-byte header for all-0xFF (free slot) |
| `00:1837` / `00:182F` | `probe_hw_model_keep_a` / `probe_port21_keep_a` | model bits: port 2 bit7 / port 0x21 low |
| `3D:6B9B` | `flash_write_byte` (inferred label) | bounds-checked Flash byte program candidate; not byte-confirmed in the disassembly. Public byte-write bcalls `_WriteAByte` (8021) / `_WriteAByteSafe` (80C6) are named in `ti83plus.inc`, but the `0x8xxx` table does not yet map either ID to this body |
| `3C:7121` | `flash_cmd_dispatch` (inferred label) | Archive/UnArchive/GC command dispatcher candidate; not byte-confirmed in the disassembly |
| `3C:7BD0` | `flash_gc_relocate` (inferred label) | GC core candidate; not byte-confirmed in the disassembly |
| `3C:7E0D` | `gc_show_screen` (inferred label) | "Garbage Collecting…" display front-end candidate; not byte-confirmed in the disassembly |
| `00:0E20` | `_MemChk` | free RAM = OPS − FPS |
| `00:0FA6` | `_EnoughMem` | ensure N bytes; reclaim temps |
| `00:0F81` | `_InsertMem` | open a RAM gap |
| `00:1368` | `_DelMem` | close a RAM gap |
| `00:12D9` | `_DelVarArc` | delete var incl. archived copy |
| `00:1308` | `_DelVar` | delete var + VAT entry |

Strings: `01:4126` "Garbage Collecting…", `01:4076` "Defragmenting…", `07:6CA9`
"ARCHIVED/VERSION/ARCHIVE FULL/VARIABLE/DUPLICATE", `01:76C9` "Garbage Collect?".
Ports: `0x06` = bank-A page select (Flash window), `0x14` = Flash write/erase control,
`0x02` bit7 = Flash-size/model. RAM run-from-RAM stub: `ramCode = 0x8100`.

## 10. Summary & open items

- **Sector map / erase-block — [confirmed], see §6b.** The archive pool is model-selected: base page
  `0x15`/`0x29`/`0x69` (`flash_page_select` `3D:726E`) up to top page `0x1E`/`0x3E`/`0x7E`
  (`flash_cmd_base` `3D:738B`); on a 1 MB TI-84 Plus that is raw pages ~`0x15…0x1E`. The OS pages
  the region into the `0x4000` window and erases one 16 KB page at a time (`flash_erase_wait`
  `3D:5ED3`, sector counter `0x82A3` from `flash_set_sector_cnt` `3D:727D`); the physical chip
  sector is 64 KB = 4 OS pages [hypothesis].
- **Record-status bytes — [confirmed], see §6a.** Monotonic bit-clear: `0xFF` erased → `0xFE` in-progress
  → `0xFC` valid via `flash_op_fe/fd/fb` (`3D:7C97/7C8F/7C93`) AND-masking; `0xF0` deleted is a direct write in the delete/GC path
  the status byte; `flash_find_nonff` (`3D:7DEA`) treats an all-`0xFF` header as free.

- **Lower-level flash helper bodies — address-keyed labels still inferred [hypothesis].** The public bcall
  entry points are canonical equates in `ti83plus.inc` and now resolve through the retail boot table:
  `_WriteAByte` (8021) → `3F:4C9F`, `_WriteAByteSafe` (80C6) → `3F:4C9A`, and `_FlashToRam2`
  (8054) → `3F:4888`. The address-keyed `flash_*` labels in §6/§9 stay inferred and
  body-undisassembled until the lower-level page-3C/3D helper graph is split cleanly.
- **Group archive path — partially pinned [hypothesis].** `_DataSize` (`00:1485`) confirms a Group
  (type `0x17`, like AppVar `0x15`/`0x16`) carries a leading word-size header, so a group *can* be
  stored as one Flash blob. In `_Arc_Unarc` the `CP 0x17` → `26E0` reject sits on the B≠0 (in-Flash)
  branch, immediately before the unarchive worker `61F4` — so an archived group is not unarchived
  through `61F4`, and groups are handled by a separate routine that walks the group's member list.
  That member-walk routine remains
  unidentified in the disassembly — `_Arc_Unarc`'s body past the entry `CALL` is not
  disassembled here (cross-page `CALL` flagged non-returning), and no group-archive function is
  named or xref-reachable. Confirming it would need a linear disassembly pass like the one behind §4.
