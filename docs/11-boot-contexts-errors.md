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

## TODO
- Decode the full `cx*` vector layout (offsets of key/display/putaway handlers within the 12-byte block).
- Finish the boot RAM-init trace; find the homescreen main loop and confirm it's the root context.
- Locate the error-message string table and map codes → messages.
