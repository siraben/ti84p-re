# 11 — Boot, contexts, and error handling

Three cross-cutting mechanisms that tie the OS together: how it starts, how it switches "modes" (contexts), and how it aborts on error.

## Boot [confirmed, partial]

```z80
0000 reset:  in a,(2); and 0x80; jp 028c     ; test port 2 bit7, go to boot continuation
028c:        port_mapBankA = 0x1F             ; bank a flash page into 4000
             (cond) DAT_io_000E = 3; port_mapBankA = 0x7F   ; configure RAM/exec paging (port 0x0E)
             port_memMapMode = 7              ; OUT (4): memory-map mode 1 + slow timer rate
             jp 0x812c                        ; into the boot page (3F:412C) — BootFree substitute here; retail boot in D84PBE1.8Xv
```

Boot configures the paging hardware (`OUT (6),0x7F` selects flash page `3F`, the boot page) and the memory-map/timer mode (`OUT (4)`), then ends `JP 0x812c` into the banked window where page `3F` sits — `3F:412C`. In this BootFree `rom.bin` page `3F` is a substitute placeholder (`3F:412C` re-maps paging rather than running the retail sequence); the retail boot page carries the real continuation (`D84PBE1.8Xv` / `ti84plus_patched.rom`, `3F:412C` = `IM 1; LD B,0; LD SP,0xFDFA; …`). The boot page eventually initializes RAM, the VAT, system flags, the LCD, and enters the main context (the homescreen).

The boot page (`3F`) and its version queries are exposed to the OS through `ti83plus.inc` bcalls: `_getBootVer` (bcall `0x80B7` → `3F:477C`) and `_getHardwareVersion` (bcall `0x80BA` → `3F:4781`). The USB boot support entry points route through the same table but land on page `2F`, for example `_AttemptUSBOSReceive` (`0x80E4` → `2F:4145`) and `_InitUSB` (`0x8108` → `2F:52A4`).

### RAM clear / re-init (`ram_reset_wipe` → `ram:0BD9`) [confirmed]

The RAM-init proper is `ram_reset_wipe` (`35:719F`, reached on a full reset; the same routine backs the `[2nd]+[+] · 7 · 1 · 2` RAM-reset and the post-boot RAM clear). It zero-fills RAM in two blocks, preserving a handful of flag bits and `0x9B73` across the wipe:

```z80
ram_reset_wipe (35:719f):
  ; save flags to preserve: (9B73), (IY+34).6, (IY+35).0, (IY+35).1, (IY+3F)&0x7F
  DI
  LD HL,8000 ; LD DE,8001 ; LD BC,1BC3 ; LD (HL),0 ; LDIR   ; clear 8000..9BC3
  ... restore the saved flag bits ...
  LD HL,9BD0 ; LD DE,9BD1 ; LD BC,642F ; LD (HL),0 ; LDIR   ; clear 9BD0..FFFF
  JP 0x0BD9
ram_init_after_reset (ram:0BD9):
  LD A,0xC0 ; OUT (0),A        ; port 0 = memory-map control
  LD SP,0xFFF7                 ; reset stack to top of RAM
  CALL 0x3EC1                  ; continue init (page-0 kernel): VAT, sysflags, LCD …
```

So RAM is wiped in two LDIR runs (`0x8000`–`0x9BC3`, then `0x9BD0`–`0xFFFF`, leaving the `0x9BC4`–`0x9BCF` window and the explicitly-saved flag bytes intact), then `ram:0BD9` resets the memory map (port 0) and the stack and hands off through `ram:3EC1`. This `ram:0BD9` entry is the same RAM re-init point cross-referenced from [12-memory-management](12-memory-management.md). The `ram:3EC1` continuation (VAT/sysflag/LCD bring-up) is page-0 kernel code and is statically present (`ram:3EC1` = `CALL 0x2B09; …`). *Residual: `JP 0x812c` targets the boot page (`3F:412C`); this `rom.bin` carries a BootFree substitute there, with the retail boot code in `D84PBE1.8Xv`.*

### The main event loop [confirmed]

