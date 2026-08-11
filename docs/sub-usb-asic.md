# USB ASIC and link assist

This page covers the OS-visible USB/link-assist hardware interface: the Z80 I/O ports the ROM uses,
the byte FIFO path used by the link layer, and the places where `link_xfer_op` chooses USB before
falling back to the 2.5 mm link. It complements [Link / data transfer](sub-link-transfer.md), which
covers the TI link packet protocol and variable-transfer state machine.

The full USB controller is broader than the variable-transfer path, but OS 2.55MP does expose enough
of it to map the public USB entry points, the link-assist byte path, and the interrupt/event path.
This page is ROM-grounded: the confirmed claims below come from OS 2.55MP disassembly/decompilation
and cite the address ranges that show them. External WikiTI names are used only as orientation where
noted, not as proof.

## ROM-grounded surface

The ROM shows four transport-facing surfaces:

| Layer | Port range | Role |
|-------|------------|------|
| Legacy link | `0x00` | 2.5 mm raw bit-banged byte path; see [Two-wire link port hardware](link-port-hardware.md). [confirmed] |
| Link-assist FIFO | `0x08`–`0x0D` | Hardware byte send/receive assist used below `_SendAByte` and `_RecAByteIO`. [confirmed] |
| USB line / interrupt gates | `0x4D`, `0x55`, `0x56` | Line-state and event/status gates used before and during link handling. [confirmed] |
| USB controller / endpoints | `0x4A`–`0x5B`, `0x80`–`0xA2` | Page-35 USB host/device stack, including setup, endpoint FIFOs, callbacks, and data transfer. [confirmed] |

In the variable-transfer code, the OS mostly treats USB as a transport selector around the existing
TI link protocol. The packet layer still sends machine IDs, command bytes, checksums, ACK/NAK, and
EOT exactly as described in [sub-link-transfer.md](sub-link-transfer.md). The hardware difference is
below that packet layer: bytes go through the assist FIFO when the ASIC path is enabled, and through
port `0x00` bit-banging otherwise. [confirmed]

## Observed port map [confirmed]

| Port | Observed use in OS 2.55MP | Evidence |
|------|---------------------------|----------|
| `0x02` | Hardware/model gate before using assist paths. The link code tests bit 7 before touching ports `0x08`–`0x0D`. | `3C:6C82`, `3C:6CB8`, `3C:6D15` |
| `0x08` | Link-assist control/idle latch. The OS writes `0x80` when clearing an inactive/error-free assist state, and `0x00` when marking the assist state active. | `OUT (0x08)` at `3C:6C4D`/`6C50`, `3C:6D48`, `3C:6D5B` |
| `0x09` | Link-assist status on reads. Bit 5 is TX-ready; bit 6 is a transmission/error condition; bit 4 marks a received byte. Masks `0x19`, `0x58`, and `0x99` are used as error/activity predicates. On writes, the OS setup value `0x97` matches WikiTI's CPU-speed-0 signaling-rate register. | `3C:6BB6`–`6BC5`, `3C:444A`, `3C:6BFA`, `3C:6CCE`, `3C:6D33`; WikiTI port `09` |
| `0x0A` | Assist receive/data register on reads; the confirmed receive path reads the byte here. On writes, the OS setup value `0xB4` matches WikiTI's CPU-speed-1 signaling-rate register. TilEm models reads as "last received byte" and stores writes as opaque assist state. | `3C:6C20`, `3C:6C2B`, `3C:6C39`; WikiTI port `0A`; TilEm `x4_io.c` |
| `0x0B`, `0x0C` | Assist signaling-rate configuration for CPU speed modes 2 and 3, initialized with `0xB4`. The ROM byte-transfer path writes them during setup but does not read them back. TilEm stores the writes without emulating timing from the values. | `3C:6C3D`, `3C:6C3F`; WikiTI ports `0B`/`0C`; TilEm `x4_io.c` |
| `0x0D` | Assist TX FIFO/data register. `_SendAByte` writes the outgoing byte here after port `0x09` bit 5 becomes set. | `3C:6BBC`–`6BBF` |
| `0x20` | CPU speed bit used to select assist/link wait-loop reloads. The send timeout uses `0xFFFF` when bit 0 is set and `0x6800` when clear. | `3C:6BCC`, `3C:6C8B`, `3C:6CC1` |
| `0x4B` | Controller-side setup control. Reset paths write `0x00`, then conditionally write `0x20`; another setup path writes `0x20` before waiting for port `0x4C = 0x5A`. WikiTI calls this USB power control, but describes its bit meanings as mostly speculative. | `35:4C69`, `35:4C76`–`4C80`, `35:59AB`; duplicated at `2F:59B6`, `2F:59C3`–`59CD`; WikiTI port `4B` |
| `0x4C` | USB controller handshake/status byte. The page-35 stack compares it with `0x5A`/`0x1A` and `0x12`/`0x52`, and clears or primes it with `0x00`/`0x08` during setup. TilEm returns `0x22` to make the calc see no attached USB peer. | `35:42B7`, `35:42F6`, `35:403C`, `35:40E6`; TilEm `x4_io.c` |
| `0x4D` | USB line-state gate. `link_xfer_op` samples bits 5 and 6 before the page-0 bjump at `ram:2E0B`, which targets `35:4280`. Page-35 handlers also branch on bits 0, 1, 4, 5, 6, and 7. TilEm returns `0xA5` to emulate "USB disconnected." | `3C:4E4A`–`4E6F`, `35:42BF`, `35:4B6A`–`4B9F`; TilEm `x4_io.c` |
| `0x4F`, `0x50` | Unnamed setup controls used beside USB GPIO and line-state accesses. The ROM writes `0x27` to `0x50`. It then updates `0x4F` to `(old & 0xBF) | 0x88`, waits, and updates it to `old & 0x37`. The electrical and PHY effects are unknown. | `35:422D`–`424C`; duplicated at `2F:538A`–`53A9` |
| `0x55` | USB interrupt status, active-low in the low five bits. The IM1 dispatcher tests `(in(0x55) ^ 0xFF) & 0x1F` first. | `00:006F`–`0075` |
| `0x56` | USB line-event bitmap used by the IM1 dispatcher after port `0x55` reports USB activity. Bits 4, 5, 6, 7, and 1 dispatch to page-35 handlers through page-0 bjumps. | `00:0085`–`00AE`, `00:0113`–`0127` |
| `0x57`, `0x5B`, `0x4A`, `0x54` | USB controller control/ack registers used by page-35 setup and event handlers. The ROM confirms values such as `0x10`, `0x20`, `0x22`, `0x50`, `0x80`, `0x90`, `0x93` on `0x57`, `0x00`/`0x01` on `0x5B`, `0x20` on `0x4A`, and `0x02`/`0x44`/`0xC4` on `0x54`. | `35:4038`–`4060`, `35:42C5`–`42EA`, `35:4B6A`–`4C14` |
| `0x5A` | Presentation-link setup writes bit 0 and reads the port back. The next instruction replaces the read value, so this routine does not test the result. It then configures indexed endpoint 2. | `35:58B2`–`58DE` |
| `0x80`–`0xA2` | Endpoint/status/FIFO region used by the public USB API. Examples: `_SendUSBData` writes 64-byte chunks to `0xA2`; `_RequestUSBData` reads 8-byte records from `0xA1`; setup/config paths write descriptor bytes through `0xA0` and use selector/status ports `0x8E`, `0x8F`, `0x91`, `0x94`, and `0x98`. | `35:4DD3`, `35:470B`, `35:48BA`, `35:48F8` |

