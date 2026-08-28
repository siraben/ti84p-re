# Keyboard and link port

The keypad scanner and link-port drivers provide the calculator's local input and wired data-transfer paths. The keyboard path turns matrix scans into cooked key codes, while the link path sends bytes through the legacy two-wire port or the hardware-assisted interface.

> **Deep dives:** [Keypad and ON-key hardware](keypad-on-hardware.md) covers the electrical matrix, scanner timing, debounce, repeat, ON interrupts, and wake. [Two-wire link port hardware](link-port-hardware.md) covers port `0x00`, electrical encoding, raw byte handshakes, timeouts, and background detection. [Link / data transfer](sub-link-transfer.md) covers silent-link packets and variable send/receive.

## Keyboard

The matrix keypad is read through port `0x01`: software writes an active-low group mask and reads active-low key lines. Standard hardware timer 1 scans it through `ram:03B4`. The separate **ON** circuit reports its level and interrupt state through ports `0x03` and `0x04`. [confirmed]

- `_GetCSC = 4018`, body `ram:04B2`, atomically reads and clears the one-byte `kbdScanCode` mailbox. It returns raw scan events and does not block. [confirmed]
- `_GetKey = 4972`, body `06:491E`, blocks, processes hooks and APD state, applies **2nd** and **ALPHA**, and returns a cooked `TIKeyCode`. [confirmed]
- `_KeyToString` at `01:6D10` maps a cooked key code to an editor token or string. [confirmed]

Scan codes such as `skEnter` identify a matrix position. Cooked key codes such as `kEnter = 5` incorporate OS modifier and context policy. `_GetCSC` returns the former; `_GetKey` returns the latter. The complete matrix, scan-code formula, diagonal-arrow exception, five-sample release filter, repeat timing, modifier state, and 46.7 ms ON debounce are reconstructed in [Keypad and ON-key hardware](keypad-on-hardware.md).

The Ghidra build types `kbdKey` at `0x8444` and `cxCurApp` at `0x859A` as
`TIKeyCode`. It applies `kLeft` and `kAlphaDown` to the byte-checked comparisons
at `39:5048` and `39:507C`. Other numeric operands keep their raw values unless
their key-code role is established. [confirmed]

### Key → token translation [confirmed]

`_KeyToString` (`01:6D10`) turns a key code into a TI-BASIC token for the editor. It's not a single flat table — it combines:

- **range arithmetic**: contiguous key ranges map to token ranges by a fixed offset (e.g. key `0x1F`→`'P'`-based, `0x59`→`'a'` for lowercase) — letters/digits;
- per-mode lookup tables on another page, reached via `cross_page_jump` (the 2nd/ALPHA-mode and function-key token tables);
- special key codes `0xFB/0xFC/0xFE/0xFF` are not tokens — they're the menu / context-switch return codes the main event loop branches on (see [Boot, contexts & errors](boot-contexts-errors.md)), so `_KeyToString` routes them out via `cross_page_jump` rather than translating.

So the input path is: keypad → ISR → `kbdScanCode` → `_GetKey` (cooked `kXxx` + modifiers) → `_KeyToString` → token → parser ([Tokenizer & TI-BASIC](tokenizer-basic.md)).

## Link port

The 2.5 mm I/O link uses two open-collector lines. Port `0x00` drives and samples them directly; ports `0x08`–`0x0D` provide the TI-84 Plus hardware-assisted byte path. [standard] for the electrical interface; [confirmed] for the ROM port use.

`_SendAByte = 4EE5`, body `3C:420D`, sends legacy bits least-significant first. It writes `1` for bit 0 and `2` for bit 1, waits for a both-low acknowledgement, releases its line, and waits for idle. `_RecAByteIO = 4F03`, body `3C:443F`, performs the inverse handshake. Both paths use bounded waits that enter the link-error machinery on timeout. [confirmed]

Installed error callback `3C:6136` reaches `3C:618D` for applicable transfer states. Its raw branch marks the link busy, selects nominal 6 MHz, drives both lines low for a 7,077,785-base-T-state loop, releases them, and clears busy; its USB branch skips port `0x00`. The documented Flash opcode wait raises the loop to 8,191,881 T-states. This is the OS's transport-specific abort cleanup. [confirmed] for the ROM role and base count; [standard] for the wait-state-adjusted count.

[Two-wire link port hardware](link-port-hardware.md) reconstructs the port read/write inversion, four transitions, receiver rotation, errors, and timer-driven activity check. [USB ASIC and link assist](sub-usb-asic.md) covers the assist FIFO selected by the same byte routines.

### Variable-transfer packet framing

A TI link packet is a 4-byte header (`machine-ID, command-ID, length-lo, length-hi`) optionally followed by `data[len]` and a 16-bit LE checksum; commands include `0x06` VAR, `0x09` CTS, `0x15` DATA, `0x56` ACK, `0x5A` NAK, `0x92` EOT. [Link transfer](sub-link-transfer.md#ti-link-packet-framing-confirmed) covers the framing, silent-link send/receive engine (`link_xfer_op`, `_SendVarCmd`), checksum and acknowledgement handling, and 16-byte Flash-batched receive path. [confirmed]