`main_event_loop` @ `ram:05e6` (page 0) is the OS root dispatcher. Structure:
```z80
05e6: LD B,8;  LD HL,0x84BE        ; iterate an 8-entry event/context stack
05eb: INC HL                       ; first slot is 0x84BF
05ec: LD A,(HL); OR A; JR Z,...    ; skip empty slots
05f5: CALL 0x3f3f                  ; per-entry dispatch (event/key router)
0601: CP 0x7F / 0xFE / 0xFC / 0xFB ; branch on the handler's return code
...
0690: LD A,0x7F; CALL call_context_main   ; run the active context's handler
0699: POP AF; JP Z,0x05e6                 ; loop
```
So the loop pumps an event/context stack (8 slots from `0x84BF`, after the `INC HL`), routes each via the dispatcher at `ram:3F3F`, and ultimately runs the active context's `cxMain` handler through `call_context_main`, looping forever.

The `ram:3F3F` router is a bjump trampoline → `event_key_router` (`page_07:4539`): given a key code, it scans key→context dispatch tables (`07:4099`, ~105 entries, for 1-byte keys; `07:422C`/`4426` for extended 2-byte keys, using `_LdHLind`/`_CpHLDE`) and returns a routing code:
- `0xFE` — normal: hand the key to the active context's handler.
- `0xFB` / `0xFC` — context switch / app launch (the key maps to a different context — recall `cxCurApp` *is* a key code, so e.g. `[GRAPH]` → the graph context).
- `0xFF`/`0x7F` — quit / no-op.

So the router classifies a mode key before the active context sees it and returns a context-switch code (`0xFB`/`0xFC`); the caller then swaps the `cx*` vectors. The router itself only writes `keyExtend` (`0x8446`, the extended-key state) — its body holds no store to the `cx*` block. [confirmed]

## Contexts — how the OS implements "modes"/apps [confirmed — key concept]

The OS is single-tasking but multi-context. A *context* is the set of handler routines for whatever is currently in front of the user (homescreen, an editor, the graph screen, a Flash App). The active context's vectors live in RAM at `cxMain` (and friends), with `cxPage` holding which flash page their code is on.

- `_AppInit` (`ram:0936`) installs a context: copies 12 bytes of handler vectors → `cxMain`, sets `flags.appFlags`, and saves `cxPage = port_mapBankA` (the page the app runs from). [confirmed]
- The dispatched handlers include things like a key handler, (re)display/paint handler, and a PutAway (suspend) handler — the OS calls them through the `cx*` vectors, paging in `cxPage` first.
- `_PutAway` (`ram:08AF`) calls the current context's PutAway handler (`cxPPutAway`) to suspend/clean up — used on APD, when switching apps, or on `2nd+QUIT`. [confirmed]

This is the backbone of the UI: the main event loop reads a key (`_GetKey`), then calls the active context's key handler; switching screens swaps the `cx*` vectors.

### Context block layout [confirmed, from ti83plus.inc + xrefs]

The active context lives at a fixed RAM block (`Context` struct, base `cxMain`=`0x858D`):

