# Variables, Archive & Unarchive

*TI-84 Plus OS 2.55MP — feature deep dive.*

Deep-dive companion to [05-variables-vat.md](05-variables-vat.md) and [12-memory-management.md](12-memory-management.md), focused on what a
program that manages memory touches: the VAT walk (`_FindSym`), variable Store/Recall, and the
**Archive / UnArchive** path (RAM ↔ Flash), the Flash **garbage collector**, and the memory checks.

All addresses verified by **disassembling the actual Z80** in the Ghidra DB (`/tmp/ti84-vat`,
headless `Disasm.java`), not just the decompiler (which mis-renders the `SET b,(IY+d)` flag ops and
the cross-page `CALL 0x2b09`-style trampolines). Page numbers are the masked flash page
(`rawpage & 0x3F`); cross-page trampolines store `lo hi rawpage` in the 3 bytes after the `CALL`.

Confidence (this doc's shorthand; see [Conventions](conventions.md)): **[C]=confirmed from disassembly** (≈`[confirmed]`), **[H]=high (structure clear, some inference)** (≈`[standard]`), **[I]=inferred / standard-TI behavior** (≈`[hypothesis]`).

---

## 1. The arcInfo workspace and key RAM pointers [C]

The archive engine keeps a 12-byte scratch block, labelled `arcInfo` (`83EEh`) in `ti83plus.inc`,
plus a saved copy `savedArcInfo` (`8406h`). `_Arc_Unarc`'s reentrant inner mover saves/restores it
(`page_07:61DC` does `LD HL,83F1 / LD DE,8406 / LD BC,0C / LDIR`; `61E8` is the inverse).

| Addr | Field (this doc's name) | Meaning |
|------|-------------------------|---------|
| `83EE` | `arcInfo.page`  | page byte of the data (Flash page if archived; RAM marker otherwise) |
| `83EF` | `arcInfo.dataPtr` | 2-byte data address (in Flash window 0x4000–0x7FFF, or RAM) |
| `83F1` | `arcInfo.vatPtr` | pointer to the **VAT entry's type byte** (the symbol record) |
| `83F3` | `arcInfo.destPtr` | destination data pointer (RAM target on unarchive) |
| `83F5` | `arcInfo.dataSize` | element/data byte count (from `_DataSize`) |
| `83F7` | `arcInfo.size` | total bytes to move |
| `83F9` | `arcInfo.sizeFull` | size + header overhead |
| `8406` | `savedArcInfo` | 12-byte save slot for nested calls |

RAM-heap pointers used by the mem checks (cluster at `0x9820`–`0x983A`, confirmed in `.inc`):
`FPS=9824`, `OPBase=9826`, **`OPS=9828` (top of the upward data heap)**, `pTemp=982E`,
`progPtr=9830`. The VAT grows **down** from `symTable=0xFE66`. `tSymPtr1=981C` holds the result
pointer from the last `_FindSym` (`_Arc_Unarc` does `LD (981C),HL`). `ramCode=8100h` is where Flash
read/write routines are copied to run (you cannot execute from a Flash page while erasing it).

---

## 2. `_FindSym` and the VAT walk [C]

`_FindSym` (`00:0E65`, = `RST 10h`) is a page-0 trampoline that cross-page-jumps to the real scanner
**`findsym_scan` @ `page_07:565F`**. `_ChkFindSym` (`00:0E60`) first type-checks OP1 (`_CkOP1Real`)
then falls into FindSym.

The scanner keys off `OP1` at `8478`: `OP1.type`/`varType` and the name token at **`8479`** (=OP1+1),
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
  on match:  B=(entry).typeFull, DE=dataPtr, A=(entry+6)=pageByte; store type→8478
```

So each VAT entry is read high-address-first; **the type byte's low 5 bits are the `TIVarType`; the
high bits flag the archive state.** `_FindSym` returns: type in `8478`, data pointer in DE, **page
byte in A** — A is the discriminator: an in-RAM var vs. a var whose data lives on a Flash page.

VAT entry shapes (consistent with `_CreateR*` header writes — see [05-variables-vat.md](05-variables-vat.md)):
- single-char (real/cplx/`Ln`/`[A]`/sysvars): `type, type2, addrLSB, addrMSB, nameToken` (5 B)
- named (prog/appvar/group/str/equ): `type, version, addrLSB, addrMSB, nameLen, name[N]`

For an **archived** entry the data address (`addrLSB/MSB`) points into the Flash window and the
**page byte** selects the Flash page; the VAT record itself always stays in RAM.

---

## 3. Store / Recall [C/H]

**Store** `_StoOther` (`38:62A9`) and siblings (`_StoAns/_StoX/_StoY/...` `38:6251–62A3`):
- Set OP1 type = 0xFF placeholder (`62A9: LD A,FF / LD (8478),A`), parse the destination name.
- `5F45` resolves/creates the target symbol; then it copies the value. It dispatches on the
  destination name token (`849B`): list-element store (`0x2A` → bounds-checks via `_ErrDimension`),
  matrix element, etc. Ultimately a `_CreateXxx` carves RAM with `_InsertMem` and the data is copied.
- A store **into an archived var is not done in place**; the OS unarchives first (you cannot rewrite
  Flash in place) — see the `_Arc_Unarc` direction logic in §4. [I/H]

**Recall** `_RclVarSym` (`38:67B1`) and `_RclVarPush` (`3A:5D07`):
- `_RclVarSym` calls `RST 2` (`17A6`/`_FindSym`), then checks the name token (`8479`). For a list
  recall (`63`/`2A`) it sizes the data with `_DataSize` (`00:1485`) and copies it into a work buffer
  (`91E0`), using `_LdHLind` and cross-page helpers; ends `JP _OP4ToOP1`.
- `_DataSize` (`00:1485`): returns the variable's data byte-count in DE from the type byte — real=9,
  list/cplx-list read the `word count` header, matrix uses cols×rows, and named types
  (`0x15` AppVar, `0x16`, `0x17` Group) read the leading `word size`.
- **The recall code does not care whether the source is RAM or Flash for *reading*** — Flash is
  memory-mapped read-only into the 0x4000 window. To *use* an archived program/var that must be
  modified or executed in RAM, the OS first copies it via `_FlashToRam` (§5). [H]

---

## 4. ARCHIVE / UNARCHIVE — `_Arc_Unarc` (`07:6248`) [C]

The headline. `bcall(_Arc_Unarc)`, OP1 = the variable name. It **toggles** the var between RAM and
the Flash archive (the same entry point does both directions, deciding from the current state).

```z80
_Arc_Unarc (07:6248):
  SET 0,(IY+0x24)              ; flag: an archive operation is in progress
  CALL 628B                    ; validate OP1 name is an archivable class; Z⇒not allowed → JP 26E0 (_ErrDataType, B2 = ERR:DATA TYPE)
  CALL _OP1ToOP3 (1A0F)
  CALL _ChkFindSym (0E60)      ; locate the VAT entry; C ⇒ JP 271D (undefined)
  DI
  LD (981C),HL                 ; tSymPtr1 = entry ptr
  LD A,B ; OR A ; JR Z,..      ; B = page byte: 0 ⇒ currently in RAM, else ⇒ in Flash
      (RAM) LD A,(HL); CP 0x17 ; Group? ⇒ JP 26E0 reject  [groups archive via a different path]
            ...  CALL 61F4     ; *** RAM → Flash:  archive ***
      (Flash) CALL 6107        ; *** Flash → RAM:  unarchive ***
  ... type-0x5D (complex-list) special-case via 32A9 / cross_page 37:4288
  LD A,(83EE); OR A; EI; RET
```

`628B` is the **archivable-name validator**: after `_CkOP1Real`, it accepts the system/real name
tokens `0x58 0x59 0x54 0x5B 0x52 0x72 0xFC`, complex `0x0C`, list `0x01`/`0x0D`, etc.; rejects others
with `_ErrDataType`. (`_arc_59f1` @`07:59F1` and `_arc_5936` @`07:5936` are companion name/range
validators for the catalog archive command.)

### 4a. RAM → Flash (archive), `61F4` [C]
```z80
61F4:  LD (83EF),DE ; LD (83EE),A      ; arcInfo.dataPtr/page = source (RAM)
       CALL 6335                       ; 6331/6335: stash vatPtr (83F1), compute dataSize (83F5) via _DataSize
       CALL 32D3                       ; size accounting
       LD A,(HL) ; CALL 146C           ; add header overhead → 83F9 (sizeFull)
       EX DE,HL ; CALL _EnoughMem(0FA6); make sure the freed RAM bookkeeping is OK
                JP C,_ErrMemory(2721)
       OR 1 ; CALL FUN_ram_0f0c        ; mark VAT type byte: set the archive flag bit
       LD (83F3),DE
       CALL 3003 (cross_page 3D:64AA)  ; *** do the actual Flash program ***  (see §6)
       RET
```
The data is **appended** to the archive Flash (Flash cannot be overwritten in place). The VAT entry's
type byte gets its archive flag set and its data ptr/page rewritten to point into Flash; the old RAM
copy is then released (the upward data heap shrinks). `3D:64AA` is the Flash writer that lays down a
fresh archived record (status marker bytes `0xFE`=in-progress / `0xFF`=valid, plus a copy of the
symbol header + name, then the data — see `3D:64E5`).

### 4b. Flash → RAM (unarchive), `6107` [C]
```z80
6107:  CALL 7866 ; DI
       CALL 614B   ; compute sizes:  (83F1)=vatPtr, _DataSize→83F7, free-RAM check via 616C
       CALL 2FF1 (cross_page 3D:61AF)  ; copy the data Flash→RAM (program the heap)
       LD HL,(83F3) ; LD DE,(83F7) ; CALL _DelMem (1368)  ; close the old flash slot bookkeeping
       RET
616C:  ... reads vatPtr type, AND 0x1F (strip archive flag),
       LD HL,(83F7)+(83F5) ; ADC ; JP C,2729 (E_Memory 0x8F/0x90/0x91)  ; fits in RAM?
       allocate via 2FDF(3D:61AF) / 2FF7(3D:62C2)
```
On unarchive the entry's **archive flag is cleared** and the data ptr/page is rewritten back to the
new RAM address; the Flash copy is left marked dead (reclaimed at the next GC). `_Chk_Batt_Low`
(`00:0D07`) gates the Flash write — archiving aborts on low battery (`61C5: CALL _Chk_Batt_Low`).

### 4c. Errors raised on the path [C]
- `2785: LD A,0x31` → `_JError` = **E_ArchFull (0x31)** "ERR:ARCHIVE FULL" (no room even after GC).
- `2729: LD A,0x8F/0x90/0x91` → E_Invalid / E_IllegalNest / E_Bound (RAM-side overflow during unarchive).
- `26E0: LD A,0xB2/0xB3/0x81/0x82` → E_Variable / E_Duplicate / E_Overflow / E_DivBy0 via `_ErrDataType`.
- Error-name strings live at `07:6CA9`: `ARCHIVED, VERSION, ARCHIVE FULL, VARIABLE, DUPLICATE`.

---

## 5. Reading archived data — `_FlashToRam` (`3D:6745`) [C]

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
Port **6** is the bank-A page-select; the read code itself runs from `ramCode (0x8100)`. This is how
an archived program/appvar is pulled back into RAM to be executed or edited.

---

## 6. Low-level Flash write / erase (pages 3C/3D, port 0x14) [C]

The Flash program/erase primitives live on flash pages **0x3C / 0x3D** and are invoked through the
page-0 cross-page trampolines:

| Trampoline (RAM) | → page:addr | Role |
|------------------|-------------|------|
| `00:2FF1` | `3D:64AA` | Flash **program** record (archive write) |
| `00:2FDF` | `3D:61AF` | Flash **program/erase** core (with batt check, port 0x14 unlock) |
| `00:2FF7` | `3D:62C2` | Flash **free-sector scan / allocate** (status markers 0xFE/0xF0/0xFF) |
| `00:2FC1` | `3C:580E` | Flash command/menu entry |
| `00:2FFD` | `3C:7121` | Flash command dispatcher (Archive/UnArchive/GarbageCollect) |
| `00:32A9` | `05:4A6E` | complex-list special-case helper |

The program core (`3D:64AA`, `3D:61AF`, `3D:6440`) all share the unlock prologue:
```z80
RES 7,(IY+0x24) ; LD A,1 ; DI ; IM 1 ; DI ; OUT (0x14),A ; DI ; CALL FUN_ram_02bf
```
`OUT (0x14),A` toggles the **Flash control port** (0x14) to enable write/erase; `FUN_ram_02bf`
sets up the RAM-resident write stub (the actual byte-poke loops run from RAM at `0x8100`/`ramCode`,
because the CPU cannot fetch from a Flash chip mid-erase). `3D:6B9B`/`3D:6B6D` are the bounds-checked
byte-program calls (return carry → caller raises **E_ArchFull**). `3D:6413` scans archive sectors for
the next free slot, reading sector status bytes (`0x80`/`0x00`/`0xFE`) and summing free space; it is
what decides whether a GC is needed before a write.

---

## 7. Flash Garbage Collector — "Garbage Collecting…" [C]

Distinct from `_CleanAll` (RAM/FP-stack cleanup, `07:52CF`). When the archive Flash fills, dead
(unarchived/deleted) records must be reclaimed by **rewriting the live records to fresh sectors and
erasing the old ones**.

- The on-screen prompt string `"Garbage\0Collecting...\0"` is at **`01:4126`**; `"Defragmenting...\0"`
  at `01:4076`. The display front-end is **`3C:7E0D`** (`LD HL,0x4126 ... CALL 3E85`), which also
  drives the progress bar.
- The GC is driven from the command dispatcher `3C:7121`: `3C:71F9` = "show GC screen + relocate"
  (`CALL 7E0D` then `CALL 7219` then `CALL 7733`), `3C:720D` = relocate-only, and the **archive-full
  auto-GC** `3C:7204` runs `71FC` (GC) then retries the write at `7F1C`.
- The relocation/erase core `3C:7BD0–7BF4`: tests a status flag, `7E6B`/`7C10` prepare the swap
  sectors (writes `0xF0` marker, sets `97A6` sector counter, `8477`), `7BE3:CALL 7E0D` shows the
  banner, `7C1F` walks live VAT/Flash entries copying each valid (`0xFE`/`0xFF`-marked) record to the
  new sector, and `7C04` finalizes (erases the old sectors, `SET 2,(IY+0x25)`). [H]
- GC is callable from the user catalog (`Archive`/the MEM menu "Garbage Collect?" — string at
  `01:76C9`).

So: archive = append to Flash; delete/unarchive = mark dead; when Flash fills, GC compacts. Exactly
the classic TI-83+/84+ behaviour, now pinned to addresses.

---

## 8. Memory checks [C]

- **`_MemChk` (`00:0E20`)** — free **RAM** = `OPS(0x9828) − FPS(0x9824)`; returns 0 if the heap top
  has met the FP stack, else `count` (`INC HL` ⇒ off-by-one inclusive). `OPS` is the top of the
  upward data heap; the gap to the downward VAT is the real free RAM (see `_InsertMem` collision
  check). The decompiler's trivial 2-line view is wrong — the real routine subtracts the two
  pointers.
- **`_EnoughMem` (`00:0FA6`)** — ensure N free bytes; if short it walks the temp/scratch entries from
  `pTemp(982E)` down toward `OPBase(9826)` at a **9-byte stride**, and `_DelVar`s any entry whose flag
  byte has bit 7 (`& 0x80`) set (a reclaimable temporary), looping until enough or exhausted. Used by
  `_CreateXxx` and by the unarchive RAM-fit check (`61F4` calls it before allocating).
- **`_InsertMem` (`00:0F81`)** / **`_DelMem` (`00:1368`)** — open / close a gap at HL by block-moving
  everything above; `_InsertMem` fails `E_Memory` if it would collide with the VAT.
- **Free archive (Flash)** is computed inside the Flash layer (`3D:6413` sums free sector space,
  comparing against the requested size, returning carry/E_ArchFull when even a GC wouldn't help). The
  catalog "MEM" screen reads it through `3C:7121`.

---

## 9. Confident address index

| space:addr | name | what |
|------------|------|------|
| `07:6248` | `_Arc_Unarc` | archive/unarchive entry; toggles arc flag, dispatches RAM↔Flash |
| `07:628B` | `arc_chk_name` | archivable-name validator |
| `07:61F4` | `arc_ram_to_flash` | RAM→Flash archive worker |
| `07:6107` | `arc_flash_to_ram` | Flash→RAM unarchive worker |
| `07:6331` | `arc_size_setup` | stash vatPtr, compute dataSize into arcInfo |
| `07:61DC`/`07:61E8` | `arc_save/restore_info` | save/restore 12-byte arcInfo↔savedArcInfo |
| `07:565F` | `findsym_scan` | the real `_FindSym` VAT scanner |
| `00:0E65` | `_FindSym` | RST10 trampoline → findsym_scan |
| `00:0E60` | `_ChkFindSym` | type-check OP1 then FindSym |
| `00:1485` | `_DataSize` | variable data byte-size by type |
| `38:62A9` | `_StoOther` | store value into named var |
| `38:67B1` | `_RclVarSym` | recall var by symbol |
| `3A:5D07` | `_RclVarPush` | recall var, push to FPS |
| `3D:6745` | `_FlashToRam` | copy archived data Flash→RAM (page-aware) |
| `3D:64AA` | `flash_write_record` | program an archived record to Flash |
| `3D:61AF` | `flash_program_core` | Flash program/erase core (port 0x14, batt check) |
| `3D:62C2` | `flash_alloc_sector` | scan/allocate next free archive sector |
| `3D:6413` | `flash_free_scan` | sum free archive space / decide GC |
| `3D:6B9B` | `flash_write_byte` | bounds-checked Flash byte program (→E_ArchFull) |
| `3C:7121` | `flash_cmd_dispatch` | Archive/UnArchive/GC command dispatcher |
| `3C:7BD0` | `flash_gc_relocate` | GC core: relocate live records, erase old sectors |
| `3C:7E0D` | `gc_show_screen` | "Garbage Collecting…" display front-end |
| `00:0E20` | `_MemChk` | free RAM = OPS − FPS |
| `00:0FA6` | `_EnoughMem` | ensure N bytes; reclaim temps |
| `00:0F81` | `_InsertMem` | open a RAM gap |
| `00:1368` | `_DelMem` | close a RAM gap |
| `00:12D9` | `_DelVarArc` | delete var incl. archived copy |
| `00:1308` | `_DelVar` | delete var + VAT entry |

Strings: `01:4126` "Garbage Collecting…", `01:4076` "Defragmenting…", `07:6CA9`
"ARCHIVED/VERSION/ARCHIVE FULL/VARIABLE/DUPLICATE", `01:76C9` "Garbage Collect?".
Ports: **0x06** = bank-A page select (Flash window), **0x14** = Flash write/erase control,
**0x02** bit7 = Flash-size/model. RAM run-from-RAM stub: `ramCode = 0x8100`.

## 10. Open items
- Exact sector map / erase-block size of the archive region (which physical Flash pages form the
  archive pool) — `3D:6413`'s sector table walk would pin it.
- The `0xFE`/`0xF0`/`0xFF` record-status byte semantics in full (in-progress / being-moved / valid).
- Group archive path (the `CP 0x17` reject in `_Arc_Unarc` routes groups elsewhere).
