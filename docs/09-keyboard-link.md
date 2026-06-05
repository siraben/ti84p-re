# 09 — Keyboard & Link Port

## Keyboard

The keypad is a matrix read through **port 1** (`port_keypad`): write a group-select mask, read back the active columns. The **interrupt** triggers periodic scans; the result is debounced into `kbdScanCode` (`0x843F`).

- `_GetCSC` (`00:04B2`) — "Get Cursor/Scan Code": with interrupts masked, returns `kbdScanCode` and clears it (one key per call, no repeat). Raw scan codes (`skXxx`). **[confirmed]**
- `_GetKey` (`06:491E`) — the cooked key API: blocks, handles **2nd/ALPHA** modifier state, key repeat, and APD; returns a `TIKeyCode` (`kXxx`, 642 values). Also runs the cursor blink. Drives menus/homescreen. **[confirmed entry; body large]**
- `_KeyToString` (`01:6D10`) — map a key code to its display token/string (for text entry).

Scan codes (`skEnter`, hardware matrix position) differ from key codes (`kEnter`=5, post-modifier). `_GetCSC` returns the former; `_GetKey` the latter.

### Key → token translation [confirmed]

`_KeyToString` (`01:6D10`) turns a key code into a TI-BASIC **token** for the editor. It's not a single flat table — it combines:
- **range arithmetic**: contiguous key ranges map to token ranges by a fixed offset (e.g. key `0x1F`→`'P'`-based, `0x59`→`'a'` for lowercase) — letters/digits;
- **per-mode lookup tables** on another page, reached via `cross_page_jump` (the 2nd/ALPHA-mode and function-key token tables);
- special key codes `0xFB/0xFC/0xFE/0xFF` are **not** tokens — they're the **menu / context-switch return codes** the main event loop branches on (see [11](11-boot-contexts-errors.md)), so `_KeyToString` routes them out via `cross_page_jump` rather than translating.

So the input path is: keypad → ISR → `kbdScanCode` → `_GetKey` (cooked `kXxx` + modifiers) → `_KeyToString` → token → parser ([07](07-tokenizer-basic.md)).

## Link port

The 2.5 mm I/O link has two open-collector lines (tip/ring), driven via **port 0** (`port_link`), with an 84+ **hardware link-assist / USB** path via ports `0x08/0x09/0x0D`.

`_SendAByte` (`3C:420D`) shows both paths **[confirmed]**:
- **Hardware-assisted** (when enabled): poll status `port 0x09` bit 5 (ready), then write the byte to `port 0x0D`; helper routines on page 3C manage the assist FIFO/timing.
- **Legacy bit-bang**: to send a bit, pull one line low (`port_link = 1` for a 0-bit, `2` for a 1-bit), wait for the receiver to mirror it, release, wait for idle — with a timeout that calls `_JErrorNo(0)` (`E_Link`) on failure. Repeats per bit of the byte.

`_RecAByteIO` (`3C:443F`) is the matching receive. Higher-level link commands (`_CmdLoad`, variable transfer, `_CircCmd`/`_VertCmd` for screen-shot/remote) sit on top.

## TODO
- Trace the keypad matrix scan routine (the ISR-side writer of `kbdScanCode`) and document the group masks per port-1 value.
- Document the link command/packet framing (`_Get_Some_Bytes`, header/checksum) for variable transfer.
