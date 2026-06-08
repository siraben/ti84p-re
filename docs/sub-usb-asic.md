# USB ASIC and link assist

*TI-84 Plus OS 2.55MP — feature deep dive.*

This page covers the OS-visible USB/link-assist hardware interface: the Z80 I/O ports the ROM uses,
the byte FIFO path used by the link layer, and the places where `_LinkXferOP` chooses USB before
falling back to the 2.5 mm link. It complements [Link / data transfer](sub-link-transfer.md), which
covers the TI link packet protocol and variable-transfer state machine.

The full USB controller is broader than the variable-transfer path, but OS 2.55MP does expose enough
of it to map the public USB entry points, the link-assist byte path, and the interrupt/event bridge.
This page is ROM-grounded: the confirmed claims below come from OS 2.55MP disassembly/decompilation
and cite the address ranges that show them. External WikiTI names are used only as orientation where
noted, not as proof.

## ROM-grounded surface

The ROM shows four transport-facing surfaces:

| Layer | Port range | Role |
|-------|------------|------|
| Legacy link | `0x00` | 2.5 mm tip/ring open-collector byte path. [confirmed: `3C:6C99`, `3C:6CF3`] |
| Link-assist FIFO | `0x08`–`0x0D` | Hardware byte send/receive assist used below `_SendAByte` and `_RecAByteIO`. [confirmed: `3C:6BB1`–`6D53`] |
| USB line / interrupt gates | `0x4D`, `0x55`, `0x56` | Line-state and event/status gates used before and during link handling. [confirmed: `3C:4E4A`, `00:006F`] |
| USB controller / endpoints | `0x4A`–`0x5B`, `0x80`–`0xA2` | Page-35 USB host/device stack, including setup, endpoint FIFOs, callbacks, and data transfer. [confirmed: `35:4031`–`5B9B`] |

In the variable-transfer code, the OS mostly treats USB as a transport selector around the existing
TI link protocol. The packet layer still sends machine IDs, command bytes, checksums, ACK/NAK, and
EOT exactly as described in [sub-link-transfer.md](sub-link-transfer.md). The hardware difference is
below that packet layer: bytes go through the assist FIFO when the ASIC path is enabled, and through
port `0x00` bit-banging otherwise. [confirmed]

## Observed port map [confirmed unless marked]

