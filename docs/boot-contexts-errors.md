# Boot, contexts, and errors

This page connects three cross-cutting mechanisms: OS startup, context
switching, and error unwinding.

## Boot [confirmed]

```z80
3F:4000:     LD A,0x07; OUT (0x04),A           ; paired mapping
             LD A,0x7F; OUT (0x06),A           ; pages 3E/3F in 4000/8000
             LD A,0x03; OUT (0x0E),A           ; extended Flash bits
             JP 0x812C                         ; page 3F in the 8000 window
```

The emulator reset trace begins at logical `0x8000`, where paired mode exposes
`retail_boot_reset_stub` at `3F:4000`. The stub keeps page `3F` in the B window
and jumps to logical `0x812C`, corresponding to `boot_os_entry` at `3F:412C`.
Page 0 also has a restart vector at
`00:0000` → `00:028C` that establishes the same paired mapping and reaches the
same continuation. At `boot_os_entry + 0x20` (`3F:414C`), the continuation
changes to independent mode while page `3F` remains visible for the next
instruction. See
[Paging](paging.md#boot-mapping-transition) for the complete window-by-window
transition. [confirmed]

[Retail boot hardware initialization](boot-hardware.md) follows the
continuation through its reset delay, RAM-window safety checks, ordered ASIC
programming, first keypad scan, OS-validity decision, and destructive RAM
diagnostic. It also reconciles standard Z80 timing with the pinned TilEm trace.

The assembled `rom.bin` validates and installs the retail `D84PBE1.8Xv`
payload at page `3F`; the pinned base already contains the same 16 KiB page, so
the installation changes no bytes. The continuation begins
`IM 1; LD B,0; LD SP,0xFDFA; …`. The boot page eventually initializes RAM, the
VAT, system flags, the LCD, and enters the main context (the homescreen).
[confirmed]

The boot page (`3F`) and its version queries are exposed to the OS through `ti83plus.inc` bcalls: `_getBootVer` (bcall `0x80B7` → `3F:477C`) and `_getHardwareVersion` (bcall `0x80BA` → `3F:4781`). The USB boot support entry points route through the same table but land on page `2F`, for example `_AttemptUSBOSReceive` (`0x80E4` → `2F:4145`) and `_InitUSB` (`0x8108` → `2F:52A4`).

### RAM clear / re-init (`ram_reset_wipe` → `ram:0BD9`) [confirmed]

The RAM-init proper is `ram_reset_wipe` (`35:719F`, reached on a full reset; the same routine backs the `[2nd]+[+] · 7 · 1 · 2` RAM-reset and the post-boot RAM clear). It zero-fills RAM in two blocks, preserving a handful of flag bits and `0x9B73` across the wipe:

```z80
ram_reset_wipe (35:719f):
  ; save flags to preserve: (9B73), (IY+34).6, (IY+35).0, (IY+35).1, (IY+3F)&0x7F
  DI
  LD HL,0x8000 ; LD DE,0x8001 ; LD BC,0x1BC3 ; LD (HL),0 ; LDIR   ; clear 8000..9BC3
  ... restore the saved flag bits ...
  LD HL,0x9BD0 ; LD DE,0x9BD1 ; LD BC,0x642F ; LD (HL),0 ; LDIR   ; clear 9BD0..FFFF
  JP 0x0BD9
ram_init_after_reset (ram:0BD9):
  LD A,0xC0 ; OUT (0),A        ; port 0 = memory-map control
  LD SP,0xFFF7                 ; reset stack to top of RAM
  CALL 0x3EC1                  ; continue init (page-0 kernel): VAT, sysflags, LCD …
```

So RAM is wiped in two LDIR runs (`0x8000`–`0x9BC3`, then `0x9BD0`–`0xFFFF`, leaving the `0x9BC4`–`0x9BCF` window and the explicitly-saved flag bytes intact), then `ram:0BD9` resets the memory map (port 0) and the stack and hands off through `ram:3EC1`. This `ram:0BD9` entry is the same RAM re-init point cross-referenced from [Memory management](memory-management.md). The `ram:3EC1` continuation (VAT/sysflag/LCD bring-up) is page-0 kernel code and is statically present (`ram:3EC1` = `CALL 0x2B09; …`). The reset jump to `boot_os_entry` is also present in the assembled database, so the page-0 and retail boot portions can be followed in one project.

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

The `ram:3F3F` router is a bjump trampoline → `event_key_router` (`07:4539`): given a key code, it scans key→context dispatch tables (`07:4099`, ~105 entries, for 1-byte keys; `07:422C`/`4426` for extended 2-byte keys, using `_LdHLind`/`_CpHLDE`) and returns a routing code:
- `0xFE` — normal: hand the key to the active context's handler.
- `0xFB` / `0xFC` — context switch / app launch (the key maps to a different context — recall `cxCurApp` *is* a key code, so e.g. `[GRAPH]` → the graph context).
- `0xFF`/`0x7F` — quit / no-op.

So the router classifies a mode key before the active context sees it and returns a context-switch code (`0xFB`/`0xFC`); the caller then swaps the `cx*` vectors. The router itself only writes `keyExtend` (`0x8446`, the extended-key state) — its body holds no store to the `cx*` block. [confirmed]

## Contexts — how the OS implements "modes"/apps [confirmed]

The OS is single-tasking but multi-context. A *context* is the set of handler routines for whatever is currently in front of the user (homescreen, an editor, the graph screen, a Flash App). The active context's vectors live in RAM at `cxMain` (and friends), with `cxPage` holding which flash page their code is on.

- `_AppInit` (`ram:0936`) installs a context: copies 12 bytes of handler vectors → `cxMain`, sets `flags.appFlags`, and saves `cxPage = port_mapBankA` (the page the app runs from). [confirmed]
- The dispatched handlers include things like a key handler, (re)display/paint handler, and a PutAway (suspend) handler — the OS calls them through the `cx*` vectors, paging in `cxPage` first.
- `_PutAway` (`ram:08AF`) calls the current context's PutAway handler (`cxPPutAway`) to suspend/clean up — used on APD, when switching apps, or on `2nd+QUIT`. [confirmed]
- `_PowerOff` (`5008`, body `ram:09E6`) performs context/display cleanup and joins `poweroff_shared_tail` at `ram:0A24`. The shared tail disables the standard timers, enables ON/link wake, and enters `poweroff_halt_loop` at `ram:0A5C`. See [Clock, timers, and power](clock-timers-power.md). [confirmed]

The UI runs on this mechanism: the main event loop reads a key (`_GetKey`), then calls the active context's key handler; switching screens swaps the `cx*` vectors.

### Context block layout [confirmed]

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

The full `_AppInit` body confirms the offsets directly — `HL` points at the app's 12-byte vector header, `LDIR` lands them at `cxMain`=`0x858D`, and the byte that follows the 12 vectors becomes a flags byte; `cxPage` is then loaded from the live bank-A page-select (port 6), not copied from the header:

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

```pseudocode
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

### Error-message table [confirmed]

The error screen shows `ERR:<MESSAGE>`; the `ERR:` prefix is at `01:4008`. The handler at `07:6A72` masks the code with `0x7F`, then indexes a little-endian pointer table at `07:6ACC` by `(code) − 1` for codes below `0x3A`. It fetches the pointer through `_LdHLind` and copies the selected null-terminated string. Codes `0x36`, `0x37`, `0x39`, and values at least `0x3A` bypass the table and select `?` at `07:6C5A`. [confirmed]

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
| … | … | UNDEFINED, MEMORY, INVALID, ILLEGAL NEST, BOUND, WINDOW RANGE, ZOOM, LABEL, STAT, SOLVER, … |
| 31–35 | link-error aliases | LINK (`6C55`) |

The `Code` column is each error's low 7 bits. Re-editable errors set the `E_EDIT` (`0x80`) bit on top — `E_Overflow equ 1+E_EDIT`, `E_DivBy0 equ 2+E_EDIT`, … — while non-editable ones (`E_Label equ 20`, `E_Stat equ 21`, …) carry no such bit. The handler masks the code (`AND 0x7F`) before indexing. Thus `_JError(0x22)` and `_JError(0x9F)` both select `LINK` at `07:6C55`, through pointer entries `07:6B0E` and `07:6B08`. `tools/describe_error.py` reproduces the table lookup from the ROM. [confirmed]

## Confirmed details

- **`cx*` vector layout — confirmed.** The six 2-byte handler slots and `cxPage` offsets are pinned by tracing `_AppInit` (`ram:0936`): `LD DE,0x858D / LD BC,0x000C / LDIR` then `IN A,(6) / LD (0x8599),A`. See [Context block layout](#context-block-layout-confirmed) above for the full offset table and `_AppInit` body. `_AppInit` installs the block; it is not the sole writer — `_POPCX` (bcall `0x49E1` → `07:6D1C`) restores a saved context into `cxMain`, and a save path at `07:5A8C` copies `cxMain` into the `cxPrev` shadow.
- **Boot RAM-init trace — raw-disassembly trace.** Emulator reset starts at logical `0x8000` on page `3F` and reaches `boot_os_entry`; the page-0 restart vector at `ram:0000` → `ram:028C` reaches the same continuation. The RAM clear/re-init is `ram_reset_wipe` (`35:719f`): two `LDIR` zero-fills (`0x8000`–`0x9BC3`, `0x9BD0`–`0xFFFF`) preserving a few flag bytes, then `JP 0x0BD9` (`ram_init_after_reset`: port 0 = `0xC0`, stack reset in the raw trace, `CALL 0x3EC1`). The `ram:0BD9` entry matches the re-init point cross-referenced in [Memory management](memory-management.md). See [RAM clear / re-init](#ram-clear--re-init-ram_reset_wipe--ram0bd9-confirmed).
- **Flash write and erase.** The retail boot table maps `_WriteFlash` (`80C9`) to `3F:4C8F`, `_WriteFlashUnsafe` (`8087`) to `3F:4CA6`, `_WriteAByte` (`8021`) to `3F:4C9F`, and `_EraseFlash` (`8024`) to `3F:4C2A`. Their program and erase loops are copied to `ramCode` at `0x8100`. A successful archive trace executes `archive_write_record` at `3D:64AA`, three `_WriteAByte` calls, and six entries through `_WriteFlashUnsafe`. See [Flash memory](flash-memory.md). [confirmed]

The `JP 0x812C` target and the `ram:3EC1` init continuation are both present in
the assembled database. The retail hardware work before the first keypad scan,
the **MODE** RAM diagnostic, and `boot_lcd_keypad_diagnostic` at `3F:4658`
are decoded in
[Retail boot hardware initialization](boot-hardware.md#dormant-lcd-and-keypad-diagnostic).
The sole branch to `boot_lcd_keypad_diagnostic` is constant-false; later recovery/UI paths remain
open. [confirmed]