| Off | Addr | Field | Meaning |
|-----|------|-------|---------|
| +0 | 858D | `cxMain` | main/event handler ptr |
| +2 | 858F | `cxPPutAway` | putaway handler ptr |
| +4 | 8591 | `cxPutAway` | putaway |
| +6 | 8593 | `cxRedisp` | redisplay/repaint handler ptr (the inc's `cxRedisp` bcall, id `0x4C6C`, body `ram:08D0`, reads this slot via `LD HL,(8593)` and dispatches it) |
| +8 | 8595 | `cxErrorEP` | error entry point ptr |
| +10 | 8597 | `cxSizeWind` | window-size handler ptr |
| +12 | 8599 | `cxPage` | flash page the handlers live on |
| +13 | 859A | `cxCurApp` | current context id — equals a key code (`cxGraph`=kGraph, `cxCmd`=kQuit, `cxPrgmEdit`=kPrgmEd …) |
| +14 | 859B | `cxPrev` | base of the 14-byte shadow of `cxMain`…`cxCurApp` (plus a separately-saved appFlags byte) — the suspended previous context |

`_AppInit` copies the 6 vectors (12 bytes, +0..+11) from an app's header into this block, then sets `cxPage`. Because `cxCurApp` is a key code, a mode-switch key naturally selects the context to load.

The full `_AppInit` body confirms the offsets directly — `HL` points at the app's 12-byte vector header, `LDIR` lands them at `cxMain`=`0x858D`, and the byte that follows the 12 vectors becomes a flags byte; `cxPage` is then loaded from the live bank-A page-select (port 6), *not* copied from the header:

```z80
_AppInit (ram:0936):
  ; HL = source (12-byte vector header) on entry
  LD DE,0x858D            ; -> cxMain
  LD BC,0x000C            ; 12 bytes = the 6 handler vectors
  LDIR                    ; cxMain..cxSizeWind+1  (+0..+11)
  LD A,(HL)               ; the 13th header byte (appFlags)
  LD (0x89FD),A           ; -> appFlagsAddr (system flag byte)
  IN A,(0x6)              ; current bank-A flash page
  LD (0x8599),A           ; -> cxPage  (+12, the page the handlers run from)
  RET
```

The destination `0x858D` and length `0x000C` pin the six 2-byte handler slots `cxMain`(+0) `cxPPutAway`(+2) `cxPutAway`(+4) `cxRedisp`(+6) `cxErrorEP`(+8) `cxSizeWind`(+10), and the explicit `LD (0x8599),A` writes `cxPage` at +12 from port 6. `_AppInit` installs a context, but it is not the only writer: `_POPCX` (bcall `0x49E1`, body `07:6D1C`) restores a suspended context by `LDIR`ing 14 bytes `cxPrev`→`cxMain` (`0x859B`→`0x858D`) and copying a 15th byte into the app-flags, and a matching save path (the `LDIR` at `07:5A8C`) copies `cxMain`→`cxPrev`. `cxCurApp`(+13, `0x859A`) is the current context id (a key code); the shadow at `cxPrev`(`0x859B`) holds the suspended context.

### How a context handler is invoked [confirmed]

```
call_context_main (ram:08fa):   set_bankA_page(cxPage); call (cxMain) via jp_hl; ret   ; run handler on its page, control returns here
call_context_savepage (ram:08e9): save port6; set_bankA_page(cxPage); jp_hl; restore port6
```
Primitives: `set_bankA_page` (`ram:078c`, `port6 = page`) and `jp_hl` (`ram:090b`, `jp (hl)` dynamic dispatch). The OS pages the handler in, runs it, and (for the savepage variant) restores the caller's page.

## Error handling [confirmed]

Errors use a non-local exit, not return codes:
- A routine detects a fault and calls `_JError` (`ram:2793`) with an error code in `A` (the `TIError` enum: `E_Domain`, `E_DivBy0`, `E_Memory`, … each ORed with `E_EDIT`=0x80 if re-editable). `_JError` stores the code to `errNo` (`0x86DD`); the sibling entry `_JErrorNo` (`ram:2799`) raises the already-stored `errNo` without taking a new code.
- The handler restores the stack from `errSP` (`0x86DE`, `LD SP,(errSP)` at `ram:27BB`), restores a sane state, and displays the error screen (`ERR:` + message, with `1:Quit 2:Goto`). `errSP` is the current error frame; `_resetStacks` seeds it from `onSP` (`0x85BC`, the context-level saved SP) at context/parse start.
- The `E_EDIT` bit (0x80) tells the handler the error is editable (offer "2:Goto" to jump to the offending token).

So `errSP` + `_JError` together implement try/catch: a context seeds `errSP` (from `onSP`) at entry, and any depth of nested calls can abort straight back to it.

### Error-message table [local data-table trace]

The error screen shows `ERR:<MESSAGE>` (the `ERR:` prefix is on `page_01:4008`). A local data-table trace shows the handler masking the code (`AND 0x7F`), then for codes below `0x3A` indexing a little-endian pointer table at `page_07:6ACC` by `(code) − 1` (`LD HL,0x6ACC; ADD HL,DE; ADD HL,DE; CALL _LdHLind`) to fetch each message pointer; the message strings themselves sit consecutively from `page_07:6B3C` as null-terminated text. Codes `≥ 0x3A` (and the special-cased `0x36`/`0x37`/`0x39`) bypass the table and fall back to the `?` message at `page_07:6C5A`. The current MCP function/xref view does not prove this data-only table directly, so treat the addresses as a data trace rather than live function symbols:

| Code | `TIError` | Message @ page_07 |
|------|-----------|-------------------|
| 1 | E_Overflow | OVERFLOW (6B3C) |
| 2 | E_DivBy0 | DIVIDE BY 0 (6B45) |
| 3 | E_SingularMat | SINGULAR MAT (6B51) |
| 4 | E_Domain | DOMAIN (6B5E) |
| 5 | E_Increment | INCREMENT (6B65) |
| 6 | E_Break | BREAK (6B6F) |
| 7 | E_NonReal | NONREAL ANS (6B75) |
| 8 | E_Syntax | SYNTAX (6B81) |
| 9 | E_DataType | DATA TYPE (6B88) |
| 10 | E_Argument | ARGUMENT (6B92) |
| 11 | E_DimMismatch | DIM MISMATCH (6B9B) |
| 12 | E_Dimension | INVALID DIM (6BA8) |
| … | … | UNDEFINED, MEMORY, INVALID, ILLEGAL NEST, BOUND, WINDOW RANGE, ZOOM, LABEL, STAT, SOLVER, … LINK (6C55) |

The `Code` column is each error's low 7 bits. Re-editable errors set the `E_EDIT` (`0x80`) bit on top — `E_Overflow equ 1+E_EDIT`, `E_DivBy0 equ 2+E_EDIT`, … — while non-editable ones (`E_Label equ 20`, `E_Stat equ 21`, …) carry no such bit. The handler masks the code (`AND 0x7F`) before indexing. So the whole error pathway is: a routine `_JError`s a code → the handler restores `SP` from `errSP` → masks the code and looks up the message here → renders `ERR:<msg>`.

## Confirmed details
- **`cx*` vector layout — confirmed.** The six 2-byte handler slots and `cxPage` offsets are pinned by tracing `_AppInit` (`ram:0936`): `LD DE,0x858D / LD BC,0x000C / LDIR` then `IN A,(6) / LD (0x8599),A`. See [Context block layout](#context-block-layout-confirmed-from-ti83plusinc--xrefs) above for the full offset table and `_AppInit` body. `_AppInit` installs the block; it is not the sole writer — `_POPCX` (bcall `0x49E1` → `07:6D1C`) restores a saved context into `cxMain`, and a save path at `07:5A8C` copies `cxMain` into the `cxPrev` shadow.
- **Boot RAM-init trace — raw-disassembly trace.** Reset (`ram:0000`) → `028c` paging setup → `JP 0x812c` (boot page `3F:412C` — BootFree substitute in this `rom.bin`; retail boot in `D84PBE1.8Xv`). The RAM clear/re-init is `ram_reset_wipe` (`35:719f`): two `LDIR` zero-fills (`0x8000`–`0x9BC3`, `0x9BD0`–`0xFFFF`) preserving a few flag bytes, then `JP 0x0BD9` (`ram_init_after_reset`: port 0 = `0xC0`, stack reset in the raw trace, `CALL 0x3EC1`). The `ram:0BD9` entry matches the re-init point cross-referenced in [12-memory-management](12-memory-management.md). See [RAM clear / re-init](#ram-clear--re-init-ram_reset_wipe--ram0bd9-confirmed).
- **Flash write/erase sector primitives — partially resolved (cross-link).** Live MCP confirms page-3D anchors such as `flash_program_buf` `3D:678C`, the per-record status writers `3D:7C8F/7C93/7C97`, and `flash_erase_wait` `3D:5ED3`, with byte-poke loops copied to `ramCode` `0x8100`. The candidate labels `flash_program_core` `3D:61AF` and `flash_write_record` `3D:64AA` are not defined functions in the current live DB; both names are project-local inferred labels, not WikiTI or `ti83plus.inc` equates. The public single-byte flash writers are `_WriteAByte` (bcall `0x8021`) and `_WriteAByteSafe` (bcall `0x80C6`) in `ti83plus.inc`; these name the public entry points, whose bodies are likewise not defined functions in the current live DB. See [sub-vat-archive §6](sub-vat-archive.md#6-low-level-flash-write--erase-pages-3c3d-port-0x14-mixed).

*Residual:* `JP 0x812c` targets the boot page (`3F:412C`); page `3F` is a BootFree substitute in this `rom.bin`, with the retail boot code in `D84PBE1.8Xv`. The `ram:3EC1` init continuation is page-0 kernel code and is statically present.
