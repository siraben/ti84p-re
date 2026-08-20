# Variables, archive & unarchive

The variable-management paths scan the VAT, store and recall values, move
objects between RAM and the Flash archive, and collect unused Flash records.
[Variables and the VAT](variables-vat.md) defines the object formats; [Memory
management](memory-management.md) provides the heap and archive overview.

Raw disassembly supplies the indexed-bit operations and cross-page trampolines
that the decompiler can mis-render.

## `arcInfo` workspace and RAM pointers [confirmed]

The archive engine keeps a confirmed 15-byte workspace prefix at `arcInfo`
(`0x83EE`). The prefix contains seven named fields followed by two bytes whose
meaning remains open:

```c
#pragma pack(push, 1)
typedef struct {
    uint8_t  page;              /* +0x00, 0x83EE */
    uint16_t data_ptr;          /* +0x01, 0x83EF */
    uint16_t vat_ptr;           /* +0x03, 0x83F1 */
    uint16_t dest_ptr;          /* +0x05, 0x83F3 */
    uint16_t data_size;         /* +0x07, 0x83F5 */
    uint16_t size;              /* +0x09, 0x83F7 */
    uint16_t size_full;         /* +0x0B, 0x83F9 */
    uint8_t  unknown_tail[2];   /* +0x0D, 0x83FB */
} ArchiveWorkspacePrefix;       /* 15 bytes */
#pragma pack(pop)
```

`savedArcInfo` at `0x8406` is not a copy of that whole prefix. `_Arc_Unarc`'s
reentrant mover at `07:61DC` copies the distinct 12-byte tail beginning at
`arcInfo.vat_ptr`: `LD HL,83F1 / LD DE,8406 / LD BC,0C / LDIR`. The slice runs
through `arcInfo.unknown_tail[1]`. [confirmed]

The matching `07:61E8` restore candidate is an inferred label, not
byte-confirmed in the disassembly. [hypothesis]

| Addr | Field | Meaning |
|------|-------------------------|---------|
| `0x83EE` | `arcInfo.page`  | page byte of the data (Flash page if archived; RAM marker otherwise) |
| `0x83EF` | `arcInfo.data_ptr` | 2-byte data address (in Flash window `0x4000`–`0x7FFF`, or RAM) |
| `0x83F1` | `arcInfo.vat_ptr` | pointer to the VAT entry's type byte (the symbol record) |
| `0x83F3` | `arcInfo.dest_ptr` | destination data pointer (RAM target on unarchive) |
| `0x83F5` | `arcInfo.data_size` | a header/record-size component (loaded from `BC` after `CALL ram:0FDE`) |
| `0x83F7` | `arcInfo.size` | the variable's data byte count (from `_DataSize`; `07:614B` does `CALL ram:1485` → `LD (83F7),DE`) |
| `0x83F9` | `arcInfo.size_full` | size + header overhead |
| `0x83FB` | `arcInfo.unknown_tail` | two bytes included in the saved tail; semantics unresolved |
| `0x8406` | `savedArcInfo` | 12-byte save slot for `arcInfo.vat_ptr` through `unknown_tail[1]` |

RAM-heap pointers used by the mem checks (cluster at `0x9820`–`0x983A`, confirmed in `.inc`):
`FPS=9824`, `OPBase=9826`, `OPS=9828` (top of the upward data heap), `pTemp=982E`,
`progPtr=9830`. The VAT grows *down* from `symTable=0xFE66`. `chkDelPtr3=981C` holds the result
pointer from the last lookup (`_Arc_Unarc` does `LD (981C),HL`) — note `981C` is `chkDelPtr3` in
`ti83plus.inc`, not `tSymPtr1` (which is `9818h`). `ramCode=8100h` is where Flash
read/write routines are copied to run (you cannot execute from a Flash page while erasing it).

---

## `_FindSym` and VAT traversal [confirmed]

`_FindSym` (`00:0E65`, = `RST 10h`) is a page-0 trampoline that cross-page-jumps to the real scanner
`findsym_scan` @ `07:565F`. `_ChkFindSym` (`00:0E60`) first type-checks OP1 (`_CkOP1Real`)
then falls into FindSym.

The scanner keys off `OP1` at `8478`: `OP1.value.type`/`varType` and the name token at `8479` (=OP1+1),
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

## Store and recall [standard]

**Store** `_StoOther` (`38:62A9`) and siblings (`_StoAns`, `_StoX`, `_StoY`, … `38:6251-62A3`):
- Set OP1 type = 0xFF placeholder (`62A9: LD A,FF / LD (8478),A`), parse the destination name.
- `5F45` resolves/creates the target symbol; then it copies the value. It dispatches on the
  destination name token (`849B`): list-element store (`0x2A` → bounds-checks via `_ErrDimension`),
  matrix element, etc. Ultimately a `_Create*` routine carves RAM with `_InsertMem` and the data is copied.