| Port | Observed use in OS 2.55MP | Evidence |
|------|---------------------------|----------|
| `0x02` | Hardware/model gate before using assist paths. The link code tests bit 7 before touching ports `0x08`–`0x0D`. | `3C:6C82`, `3C:6CB8`, `3C:6D15` |
| `0x08` | Link-assist control/idle latch. The OS writes `0x80` when clearing an inactive/error-free assist state, and `0x00` when marking the assist state active. | `OUT (0x08)` at `3C:6C4D`/`6C50`, `3C:6D48`, `3C:6D5B` |
| `0x09` | Link-assist status on reads. Bit 5 is TX-ready; bit 6 is a transmission/error condition; bit 4 marks a received byte. Masks `0x19`, `0x58`, and `0x99` are used as error/activity predicates. On writes, the OS setup value `0x97` matches WikiTI's CPU-speed-0 signaling-rate register. | `3C:6BB6`–`6BC5`, `3C:444A`, `3C:6BFA`, `3C:6CCE`, `3C:6D33`; WikiTI port `09` |
| `0x0A` | Assist receive/data register on reads; the confirmed receive path reads the byte here. On writes, the OS setup value `0xB4` matches WikiTI's CPU-speed-1 signaling-rate register. Tilem models reads as "last received byte" and stores writes as opaque assist state. | `3C:6C20`, `3C:6C2B`, `3C:6C39`; WikiTI port `0A`; Tilem `x4_io.c` |
| `0x0B`, `0x0C` | Assist signaling-rate configuration for CPU speed modes 2 and 3, initialized with `0xB4`. The ROM byte-transfer path writes them during setup but does not read them back. Tilem stores the writes without emulating timing from the values. | `3C:6C3D`, `3C:6C3F`; WikiTI ports `0B`/`0C`; Tilem `x4_io.c` |
| `0x0D` | Assist TX FIFO/data register. `_SendAByte` writes the outgoing byte here after port `0x09` bit 5 becomes set. | `3C:6BBC`–`6BBF` |
| `0x20` | CPU speed bit used to select assist/link wait-loop reloads. The send timeout uses `0xFFFF` when bit 0 is set and `0x6800` when clear. | `3C:6BCC`, `3C:6C8B`, `3C:6CC1` |
| `0x4C` | USB controller handshake/status byte. The page-35 stack compares it with `0x5A`/`0x1A` and `0x12`/`0x52`, and clears or primes it with `0x00`/`0x08` during setup. Tilem returns `0x22` to make the calc see no attached USB peer. | `35:42B7`, `35:42F6`, `35:403C`, `35:40E6`; Tilem `x4_io.c` |
| `0x4D` | USB line-state gate. `_LinkXferOP` samples bits 5 and 6 before the page-0 bjump at `ram:2E0B`, which targets `35:4280`. Page-35 handlers also branch on bits 0, 1, 4, 5, 6, and 7. Tilem returns `0xA5` to emulate "USB disconnected." | `3C:4E4A`–`4E6F`, `35:42BF`, `35:4B6A`–`4B9F`; Tilem `x4_io.c` |
| `0x55` | USB interrupt status, active-low in the low five bits. The IM1 dispatcher tests `(in(0x55) ^ 0xFF) & 0x1F` first. | `00:006F`–`0075` |
| `0x56` | USB line-event bitmap used by the IM1 dispatcher after port `0x55` reports USB activity. Bits 4, 5, 6, 7, and 1 dispatch to page-35 handlers through page-0 bjumps. | `00:0085`–`00AE`, `00:0113`–`0127` |
| `0x57`, `0x5B`, `0x4A`, `0x54` | USB controller control/ack registers used by page-35 setup and event handlers. The ROM confirms values such as `0x10`, `0x20`, `0x22`, `0x50`, `0x80`, `0x90`, `0x93` on `0x57`, `0x00`/`0x01` on `0x5B`, `0x20` on `0x4A`, and `0x02`/`0x44`/`0xC4` on `0x54`. | `35:4038`–`4060`, `35:42C5`–`42EA`, `35:4B6A`–`4C14` |
| `0x80`–`0xA2` | Endpoint/status/FIFO region used by the public USB API. Examples: `_SendUSBData` writes 64-byte chunks to `0xA2`; `_RequestUSBData` reads 8-byte records from `0xA1`; setup/config paths write descriptor bytes through `0xA0` and use selector/status ports `0x8E`, `0x8F`, `0x91`, `0x94`, and `0x98`. | `35:4DD3`, `35:470B`, `35:48BA`, `35:48F8` |

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
assist helpers around `3C:6BF4`–`6D40`.

The hardware-facing receive loop waits until port `0x09 & 0x58` becomes nonzero. In the confirmed
path:

- `0x40` (bit 6) is treated as a transmission/error condition.
- `0x10` (bit 4) is the "byte received" condition.
- `0x08` is an assist read-busy/activity bit: it wakes the wait loop, but the byte is not accepted
  until bit 4 or an error/status bit is also present. Tilem names the corresponding state
  `TILEM_LINK_ASSIST_READ_BUSY`.
- When the receive condition is accepted, the byte is read from port `0x0A` into `C`.
- The status masks `0x19` and `0x99` select error/activity cases before the code resets or re-arms
  the assist latch through port `0x08`.

`lnk_rec_status` also uses the sentinel byte `0xE0`: callers pass it for a nonblocking/probe style
receive check. If the caller requires a byte and the status path reports anything else, the code
raises `E_LnkErr` through `_JError(0x9F)`. [confirmed]

The assist reset/enable sequence at `3C:6C3B` writes:

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