The endpoint receive helper at `35:4FA1` accepts a count in `B`, caps it at 64
bytes, and reads port `0xA1` in the loop at `35:500E`. The USB
receive-to-memory body at `36:40E7` reaches it through the page-0 bjump stub at
`00:2E17`. For a Flash-window destination, `36:413A` caps the chunk at 16
bytes, receives it into `0x983A`, and calls the page-`3C` Flash-staging
dispatcher in mode `3` at `36:415C`. RAM destinations use chunks of up to 64
bytes and skip that Flash flush. [confirmed]

The project-local `tools/ports.txt` names the observed assist, USB-control, and
USB-interrupt ports so future Ghidra rebuilds show the same surface in the
database. Neutral labels retain `Unknown` for ports `0x4F` and `0x50` because
the ROM does not identify their signals. The file also applies the FDRC-family
names below to ports `0x80`–`0xA2`. Those names identify the register layout;
they do not prove the exact ASIC implementation or its electrical behavior.

## Transceiver and enable-timer ports without confirmed ROM control flow

WikiTI assigns low-level USB meanings to three ports that OS 2.55MP does not
use through a confirmed I/O instruction:

| Port | WikiTI description | Evidence limit |
|------|--------------------|----------------|
| `0x49` | Raw USB-transceiver status, including proposed D+ and D− bits 1 and 2 | The page calls several other bits only “something” or “possible.” No ROM read, emulator handler, datasheet, or physical sample confirms the bit map. [hypothesis] |
| `0x51` | Delay between starting a separate 48 MHz crystal and enabling USB, counted in two-tick units from 32.768 kHz | No ROM write or cited primary source establishes the clock, unit, or enable effect. [hypothesis] |
| `0x52` | Charge-pump enable timer with timing like port `0x51` | The public description says only that it has “something to do” with charge-pump timing. [hypothesis] |

The complete immediate-port and conservative literal-`C` scan initially
reports six candidates for these ports. Raw descriptor decoding accounts for
four of them. `tools/analyze_rom_io.py` attaches this classification to each
report and `--exclude-descriptors` removes the four structural overlaps:
[confirmed]

| Linear candidate | Actual bytes and role |
|------------------|-----------------------|
| `00:3EDC` — apparent `OUT (0x51),A` | Inline target `37:51D3`, page byte `0x77`, after `CALL 2B09h`; this is a cross-page call descriptor. |
| `37:46D7` — apparent `IN A,(0x52)` | Low and high bytes `DB 52` of bcall ID `52DB`, `_ResetGraphSettings`. |
| `39:583F` — apparent `OUT (0x51),A` | Low and high bytes `D3 51` of unnamed bcall ID `51D3`. |
| `3B:620A` — apparent `IN A,(0x49)` | Low and high bytes `DB 49` of bcall ID `49DB`, which resolves to `36:7DA9`. |

