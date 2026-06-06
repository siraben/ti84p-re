# 11 — Boot, contexts, and error handling

Three cross-cutting mechanisms that tie the OS together: how it starts, how it switches "modes" (contexts), and how it aborts on error.

## Boot [confirmed, partial]

```z80
0000 reset:  in a,(2); and 0x80; jp 028c     ; test port 2 bit7, go to boot continuation
028c:        port_mapBankA = 0x1F             ; bank a flash page into 4000
             (cond) DAT_io_000E = 3; port_mapBankA = 0x7F   ; configure RAM/exec paging (port 0x0E)
             port_memMapMode = 7              ; OUT (4): memory-map mode 1 + slow timer rate
             ... (jumps into RAM-copied code — static disasm stops here)
```

Boot configures the paging hardware (ports 6 and `0x0E`) and the memory-map/timer mode (port 4 write), then transfers to code it copies into RAM (why the static trace ends with "bad instruction"). The continuation at `028c` ends `JP 0x812c`. `0x812c` is in the RAM execution window and is *blank in the static image*: the bytes are filled in at boot by the copy this stub performs, so the static trace cannot follow it. It eventually initializes RAM, the VAT, system flags, the LCD, and enters the main context (the homescreen).

### RAM clear / re-init (`ram_reset_wipe` → `0x0BD9`) [confirmed]

The RAM-init proper is `ram_reset_wipe` (`page_35::719f`, reached on a full reset; the same routine backs the `[2nd]+[+] · 7 · 1 · 2` RAM-reset and the post-boot RAM clear). It zero-fills RAM in two blocks, preserving a handful of flag bits and `0x9B73` across the wipe:

```z80
ram_reset_wipe (35:719f):
  ; save flags to preserve: (9B73), (IY+34).6, (IY+35).0, (IY+3F)&0x7F
  DI
  LD HL,8000 ; LD DE,8001 ; LD BC,1BC3 ; LD (HL),0 ; LDIR   ; clear 8000..9BC3
  ... restore the saved flag bits ...
  LD HL,9BD0 ; LD DE,9BD1 ; LD BC,642F ; LD (HL),0 ; LDIR   ; clear 9BD0..FFFF
  JP 0x0BD9
ram_init_after_reset (00:0BD9):
  LD A,0xC0 ; OUT (0),A        ; port 0 = memory-map control
  LD SP,0xFFF7                 ; reset stack to top of RAM
  CALL 0x3EC1                  ; (cross-page trampoline) continue init: VAT, sysflags, LCD …
```

So RAM is wiped in two LDIR runs (`0x8000`–`0x9BC3`, then `0x9BD0`–`0xFFFF`, leaving the `0x9BC4`–`0x9BCF` window and the explicitly-saved flag bytes intact), then `0x0BD9` resets the memory map (port 0) and the stack and hands off through `0x3EC1`. This `0x0BD9` entry is the same RAM re-init point cross-referenced from [12-memory-management](12-memory-management.md). *Residual: the `0x3EC1` continuation (VAT/sysflag/LCD bring-up) and the in-RAM `0x812c` stub run only from copied-in RAM code and are not statically disassemblable.*

### The main event loop [confirmed]

`main_event_loop` @ `ram:05e6` (page 0) is the OS root dispatcher. Structure:
```z80
05e6: LD B,8;  LD HL,0x84BE        ; iterate an 8-entry event/context stack
05ec: LD A,(HL); OR A; JR Z,...    ; skip empty slots
05f5: CALL 0x3f3f                  ; per-entry dispatch (event/key router)
0601: CP 0x7F / 0xFE / 0xFC / 0xFB ; branch on the handler's return code
...
0690: LD A,0x7F; CALL call_context_main   ; run the active context's handler
0699: POP AF; JP Z,0x05e6                 ; loop
```
So the loop pumps an **event/context stack** (8 slots near `0x84BE`), routes each via the dispatcher at `0x3f3f`, and ultimately runs the active context's `cxMain` handler through `call_context_main`, looping forever.

