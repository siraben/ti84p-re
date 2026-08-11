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
     else step HL -= 3 from the name pointer (9 bytes type-to-type for fixed entries)
          / -= (6+nameLen) for named entries, and continue
  on match:  B=(entry).pageByte, DE=dataPtr, A=(entry+6)=type; store type→8478
```

So each VAT entry is read high-address-first; the type byte's low 5 bits are the `TIVarType`; the
high bits flag the archive state. `_FindSym` returns: type in `A` and `8478`, data pointer in DE,
and the page byte in `B` — `B` is the discriminator: zero for an in-RAM var, nonzero for a var
whose data lives on a Flash page.

VAT entry shapes (consistent with `_CreateR*` header writes — see [variables-vat.md](variables-vat.md)):
- fixed-token entries (real/cplx/`Ln`/`[A]`/sysvars) occupy nine bytes. Relative to matched name token `N`, `findsym_scan` reads page at `N+1`, the high/low data-address bytes at `N+2`/`N+3`, skips version and T2 at `N+4`/`N+5`, and reads type at `N+6`.
- named entries (prog/appvar/group/str/equ) use a high-address-first variable-length name plus the same six metadata bytes. The exact byte order is easiest to reason about relative to the matched name token rather than as a forward C struct.

For an archived entry the data address (`addrLSB/MSB`) points into the Flash window and the
page byte selects the Flash page; the VAT record itself always stays in RAM.

---

## 3. Store / Recall [standard]

**Store** `_StoOther` (`38:62A9`) and siblings (`_StoAns`, `_StoX`, `_StoY`, … `38:6251-62A3`):
- Set OP1 type = 0xFF placeholder (`62A9: LD A,FF / LD (8478),A`), parse the destination name.
- `5F45` resolves/creates the target symbol; then it copies the value. It dispatches on the
  destination name token (`849B`): list-element store (`0x2A` → bounds-checks via `_ErrDimension`),
  matrix element, etc. Ultimately a `_Create*` routine carves RAM with `_InsertMem` and the data is copied.
- A store into an archived var is not done in place; the OS unarchives first (you cannot rewrite
  Flash in place) — see the `_Arc_Unarc` direction logic in §4. [hypothesis]

**Recall** `_RclVarSym` (`38:67B1`) and `rcl_var_push` (`3A:5D07`):
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
`_JError`); archivable classes (lists, matrices, programs, appvars, …) return NZ and continue. (`arc_59f1` @`07:59F1` and `arc_5936` @`07:5936` are companion name/range
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
copy is then released (the upward data heap shrinks). `archive_write_record` at `3D:64AA` lays down a fresh archived record plus a copy of the symbol header, name, and data. The status markers are `0xFE` for in progress, `0xFC` for valid, `0xF0` for deleted, and `0xFF` for erased space. The successful archive trace executes the complete body and its six boot-page writes. [confirmed] `_Chk_Batt_Low` (`00:0D07`) gates the Flash write — archiving aborts on low battery (`07:61C5: CALL _Chk_Batt_Low`).

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

## 6. Archive record allocation and programming [confirmed]

The archive manager chooses a free record and then calls the boot-page Flash API. [Flash memory](flash-memory.md) reconstructs port `0x14`, `_WriteFlash`, `_WriteFlashUnsafe`, `_WriteAByte`, erase sectors, DQ polling, and the RAM workers. This section covers the archive-specific layer above that API.

| Trampoline | Target | Role |
|------------|--------|------|
| `ram:2FDF` | `3D:61AF` | prepare archive accounting and scan state |
| `ram:2FF7` | `3D:62C2` `archive_find_free_span` | scan records for a span large enough for the new object |
| `ram:2FF1` | `3D:64AA` `archive_write_record` | write the record marker, header, name, data, and final status |
| `ram:3003` | `3D:6440` | copy an archived record to RAM and retire its Flash record |

`archive_write_record` unlocks Flash with the protected port-`0x14` sequence. It writes an initial `0xF0` marker when the selected position requires one, starts the record with `0xFE`, writes the size and variable metadata, copies the data, and finalizes the status as `0xFC`. It uses `_WriteAByte` (`8021`, body `3F:4C9F`) for marker bytes and `_WriteFlashUnsafe` (`8087`, body `3F:4CA6`) for blocks. [confirmed]

The bounds checks at `3D:6B6D` and `3D:6B9B` reject pages below `08` and pages at or above the dynamic App boundary from `3D:6413`. Both require the Flash destination to be at least `0x4000`; the block form at `3D:6B6D` also requires `HL >= 0x4000`. Carry reports rejection to the caller, which raises `E_ArchFull`. [confirmed]

A generated 17,000-byte program makes the record data span pages. The traced record writer passes its 17,002-byte `[size][body]` field to one `_WriteFlashUnsafe` invocation, which programs physical `0x20013` through `0x2427C` continuously across `08:7FFF` to `09:4000`. The copied worker increments port `0x06` from `0x08` to `0x09`, resets `DE` to `0x4000`, and finishes with its `0xF0` reset at the final target. This is direct TilEm evidence for the ordinary archive page-crossing path, not a physical-calculator measurement. [confirmed]

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

### 6b. Dynamic archive and App boundary [confirmed]

The archive begins at page `08`. `archive_app_boundary` (`3D:6413`) computes its exclusive upper bound by starting at the model-specific top App page from `3D:726E`, validating each installed App header, obtaining its span from `_FindAppNumPages` (`3D:4AA3`), and subtracting that span until it reaches the first page below the installed App run. [confirmed]

| Model test | Top App page from `3D:726E` | Certificate page from `3D:738B` |
|------------|--------------------------------:|----------------------------------:|
| port `0x02` bit 7 clear | `0x15` | `0x1E` |
| port `0x21 & 3` equals zero | `0x29` | `0x3E` |
| remaining branch | `0x69` | `0x7E` |

The second column is the App scan start, not an archive base. The third column selects the certificate page, not an archive endpoint. `archive_find_free_span` stores the computed boundary, starts at page `08`, and scans upward. On the OS-only TI-84 Plus image, the boundary is `0x29`; the successful `Archive prgmA` trace selects `08:4000`. Installed Apps consume pages downward from the upper end and reduce the archive interval. [confirmed]

The ASIC pages Flash in 16 KiB units, but the chip erases ordinary sectors in 64 KiB units. Page `3E` contains two 8 KiB certificate sectors, and page `3F` is a 16 KiB boot sector. See [Sector geometry](flash-memory.md#sector-geometry). [standard]

---

## 7. Flash garbage collector [confirmed]

The archive garbage collector compacts records in 64 KiB sector units. It also journals its phase
in the inactive half of page `3E`, so startup code can distinguish an interrupted collection from a
normal archive layout. This mechanism is separate from `_CleanAll`, which only compacts RAM.

### 7a. Command and normal collector entries

`gc_command` at `3C:71F8` displays the two-line banner, runs a recovery preflight, and calls the
normal collector: [confirmed]

```z80
3C:71F8  di
3C:71F9  call 7E0Dh  ; gc_show_screen
3C:71FC  call 7219h  ; gc_recovery_preflight
3C:71FF  call 7733h  ; archive_gc_collect
3C:7202  ei
3C:7203  ret
```

`gc_show_screen` at `3C:7E0D` is byte-confirmed. It loads the strings at `01:4126` (`"Garbage"`)
and `01:412E` (`"Collecting..."`). The related path at `3C:7E23` loads `01:4076`
(`"Defragmenting..."`). [confirmed]

The deterministic `GCFLASH` fixture archives `A` and `B`, unarchives `A`, accepts the
`GarbageCollect` prompt, and reaches `3C:71F8`, `3C:7219`, `3C:7733`, and `3C:7CFB` once each. The
preflight branch at `3C:7232` sees carry set and returns through `3C:7246`; it does not enter the
recovery dispatcher during this normal run. [confirmed]

### 7b. Four-page archive sectors

`3C:749C` groups the current archive page into one physical 64 KiB sector: [confirmed]

```z80
ld a,(8435h)
or 03h
ld c,a            ; last 16 KiB page
and 0FCh
ld b,a            ; first 16 KiB page
ret
```

`gc_check_archive_sectors` at `3C:7768` applies that grouping while scanning downward from the
dynamic App boundary. It examines the byte at `4000` on the first page of each group, then checks
record status bytes within a selected sector. In the fixture it tests nine group starts and finds
the source sector at page `08`. [confirmed]

Sector-header bytes use the same monotonic bit-clearing property as record statuses, but they are
a separate structure. In the observed collection, `0xFE` identifies the erased scratch sector,
`0xFC` and `0xF8` are copy-progress states, and `0xF0` identifies the committed sector containing
the compacted records. Record bytes one or more bytes after the sector header independently use
`0xFE`, `0xFC`, `0xF8`, and `0xF0`. [confirmed]

### 7c. Observed sector-copy sequence

`archive_gc_collect` at `3C:7733` executes the protected port-`0x14` unlock sequence. It checks the
archive sectors, adjusts the Flash execution bound, prepares a destination sector, initializes the
certificate journal, runs `gc_run_phase_machine` at `3C:7CFB`, restores the Flash bound with
`_SetFlashLowerBound` (`80CF`), and returns. [confirmed]

The trace decodes to 1,133 byte-program commands and seven physical sector erases. The ordinary
archive-sector operations occur in this order: [confirmed]

| Clock | Operation | Meaning |
|------:|-----------|---------|
| `325020849` | erase sector containing `0C:4000` | create the 64 KiB destination sector |
| `328027494` | program `0C:4000 = 0xFE` | mark page `0C`'s sector as the scratch destination |
| `334678845` | program `0C:4000 = 0xFC` | advance the destination-sector phase before record copy |
| `334829015`–`334924553` | program `0C:4001`–`0C:4015` | copy and finalize the surviving `B` record |
| `334939256` | program `08:4016 = 0xF8` | mark the old `B` record as moved |
| `335005172` | program `0C:4000 = 0xF8` | advance the destination-sector phase |
| `335063060` | program `08:4016 = 0xF0` | retire the old `B` record |
| `335227372` | erase sector containing `08:4000` | reclaim the original 64 KiB sector |
| `338253448` | program `08:4000 = 0xFE` | make page `08` the next empty scratch sector |
| `338293984` | program `0C:4000 = 0xF0` | commit page `0C`'s sector with the compacted record |

The copied record begins at `0C:4001`, immediately after the sector header. Its bytes are
`FE 12 00 00 00 00 01 40 0C 42 00 00 00 80 20 00 00 00 00 00 00`; the first byte then changes
to `0xFC`. The record matches the surviving archived real variable `B`. `3C:79A6` also updates its
VAT location while moving the record. [confirmed]

The final layout therefore contains an empty `0xFE` scratch sector at page `08` and a committed
`0xF0` sector at page `0C`. The live `B` record remains `0xFC` at `0C:4001`. The `0xF0` byte at
`0C:4000` is a sector header, not a deletion marker for the record that follows it. [confirmed]

### 7d. Certificate-sector journal

The collector uses the two 8 KiB halves of page `3E` transactionally. `_GetCertificateStart`
(`8057`) selects the active half. `3D:48E3` toggles `H` with `0x20`, and
`_EraseCertificateSector` (`8060`) erases the inactive half before the page-3D certificate rewrite
helper runs. [confirmed]

The fixture first erases `3E:6000`–`3E:7FFF`. It copies the used tail at `3E:7DD2`–`3E:7FFF` into
that half, programs its base byte through `0x8F` to `0x00`, and erases the old half at
`3E:4000`–`3E:5FFF`. After archive relocation it reverses the operation: it copies
`3E:5DD2`–`3E:5FFF`, programs `3E:4000` through `0x8F` to `0x00`, and erases the temporary
`3E:6000` half. Most copied bytes are `0xFF`; the boot worker still issues a program command for
each one. [confirmed]

Journal bytes near the end of the active half advance monotonically. The observed phase byte at
logical `3E:7DED` changes from erased `0xFF` to `0xFE`, then to `0xE0`. The per-sector byte at
`3E:7DF0` changes `0xFF → 0xFE → 0xFC` around the page-`08` erase. The RAM mirrors are in the
model-selected tables at `0x82A5` or `0x837B`; helpers at `3C:7E78`–`3C:7EBA` select individual
fields. [confirmed]

`gc_recover_by_phase` at `3C:7C1F` dispatches the mirrored phase byte through cases `0xFF`,
`0xFE`, `0xFC`, `0xF8`, `0xF0`, and `0xE0`. This is the interruption-recovery dispatcher, not the
normal record-copy entry. `gc_check_interrupted` begins at `3C:7BC7`; `3C:7BD0` is a call inside
that routine. The fixture's startup check reads an erased status, executes through `3C:7BDB`, and
skips the branch to `3C:7BDD` and `3C:7C1F`. [confirmed]

The exact crash guarantee attached to each phase value still needs fault-injection traces stopped
after individual Flash commands. The bytes and dispatcher targets establish the journal state
machine, but they do not prove which interrupted state is recoverable after physical power loss.
[hypothesis]

### 7e. Reproducing the command timeline

`tools/flash_trace.py` is the importable AMD-command decoder. The CLI resolves mapping changes,
decodes command sequences, and compacts adjacent program operations: [confirmed]

```sh
python tools/analyze_flash_trace.py \
  /tmp/tibasic-smoke/gcflash.trace \
  --clock 321347460-344829074 \
  --timeline