The sequence proves the ports touched and the RAM flag used by the OS. WikiTI names these writes as
link-assist signaling-rate setup values for CPU speed modes 0-3: ports `0x09`, `0x0A`, `0x0B`, and
`0x0C` correspond to speed modes 0, 1, 2, and 3 respectively. Its field description says bits 5-7
select the link-assist clock divisor as `2^n`, with `111b` halting the assist, and bits 0-4 select
the inter-bit wait. Under that decoding, the ROM constants are:

| Port | CPU speed mode | Value | Divisor field | Wait field |
|------|----------------|-------|---------------|------------|
| `0x09` | 0, 6 MHz | `0x97` (`10010111b`) | `100b` -> divide by 16 | `0x17` |
| `0x0A` | 1 | `0xB4` (`10110100b`) | `101b` -> divide by 32 | `0x14` |
| `0x0B` | 2, 15 MHz duplicate 1 | `0xB4` (`10110100b`) | `101b` -> divide by 32 | `0x14` |
| `0x0C` | 3, 15 MHz duplicate 2 | `0xB4` (`10110100b`) | `101b` -> divide by 32 | `0x14` |

Direct ROM scans found the page-3C byte-transfer path writing those constants during setup, then
using the read side of `0x09` for status and `0x0A` for received bytes. Tilem agrees on the runtime
status/data behavior and stores ports `0x09`–`0x0C`, but its `x4`/`xn`/`xs`/`xz` models label the
write-side settings as unknown or timeout-like and do not derive link timing from `0x97`/`0xB4`.
[ROM-confirmed writes; WikiTI field names; Tilem storage-only]

## USB selection in `_LinkXferOP` [confirmed]

`_LinkXferOP` (`3C:4DD2`, bcall ID `0x50FB`) is the OS entry that sends a silent link request and
prefers the USB path when its mode flags ask for it. `ti83plus.inc` names bcall `0x50FB`
`_GetVarCmdUSB`, the USB variant of `_GetVarCmd` (`0x4A11`) / `_SendVarCmd` (`0x4A14`); that public
name matches the USB-first variable-command behavior decoded here, while `_LinkXferOP` is the
inferred name for the page-3C body. The ROM-confirmed setup is:

- `OP1` holds the variable type/name.
- `sndRecState` (`0x8672`) is `0x15` for DATA-style receive.
- `IY+0x1B` bit 0 selects USB-first behavior; reset means use the link port path.

The OS confirms that contract in the `4E35`–`4E73` gate:

1. If `IY+0x1B` bit 0 is clear, it skips USB probing and sends through the ordinary link path.
2. If bit 0 is set and either `IY+0x1B` bit 5 or bit 6 asks for USB handling, it reads port `0x4D`.
3. If port `0x4D` bit 5 is clear, or bit 5 is set and bit 6 is clear, the OS sets `IY+0x1B` bit 5
   and calls the page-0 bjump at `ram:2E0B`.
4. `ram:2E0B` dispatches via inline descriptor `80 42 75`, which is target `35:4280` after the
   normal page mask. That routine calls the public `_InitUSBDevice` body at `35:42B0`, then accepts
   only TI vendor `0x0451` with product IDs `0xE003`, `0xE008`, or `0xE00F`; success returns carry
   clear, while mismatch or init failure returns carry set.
5. On carry set, `_LinkXferOP` clears `IY+0x1B` bit 5 and continues into `lnk_send_data_867d`
   (`3C:4055`), which
   sends the same TI link request/VAR/DATA packets described in the link-transfer page.
6. On carry clear, the USB path remains selected and the OS calls the bjump reached through
   `ram:3FC3` with `A=0x0A`.

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
through `(IY+0x09)` bit 3 and `port 0x07 == 0x81` before using the USB/timer event path. The page-0
bjumps resolve as:

| `port 0x56` bit | Page-0 dispatch | Page-35 target | Observed role |
|-----------------|-----------------|----------------|---------------|
| 4 | `00:0122` -> `ram:3FA5` | `35:4B6A` | line/event settle path; waits on `0x4D` bits 7 and 0, writes `0x57 = 0x22`. |
| 5 | `00:0127` -> `ram:3FAB` | `35:4B9F` | event clear/re-arm path; may clear `0x4C`, reset `USBFlag2` bit 6, and write `0x57 = 0x50/0x93`. |
| 6 | `00:0113` -> `ram:3F93` | `35:40B2` | USB setup path; sets `IY+0x1B` bit 5, initializes controller state, and waits for `0x4C = 0x1A/0x5A`. |
| 7 | `00:0118` -> `ram:3F99` | `35:4C14` | cleanup/reset path; clears `0x5B`, resets `USBFlag2` bit 0, and jumps through the common controller reset. |
| 1 | `00:011D` -> `ram:3F9F` | `35:4031` | alternate setup path; waits for `0x4C = 0x12/0x52` and uses endpoint/status ports `0x87`/`0x89`/`0x8B`. |

[confirmed]

The timer/idle side of the same handler also bridges to the assist path. At `ram:01B1` it calls
`ram:1837` (`IN A,(0x2); AND 0x80; XOR 0x80`), the same hardware-model gate used elsewhere before assist-port access. On the legacy path it checks `port 0x00 & 0x03`; on the assist
path it checks `port 0x09 & 0x18`. If either assist bit is set, it reloads `0x9C86 = 0xFA`, pulses
port `0x08` with `0x80` then `0x00`, sets `IY+0x3E` bit 0, and calls the common link activity hook
at `ram:3FD5`. [confirmed: `00:01B1`–`01DB`]

For application code, this means a custom interrupt handler that does not chain to the OS handler
must account for port `0x55`/`0x56` activity itself and then either reproduce the relevant page-35
event handling or deliberately leave USB disabled. The OS still acknowledges the legacy interrupt
mask through port `0x03` on exit, but the USB event work is selected by `0x55`/`0x56` and page-35
controller ports, not by a writeable `0x56` mask. [confirmed]

## Public USB API bodies [confirmed]

The public USB names in `ti83plus.inc` are backed by the main page-3B bcall table for the `0x50xx`,
`0x52xx`, and `0x53xx` IDs. The table entries are `addr_lo, addr_hi, page`; page bytes like `0x75`
mask to physical page `0x35`.

| Bcall ID | Public name | Body | ROM-grounded behavior |
|----------|-------------|------|-----------------------|
| `50F2` | `_SendUSBData` | `35:4DD3` | Sends from `HL` with byte count in `DE`; stores progress at `0x9C7E`/`0x9C81` and writes 64-byte chunks to port `0xA2`. |
| `50F5` | `_AppGetCBLUSB` | `3B:54C7` | Sets `IY+0x1B` bit 1, clears bit 2, then reaches `_GetVarCmdUSB`. |
| `50F8` | `_AppGetCalcUSB` | `3B:54F0` | At `3B:54DE` clears `IY+0x16` bit 0 and sets `sndRecState`=0x15, then `bcall 0x50FB` (shared get-var path). |
| `50FB` | `_GetVarCmdUSB` / `_LinkXferOP` | `3C:4DD2` | USB-first variable command wrapper described above. |
| `5254` | `_InitUSBDeviceCallback` | `35:4696` | Initializes device mode, stores callback page/address at `0x9C13`/`0x9C14`, and returns `0xFC`–`0xFF` style error bytes with carry set on failure. |
| `5257` / `5311` | `_KillUSBDevice` / `_RecycleUSB` | `35:46FC` / `35:5B9B` | Clears callback state and recycles through the same cleanup path. |
| `525A` | `_SetUSBConfiguration` | `35:470B` | Builds an 8-byte request block at `0x9C29` and writes it through port `0xA0`. |
| `525D` / `5260` | `_RequestUSBData` / `_StopReceivingUSBData` | `35:48BA` / `35:48D1` | Stores or clears the receive-buffer descriptor at `0x9C1E`; receive records are read from port `0xA1`. |
| `528A` / `528D` | `_EnableUSBHook` / `_DisableUSBHook` | `3B:7DC6` / `3B:7DD1` | Stores `USBActivityHookPtr`/page at `0x9BD4`/`0x9BD6` and toggles `(IY+0x3A)` bit 0. |
| `5290` | `_InitUSBDevice` | `35:42B0` | Main controller/device initialization path; uses `0x4C`/`0x4D` line handshakes and endpoint ports `0x80`–`0x9B`. |
| `5293` | `_KillUSBPeripheral` | `35:59CF` | Peripheral teardown; sets controller state `0x9C28 = 5` and manipulates ports `0x54`/`0x81`. |
| `530B` | `_ToggleUSBSmartPadInput` | `35:5B84` | Sets or clears bit 3 in `0x9C75` according to `A == 1`. |
| `530E` | `_IsUSBDeviceConnected` | `35:5B92` | Preserves `A`; returns flags from `IN (0x81) & 0x40` (bit 6). (The `.inc` comment guesses `bit 4,(81h)`, but the body actually masks bit 6.) |