The `0x3f3f` router is a bjump trampoline → **`event_key_router` (`page_07:4539`)**: given a key code, it scans **key→context dispatch tables** (`07:4099`, ~105 entries, for 1-byte keys; `07:422C`/`4426` for extended 2-byte keys, using `_LdHLind`/`_CpHLDE`) and returns a **routing code**:
- `0xFE` — normal: hand the key to the active context's handler.
- `0xFB` / `0xFC` — **context switch** / app launch (the key maps to a different context — recall `cxCurApp` *is* a key code, so e.g. `[GRAPH]` → the graph context).
- `0xFF`/`0x7F` — quit / no-op.

So the router intercepts a mode key before the active context sees it and swaps `cx*` to the new context. `keyExtend` (`0x8446`) holds the extended-key state. **[confirmed]**

## Contexts — how the OS implements "modes"/apps [confirmed — key concept]

The OS is single-tasking but multi-**context**. A *context* is the set of handler routines for whatever is currently in front of the user (homescreen, an editor, the graph screen, a Flash App). The active context's vectors live in RAM at **`cxMain`** (and friends), with **`cxPage`** holding which flash page their code is on.

- `_AppInit` (`00:0936`) installs a context: copies **12 bytes** of handler vectors → `cxMain`, sets `flags.appFlags`, and saves `cxPage = port_mapBankA` (the page the app runs from). **[confirmed]**
- The dispatched handlers include things like a **key handler**, **(re)display/paint handler**, and a **PutAway** (suspend) handler — the OS calls them through the `cx*` vectors, paging in `cxPage` first.
- `_PutAway` (`00:08AF`) calls the current context's PutAway handler (`cxPPutAway`) to suspend/clean up — used on APD, when switching apps, or on `2nd+QUIT`. **[confirmed]**

This is the backbone of the UI: the main event loop reads a key (`_GetKey`), then calls the active context's key handler; switching screens swaps the `cx*` vectors.

### Context block layout [confirmed, from ti83plus.inc + xrefs]

The active context lives at a fixed RAM block (`Context` struct, base `cxMain`=`0x858D`):

| Off | Addr | Field | Meaning |
|-----|------|-------|---------|
| +0 | 858D | `cxMain` | main/event handler ptr |
| +2 | 858F | `cxPPutAway` | putaway handler ptr |
| +4 | 8591 | `cxPutAway` | putaway |
| +6 | 8593 | `cxRedisp` | redisplay/repaint handler ptr |
| +8 | 8595 | `cxErrorEP` | error entry point ptr |
| +10 | 8597 | `cxSizeWind` | window-size handler ptr |
| +12 | 8599 | `cxPage` | flash page the handlers live on |
| +13 | 859A | `cxCurApp` | current context id — **equals a key code** (`cxGraph`=kGraph, `cxCmd`=kQuit, `cxPrgmEdit`=kPrgmEd …) |
| +14 | 859B | `cxPrev` | previous context id |

`_AppInit` copies the **6 vectors (12 bytes, +0..+11)** from an app's header into this block, then sets `cxPage`. Because `cxCurApp` is a key code, a mode-switch key naturally selects the context to load.

The full `_AppInit` body confirms the offsets directly — `HL` points at the app's 12-byte vector header, `LDIR` lands them at `cxMain`=`0x858D`, and the byte that follows the 12 vectors becomes a flags byte; `cxPage` is then loaded from the live bank-A page-select (port 6), *not* copied from the header:

```z80
_AppInit (00:0936):
  ; HL = source (12-byte vector header) on entry
  LD DE,0x858D            ; -> cxMain
  LD BC,0x000C            ; 12 bytes = the 6 handler vectors
  LDIR                    ; cxMain..cxSizeWind+1  (+0..+11)
  LD A,(HL)               ; the 13th header byte (appFlags)
  LD (0x89FD),A           ; -> appInitFlag (system flag byte)
  IN A,(0x6)              ; current bank-A flash page
  LD (0x8599),A           ; -> cxPage  (+12, the page the handlers run from)
  RET
```

The destination `0x858D` and length `0x000C` pin the six 2-byte handler slots `cxMain`(+0) `cxPPutAway`(+2) `cxPutAway`(+4) `cxRedisp`(+6) `cxErrorEP`(+8) `cxSizeWind`(+10), and the explicit `LD (0x8599),A` writes `cxPage` at +12 from port 6. `0x858D` is the *only* writer of this block (the rest of the OS — `call_context_main` `00:08FB`, `_GetKey` `06:4A85`, etc. — only reads it), confirming `_AppInit` is the sole installer. `cxCurApp`(+13, `0x859A`) and `cxPrev`(+14, `0x859B`) are maintained separately by the context-switch logic, not by this copy.

