# Keyboard and link port

The keypad scanner and link-port drivers provide the calculator's local input and wired data-transfer paths. The keyboard path turns matrix scans into cooked key codes, while the link path sends bytes through the legacy two-wire port or the hardware-assisted interface.

> **Deep dives:** [Keypad and ON-key hardware](keypad-on-hardware.md) covers the electrical matrix, scanner timing, debounce, repeat, ON interrupts, and wake. [Link / data transfer](sub-link-transfer.md) covers silent-link packets and variable send/receive.

## Keyboard

The matrix keypad is read through port `0x01`: software writes an active-low group mask and reads active-low key lines. Standard hardware timer 1 scans it through `ram:03B4`. The separate **ON** circuit reports its level and interrupt state through ports `0x03` and `0x04`. [confirmed]

- `_GetCSC = 4018`, body `ram:04B2`, atomically reads and clears the one-byte `kbdScanCode` mailbox. It returns raw scan events and does not block. [confirmed]
- `_GetKey = 4972`, body `06:491E`, blocks, processes hooks and APD state, applies **2nd** and **ALPHA**, and returns a cooked `TIKeyCode`. [confirmed]
- `_KeyToString` at `01:6D10` maps a cooked key code to an editor token or string. [confirmed]

Scan codes such as `skEnter` identify a matrix position. Cooked key codes such as `kEnter = 5` incorporate OS modifier and context policy. `_GetCSC` returns the former; `_GetKey` returns the latter. The complete matrix, scan-code formula, diagonal-arrow exception, five-sample release filter, repeat timing, modifier state, and 46.7 ms ON debounce are reconstructed in [Keypad and ON-key hardware](keypad-on-hardware.md).

### Key → token translation [confirmed]

`_KeyToString` (`01:6D10`) turns a key code into a TI-BASIC token for the editor. It's not a single flat table — it combines:

- **range arithmetic**: contiguous key ranges map to token ranges by a fixed offset (e.g. key `0x1F`→`'P'`-based, `0x59`→`'a'` for lowercase) — letters/digits;
- per-mode lookup tables on another page, reached via `cross_page_jump` (the 2nd/ALPHA-mode and function-key token tables);
- special key codes `0xFB/0xFC/0xFE/0xFF` are not tokens — they're the menu / context-switch return codes the main event loop branches on (see [Boot, contexts & errors](boot-contexts-errors.md)), so `_KeyToString` routes them out via `cross_page_jump` rather than translating.

So the input path is: keypad → ISR → `kbdScanCode` → `_GetKey` (cooked `kXxx` + modifiers) → `_KeyToString` → token → parser ([Tokenizer & TI-BASIC](tokenizer-basic.md)).

## Link port

The 2.5 mm I/O link has two open-collector lines (tip/ring), driven via `port 0` (`port_link`), with an 84+ hardware link-assist / USB path via ports `0x08`–`0x0D`. See [USB ASIC and link assist](sub-usb-asic.md) for the ASIC-facing port map and the `link_xfer_op` USB-selection gate.

`_SendAByte` (`3C:420D`) shows both paths [confirmed]:
- **Hardware-assisted** (when enabled): poll status `port 0x09` bit 5 (ready), then write the byte to `port 0x0D`; helper routines on page 3C manage the assist FIFO/timing.
- **Legacy bit-bang**: to send a bit, pull one line low (write `1` to `port_link` for a 0-bit, `2` for a 1-bit), wait for the receiver to mirror it, release, wait for idle — with a timeout that raises `E_LnkErr` (`0x9F`, "ERR:LINK") via `_JErrorNo` on failure (matching [sub-link-transfer.md](sub-link-transfer.md)). Repeats per bit of the byte.

`_RecAByteIO` (`3C:443F`) is the matching receive. Higher-level link commands (`_SendCmd` (bcall `4F3F`), variable transfer, plus screen-shot / remote-control commands) sit on top. (Note: the names `_CircCmd`/`_VertCmd` are documented in [sub-graphing.md](sub-graphing.md) as the graphing draw commands `Circle(` (`33:74CE`) and `Vertical` (`04:7955`); the link-layer command routines referenced here are distinct and were not separately traced — treat this as a [hypothesis].)

### Variable-transfer command/packet framing

A TI link packet is a 4-byte header (`machine-ID, command-ID, length-lo, length-hi`) optionally followed by `data[len]` and a 16-bit LE checksum; commands include `0x06` VAR, `0x09` CTS, `0x15` DATA, `0x56` ACK, `0x5A` NAK, `0x92` EOT. The full framing, the silent-link send/receive engine (`link_xfer_op`, `_SendVarCmd`), checksum/ACK handling, and the 16-byte Flash-batched receive path are all reverse-engineered in [sub-link-transfer.md](sub-link-transfer.md) — see §3 (framing) and §5 (variable send). [confirmed]