## How to use it in code [grounded by OS calls]

Prefer the OS entry points unless the program is deliberately writing a USB driver:

| Need | OS surface | ROM support |
|------|------------|-------------|
| Send or request a variable over USB/link | `_GetVarCmdUSB`/`_LinkXferOP` (`50FB` -> `3C:4DD2`) or `_SendVarCmd` (`4A14` -> `3C:4EDD`) | Packet engine and USB-selection gate confirmed on page `3C`. `0x50FB` is `_GetVarCmdUSB` in `ti83plus.inc`. |
| Send one byte on the active link transport | `_SendAByte` (`4EE5` -> `3C:420D`) | Assist branch writes `C` to port `0x0D` after port `0x09` bit 5. |
| Receive one byte on the active link transport | `_RecAByteIO` (`4F03` -> `3C:443F`) | Status path checks port `0x09` and reads port `0x0A` on the assist path. |
| Use the raw assist FIFO | Poll port `0x09` bit 5, then write the byte to port `0x0D`; for receive, observe port `0x09` bit 4/error bits and read port `0x0A`. | Confirmed as an OS pattern, but not a complete public API. |

The raw FIFO sequence is only the byte layer. A working transfer still needs the packet layer:
machine ID, command, length, payload checksum, ACK/NAK, and EOT. That framing is documented in
[sub-link-transfer.md](sub-link-transfer.md#3-packet-framing--the-ti-link-protocol-confirmed).

Practical rules:

- Set up `IY+0x1B` consistently before calling `_LinkXferOP`. Bit 0 is the USB-first selector.
- Do not write ports `0x08`–`0x0D` while the OS link engine is active; the OS keeps state in
  `IY+0x3E` bit 0, `0x9C86`, and `0x9CAC`.
- If a custom interrupt handler is installed, either chain to the OS handler or service the same
  source gates. The OS itself expects to handle port `0x55`/`0x56` events.
- Use the public USB bcalls for endpoint/controller work. The raw page-35 endpoint ports are
  mapped well enough to identify the FIFOs and state variables, but their bit-level protocol is not
  a stable public API.

## Limits

- The ROM calls `ram:2E0B`, a `cross_page_jump` thunk to `35:4280`. Its
  carry-clear/carry-set result is decoded above.
- The public `0x50xx`/`0x52xx`/`0x53xx` USB APIs are mapped to bodies and sampled above. The boot-page
  `0x8xxx` USB names (`_InitUSB`, `_KillUSB`, `_AttemptUSBOSReceive`, `_ReceiveOS_USB`,
  `_USBErrorCleanup`) remain part of the repository-wide `0x8xxx` bcall-table reconciliation problem,
  not a page-3C link-transfer gap.
- The ROM does not give bit names for every page-35 controller register, and Tilem does not model
  physical timing from the assist setup values. This page therefore treats the `0x97`/`0xB4` field
  names as WikiTI-supported timing configuration, while ROM-confirmed claims remain limited to the
  written constants, status/data port use, comparisons, branch bits, RAM state, and FIFO direction.
