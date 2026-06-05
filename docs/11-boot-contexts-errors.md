# 11 — Boot, Contexts & Error Handling

Three cross-cutting mechanisms that tie the OS together: how it starts, how it switches "modes" (contexts), and how it aborts on error.

## Boot [confirmed, partial]

```
0000 reset:  in a,(2); and 0x80; jp 028c     ; test port 2 bit7, go to boot continuation
028c:        port_mapBankA = 0x1F             ; bank a flash page into 4000
             (cond) DAT_io_000E = 3; port_mapBankA = 0x7F   ; configure RAM/exec paging (port 0x0E)
             port_intStatus = 7               ; set up interrupt sources
             ... (jumps into RAM-copied code — static disasm stops here)
```

Boot configures the paging hardware (ports 6 and `0x0E`) and interrupt controller, then transfers to code it copies into RAM (why the static trace ends with "bad instruction"). It eventually initializes RAM, the VAT, system flags, the LCD, and enters the main context (the homescreen). *To finish: follow the RAM-copied stub and the RAM-init path.*

### The main event loop [confirmed]

`main_event_loop` @ `ram:05e6` (page 0) is the OS root dispatcher. Structure:
```
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

So a mode key doesn't reach the active context — the router intercepts it and swaps `cx*` to the new context. `keyExtend` (`0x8446`) holds the extended-key state. **[confirmed]**

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

### Error-message table [confirmed]

The error screen shows `ERR:<MESSAGE>` (the `ERR:` prefix is on `page_01:4008`). The messages are a string table on **`page_07:6B3B`**, ordered by error code — the handler indexes it by `(code & 0x7F) − 1`:

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

## TODO
- Decode the full `cx*` vector layout (offsets of key/display/putaway handlers within the 12-byte block).
- Finish the boot RAM-init trace.
- Flash write/erase sector primitives are RAM-resident (84+-specific, not in the 2001 equates); locate via `_CleanAll`'s callees on page 7.