### How a context handler is invoked [confirmed]

```
call_context_main (ram:08fa):   set_bankA_page(cxPage); jp (cxMain)      ; run handler on its page
call_context_savepage (ram:08e9): save port6; set_bankA_page(cxPage); jp_hl; restore port6
```
Primitives: `set_bankA_page` (`ram:078c`, `port6 = page`) and `jp_hl` (`ram:090b`, `jp (hl)` dynamic dispatch). The OS pages the handler in, runs it, and (for the savepage variant) restores the caller's page.

## Error handling [confirmed]

Errors use a non-local exit, not return codes:
- A routine detects a fault and calls `_JError` (`00:2793`) / `_JErrorNo` with an error code in `A` (the `TIError` enum: `E_Domain`, `E_DivBy0`, `E_Memory`, … each ORed with `E_EDIT`=0x80 if re-editable).
- `_JError` `cross_page_jump`s to the handler, which **unwinds the stack to `onSP`** (`0x85BC`, the SP saved when the current context/parse began), restores a sane state, and displays the error screen (`ERROR:` + message, with `1:Quit 2:Goto`).
- The `E_EDIT` bit (0x80) tells the handler the error is editable (offer "2:Goto" to jump to the offending token).

So `onSP` + `_JError` together implement try/catch: the context sets `onSP`, and any depth of nested calls can abort straight back to it.

### Error-message table [local data-table trace]

The error screen shows `ERR:<MESSAGE>` (the `ERR:` prefix is on `page_01:4008`). A local data-table trace places the messages on **`page_07:6B3B`**, ordered by error code, with the handler indexing by `(code & 0x7F) − 1`. The current MCP function/xref view does not prove this data-only table directly, so treat the address as a data trace rather than a live function symbol:

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

This exactly matches the `E_*` values in `ti83plus.inc` — confirming the `TIError` enum and the whole error pathway: a routine `_JError`s a code → handler unwinds to `onSP` → looks up the message here → renders `ERR:<msg>`.

## Resolved (was TODO)
- **`cx*` vector layout — confirmed.** The six 2-byte handler slots and `cxPage` offsets are pinned by tracing `_AppInit` (`00:0936`): `LD DE,0x858D / LD BC,0x000C / LDIR` then `IN A,(6) / LD (0x8599),A`. See [Context block layout](#context-block-layout-confirmed-from-ti83plusinc--xrefs) above for the full offset table and `_AppInit` body. `0x858D` (`cxMain`) is the only writer of the block.
- **Boot RAM-init trace — raw-disassembly trace.** Reset (`ram:0000`) → `028c` paging setup → `JP 0x812c` (RAM-copied stub, blank in the static image). The RAM clear/re-init is `ram_reset_wipe` (`35:719f`): two `LDIR` zero-fills (`0x8000`–`0x9BC3`, `0x9BD0`–`0xFFFF`) preserving a few flag bytes, then `JP 0x0BD9` (`ram_init_after_reset`: port 0 = `0xC0`, stack reset in the raw trace, `CALL 0x3EC1`). The `0x0BD9` entry matches the re-init point cross-referenced in [12-memory-management](12-memory-management.md). See [RAM clear / re-init](#ram-clear--re-init-ram_reset_wipe--0x0bd9-confirmed).
- **Flash write/erase sector primitives — partially resolved (cross-link).** Live MCP confirms page-3D anchors such as `flash_program_buf` `3D:678C`, the per-record status writers `3D:7C8F/7C93/7C97`, and `flash_erase_wait` `3D:5ED3`, with byte-poke loops copied to `ramCode` `0x8100`. Older labels like `flash_program_core` `3D:61AF` and `flash_write_record` `3D:64AA` are not current live-MCP functions; see [sub-vat-archive §6](sub-vat-archive.md#6-low-level-flash-write--erase-pages-3c3d-port-0x14-c).

*Residual (genuinely not statically traceable):* the in-RAM boot stub at `0x812c` and the `0x3EC1` init continuation run only from code copied into RAM during boot, so they have no static disassembly.
