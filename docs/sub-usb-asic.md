# USB ASIC and link assist

*TI-84 Plus OS 2.55MP - feature deep dive.*

This page covers the OS-visible USB/link-assist hardware interface: the Z80 I/O ports the ROM uses,
the byte FIFO path used by the link layer, and the places where `_LinkXferOP` chooses USB before
falling back to the 2.5 mm link. It complements [Link / data transfer](sub-link-transfer.md), which
covers the TI link packet protocol and variable-transfer state machine.

The full USB controller is broader than the variable-transfer path. This page is ROM-grounded: the
confirmed claims below come from OS 2.55MP disassembly/decompilation and cite the address ranges that
show them. External WikiTI names are used only as orientation where noted, not as proof.

## ROM-grounded surface

The ROM shows three transport-facing surfaces:

| Layer | Port range | Role |
|-------|------------|------|
| Legacy link | `0x00` | 2.5 mm tip/ring open-collector byte path. [confirmed: `3C:6C99`, `3C:6CF3`] |
| Link-assist FIFO | `0x08`-`0x0D` | Hardware byte send/receive assist used below `_SendAByte` and `_RecAByteIO`. [confirmed: `3C:6BB1`-`6D53`] |
| USB line / interrupt gates | `0x4D`, `0x55`, `0x56` | Line-state and event/status gates used before and during link handling. [confirmed: `3C:4E4A`, `00:006F`] |

In the variable-transfer code, the OS mostly treats USB as a transport selector around the existing
TI link protocol. The packet layer still sends machine IDs, command bytes, checksums, ACK/NAK, and
EOT exactly as described in [sub-link-transfer.md](sub-link-transfer.md). The hardware difference is
below that packet layer: bytes go through the assist FIFO when the ASIC path is enabled, and through
port `0x00` bit-banging otherwise. [confirmed]

## Observed port map [confirmed unless marked]

| Port | Observed use in OS 2.55MP | Evidence |
|------|---------------------------|----------|
| `0x02` | Hardware/model gate before using assist paths. The link code tests bit 7 before touching ports `0x08`-`0x0D`. | `3C:6C82`, `3C:6CB8`, `3C:6D15` |
| `0x08` | Link-assist control/idle latch. The OS writes `0x80` when clearing an inactive/error-free assist state, and `0x00` when marking the assist state active. | `3C:6C41`-`6C48`, `3C:6D38`-`6D40`, `3C:6D4B`-`6D53` |
| `0x09` | Link-assist status. Bit 5 is TX-ready; bit 6 is a transmission/error condition; bit 4 marks a received byte. Masks `0x19`, `0x58`, and `0x99` are used as error/activity predicates. | `3C:6BB6`-`6BC5`, `3C:444A`, `3C:6BFA`, `3C:6CCE`, `3C:6D33` |
| `0x0A` | Assist receive/data register on the confirmed receive path; also initialized with `0xB4` beside `0x0B/0x0C`. The write-side meaning of `0xB4` is still [hypothesis]. | `3C:6C20`, `3C:6C2B`, `3C:6C39` |
| `0x0B`, `0x0C` | Assist-side configuration registers initialized with `0xB4`; semantics not decoded. [hypothesis] | `3C:6C3D`, `3C:6C3F` |
| `0x0D` | Assist TX FIFO/data register. `_SendAByte` writes the outgoing byte here after port `0x09` bit 5 becomes set. | `3C:6BBC`-`6BBF` |
| `0x20` | CPU speed bit used to select assist/link wait-loop reloads. The send timeout uses `0xFFFF` when bit 0 is set and `0x6800` when clear. | `3C:6BCC`, `3C:6C8B`, `3C:6CC1` |
| `0x4D` | USB line-state gate. `_LinkXferOP` samples bits 5 and 6 before the unresolved `ram:2E48` call target. The ROM use proves only the bit tests, not the electrical names of those bits. | `3C:4E4A`-`4E6F` |
| `0x55` | USB interrupt status, active-low in the low five bits. The IM1 dispatcher tests `(in(0x55) ^ 0xFF) & 0x1F` first. | `00:006F`-`0075` |
| `0x56` | USB line-event bitmap used by the IM1 dispatcher after port `0x55` reports USB activity. The visible dispatcher branches on bits 1, 4, 5, 6, and 7. Event names are not derived from the ROM alone. | `00:0085`-`00AE` |