The remaining apparent port-`0x49` instruction at `01:4304` and
port-`0x51` instruction at `3B:4F45` lie in table-shaped byte regions. Neither
has a direct page-local control-flow reference, and neither has trace evidence.
The complete [ROM I/O candidate audit](asic-status-gpio.md#complete-rom-io-candidate-audit)
also finds no containing Ghidra function or xref for either location. They are
reviewed data decodes rather than I/O evidence. The scan confirms no OS 2.55MP
transaction for ports `0x49`, `0x51`, or `0x52`.
The separate raw `ED`-opcode census covers register and block I/O without
assuming that `C` can be propagated through control flow. Its only two aligned
instructions access RTC ports `0x48` and `0x44`, so it adds no hidden USB-port
transaction. [confirmed]

TilEm, Wabbitemu, and MAME omit all three ports from their TI-84 Plus USB
handlers. Their omission cannot establish physical absence or reset values.
The read-only [USB control snapshot](hardware-probes.md#usb-control-snapshot)
records these ports together with the adjacent low-USB controls on a physical
calculator. No exported result has been recorded. [standard] for emulator
coverage; [confirmed] for the assembled probe; [hypothesis] for pending
physical values.

## Presentation-link mirroring setup

The helper at `35:58B2` sets `IY+0x41` bit 0, writes `0x01` to port
`0x5A`, and reads the port back. `LD A,0x02` immediately replaces the read
value, so the helper does not branch on or retain it. The remaining writes
select indexed endpoint 2 and initialize its transmit registers: [confirmed]

```z80
; 35:58B2
SET 0,(IY+41h)
LD A,01h
OUT (5Ah),A
IN A,(5Ah)       ; discarded by the following LD
LD A,02h
OUT (8Eh),A
LD A,22h
OUT (98h),A
LD A,48h
OUT (91h),A
LD A,02h
OUT (90h),A
XOR A
OUT (87h),A
OUT (89h),A
OUT (8Bh),A
OUT (5Bh),A
LD A,10h
OUT (92h),A
IN A,(92h)
NOP
NOP
NOP
RET
```

The port-`0x8E` index and port-`0x98` endpoint-type interpretation follow the
FDRC-family match below. The exact writes and selected index are [confirmed];
the imported register names remain [hypothesis].

A static call scan finds one direct caller at `35:4481`. It calls this helper,
then `35:3EF1`, then `35:58DF`. The last routine performs 64 iterations over
LCD ports `0x10` and `0x11`: it writes commands, reads 12 data bytes, and
writes those bytes back. This control flow ties the port-`0x5A` setup to LCD
traffic and presentation mode, but the ROM alone does not expose what appears
on the USB wire. [confirmed]

WikiTI calls port `0x5A` the presentation-link mirroring enable. It reports
that bit 0 mirrors writes to LCD ports `0x10` and `0x11` as two-byte packets on
outgoing bulk endpoint 2, and that the feature works only in host mode. The
page also labels part of its packet interpretation untested. No cited vendor
datasheet or physical capture establishes the packet format or host-mode
restriction, so those details remain [hypothesis].

TilEm, Wabbitemu, and MAME do not implement port `0x5A` or a connected
endpoint-2 transfer for this calculator. Emulator execution therefore cannot
validate the mirroring behavior. The port accesses above were regenerated from
the retail OS 2.55MP bytes with `tools/analyze_rom_io.py`; the surrounding
instructions come from the same page through `tools/z80_disassembly.py`.
Physical validation requires a presentation-link adapter or a controlled USB
capture. [standard] for the emulator implementations; [confirmed] for the ROM
sequence.

## Mentor FDRC register-family match [hypothesis]

The ROM-visible accesses in the controller region at `0x80`–`0x9B` align with the Mentor Graphics
MUSBFDRC register file. A Mentor-authored 2004 `mu_fdrdf.h` header assigns offsets `0x00`–`0x1F`
in the same order and places the non-AHB FIFO window at offset `0x20`. The preserved header labels
itself proprietary; it is primary-origin source code in a third-party SDK tree, not a publicly
released TI ASIC specification. The independent VSF FDRC implementation reproduces the compact
ordering. Adding the candidate TI base port `0x80` produces the map below. [standard] for the two
external layouts; [hypothesis] for applying that identity to the TI ASIC.

The ROM does not contain a silicon identifier. Board-level identification remains open, so the
family identification remains [hypothesis].

| TI ports | FDRC names | ROM cross-check |
|----------|------------|-----------------|
| `0x80` | `FADDR` | The control-transfer path defers a device-address write until the status stage at `35:4630`. [confirmed] |
| `0x81` | `POWER` | Initialization polls bit 6 and later writes or modifies bits 0–3. The FDRC masks call these `VBUSVAL`, `ENSUSPEND`, `SUSPENDM`, `RESUME`, and `RESET`. [confirmed] for the operations; [hypothesis] for the imported bit names |
| `0x82`–`0x85` | `INTRTX1/2`, `INTRRX1/2` | The protocol handler reads transmit and receive endpoint-event bytes at `35:4D03` and `35:4D57`. [confirmed] |
| `0x86` | `INTRUSB` | Host setup waits for bit 4; the peripheral handler branches on bit 2 at `35:40A2` and `35:4CFE`. Those masks match FDRC `CONNECT` and `RESET`. [confirmed] for the branches; [hypothesis] for the event names |
| `0x87`–`0x8A` | `INTRTX1E/2E`, `INTRRX1E/2E` | Setup enables transmit events with `0xFF` at `35:407B` and receive endpoint events with `0x0E` at `35:4084`. [confirmed] |
| `0x8B` | `INTRUSBE` | The ROM uses masks including `0x05`, `0x21`, `0xA1`, and `0xF7`. FDRC defines the bits as suspend, resume, reset/babble, SOF, connect, disconnect, session request, and VBUS error. [confirmed] for the masks; [hypothesis] for the imported names |
| `0x8C`–`0x8D` | `FRAME1/2` | Initialization waits for the low frame byte to become nonzero at `35:411B` and `35:418D`. [confirmed] |
| `0x8E` | `INDEX` | Endpoint setup and transfer routines select a pipe before using the shared endpoint registers. [confirmed] |
| `0x8F` | `DEVCTL` | The ROM tests bit 7 for B-device state and bit 2 for host mode, then writes bit 0 to start a session. These are the FDRC `BDEVICE`, `HM`, and `SESSION` masks. [confirmed] for the operations; [hypothesis] for the imported names |
| `0x90`–`0x92` | `TXMAXP`, `CSR0`/`TXCSR1`, `CSR02`/`TXCSR2` | Endpoint 0 uses `CSR0`; nonzero indexed endpoints use the transmit CSR pair. The ROM writes bit 1 to launch endpoint-0 packets and bit 0 to launch nonzero-endpoint packets. [confirmed] |
| `0x93`–`0x97` | `RXMAXP`, `RXCSR1/2`, `COUNT0`/`RXCOUNT1/2` | Receive paths select an endpoint, test `RXCSR1` bit 0, read the count, drain the matching FIFO, and clear the ready condition. [confirmed] |
| `0x98`–`0x9B` | `TXTYPE`, `TXINTERVAL`/`NAKLIMIT0`, `RXTYPE`, `RXINTERVAL` | Host setup writes endpoint type/address and interval values before starting transfers. [confirmed] |
| `0x9C`–`0x9F` | `TXFIFO1/2`, `RXFIFO1/2`; `FIFOSIZE`/`CONFIGDATA` aliases at `0x9F` | These offsets complete the Mentor FDRC register file. A static page-`2F`/`35` scan found no resolved immediate or literal-`C` access, so the TI use of these registers remains [hypothesis]. |
| `0xA0`–`0xAF` | endpoint FIFOs 0–15 | Mentor's non-AHB macro maps endpoint $n$ to offset `0x20 + n`. The ROM confirms FIFO 0 at `0xA0`, FIFO 1 at `0xA1`, and FIFO 2 at `0xA2`; higher endpoints remain [hypothesis]. |

The FDRC ordering matters because the common HDRC/MUSB byte layout in Linux's Mentor/TI-copyrighted
driver header places several interrupt registers at different offsets. These offsets distinguish
the candidates:

| TI port | Relative offset | FDRC candidate | Common HDRC candidate | ROM cross-check |
|---------|-----------------|----------------|-----------------------|-----------------|
| `0x86` | `0x06` | `INTRUSB` | low byte of `INTRTXE` | The ROM waits on bit 4 and branches on bit 2. FDRC names these global connect and reset/babble events. [confirmed] for the operations; [hypothesis] for the names |
| `0x87` | `0x07` | `INTRTX1E` | high byte of `INTRTXE` | Setup writes `0xFF`. Both candidates make this byte an enable register, although they assign it to different endpoint ranges. This access alone does not distinguish the layouts. [confirmed] |
| `0x89` | `0x09` | `INTRRX1E` | high byte of `INTRRXE` | Setup writes `0x0E`, matching receive endpoints 1–3 in the FDRC low-byte register. [confirmed] for the value; [hypothesis] for the imported endpoint names |
| `0x8B` | `0x0B` | `INTRUSBE` | `INTRUSBE` | Both layouts agree at this offset; the write masks do not distinguish them. [confirmed] |
| `0x8F` | `0x0F` | `DEVCTL` | `TESTMODE` | The ROM tests bits 7 and 2 and sets bit 0. FDRC names them B-device, host mode, and session. [confirmed] for the operations; [hypothesis] for the names |

The combination at `0x86`, `0x89`, and `0x8F` favors the compact FDRC ordering over the common
HDRC map. It does not identify the surrounding TI ASIC or its PHY. Linky commit `89586b0`
independently calls this block MUSBFDRC and performs the same initialization sequence. Linky is
calculator software evidence, not a vendor specification. [hypothesis]

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
6BB2: CALL 6D4Fh        ; clear/prepare assist I/O latch
6BB5: CALL 6BD2h        ; seed 9CAC from CPU speed
6BB8: CALL 6BD2h

6BBB: LD   A,0FAh
6BBD: LD   (9C86h),A    ; inner retry reload
6BC0: IN   A,(09h)
6BC2: BIT  5,A
6BC4: JR   Z,6BCAh      ; TX not ready
6BC6: LD   A,C
6BC7: OUT  (0Dh),A      ; write byte to assist FIFO
6BC9: RET

6BCA: CALL 6BE4h        ; decrement 9CAC, Z means keep polling
6BCD: JR   Z,6BBBh
6BCF: JP   4434h        ; link timeout/error path
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
  until bit 4 or an error/status bit is also present. TilEm names the corresponding state
  `TILEM_LINK_ASSIST_READ_BUSY`.
- When the receive condition is accepted, the byte is read from port `0x0A` into `C`.
- The status masks `0x19` and `0x99` select error/activity cases before the code resets or re-arms
  the assist latch through port `0x08`.

The assist receiver returns a normal byte in `C` with `A=0`; the port-`0x09`
bit-6 path returns `A=1`. `lnk_rec_status` compares the returned `C` with
`0xE0`, and raises `E_LnkErr` when `A=1` and `C != 0xE0`. `_RecAByteIO`
preserves no caller-supplied `A`. The exceptional `0xE0` is the TI-Keyboard
prefix, not an assist-register sentinel: `_KeyboardGetKey = 50E9`, body
`3C:6D5E`, expects it before a deliberate DBUS error delimiter, command `0x01`,
and a final data byte. The ROM-confirmed decoder and the independently sourced
peripheral description are separated in
[Two-wire link port hardware](link-port-hardware.md#the-ti-keyboard-error-delimiter).
[confirmed] for the receive path and decoder; [standard] for the reported
physical-keyboard transmitter sequence.

The assist reset/enable sequence at `3C:6C3B` writes:

```z80
OUT (0x00),0x00
OUT (0x09),0x97
OUT (0x0A),0xB4
OUT (0x0B),0xB4
OUT (0x0C),0xB4
OUT (0x08),0x80
OUT (0x08),0x00
IN  A,(0x09)
SET 0,(IY+0x3E)
```

The sequence proves the ports touched and the RAM flag used by the OS. WikiTI names these writes as
link-assist signaling-rate setup values for CPU speed modes 0-3: ports `0x09`, `0x0A`, `0x0B`, and
`0x0C` correspond to speed modes 0, 1, 2, and 3 respectively. Its field description says bits 5-7
select the link-assist clock divisor as `2^n`, with `111b` halting the assist, and bits 0-4 select
the inter-bit wait. Under that decoding, the ROM constants are:

| Port | CPU speed mode | Value | Divisor field | Wait field |
|------|----------------|-------|---------------|------------|
| `0x09` | 0, 6 MHz | `0x97` (`10010111b`) | `100b` → divide by 16 | `0x17` |
| `0x0A` | 1 | `0xB4` (`10110100b`) | `101b` → divide by 32 | `0x14` |
| `0x0B` | 2, 15 MHz duplicate 1 | `0xB4` (`10110100b`) | `101b` → divide by 32 | `0x14` |
| `0x0C` | 3, 15 MHz duplicate 2 | `0xB4` (`10110100b`) | `101b` → divide by 32 | `0x14` |

Direct ROM scans found the page-3C byte-transfer path writing those constants during setup, then
using the read side of `0x09` for status and `0x0A` for received bytes. TilEm agrees on the runtime
status/data behavior and stores ports `0x09`–`0x0C`, but its `x4`/`xn`/`xs`/`xz` models label the
write-side settings as unknown or timeout-like and do not derive link timing from `0x97`/`0xB4`. [confirmed]

## USB selection in `link_xfer_op` [confirmed]

`link_xfer_op` (`3C:4DD2`, bcall ID `0x50FB`) is the OS entry that sends a silent link request and
prefers the USB path when its mode flags ask for it. `ti83plus.inc` names bcall `0x50FB`
`_GetVarCmdUSB`, the USB variant of `_GetVarCmd` (`0x4A11`) / `_SendVarCmd` (`0x4A14`); that public
name matches the USB-first variable-command behavior decoded here, while `link_xfer_op` is the
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
5. On carry set, `link_xfer_op` clears `IY+0x1B` bit 5 and continues into `lnk_send_data_867d`
   (`3C:4055`), which
   sends the same TI link request/VAR/DATA packets described in the link-transfer page.
6. On carry clear, the USB path remains selected and the OS calls the bjump reached through
   `ram:3FC3` with `A=0x0A`.

This makes `link_xfer_op` a USB-first wrapper around the existing link transfer engine. It does not
replace the packet format. The transport choice happens before `_SendAByte` writes each byte through
the assist FIFO or falls back to port `0x00`. [confirmed]

## Interrupt integration [confirmed]

The IM1 dispatcher (`ram:006F`) tests the USB interrupt status before the separate legacy controller:

```z80
IN A,(0x55)
XOR 0xFF
AND 0x1F
```

If no low-five-bit USB source is active, the handler falls through to the other interrupt work. If a
USB source is active, it reads port `0x56` and branches on event bits. In the visible dispatcher,
bits 4, 5, 6, 7, and 1 are routed to subhandlers; the surrounding code also checks 84+ hardware mode
through `(IY+0x09)` bit 3 and `port 0x07 == 0x81` before using the USB/timer event path. The page-0
bjumps resolve as:

| `port 0x56` bit | Page-0 dispatch | Page-35 target | Observed role |
|-----------------|-----------------|----------------|---------------|
| 4 | `00:0122` → `ram:3FA5` | `35:4B6A` | line/event settle path; waits on `0x4D` bits 7 and 0, writes `0x57 = 0x22`. |
| 5 | `00:0127` → `ram:3FAB` | `35:4B9F` | event clear/re-arm path; may clear `0x4C`, reset `USBFlag2` bit 6, and write `0x57 = 0x50/0x93`. |
| 6 | `00:0113` → `ram:3F93` | `35:40B2` | USB setup path; sets `IY+0x1B` bit 5, initializes controller state, and waits for `0x4C = 0x1A/0x5A`. |
| 7 | `00:0118` → `ram:3F99` | `35:4C14` | cleanup/reset path; clears `0x5B`, resets `USBFlag2` bit 0, and jumps through the common controller reset. |
| 1 | `00:011D` → `ram:3F9F` | `35:4031` | alternate setup path; waits for `0x4C = 0x12/0x52` and uses endpoint/status ports `0x87`/`0x89`/`0x8B`. |

Both paths are [confirmed].

The timer/idle side of the same handler also bridges to the assist path. At `ram:01B1` it calls
`ram:1837` (`IN A,(0x2); AND 0x80; XOR 0x80`), the same hardware-model gate used elsewhere before assist-port access. On the legacy path it checks `port 0x00 & 0x03`; on the assist
path it checks `port 0x09 & 0x18`. If either assist bit is set, it reloads `0x9C86 = 0xFA`, pulses
port `0x08` with `0x80` then `0x00`, sets `IY+0x3E` bit 0, and calls the common link activity hook
at `ram:3FD5`. [confirmed]

The raw-line encoding, the corresponding port-`0x00` receiver, and the distinction between this periodic check and a direct line interrupt are detailed in [Two-wire link port hardware](link-port-hardware.md#background-link-detection-and-interrupts).

For application code, this means a custom interrupt handler that does not chain to the OS handler
must account for port `0x55`/`0x56` activity itself and then either reproduce the relevant page-35
event handling or deliberately leave USB disabled. The OS still acknowledges the legacy interrupt
mask through port `0x03` on exit, but the USB event work is selected by `0x55`/`0x56` and page-35
controller ports, not by a writeable `0x56` mask. Port `0x55` is not a summary of ON, standard-timer,
or legacy link requests. See [Interrupts (IM1)](interrupts.md#usb-gate-and-legacy-controller) for the
two-stage dispatch and legacy acknowledgement. [confirmed]

## Public USB API bodies [confirmed]

The public USB names in `ti83plus.inc` are backed by the main page-3B bcall table for the `0x50xx`,
`0x52xx`, and `0x53xx` IDs. The table entries are `addr_lo, addr_hi, page`; page bytes like `0x75`
mask to physical page `0x35`.

| Bcall ID | Public name | Body | ROM-grounded behavior |
|----------|-------------|------|-----------------------|
| `50F2` | `_SendUSBData` | `35:4DD3` | Sends from `HL` with byte count in `DE`; stores progress at `0x9C7E`/`0x9C81` and writes 64-byte chunks to port `0xA2`. |
| `50F5` | `_AppGetCBLUSB` | `3B:54C7` | Sets `IY+0x1B` bit 1, clears bit 2, then reaches `_GetVarCmdUSB`. |
| `50F8` | `_AppGetCalcUSB` | `3B:54F0` | At `3B:54DE` clears `IY+0x16` bit 0 and sets `sndRecState`=0x15, then `bcall 0x50FB` (shared get-var path). |
| `50FB` | `_GetVarCmdUSB` / `link_xfer_op` | `3C:4DD2` | USB-first variable command wrapper described above. |
| `5254` | `_InitUSBDeviceCallback` | `35:4696` | Initializes device mode, stores callback page/address at `0x9C13`/`0x9C14`, and returns `0xFC`–`0xFF` style error bytes with carry set on failure. |
| `5257` / `5311` | `_KillUSBDevice` / `_RecycleUSB` | `35:46FC` / `35:5B9B` | Clears callback state and recycles through the same cleanup path. |
| `525A` | `_SetUSBConfiguration` | `35:470B` | Builds an 8-byte request block at `0x9C29` and writes it through port `0xA0`. |
| `525D` / `5260` | `_RequestUSBData` / `_StopReceivingUSBData` | `35:48BA` / `35:48D1` | Stores or clears the receive-buffer descriptor at `0x9C1E`; receive records are read from port `0xA1`. |
| `528A` / `528D` | `_EnableUSBHook` / `_DisableUSBHook` | `3B:7DC6` / `3B:7DD1` | Stores `USBActivityHookPtr`/page at `0x9BD4`/`0x9BD6` and toggles `(IY+0x3A)` bit 0. |
| `5290` | `_InitUSBDevice` | `35:42B0` | Main controller/device initialization path; uses `0x4C`/`0x4D` line handshakes and endpoint ports `0x80`–`0x9B`. |
| `5293` | `_KillUSBPeripheral` | `35:59CF` | Peripheral teardown; sets controller state `0x9C28 = 5` and manipulates ports `0x54`/`0x81`. |
| `530B` | `_ToggleUSBSmartPadInput` | `35:5B84` | Sets or clears bit 3 in `0x9C75` according to `A == 1`. |
| `530E` | `_IsUSBDeviceConnected` | `35:5B92` | Preserves `A`; returns flags from `IN (0x81) & 0x40` (bit 6). (The `.inc` comment guesses `bit 4,(81h)`, but the body actually masks bit 6.) |

## Boot-page OS receive API

The retail boot table on page `3F` also exposes a USB stack whose bodies run on page `2F`. This stack receives an operating-system image. It is separate from the page-35 application-facing API above. The table bytes and entry prologues can be reproduced with `tools/inspect_bcall.py`. [confirmed]

| Bcall | ID | Table bytes | Body | Observed role |
|-------|---:|-------------|------|---------------|
| `_AttemptUSBOSReceive` | `80E4` | `45 41 2F` | `2F:4145` | Wait for or dispatch a USB line event, initialize the controller, then enter the OS-receive pipeline. [confirmed] |
| `_ReceiveOS_USB` | `80F6` | `CA 48 2F` | `2F:48CA` | Negotiate transfer records and write the received OS image through the Flash-control path. [confirmed] |
| `_USBErrorCleanup` | `8105` | `58 59 2F` | `2F:5958` | Clear port `0x5B`, restore controller line state, and re-arm according to port `0x4D`. [confirmed] |
| `_InitUSB` | `8108` | `A4 52 2F` | `2F:52A4` | Initialize peripheral mode and return carry set after timeout cleanup. [confirmed] |
| unnamed entry | `810B` | `C5 62 2F` | `2F:62C5` | Set port `0x81` mask `0x01`, then wait through the timer-3 delay helper. [confirmed] |
| `_KillUSB` | `810E` | `61 59 2F` | `2F:5961` | Run the error-cleanup sequence with an additional `OUT (0x4C),0`. [confirmed] |

Inspect a named entry and the unnamed slot directly:

```sh
nix develop -c python tools/inspect_bcall.py 0x8108 --bytes 24
nix develop -c python tools/inspect_bcall.py 0x810B --bytes 24
```

### `_AttemptUSBOSReceive` input and dispatch

The first instruction at `2F:4145` is `JR NZ,2F:414A`. The input Z flag therefore controls whether the routine waits for a new event. With Z set, `usb_wait_line_event` at `2F:514C` checks the cancel/timeout helper, then samples port `0x4D` bit 6. If that bit is clear, it returns `port 0x56 & 0xF2` instead. With Z clear, dispatch begins with the caller's `A` unchanged. [confirmed]

The dispatcher tests event bits in this order: 5, 4, 6, then 7. Bits 5 or 4 call the line-state cleanup helper and resume waiting. Bit 6 calls `_InitUSB`. Bit 7 jumps to the common error exit at `2F:4FFD`. When none of those bits is set, the routine reads port `0x4D`; bit 5 selects `_InitUSB`, while the other branch calls the controller setup path at `2F:5220`. Both successful branches continue at `2F:4170` into the receive protocol. [confirmed]

The `ti83plus.inc` comment says Z means “wait” and NZ means “dispatch the supplied port value.” The entry bytes verify that contract and establish the bit priority. [confirmed]

### `_InitUSB` transaction and return

`_InitUSB` sets `IY+0x1B` bit 5 and writes controller state 2 to `0x9C28`. It then performs this prefix: [confirmed]

```z80
; 2F:52AD
LD A,80h
OUT (57h),A
XOR A
OUT (4Ch),A
IN A,(4Ch)
LD A,02h
OUT (54h),A
LD A,20h
OUT (4Ah),A
CALL 59C3h
LD A,08h
OUT (4Ch),A
```

The reset helper at `2F:59C3` drives port `0x4B`, pulses port `0x54`, and uses programmable timer 3 through ports `0x36`–`0x38` for a delay. `_InitUSB` then waits for port `0x4C` to equal `0x1A` or `0x5A`. Each poll decrements a 16-bit `DE` timeout through `2F:5313`. [confirmed]

After the handshake, the routine writes `0xFF` to port `0x87`, zero to `0x92`, reads `0x87`, writes `0x0E` to `0x89`, clears `0x9C26` and `0x9C27`, and writes `0x21` to `0x8B`. The tail at `2F:52F6` gives port `0x8C` five timeout windows to become nonzero. Success executes `OR A; RET`, which clears carry. Failure calls `_USBErrorCleanup` through `2F:5B87`, sets carry, and returns. [confirmed]

The unnamed bcall `810B` reads port `0x81`, ORs mask `0x01`, writes the result back, and jumps to the timer-3 delay at `2F:5A06`. The `ti83plus.inc` comment calls this bit 1, while mask `0x01` sets bit 0. No controller-state poll occurs in this entry itself. [confirmed]

### Receive and cleanup boundaries

`_ReceiveOS_USB` disables interrupts, enters the record-transfer helpers, and feeds the values `0`, `8`, `3`, `0`, `0x0104`, `0`, and `0` through `2F:42AA`. It then sets port `0x20` to 1, clears receive state at `0x8271`, `0x822F`, and `0x83A4`, and uses `0x86EC` as a `0x0104`-byte record workspace. Later branches subtract a four-byte framing size, validate record fields, and program Flash through port `0x14`. [confirmed]

This body is an OS installer, not a general USB receive primitive. It changes CPU speed, validates memory and page state, and writes Flash. Error branches converge on `2F:4FFD`, which calls `_USBErrorCleanup`. Application code should use the page-35 API instead. [confirmed]

`_USBErrorCleanup` and `_KillUSB` share almost all their code: [confirmed]

```z80
; _USBErrorCleanup = 2F:5958
XOR A
OUT (5Bh),A
CALL 591Bh
JP 58D0h

; _KillUSB = 2F:5961
XOR A
OUT (5Bh),A
CALL 591Bh
XOR A
OUT (4Ch),A
JP 58D0h
```

The helper at `2F:591B` chooses the port-`0x4C` value from port `0x4D` bits 5 and 6, writes `0x02` to port `0x54`, and clears low control bits on port `0x39`. The tail at `2F:58D0` re-arms port `0x57` according to the current line state. `_KillUSB` differs only by forcing port `0x4C` to zero between those helpers. [confirmed]

The setup paths also update GPIO data at port `0x3A` and GPIO configuration at
port `0x39`. Their low-bit read-modify-write sequences are decoded in
[ASIC status, identity, protection, and GPIO](asic-status-gpio.md#usb-gpio-sequence).
The ROM ties those bits to USB setup but does not expose their electrical signal
names. [confirmed] for the operations; [hypothesis] for signal assignments.

## Emulator comparison

The three pinned emulators implement disconnected or partial USB behavior. None implements the page-35 endpoint transactions needed for a connected transfer. [standard]

| Area | TilEm `f56ad63` | Wabbitemu `48c2dc0` | MAME 0.287 |
|------|-----------------|------------------------|------------|
| Controller ports | fixed reads at `0x4C`, `0x4D`, `0x55`–`0x57` | handlers at `0x4A`, `0x4C`, `0x4D`, `0x55`–`0x57`, `0x5B`, and `0x80` | fixed reads at `0x55` and `0x56` only |
| Initial/disconnected `0x4C`, `0x4D` | `0x22`, `0xA5` | `0x22`, `0xA5` | unmapped |
| Initial `0x55`, `0x56`, `0x57` | `0x1F`, `0x00`, `0x50` | `0x1F`, `0x50`, `0x00` | `0x1F`, `0x00`, unmapped |
| Line/event state | fixed | paired-state latch and event byte | none |
| FDRC block | unmapped | only device address at `0x80` | unmapped |
| Connected transfer | unavailable | unavailable | unavailable |
| Driver status | disconnected traces run | source calls the block `Fake USB` | TI-84 Plus driver is `MACHINE_NOT_WORKING` |

TilEm's fixed port `0x4C = 0x22` cannot satisfy `_InitUSB`'s `0x1A`/`0x5A` handshake. Its `x4_io.c` has no controller or endpoint write cases. A TilEm trace can therefore exercise timeout and disconnected cleanup, but not connected setup or receive. [standard] for emulator behavior; [confirmed] for the ROM comparison.

Wabbitemu assigns paired states to port `0x4D`: D+ low/high in bits 0/1, D- low/high in bits 2/3, ID low/high in bits 4/5, and VBUS high/low in bits 6/7. Reset value `0xA5` therefore selects D+ low, D- low, ID high, and VBUS low under its own labels. Port `0x56` starts at `0x50`, port `0x57` stores an event mask, and port `0x55` reports line and protocol requests as active-low bits 2 and 4. [standard]

The partial model has five source-visible defects: [standard]

- Device initialization registers port `0x55` twice. The first handler was written for port `0x54`, so the port-`0x54` PHY control model is unreachable.
- `GenerateUSBEvent` does not consult the mask stored at port `0x57`; it raises the CPU interrupt unconditionally.
- From reset state, writing `0x08` to port `0x4A` sets VBUS-high bit 6 without clearing VBUS-low bit 7. The line byte becomes `0xE5`, in which both Wabbitemu VBUS state bits are set.
- The same write records a D-minus-high event by changing the event byte from `0x50` to `0x58`, but it does not set D-minus-high in the line byte. Repeated writes can therefore regenerate the event.
- Port `0x4D` tries to select one D+ state with `BIT(1) & ~BIT(0)` or its inverse. Each expression evaluates to one set bit. The handler ORs that bit into the line-state byte without clearing the paired bit.

These inconsistencies prevent Wabbitemu from serving as a connected PHY reference. Its paired-state representation and active-low summary still provide an independent comparison with the ROM's bit tests. The electrical labels remain emulator evidence because the ROM does not name the signals. [standard] for source behavior; [hypothesis] for physical signal assignments.

MAME maps ports `0x55` and `0x56` to constant disconnected values `0x1F` and
zero. Ports `0x4A`–`0x5B` outside that pair and the FDRC region at
`0x80`–`0xA2` are absent from the TI-84 Plus map. A guarded native sweep reads
zeros across `0x4A`–`0x5B` except for `0x55 = 0x1F`; patterned writes leave the
complete block unchanged. A soft reset produces the same pair. [standard]

### Native Wabbitemu USB edges

A guarded initialized-core run invokes the registered handlers without
executing TI-OS. Ports `0x4A`, `0x4C`, `0x4D`, `0x55`–`0x57`, `0x5B`, and
`0x80` accept reads. Port `0x54` is inactive and returns the unhandled-port
fallback `0xFF`. Reset reads are `0x04`, `0x22`, `0xA5`, `0x1F`, `0x50`,
`0x00`, `0x00`, and `0x00` in mapped-port order. The run also checks the
internal reset fields: line state `0xA5`, events `0x50`, mask zero, both
interrupt fields clear, and all three stored control bytes zero. [standard]

Port `0x57` stores both `0xFF` and zero. With the mask set to zero, writing
`0x08` to port `0x4A` asserts Wabbitemu's CPU interrupt and line-interrupt
fields. The line state becomes `0xE5`, the event byte becomes `0x58`, port
`0x55` reads `0x1B`, and port `0x56` reads `0x58`. Clearing only the CPU
interrupt field and repeating the same port write asserts it again. This
confirms the mask omission and repeat-event path in the initialized core.
[standard]

Directly seeded handler-contract cases produce the complete port-`0x55`
matrix `0x1F`, `0x1B`, `0x0F`, and `0x0B` for neither, line, protocol, and
both requests. Port `0x5B` masks `0xFF` to bit 0, and port `0x80` masks it to
`0x7F`. The two port-`0x4D` cases return `0xA7` and `0xE7`, retaining both D+
bits after the handler adds the selected bit. These directly seeded states
test handler arithmetic; the run does not claim that registered ports can
reach them naturally. [standard]

## Reusable USB tools

`tools/usb_hardware.py` contains the FDRC offset map, the common HDRC comparison map, pinned source
provenance, imported global bit names, link-assist rate fields, page-35 and boot-event decoders,
paired line-state decoder, emulator profiles, and pure functions for Wabbitemu's USB read handlers.
`tools/describe_usb_hardware.py` exposes the general models as text or JSON.
`tools/wabbitemu_usb_probe.py` validates native reports against the reusable handler model, while
`tools/run_wabbitemu_usb_edge_probe.py` provides the exact-ROM guard and writes a hashed JSON
manifest. The link-assist state model remains in `tools/link_port.py`;
`tools/tilem_link.py` and `tools/run_tilem_link_probe.py` add the guarded TilEm
native report and manifest. `tools/port_definitions.py` parses the project port
labels with duplicate checks. `tools/analyze_rom_io.py` uses that library to
attach labels to static I/O reports and can restrict output to ports absent
from the label file. `tools/rom_io_coverage.py` pins and reconciles the complete
ROM-wide set of aligned non-descriptor candidates absent from that file.

```sh
# Map global, indexed, dynamic-sizing, and FIFO registers.
nix develop -c python tools/describe_usb_hardware.py \
  register 0x80 0x91 0x9F 0xA2

# Compare the FDRC hypothesis with the common HDRC byte layout.
nix develop -c python tools/describe_usb_hardware.py layouts
nix develop -c python tools/describe_usb_hardware.py --json layouts

# Keep active-low port-0x55 and port-0x56 interpretations separate.
nix develop -c python tools/describe_usb_hardware.py events 0x1F 0x50

nix develop -c python tools/describe_usb_hardware.py assist 0x97 0xB4 0xE0
nix develop -c python tools/describe_usb_hardware.py line 0xA5 0xE5
nix develop -c python tools/describe_usb_hardware.py reads 0x4C 0x4D 0x55 0x56 0x57 0x80
nix develop -c python tools/describe_usb_hardware.py wabbit-port4a 0x08

# Audit direct page-35 accesses whose ports lack project-local labels.
nix develop -c python tools/analyze_rom_io.py \
  --page 0x35 --direct-only --unlisted --summary 0x40-0x7F

# Retain only the two table-shaped candidates for unobserved USB ports.
nix develop -c python tools/analyze_rom_io.py \
  --direct-only --exclude-descriptors 0x49 0x51 0x52

# Verify every candidate for every port absent from tools/ports.txt.
nix develop -c python tools/describe_rom_io_coverage.py --json
```

The FDRC names and bit labels remain a controller-family hypothesis. The CLI identifies that evidence boundary in its register records; it does not promote imported Mentor names to TI silicon confirmation.

## How to use it in code [confirmed]

Prefer the OS entry points unless the program is deliberately writing a USB driver:

| Need | OS surface | ROM support |
|------|------------|-------------|
| Send or request a variable over USB/link | `_GetVarCmdUSB`/`link_xfer_op` (`50FB` → `3C:4DD2`) or `_SendVarCmd` (`4A14` → `3C:4EDD`) | Packet engine and USB-selection gate confirmed on page `3C`. `0x50FB` is `_GetVarCmdUSB` in `ti83plus.inc`. |
| Send one byte on the active link transport | `_SendAByte` (`4EE5` → `3C:420D`) | Assist branch writes `C` to port `0x0D` after port `0x09` bit 5. |
| Receive one byte on the active link transport | `_RecAByteIO` (`4F03` → `3C:443F`) | Status path checks port `0x09` and reads port `0x0A` on the assist path. |
| Use the raw assist FIFO | Poll port `0x09` bit 5, then write the byte to port `0x0D`; for receive, observe port `0x09` bit 4/error bits and read port `0x0A`. | Confirmed as an OS pattern, but not a complete public API. |

The raw FIFO sequence is only the byte layer. A working transfer still needs the packet layer:
machine ID, command, length, payload checksum, ACK/NAK, and EOT. That framing is documented in
[sub-link-transfer.md](sub-link-transfer.md#3-packet-framing--the-ti-link-protocol-confirmed).

### Native TilEm link-assist edges

The guarded TilEm direct-core probe maps all handlers from `0x08` through
`0x0D`. A fresh disabled engine reports `0x20`. The read sides of
ports `0x09`–`0x0C` remain computed status or zero after the write sides store
`0x91`, `0xA2`, `0xB3`, and `0xC4`. This covers the complete four-register
setup surface that OS 2.55MP initializes. [standard]

Idle-ready reports `0x22` and asserts the CPU interrupt. Reading port `0x0D`
does not acknowledge that condition. A completed `0xA5` receive reports
`0x31`; reading port `0x0A` returns the byte and changes status to `0x20`.
An illegal both-low input reports `0x64`; the first status read clears only the
interrupt request, leaving error status `0x60`. [standard]

Full reset restores port `0x08 = 0x80` and clears the active transfer fields,
but retains the four auxiliary write registers and external peer-line state.
Direct handler calls consume zero modeled CPU clocks. These results describe
the pinned TilEm implementation, not physical assist timing or reset
retention. See [Two-wire link port hardware](link-port-hardware.md#native-tilem-raw-and-assist-edges)
for the raw matrix, LSB-first transfer sequence, and guarded command.
[standard]

### Native Wabbitemu link-assist edges

The guarded Wabbitemu initialized-core probe maps ports `0x08`, `0x09`,
`0x0A`, and `0x0D`; ports `0x0B` and `0x0C` are absent. This means its assist
engine cannot represent the OS's complete four-register signaling-rate setup
for CPU speed modes 0–3. [standard]

The same run sends and receives `0xA5` through controlled peer handshakes.
Transmit completion reports `0x22`; receive completion reports `0x11`.
Reading port `0x0D` clears ready, and reading port `0x0A` clears read-ready.
Both enabled conditions assert Wabbitemu's CPU interrupt line. A separately
seeded error produces `0x4C` and clears on the first port-`0x09` read, but the
pinned source contains no path that sets the error field. These are emulator
state-machine results, not physical assist timing or TI-OS execution.
[standard]

See [Two-wire link port hardware](link-port-hardware.md#native-wabbitemu-raw-and-assist-edges)
for the full raw matrix, transfer sequence, and guarded command.

Practical rules:

- Set up `IY+0x1B` consistently before calling `link_xfer_op`. Bit 0 is the USB-first selector.
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
- The public `0x50xx`/`0x52xx`/`0x53xx` USB APIs and the boot-page `0x8xxx` USB entries are mapped above. The connected boot receive path remains dynamically untested because TilEm models USB as disconnected.
- The FDRC layout names the endpoint register block, but physical tests have not confirmed every
  imported bit meaning or the TI-specific PHY at ports `0x4A`–`0x5B`. TilEm does not model physical
  timing from the assist setup values. ROM-confirmed claims remain limited to written constants,
  comparisons, branch bits, RAM state, FIFO direction, and the transfer sequences cited above.
- The ROM confirms the port-`0x4B` writes and the port-`0x4F`/`0x50`
  read-modify-write sequence. It does not identify their electrical effects.
  Port-`0x5A` bit 0, endpoint-2 setup, and subsequent LCD traffic are
  ROM-confirmed; mirroring on the wire, its packet format, and the reported
  host-mode restriction remain physically unverified.
- The guarded TilEm link probe verifies handler-visible assist behavior, but it
  does not establish physical signaling-rate divisors, wait states, electrical
  levels, or reset retention.
- TilEm, Wabbitemu, and MAME do not implement a connected page-35 transfer. The initialized-core Wabbitemu run confirms its port-registration, event-mask, contradictory-line-state, repeat-event, and paired-bit handler defects. Dynamic connected-path evidence therefore still requires physical hardware or a controlled port-level harness.

## Sources

| Source | Use |
|--------|-----|
| Retail OS 2.55MP and boot 1.03 ROM bytes | Main and boot bcall tables, page-`2F`/`35` bodies, ports, branches, and RAM state |
| `tools/ti83plus.inc` | Historical public names and comments, checked against table entries and bodies |
| [TilEm `x4_io.c` at `f56ad63`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_io.c) | Link-assist implementation and fixed disconnected USB reads |
| [Mentor `mu_fdrdf.h` revision 1.7 as preserved in `lightcube`](https://github.com/illusionlee/lightcube/blob/ac49c480c45c4106cba46a93fd4ae09969db5a1e/beken378/driver/usb/src/cd/mu_fdrdf.h) | Mentor-authored 2004 FDRC register offsets and bit masks. The header labels itself proprietary; the mirror is controller-family evidence, not TI silicon identification. |
| [VSF FDRC register structure at `4327394`](https://github.com/vsfteam/vsf/blob/4327394b125aae68f67ed48b3aa891fd203a6ca8/source/component/usb/driver/otg/musb/fdrc/vsf_musb_fdrc_hw.h) | Independent implementation that corroborates the compact FDRC byte ordering; not TI-84 Plus evidence |
| [Linux `musb_regs.h` at `db2ddb8`](https://github.com/torvalds/linux/blob/db2ddb87143519e20a95aa36c60b36107b736a58/drivers/usb/musb/musb_regs.h) | Mentor/TI-copyrighted common HDRC/MUSB map used as the comparison candidate; not TI-84 Plus silicon documentation |
| [Linky at `89586b0`](https://github.com/brandonlw/Linky/tree/89586b0d33796d9746934560c030bb247193d37a) | Independent calculator software that names MUSBFDRC and exercises the same ports |
| [Wabbitemu `83psehw.c` at `48c2dc0`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/hardware/83psehw.c) | Partial line-state and interrupt model, with the implementation limits described above |
| [MAME 0.287 `ti85.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85.cpp) and [`ti85_m.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85_m.cpp) | Fixed USB interrupt reads and absent controller/endpoint ports |
| [WikiTI port `0x09`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:09) | Historical link-assist timing-field interpretation, kept separate from ROM observations |
| [WikiTI port `0x4B`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:4B) | Historical USB-power orientation. The page calls its own bit descriptions mostly speculative. |
| [WikiTI port `0x49`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:49) | Historical raw-transceiver bit claims; no primary hardware source or ROM use found |
| [WikiTI port `0x51`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:51) | Historical USB enable-timer claim; physical clock and units remain unverified |
| [WikiTI port `0x52`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:52) | Historical charge-pump timer claim; physical behavior remains unverified |
| [WikiTI port `0x5A`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:5A) | Historical presentation-mirroring description, treated as an unverified physical claim beyond the ROM-visible setup sequence |
| [WikiTI `_KeyboardGetKey` revision 5510](https://wikiti.brandonw.net/index.php?title=83Plus:BCALLs:50E9&oldid=5510) | Historical TI-Keyboard transmitter sequence, checked against but not substituted for ROM control flow |