- A store into an archived var is not done in place; the OS unarchives first (you cannot rewrite
  Flash in place); see the [`_Arc_Unarc` direction logic](#archive-and-unarchive-confirmed). [hypothesis]

**Recall** `_RclVarSym` (`38:67B1`) and `rcl_var_push` (`3A:5D07`):
- `_RclVarSym` calls `RST 10h` (`17A6`, a `_FindSym`+error-check wrapper: `RST 10h; JP C,271D`), then checks the name token (`8479`). For a list
  recall (`63`/`2A`) it sizes the data with `_DataSize` (`00:1485`) and copies it into a work buffer
  (`91E0`), using `_LdHLind` and cross-page helpers; ends `JP _OP4ToOP1`.
- `_DataSize` (`00:1485`): returns the variable's data byte-count in DE from the type byte — real=9,
  list/cplx-list read the `word count` header, matrix uses cols×rows, and named types
  (`0x15` AppVar, `0x16`, `0x17` Group) read the leading `word size`.
- The recall code does not care whether the source is RAM or Flash for *reading* — Flash is
  memory-mapped read-only into the 0x4000 window. To *use* an archived program/var that must be
  modified or executed in RAM, the OS first copies it via [`_FlashToRam`](#reading-archived-data-with-_flashtoram-confirmed). [standard]

---

## Archive and unarchive [confirmed]

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

### RAM-to-Flash archive path [confirmed]

```z80
6107:  CALL 7866 ; DI
       CALL 614B                       ; arcInfo.vat_ptr and arcInfo.size
                                       ;   616C reserves the archive-Flash slot
       CALL 2FF1 (cross_page 3D:64AA)  ; program the data into archive Flash
       LD HL,(83F3) ; LD DE,(83F7) ; CALL _DelMem (1368)  ; release the old RAM copy
       RET
616C:  reads vatPtr type, AND 0x1F (clean type for the record header),
       LD HL,(83F7)+(83F5) ; ADC ; JP C,2729 (E_Invalid, 0x8F)  ; size overflow?
       reserves a Flash slot via archive_prepare_scan / archive_find_free_span
```
The data is appended to the archive Flash (Flash cannot be overwritten in place). The VAT entry's
type byte gets its archive flag set and its data ptr/page rewritten to point into Flash; the old RAM
copy is then released (the upward data heap shrinks). `archive_write_record` at `3D:64AA` lays down a fresh archived record plus a copy of the symbol header, name, and data. The status markers are `0xFE` for in progress, `0xFC` for valid, `0xF0` for deleted, and `0xFF` for erased space. The successful archive trace executes the complete body and its six boot-page writes. [confirmed] `_Chk_Batt_Low` (`00:0D07`) gates the Flash write — archiving aborts on low battery (`07:61C5: CALL _Chk_Batt_Low`).

### Flash-to-RAM unarchive path [confirmed]

```z80
61F4:  LD (83EF),DE ; LD (83EE),A      ; arcInfo.data_ptr/page = source
       CALL 6335                       ; set arcInfo.vat_ptr and arcInfo.data_size
       CALL 32D3                       ; size accounting
       LD A,(HL) ; CALL 146C           ; add header overhead → arcInfo.size_full
       EX DE,HL ; CALL _EnoughMem(0FA6); ensure there is RAM room for the unarchived copy
                JP C,_ErrMemory(2721)
       OR 1 ; CALL 0F0C                ; carve the RAM gap (internal create-gap routine)
       LD (83F3),DE                    ; arcInfo.dest_ptr = new RAM address
       CALL 3003 (unarchive_record_to_ram) ; copy Flash→RAM, retire old record
       RET
```
The data is copied from Flash into the freshly-carved RAM gap. The VAT entry's archive flag is
cleared and its data ptr/page rewritten back to the new RAM address; the old Flash record is left
marked dead (`0xF0`, reclaimed at the next GC). `unarchive_record_to_ram`
at `3D:6440` shares the page-3D flash-control prologue
(`OUT (0x14)`) and is an inferred label, not byte-confirmed in the disassembly.

### Errors [confirmed]

- `2785: LD A,0x31` → `_JError` = `E_ArchFull` (0x31) "ERR:ARCHIVE FULL" (no room even after GC).
- `2729`/`272D`/`2731`: `LD A,0x8F`/`0x90`/`0x91` → E_Invalid / E_IllegalNest / E_Bound. The archive size check (`616C`) takes the `2729` (E_Invalid, `0x8F`) entry on overflow.
- `26E0`+ is a cluster of local error shims: each loads its code (`0xB2`=E_Variable, `0xB3`=E_Duplicate, `0x81`=E_Overflow, `0x82`=E_DivBy0) into `A` and enters `_JError` — not `_ErrDataType`.
- Error-name strings live at `07:6CA9`: `ARCHIVED, VERSION, ARCHIVE FULL, VARIABLE, DUPLICATE`.

---

## Reading archived data with `_FlashToRam` [confirmed]

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

## Archive record allocation and programming [confirmed]

The archive manager chooses a free record and then calls the boot-page Flash API. [Flash memory](flash-memory.md) reconstructs port `0x14`, `_WriteFlash`, `_WriteFlashUnsafe`, `_WriteAByte`, erase sectors, DQ polling, and the RAM workers. This section covers the archive-specific layer above that API.

| Trampoline | Target | Role |
|------------|--------|------|
| `ram:2FDF` | `3D:61AF` `archive_prepare_scan` | prepare archive accounting and scan state |
| `ram:2FF7` | `3D:62C2` `archive_find_free_span` | scan records for a span large enough for the new object |
| `ram:2FF1` | `3D:64AA` `archive_write_record` | write the record marker, header, name, data, and final status |
| `ram:3003` | `3D:6440` `unarchive_record_to_ram` | copy an archived record to RAM and retire its Flash record |

`archive_write_record` unlocks Flash with the protected port-`0x14` sequence. It writes an initial `0xF0` marker when the selected position requires one, starts the record with `0xFE`, writes the size and variable metadata, copies the data, and finalizes the status as `0xFC`. It uses `_WriteAByte` (`8021`, body `3F:4C9F`) for marker bytes and `_WriteFlashUnsafe` (`8087`, body `3F:4CA6`) for blocks. [confirmed]

The bounds checks at `3D:6B6D` and `3D:6B9B` reject pages below `08` and pages at or above the dynamic App boundary from `3D:6413`. Both require the Flash destination to be at least `0x4000`; the block form at `3D:6B6D` also requires `HL >= 0x4000`. Carry reports rejection to the caller, which raises `E_ArchFull`. [confirmed]

A generated 17,000-byte program makes the record data span pages. The traced record writer passes its 17,002-byte `[size][body]` field to one `_WriteFlashUnsafe` invocation, which programs physical `0x20013` through `0x2427C` continuously across `08:7FFF` to `09:4000`. The copied worker increments port `0x06` from `0x08` to `0x09`, resets `DE` to `0x4000`, and finishes with its `0xF0` reset at the final target. This is direct TilEm evidence for the ordinary archive page-crossing path, not a physical-calculator measurement. [confirmed]

### Record-status byte [confirmed]

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
0–3 clear) with a direct write in the [delete and garbage-collection path](#flash-garbage-collector-confirmed), not via those three in-progress/valid
helpers. Because only bits go `1→0`, a deleted record
can never be re-validated in place — it is reclaimed only by GC erasing the whole sector.
`flash_find_nonff` (`3D:7DEA`) confirms `0xFF` = empty: it reads the 13-byte record header and `CP 0xFF`
on each, treating an all-`0xFF` run as a free slot. (`3D:7C99` additionally folds in `AND 0xE7` and
conditional `OR 0x10`/`OR 0x08` for the swap/relocate state bits driven by `(IY+0x1A).0` and `(IY+0).2`.)

### Dynamic archive and application boundary [confirmed]

The archive begins at page `08`. `archive_app_boundary` (`3D:6413`) computes its exclusive upper bound by starting at the model-specific top App page from `3D:726E`, validating each installed App header, obtaining its span from `_FindAppNumPages` (`3D:4AA3`), and subtracting that span until it reaches the first page below the installed App run. [confirmed]

| Model test | Top App page from `3D:726E` | Certificate page from `3D:738B` |
|------------|--------------------------------:|----------------------------------:|
| port `0x02` bit 7 clear | `0x15` | `0x1E` |
| port `0x21 & 3` equals zero | `0x29` | `0x3E` |
| remaining branch | `0x69` | `0x7E` |

The second column is the App scan start, not an archive base. The third column selects the certificate page, not an archive endpoint. `archive_find_free_span` stores the computed boundary, starts at page `08`, and scans upward. On the OS-only TI-84 Plus image, the boundary is `0x29`; the successful `Archive prgmA` trace selects `08:4000`. Installed Apps consume pages downward from the upper end and reduce the archive interval. [confirmed]

The ASIC pages Flash in 16 KiB units, but the chip erases ordinary sectors in 64 KiB units. Page `3E` contains two 8 KiB certificate sectors, and page `3F` is a 16 KiB boot sector. See [Sector geometry](flash-memory.md#sector-geometry). [standard]

---

## Flash garbage collector [confirmed]

The archive garbage collector compacts records in 64 KiB sector units. It also journals its phase
in the inactive half of page `3E`, so startup code can distinguish an interrupted collection from a
normal archive layout. This mechanism is separate from `_CleanAll`, which only compacts RAM.

### Collector entries

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

### Four-page archive sectors

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

### Observed sector-copy sequence

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

### Certificate-sector journal

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

The certificate rebuild dispatcher confirms the journal's half-relative span.
Mode `3` replaces `0x1DEA`–`0x1E4F`. Mode `4` replaces that block and the
validity tail at `0x1FE0`–`0x1FFF`. [confirmed]

The GC block has model-dependent RAM mirrors beginning at `0x837B` or
`0x82A5`. The helper addresses pin its first fields: [confirmed]

| Block offset | Certificate offset | Helper | RAM mirrors | ROM use |
|-------------:|-------------------:|--------|-------------|---------|
| `+0x00` | `0x1DEA` | `3C:7E78` | `0x837B`, `0x82A5` | Control flags tested during preparation and recovery. |
| `+0x01` | `0x1DEB` | `3C:7E83` | `0x837C`, `0x82A6` | The archive App boundary from `3D:6413`, incremented once. |
| `+0x02` | `0x1DEC` | `3C:7E8E` | `0x837D`, `0x82A7` | Selected 64 KiB archive-sector page. |
| `+0x03` | `0x1DED` | `3C:7E99` | `0x837E`, `0x82A8` | Master recovery phase. |
| `+0x04` | `0x1DEE` | `3C:7EA4` | `0x837F`, `0x82A9` | Page erased by the phase-`0xF8` recovery branch. |
| `+0x05` | `0x1DEF` | `3C:7EBA` | `0x8380`, `0x82AA` | Optional second page erased by the phase-`0xFC` branch. |
| `+0x06` | `0x1DF0` | `3C:7EAF` | `0x8381`, `0x82AB` | Start of the archive-sector state array. |

The initialization bounds are narrower than the certificate rebuild span.
`3C:7E6B` first loads the current certificate data into RAM. The initializer at
`3C:7317` then writes `0xFF` to 100 bytes beginning at `0x82A5` when port-`0x02`
bit 7 is set; its bit-clear branch writes 18 bytes beginning at `0x837B`.
Because the first six bytes are the fields above, those lengths leave capacity
for 94 and 12 sector-state bytes respectively. [confirmed]

The mode-`4` certificate rebuild path at `3D:4274` copies `0x66` bytes from
`0x82A5`, two more than the TI-84 Plus initializer erases. Offsets `+0x64` and
`+0x65` are therefore retained from the previously loaded certificate block;
they are not initialized sector states. No direct semantic accessor for those
two bytes has been found. [confirmed] for the load, initialization, and rebuild
bounds; [hypothesis] for the trailing bytes' semantic owner.

`3C:7DA9` indexes the sector-state array as
`(archive_page >> 2) - 2`. Page `08` maps to slot `0`, page `0C` maps to slot
`1`, and each later 64 KiB sector advances one slot. The normal path writes
`0xFE` through `3C:7848`, then `0xFC` through `3C:7853`. The recovery path can
write `0xFC` through `3C:7C54`. [confirmed]

Capacity is not the live range. The no-App TI-84 Plus archive limit is `0x2A`,
so the only possible sector-start pages below it are `08`, `0C`, `10`, `14`,
`18`, `1C`, `20`, `24`, and `28`: slots `0`–`8`. Installed Apps can lower the
limit further. The ROM's larger advanced-family branch can raise the exclusive
limit to `0x6A`, which still uses only 25 slots. The remaining initialized bytes
are spare capacity in this ROM's reachable archive geometry. [confirmed]

`gc_recover_by_phase` at `3C:7C1F` dispatches the master byte. The branch
targets and their joins show how each interrupted phase resumes: [confirmed]

| Phase | Branch | Recovery action visible in the ROM | Join |
|------:|--------|------------------------------------|------|
| `0xFF` | `3C:7C43` | Run the phase-`0xFE` initializer. | `gc_run_phase_machine` at `3C:7CFB` |
| `0xFE` | `3C:7C48` | Inspect pending sector slots, repair scratch-sector setup, and resume phase processing. | `3C:7CFB` after internal repair branches |
| `0xFC` | `3C:7CC6` | Erase the selected recovery page and an optional second page through `_EraseFlashPage = 8084h`. | `3C:7D0A`, after the phase-`0xFC` write point |
| `0xF8` | `3C:7CDA` | Erase the page stored at block offset `+0x04`. | `3C:7D1B`, after the phase-`0xF8` write point |
| `0xF0` | `3C:7CE3` | Search `0xFC` and `0xF8` archive-sector headers, then repair or erase the remaining sector. | finalization at `3C:7D25` or `3C:7D2B` |
| `0xE0` | `3C:7D30` | Run final journal cleanup through `3C:7B90` and `3C:7B2A`. | return |

The shared writer at `3C:7AA6` updates Flash and the model-dependent RAM
mirror. The normal phase machine emits the following values: [confirmed]

| Value | Load and call | Condition |
|------:|---------------|-----------|
| `0xFE` | `3C:7ACF → 3C:7AD1` | Always after optional scratch-sector header programming. |
| `0xFC` | `3C:7D05 → 3C:7D07` | Journal flags bit `3` is clear. |
| `0xF8` | `3C:7D10 → 3C:7D12` | Journal flags bit `3` is clear. |
| `0xF0` | `3C:7D20 → 3C:7D22` | The archive-sector consistency check returns carry. |
| `0xE0` | `3C:7D2B → 3C:7D2D` | Always before final cleanup. |

Every transition only clears bits. The complete ROM-reachable progression is
`FF → FE → FC → F8 → F0 → E0`, with conditional edges that skip `FC/F8` or
`F0`. The direct skip edges are `FE → F0`, `FE → E0`, and `F8 → E0`.
[confirmed]

The `GCFLASH` trace takes a short path. The master byte at `3E:7DED` receives
`0xFE` at clock `334587331` and `0xE0` at clock `338262732`. Slot `0` at
`3E:7DF0`, which maps page `08`, receives `0xFE` at clock `335222873` and
`0xFC` at clock `338237430`. [confirmed] for the decoded TilEm trace.

The rebuild worker also issues program commands with data `0xFF` while copying
the block. Those commands cannot clear NOR bits and are not phase transitions.
`tools/gc_journal.py` separates them from state-changing commands. Its CLI can
report the static structure alone or correlate a trace: [confirmed]

```sh
python tools/analyze_gc_journal.py --json
python tools/analyze_gc_journal.py \
  --trace /tmp/tibasic-smoke/gcflash.trace --json
```

`gc_check_interrupted` begins at `3C:7BC7`. The fixture's startup check reads
an erased status and skips the branch to `3C:7BDD` and `3C:7C1F`.
[confirmed]

### TilEm restart at six journal boundaries

The `GCFLASH` command trace can produce interrupted Flash images without
guessing archive contents. `tools/flash_replay.py` applies decoded byte-program
commands as `old & requested` and applies sector erases with the top-boot
geometry. `tools/replay_flash_trace.py` stops when an initialized journal phase
belongs to the sole certificate half whose base marker is `0x00`. [confirmed]

This replay treats the command-shaped CPU writes as accepted device commands.
The fixture supports that assumption in three independent ways: all 62 ordinary
program invocations and all six certificate invocations end at OS success
resets, the decoder finds no unmatched writes, and later trace reads use the
programmed archive state. TLMT does not directly record ASIC or Flash-device
acceptance, so the CLI requires `--accept-command-shapes`. [confirmed] for this
fixture; [hypothesis] for an arbitrary trace.

The active journal has flags `0xFB`, archive limit `0x2A`, selected sector page
`0x08`, and active half base `0xFA000`. The `0xFF` snapshot begins only when
`3E:6000` reaches its final `0x00` marker at clock `334577678`. The earlier
`0xFF` program at `3E:7DED` occurs while that half is still inactive. The same
trace then supplies active `0xFE` and `0xE0` snapshots: [confirmed]

| Input phase | Original-trace trigger | Input image SHA-256 | Cold-restart path | Recovery command shapes |
|------------:|-----------------------:|--------------------|-------------------|-------------------------|
| `0xFF` | `334577678` | `4e484ad4b99f07a333ae3845ee795b36cb6181e9a829261b2d52ff7931ac8f05` | `3C:7BC7 → 3C:7C1F → 3C:7C43 → 3C:7CFB → 3C:7D30` | 582 programs, three erases, 36 resets |
| `0xFE` | `334587331` | `b59cb47398bd186e2eaf7791ad42729e6f29f670da6b1854497eb7fbdbc362a8` | `3C:7BC7 → 3C:7C1F → 3C:7C48 → 3C:7CFB → 3C:7D30` | 581 programs, three erases, 35 resets |
| `0xE0` | `338262732` | `9c85a13be6d123443457eb772a16664a4a49f06a3d1dc0340b8b8d96a9b12b6b` | `3C:7BC7 → 3C:7C1F → 3C:7D30` | 551 programs, two erases, 20 resets |

Each input image boots with a fresh RAM reset under the pinned TilEm build. The
`0xFF` and `0xFE` paths erase the page-`08` archive sector and both certificate
halves while completing the sector move. The `0xE0` path programs the page-`0C`
sector header to `0xF0` and performs certificate cleanup without erasing page
`08`. [confirmed] for TilEm.

Replaying each recovery trace over its input image produces SHA-256
`8c857701d7da118d5c5f4c240ee21af91a10b95539059e74fb5e423368a683f9`.
Replaying the uninterrupted `GCFLASH` trace from the pinned ROM produces the
same 1 MiB image. `cmp` reports exact equality for all four images. This proves
TilEm convergence after successful command boundaries at `0xFF`, `0xFE`, and
`0xE0`; it does not model a cut during a pending program or erase. [confirmed]
for TilEm.

Two controlled archive topologies reach the other dispatcher states. The first
starts with only two synthetic bytes: page `08`'s erased header becomes `0xFE`,
and page `28`'s erased header becomes `0xF0`. `tools/gc_layout.py` builds the
copy without modifying its source; `tools/build_gc_layout.py` requires the
source hash, refuses existing output by default, and reports every mutation.
The pinned-ROM input and controlled output hashes are: [confirmed]

```text
source:     7d9a7d96d89fc552ebee6afdbdd011fdc6047be9c16d308245dff07eb1f7bd6d
controlled: 788b3c088e2954be5e53689afa7ac07d80159086a45d213a53f88952a65dd2e1
```

The starting topology is synthetic, but the unmodified ROM writes the journal
and all later archive state. Its `GCFLASH` trace reaches `3C:7801` and writes
active `0xFC` and `0xF8` phases. Fresh-RAM cold boots visit the statically
decoded recovery branches: [confirmed] for TilEm.

| Input phase | Original-trace trigger | Input image SHA-256 | Recovery branch | Recovery command shapes |
|------------:|-----------------------:|--------------------|-----------------|-------------------------|
| `0xFC` | `340858598` | `f88f242026c8ae633764573f6dce0e2ef322668dbd149c36a8fb0732987da491` | `3C:7BC7 → 3C:7C1F → 3C:7CC6 → 3C:7D30` | 554 programs, four erases, 23 resets |
| `0xF8` | `340966279` | `77b7671e1bdd287022e1863de50a324b9818487be4f05403016e7f4e57b3f782` | `3C:7BC7 → 3C:7C1F → 3C:7CDA → 3C:7D30` | 553 programs, three erases, 22 resets |

Both recovery replays and uninterrupted execution produce the same complete
image, SHA-256
`0dcf62f7445f5bc44b93effb7fd4cdf90d1cf813ad5ea55dd1f7445e0c14003f`.
This is byte-for-byte convergence from ROM-written phases; it does not make the
two input header bytes calculator-authentic. [confirmed]

The `0xF0` reference input contains eight ordinary program records in the
page-`08` and page-`0C` sectors. Three 17,000-byte records and one 14,454-byte
record fill each sector, leaving one erased trailing byte. Normal archive-UI
runs and successful OS Flash-worker traces produce SHA-256
`389ed80fe8635740f855c7b8ffec6312a5182027dd0605e8a6e2b094c8481452`.
`tools/archive_fixture.py` independently serializes the observed record header
and first-fit placement into erased 64 KiB sectors. Its guarded CLI reproduces
that complete image byte for byte from `tools/rom.bin` and the eight ordered
name/size pairs. [confirmed]

Running `GCFLASH` from the reconstructed input puts its dead record in page
`10`; page `08` and page `0C` remain occupied when
`gc_check_archive_consistency` runs. An unmodified-ROM recapture takes the
direct `0xFE → 0xF0` transition and reproduces the phase image hash below.
[confirmed] for TilEm.

| Phase | Reference trigger clock | Input image SHA-256 | Recovery branch |
|------:|------------------------:|--------------------|-----------------|
| `0xF0` | `333006337` | `df49d6ec77483e33944fdbcee969084fc065b01a4e44327f83246a9de363fcb2` | `3C:7BC7 → 3C:7C1F → 3C:7CE3 → 3C:7D30` |

The reconstructed run reaches `0xF0` at clock `339126369`. Its trace SHA-256
is `ffd6b2fb7a18713a2814666516f25f76bc9999314dfab83f3361c35e7bdd42ac`.
Clock and whole-trace differences therefore leave the materialized phase image
unchanged. [confirmed]

The first uninterrupted and recovered outputs are not byte-identical. Their
archive regions match, but 11 certificate bytes differ: uninterrupted execution
ends with an active `0xE0` cleanup journal, while the `0xF0` restart completes
that cleanup during its boot. Cold-booting the uninterrupted output once erases
both certificate halves and produces the recovered SHA-256
`39113ee67921340b8817e35576a8f8fda467122af7713b099f399512d65d9bc3`.
Cold-booting the recovered output produces no Flash commands. Thus the `0xF0`
case converges to the same stable Flash image after deferred `0xE0` cleanup,
not at the first trace endpoint. [confirmed] for TilEm.

TilEm and Wabbitemu exercise all six phase boundaries after successful command
boundaries. Cuts during busy commands and physical power loss remain untested.
[confirmed] for the emulator runs; [hypothesis] for the remaining cases.

### Wabbitemu restart at six journal boundaries

A Linux headless adapter now runs the pinned Wabbitemu commit `48c2dc0` without
its Windows interface. The acquisition procedure verifies the codeload archive
hash; the builder then verifies a path-and-content hash over all 334 extracted
source files and the individual translation units. Its only compatibility
changes remove the MSVC-only `__pragma` tokens and provide inert callbacks for
debugger registration and disabled audio. The CPU, memory, Flash, device,
keypad, interrupt, and LCD implementations are unmodified. [confirmed]

Each run begins with fresh RAM, presses ON at 24,000,000 t-states, releases it
at 24,900,000 t-states, executes at least 20,000,000 instructions, and requires
ten identical Flash samples one million instructions apart. An unmodified-ROM
baseline reaches the OS after the same wake transition without changing any of
the 1 MiB Flash image. The interrupted runs execute these page-`0x3C` points:
[confirmed]

| Input phase | Wabbitemu dispatcher visits | Changed input bytes | Output SHA-256 |
|------------:|------------------------------|--------------------:|----------------|
| `0xFF` | `7BC7 → 7C1F → 7C43 → 7CFB → 7D30` | 74 | `8c857701d7da118d5c5f4c240ee21af91a10b95539059e74fb5e423368a683f9` |
| `0xFE` | `7BC7 → 7C1F → 7C48 → 7CFB → 7D30` | 75 | `8c857701d7da118d5c5f4c240ee21af91a10b95539059e74fb5e423368a683f9` |
| `0xFC` | `7BC7 → 7C1F → 7CC6 → 7D30` | 14 | `0dcf62f7445f5bc44b93effb7fd4cdf90d1cf813ad5ea55dd1f7445e0c14003f` |
| `0xF8` | `7BC7 → 7C1F → 7CDA → 7D30` | 14 | `0dcf62f7445f5bc44b93effb7fd4cdf90d1cf813ad5ea55dd1f7445e0c14003f` |
| `0xF0` | `7BC7 → 7C1F → 7CE3 → 7D30` | 131,082 | `39113ee67921340b8817e35576a8f8fda467122af7713b099f399512d65d9bc3` |
| `0xE0` | `7BC7 → 7C1F → 7D30` | 12 | `8c857701d7da118d5c5f4c240ee21af91a10b95539059e74fb5e423368a683f9` |

The outputs equal the corresponding uninterrupted TilEm replays byte for byte;
matching only the journal byte or archive range was not used as the criterion.
The `0xF0` run starts from the deterministically reconstructed `df49d6…` phase
image. It executes 20,000,000 instructions and 231,942,592 t-states before
reaching ten unchanged Flash samples. Its complete 1 MiB output equals both the
TilEm recovery and the normalized uninterrupted result.
`tools/compare_flash_images.py` enforces the input hashes and complete-image
equality. [confirmed] for all six Wabbitemu command-boundary runs;
[hypothesis] for cuts during busy commands and physical power loss.

The cold-start caller at `00:0D73` reaches the wrapper at `3D:6098` through
the bjump stub at `00:3EEB`. Wabbitemu accepts the protected `OUT (0x14),A`
at `3D:60A6`, changing its gate from locked to unlocked. The wrapper enters
`gc_check_interrupted` at `3C:7BC7` through `00:2BAD`, then relocks at
`3D:5CEF` after recovery returns. Every phase run records the same unlock and
relock transitions. Between them, each run reaches `_WriteFlashUnsafe`, the
byte-identical 124-byte worker copied from `3F:4CCA` to `0x8100`, and its
success tail. No phase reaches that worker's failure tail. This is a genuine
retail startup and recovery path under Wabbitemu, with no injected CPU state or
direct assignment to `flash_locked`. [confirmed]

The native adapter, importable orchestration library, and guarded build/run
CLIs are documented in `tools/dynamic-tracing.md`. Their JSON reports include
typed gate writes and transitions, retail-bcall and copied-worker coverage,
input and output hashes, exact dispatcher visits, instruction and t-state
counts, changed-byte counts, wake completion, and Flash-settling status.

### Reproducing the command timeline

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

## Memory checks [confirmed]

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
- Free archive is computed inside the page-3D archive layer.
  `archive_prepare_scan` at `3D:61AF` prepares its accounting state,
  `archive_find_free_span` at `3D:62C2` searches for placement, and
  `archive_app_boundary` at `3D:6413` supplies the dynamic exclusive upper
  page. The catalog **MEM** path runs through `3C:7121`. [confirmed]

---

## Routine index

| space:addr | name | what |
|------------|------|------|
| `07:6248` | `_Arc_Unarc` | archive/unarchive entry; toggles arc flag, dispatches RAM↔Flash |
| `07:628B` | `arc_chk_name` | archivable-name validator |
| `07:6107` | `arc_ram_to_flash` | RAM→Flash archive worker (programs Flash, frees old RAM) |
| `07:61F4` | `arc_flash_to_ram` | Flash→RAM unarchive worker (carves RAM, copies from Flash) |
| `07:6331` | `arc_size_setup` | stash vatPtr, compute dataSize into arcInfo |
| `07:61DC` | `arc_save_info` | save the 12-byte tail from `arcInfo.vat_ptr` into `savedArcInfo`; `07:61E8` is an inferred restore candidate |
| `07:565F` | `findsym_scan` | the real `_FindSym` VAT scanner |
| `00:0E65` | `_FindSym` | RST10 trampoline → findsym_scan |
| `00:0E60` | `_ChkFindSym` | type-check OP1 then FindSym |
| `00:1485` | `_DataSize` | variable data byte-size by type |
| `38:62A9` | `_StoOther` | store value into named var |
| `38:67B1` | `_RclVarSym` | recall var by symbol |
| `3A:5D07` | `rcl_var_push` | recall var, push to FPS |
| `3D:6745` | `_FlashToRam` | copy archived data Flash→RAM (page-aware); `ti83plus.inc` sibling `_FlashToRam2` (id 8054) is named but its body is unmapped in the disassembly |
| `3D:678C` | `ram_worker_launcher` | copy a length-prefixed worker to `0x8100` and execute it; used by `_FlashToRam` and certificate-page programming |
| `3D:61AF` | `archive_prepare_scan` | prepare archive accounting and scan state |
| `3D:64AA` | `archive_write_record` | program a complete archive record; executed in the archive trace |
| `3D:6440` | `unarchive_record_to_ram` | copy an archived record to RAM and retire its Flash record |
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

## Resolved behavior and open items

- **Archive allocation.** [confirmed] The allocator scans upward from page `08` to the exclusive App boundary from `3D:6413`. On the traced OS-only TI-84 Plus, that interval is pages `08`–`28`; the new record begins at `08:4000`.
- **Hardware Flash path.** [confirmed] `archive_write_record` at `3D:64AA` invokes `_WriteAByte` and `_WriteFlashUnsafe`; the boot worker runs at `0x8100`, issues AMD byte-program commands, polls DQ7/DQ5, and returns success. See [Flash memory](flash-memory.md).
- **Erase granularity.** [standard] Ordinary sectors are 64 KiB, not one 16 KiB paging unit. The top-boot geometry also has 32, 8, 8, and 16 KiB sectors at physical `0xF0000`–`0xFFFFF`.
- **Record-status bytes.** [confirmed] The [record-status byte](#record-status-byte-confirmed) uses monotonic bit clearing: `0xFF` erased → `0xFE` in-progress
  → `0xFC` valid via `flash_op_fe/fd/fb` (`3D:7C97/7C8F/7C93`) AND-masking; `0xF0` deleted is a direct write in the delete/GC path
  the status byte; `flash_find_nonff` (`3D:7DEA`) treats an all-`0xFF` header as free.

- **Garbage collection.** [confirmed] `archive_gc_collect` at `3C:7733` moves live records in 64 KiB sector units and uses the inactive 8 KiB certificate half as a persistent journal. The ordinary `GCFLASH` trace copies the surviving `B` record from the page-`08` sector to page `0C`, erases the old sector, and rotates the empty scratch sector back to page `08`. TilEm and pinned Wabbitemu cold restarts exercise all six ROM-written journal phases. Five converge byte-for-byte with uninterrupted execution; `0xF0` converges after the uninterrupted result performs deferred `0xE0` cleanup on its next boot. [hypothesis] Physical power loss and cuts inside busy commands remain untested.
- **Group archive path.** [hypothesis] The path is partially pinned. `_DataSize` (`00:1485`) confirms a Group
  (type `0x17`, like AppVar `0x15`/`0x16`) carries a leading word-size header, so a group *can* be
  stored as one Flash blob. In `_Arc_Unarc` the `CP 0x17` → `26E0` reject sits on the B≠0 (in-Flash)
  branch, immediately before the unarchive worker `61F4` — so an archived group is not unarchived
  through `61F4`, and groups are handled by a separate routine that walks the group's member list.
  That member-walk routine remains
  unidentified in the disassembly — `_Arc_Unarc`'s body past the entry `CALL` is not
  disassembled here (cross-page `CALL` flagged non-returning), and no group-archive function is
  named or xref-reachable. Confirming it would need a linear disassembly pass like the one used for [archive and unarchive](#archive-and-unarchive-confirmed).