The project-local `tools/ports.txt` now names the confirmed assist and USB interrupt ports so future
Ghidra rebuilds show the same surface in the database. These labels describe the observed OS use,
not a complete vendor register map.

## Sending one byte through the assist FIFO [confirmed]

The hardware send entry is `lnk_send_byte_hw` at `3C:6BB2` (the preceding byte at `3C:6BB1` is a
`RET` from the prior helper). It is the assist branch behind `_SendAByte` (`3C:420D`).

Mechanically, it does four things:

1. Seed the inner retry counter at RAM `0x9C86` with `0xFA`.
2. Read port `0x09`.
3. If bit 5 is set, copy the outgoing byte from `C` to port `0x0D` and return.
4. If bit 5 is clear, call the timeout decrementer (`3C:6BE4`/`lnk_timeout_dec`) and retry until
   the outer counter at `0x9CAC` expires, then fall into the link error path at `3C:4434`.

The ROM disassembles to:

```z80
; 3C:6BB2, assist send path
6BB2: call 6D4Fh        ; clear/prepare assist I/O latch
6BB5: call 6BD2h        ; seed 9CAC from CPU speed
6BB8: call 6BD2h

6BBB: ld   a,0FAh
6BBD: ld   (9C86h),a    ; inner retry reload
6BC0: in   a,(09h)
6BC2: bit  5,a
6BC4: jr   z,6BCAh      ; TX not ready
6BC6: ld   a,c
6BC7: out  (0Dh),a      ; write byte to assist FIFO
6BC9: ret

6BCA: call 6BE4h        ; decrement 9CAC, Z means keep polling
6BCD: jr   z,6BBBh
6BCF: jp   4434h        ; link timeout/error path
```

`lnk_set_timeout` (`3C:6BD2`) seeds `0x9CAC` from CPU speed. When port `0x20` bit 0 is clear it uses
`0x6800`; when the bit is set it leaves the larger `0xFFFF` seed. The ROM confirms the two reload
values, while the wall-clock timeout they target is not measured here. [confirmed]

## Receiving and status handling [confirmed]

The receive path is split between `_RecAByteIO` (`3C:443F`), `lnk_rec_status` (`3C:444A`), and the
assist helpers around `3C:6BF4`-`6D40`.

The hardware-facing receive loop waits until port `0x09 & 0x58` becomes nonzero. In the confirmed
path:

- `0x40` (bit 6) is treated as a transmission/error condition.
- `0x10` (bit 4) is the "byte received" condition.
- `0x08` participates in the wait condition but is not fully named in this pass.
- When the receive condition is accepted, the byte is read from port `0x0A` into `C`.
- The status masks `0x19` and `0x99` select error/activity cases before the code resets or re-arms
  the assist latch through port `0x08`.

`lnk_rec_status` also uses the sentinel byte `0xE0`: callers pass it for a nonblocking/probe style
receive check. If the caller requires a byte and the status path reports anything else, the code
raises `E_LnkErr` through `_JError(0x9F)`. [confirmed]

The assist reset/enable sequence at `3C:6C31` writes:

```z80
out (0x00),0x00
out (0x09),0x97
out (0x0A),0xB4
out (0x0B),0xB4
out (0x0C),0xB4
out (0x08),0x80
out (0x08),0x00
in  a,(0x09)
set 0,(IY+0x3E)
```

The sequence proves the ports touched and the RAM flag used by the OS. It does not by itself name
the bit fields inside `0x97` or `0xB4`. [confirmed ports; bit meanings open]

## USB selection in `_LinkXferOP` [confirmed]

`_LinkXferOP` (`3C:4DD2`, bcall ID `0x50FB`) is the OS entry that sends a silent link request and
prefers the USB path when its mode flags ask for it. The ROM-confirmed setup is:

- `OP1` holds the variable type/name.
- `sndRecState` (`0x8672`) is `0x15` for DATA-style receive.
- `IY+0x1B` bit 0 selects USB-first behavior; reset means use the link port path.

The OS confirms that contract in the `4E35`-`4E73` gate:

1. If `IY+0x1B` bit 0 is clear, it skips USB probing and sends through the ordinary link path.
2. If bit 0 is set and either `IY+0x1B` bit 5 or bit 6 asks for USB handling, it reads port `0x4D`.
3. If port `0x4D` bit 5 is clear, or bit 5 is set and bit 6 is clear, the OS sets `IY+0x1B` bit 5
   and calls the target at `ram:2E48`.