python tools/analyze_trace_points.py \
  /tmp/tibasic-smoke/gcflash.trace \
  --point page_3C:71f8 \
  --point page_3C:7733 \
  --point page_3C:7cfb
```

The user command is also reachable through the MEM prompt whose `"Garbage Collect?"` string is at
`01:76C9`. Automatic collection on archive exhaustion calls the same collector before retrying the
archive operation at `3C:7F1C`. [confirmed]

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
- Free archive is computed inside the page-3D archive layer. `3D:61AF` prepares its accounting state, `archive_find_free_span` at `3D:62C2` searches for placement, and `archive_app_boundary` at `3D:6413` supplies the dynamic exclusive upper page. The catalog **MEM** path runs through `3C:7121`. [confirmed]

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
| `3A:5D07` | `rcl_var_push` | recall var, push to FPS |
| `3D:6745` | `_FlashToRam` | copy archived data Flash→RAM (page-aware); `ti83plus.inc` sibling `_FlashToRam2` (id 8054) is named but its body is unmapped in the disassembly |
| `3D:678C` | `flash_to_ram_run_worker` | copy the `_FlashToRam` worker to `0x8100` and execute it |
| `3D:64AA` | `archive_write_record` | program a complete archive record; executed in the archive trace |
| `3D:62C2` | `archive_find_free_span` | scan from page `08` to the dynamic App boundary for space |
| `3D:6413` | `archive_app_boundary` | return the first page below the installed App run in `B` |
| `3D:726E` | `model_app_top_page` | model-specific App scan start (`0x15`/`0x29`/`0x69`) |
| `3D:738B` | `model_certificate_page` | model-specific certificate page (`0x1E`/`0x3E`/`0x7E`) |
| `3D:727D` | `init_flash_page_counter` | set `appSearchPage` (`0x82A3`) to top App page + 1 |
| `3D:7C97` / `3D:7C8F` / `3D:7C93` | `flash_op_fe/fd/fb` | clear status bit (0xFE/0xFD/0xFB AND-mask) |
| `3D:7DEA` | `flash_find_nonff` | scan 13-byte header for all-0xFF (free slot) |
| `00:1837` / `00:182F` | `probe_hw_model_keep_a` / `probe_port21_keep_a` | model bits: port 2 bit7 / port 0x21 low |
| `3D:6B6D` / `3D:6B9B` | `flash_write_bounds_check` / `flash_write_byte_bounds_check` | enforce page `08` and dynamic App-boundary limits before block or byte writes |
| `3C:71F8` | `gc_command` | display the Garbage Collecting screen, run recovery preflight, and call the collector |
| `3C:7219` | `gc_recovery_preflight` | inspect persistent GC state and enter recovery only when needed |
| `3C:7733` | `archive_gc_collect` | normal collector entry and Flash-unlock wrapper |
| `3C:7768` | `gc_check_archive_sectors` | scan four-page archive sectors for a valid starting state |
| `3C:77B5` | `gc_prepare_journal` | initialize the RAM phase table and inactive certificate half |
| `3C:781A` | `gc_process_sector_states` | dispatch ordinary-sector copy, erase, and finalization work |
| `3C:7BC7` | `gc_check_interrupted` | test persistent journal bits at startup |
| `3C:7C1F` | `gc_recover_by_phase` | dispatch interrupted states `FF/FE/FC/F8/F0/E0` |
| `3C:7CFB` | `gc_run_phase_machine` | run the normal sector pass and advance persistent phases |
| `3C:7E0D` | `gc_show_screen` | display `"Garbage"` and `"Collecting..."` from page `01` |
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

## 10. Summary and open items

- **Archive allocation.** [confirmed] The allocator scans upward from page `08` to the exclusive App boundary from `3D:6413`. On the traced OS-only TI-84 Plus, that interval is pages `08`–`28`; the new record begins at `08:4000`.
- **Hardware Flash path.** [confirmed] `archive_write_record` at `3D:64AA` invokes `_WriteAByte` and `_WriteFlashUnsafe`; the boot worker runs at `0x8100`, issues AMD byte-program commands, polls DQ7/DQ5, and returns success. See [Flash memory](flash-memory.md).
- **Erase granularity.** [standard] Ordinary sectors are 64 KiB, not one 16 KiB paging unit. The top-boot geometry also has 32, 8, 8, and 16 KiB sectors at physical `0xF0000`–`0xFFFFF`.
- **Record-status bytes.** [confirmed] See §6a. Monotonic bit-clear: `0xFF` erased → `0xFE` in-progress
  → `0xFC` valid via `flash_op_fe/fd/fb` (`3D:7C97/7C8F/7C93`) AND-masking; `0xF0` deleted is a direct write in the delete/GC path
  the status byte; `flash_find_nonff` (`3D:7DEA`) treats an all-`0xFF` header as free.

- **Garbage collection.** [confirmed] `archive_gc_collect` at `3C:7733` moves live records in 64 KiB sector units and uses the inactive 8 KiB certificate half as a persistent journal. The `GCFLASH` trace copies the surviving `B` record from the page-`08` sector to page `0C`, erases the old sector, and rotates the empty scratch sector back to page `08`. The remaining [hypothesis] is the physical-power-loss guarantee for each recovery phase.
- **Group archive path.** [hypothesis] The path is partially pinned. `_DataSize` (`00:1485`) confirms a Group
  (type `0x17`, like AppVar `0x15`/`0x16`) carries a leading word-size header, so a group *can* be
  stored as one Flash blob. In `_Arc_Unarc` the `CP 0x17` → `26E0` reject sits on the B≠0 (in-Flash)
  branch, immediately before the unarchive worker `61F4` — so an archived group is not unarchived
  through `61F4`, and groups are handled by a separate routine that walks the group's member list.
  That member-walk routine remains
  unidentified in the disassembly — `_Arc_Unarc`'s body past the entry `CALL` is not
  disassembled here (cross-page `CALL` flagged non-returning), and no group-archive function is
  named or xref-reachable. Confirming it would need a linear disassembly pass like the one behind §4.