4. Otherwise it clears `IY+0x1B` bit 5 and continues into `lnk_send_data_867d` (`3C:4055`), which
   sends the same TI link request/VAR/DATA packets described in the link-transfer page.

This makes `_LinkXferOP` a USB-first wrapper around the existing link transfer engine. It does not
replace the packet format. The transport choice happens before `_SendAByte` writes each byte through
the assist FIFO or falls back to port `0x00`. [confirmed]

## Interrupt integration [confirmed]

The IM1 dispatcher (`ram:006F`) treats the USB interrupt status as its first source gate:

```z80
in a,(0x55)
xor 0xFF
and 0x1F
```

If no low-five-bit USB source is active, the handler falls through to the other interrupt work. If a
USB source is active, it reads port `0x56` and branches on event bits. In the visible dispatcher,
bits 4, 5, 6, 7, and 1 are routed to subhandlers; the surrounding code also checks 84+ hardware mode
through `(IY+0x09)` bit 3 and `port 0x07 == 0x81` before using the USB/timer event path. [confirmed]

The timer/idle side of the same handler also bridges to the assist path. At `ram:01B1` it calls
`ram:1850`, the same hardware-gate routine used elsewhere before assist-port access. On the legacy path it checks `port 0x00 & 0x03`; on the assist
path it checks `port 0x09 & 0x18`. If either assist bit is set, it reloads `0x9C86 = 0xFA`, pulses
port `0x08` with `0x80` then `0x00`, sets `IY+0x3E` bit 0, and calls the common link activity hook
at `ram:3FD6`. [confirmed: `00:01B1`-`01DB`]

For application code, this means a custom interrupt handler that does not chain to the OS handler
must account for port `0x55`/`0x56` activity itself. The exact masking sequence is outside this
ROM-grounded pass. [confirmed for the need to service sources; masking details open]

## How to use it in code [grounded by OS calls]

Prefer the OS entry points unless the program is deliberately writing a USB driver:

| Need | OS surface | ROM support |
|------|------------|-------------|
| Send or request a variable over USB/link | `_LinkXferOP` (`50FB` -> `3C:4DD2`) or `_SendVarCmd` (`4A14` -> `3C:4EDD`) | Packet engine and USB-selection gate confirmed on page `3C`. |
| Send one byte on the active link transport | `_SendAByte` (`4EE5` -> `3C:420D`) | Assist branch writes `C` to port `0x0D` after port `0x09` bit 5. |
| Receive one byte on the active link transport | `_RecAByteIO` (`4F03` -> `3C:443F`) | Status path checks port `0x09` and reads port `0x0A` on the assist path. |
| Use the raw assist FIFO | Poll port `0x09` bit 5, then write the byte to port `0x0D`; for receive, observe port `0x09` bit 4/error bits and read port `0x0A`. | Confirmed as an OS pattern, but not a complete public API. |

The raw FIFO sequence is only the byte layer. A working transfer still needs the packet layer:
machine ID, command, length, payload checksum, ACK/NAK, and EOT. That framing is documented in
[sub-link-transfer.md](sub-link-transfer.md#3-packet-framing--the-ti-link-protocol-c).

Practical rules:

- Set up `IY+0x1B` consistently before calling `_LinkXferOP`. Bit 0 is the USB-first selector.
- Do not write ports `0x08`-`0x0D` while the OS link engine is active; the OS keeps state in
  `IY+0x3E` bit 0, `0x9C86`, and `0x9CAC`.
- If a custom interrupt handler is installed, either chain to the OS handler or service the same
  source gates. The OS itself expects to handle port `0x55`/`0x56` events.
- Treat any high-level USB endpoint/pipe controller claims as outside this page's confirmed scope.
  This ROM pass does not trace a general USB host/device stack.

## Open pieces

- The target at `ram:2E48`, called from `_LinkXferOP` after the port `0x4D` line-state test, is not
  a normal function in the current Ghidra database. A raw `z80dasm` window around `2E48` does not
  decode as a clean routine body, so its exact side effects remain open. [hypothesis]
- Port `0x0A` is confirmed as the assist RX/data read register on this path, but its initialization
  value `0xB4` and the paired writes to `0x0B`/`0x0C` still need bit-level interpretation.
  [hypothesis]
- A future pass should trace the EasyData/USB app paths and reconcile any endpoint/pipe ports with
  the OS 2.55MP database. [hypothesis]
