# Two-wire link port hardware

*TI-84 Plus OS 2.55MP — port `0x00`, raw bytes, and line handshakes.*

The 2.5 mm link port carries each byte over two bidirectional lines. This page reconstructs the port encoding, the four-transition bit handshake, timeout behavior, and background link detection.

The packet layer above these byte routines is covered in [Link / data transfer](sub-link-transfer.md). The hardware-assisted byte path is covered in [USB ASIC and link assist](sub-usb-asic.md).

## Evidence boundaries

The sources answer different questions:

| Source | What it establishes | Confidence |
|--------|---------------------|------------|
| OS 2.55MP bytes | Values written to port `0x00`, values accepted on reads, bit order, acknowledgements, and error branches | [confirmed] |
| TilEm and Wabbitemu | Two independent digital models of port reads, local output latches, and connected endpoints | [standard] where both match the public port contract |
| TI Link Protocol Guide and WikiTI | Open-collector electrical description and red/tip versus white/ring names | [standard] |
| Physical measurements | Rise time, pull-up resistance, voltage thresholds, and ASIC-specific edge timing | [hypothesis] until measured on this hardware |

The code below therefore uses *line 0* and *line 1* for ROM-derived behavior. Connector names appear only where an external hardware source supplies them.

## Port `0x00` line encoding

The low two write bits are active-high drive controls. Setting a bit pulls that line low. Clearing it releases the line so the pull-up can make it high. The low two read bits have the opposite sense: a set bit reports a physically high line. [standard]

| Low write bits | Local action | Unopposed low read bits |
|----------------|--------------|-------------------------|
| `0` | release both lines | `3` |
| `1` | pull line 0 low | `2` |
| `2` | pull line 1 low | `1` |
| `3` | pull both lines low | `0` |

Let `L` be the local two-bit pull-low mask and `P` the peer mask. TilEm computes the physical high-line mask as:

$$
H = \mathord{\sim}(L \mathbin{|} P) \mathbin{\\&} 3
$$

Wabbitemu uses the equivalent expression `((L | P) & 3) ^ 3`. Both models put the local output latch in read bits 4–5, giving `(L << 4) | H`. WikiTI documents the same latch behavior. [standard]

The ROM masks reads with `AND 0x03`, so the raw byte routines do not depend on bits 2–7. The reusable model in `tools/link_port.py` intentionally models only the two line bits and the documented bits 4–5 latch.

### Connector-contact names

The archived TI Link Protocol Guide calls line 0 red/tip and line 1 white/ring. WikiTI gives the same bit-to-contact mapping. It also describes both lines as open-collector outputs with pull-ups. [standard]

OS 2.55MP sends a zero bit with write `1` and a one bit with write `2`. That agrees with the guide's rule that zero pulls red/tip first and one pulls white/ring first. [confirmed] for the write values; [standard] for the physical contact names.

## Sending one byte at `3C:420D`

`_SendAByte = 4EE5`, body `3C:420D`, copies the byte from `A` to `C`. The model probe at `3C:420E` selects the link-assist path when available. The legacy path sends eight bits least-significant first. [confirmed]

```z80
3C:4214  LD B,8
3C:4216  LD DE,0xFFFF
3C:4219  RR C
3C:421B  JR NC,send_zero
3C:421D  LD A,2
3C:421F  JP drive_bit
send_zero:
3C:4222  LD A,1
drive_bit:
3C:4224  OUT (0),A
```

`RR C` places the next low bit in carry. Carry clear chooses write `1`; carry set chooses write `2`. Repeating the rotation eight times consumes the original byte from bit 0 through bit 7. [confirmed]

After driving the selected line, the sender polls until both lines read low:

```z80
3C:4226  IN A,(0)
3C:4228  AND 3
3C:422A  JP Z,acknowledged
3C:422D  IN A,(0)
3C:422F  AND 3
3C:4231  JP Z,acknowledged
3C:4234  DEC DE
3C:4237  JP NZ,0x4226
3C:423A  JP 0x2799
```

The receiver acknowledges by pulling the other line low. The combined read value becomes `0`. The sender then writes `0` to release its own line and waits for read value `3`, which means the receiver also released its acknowledgement. [confirmed]

```z80
acknowledged:
3C:423D  LD A,0
3C:423F  OUT (0),A
3C:4241  LD DE,0xFFFF
3C:4244  DEC DE
3C:4249  IN A,(0)
3C:424B  AND 3
3C:424D  CP 3
3C:424F  JP NZ,0x4244
3C:4252  DJNZ 0x4216
3C:4254  RET
```

## The four-transition handshake

Each bit uses the same four transitions. The sender chooses which line moves first; the receiver pulls the other line low; then each endpoint releases its own line. [confirmed]

| Phase | Sender drive | Receiver drive | Read value for bit 0 | Read value for bit 1 |
|-------|--------------|----------------|----------------------|----------------------|
| Sender asserts | `1` for bit 0; `2` for bit 1 | `0` | `2` | `1` |
| Receiver acknowledges | unchanged | the other line | `0` | `0` |
| Sender releases | `0` | unchanged | `1` | `2` |
| Receiver releases | `0` | `0` | `3` | `3` |

This is a level handshake, not a clocked UART waveform. Either endpoint can pause a transfer by delaying its next transition, up to the software or hardware timeout. Byte boundaries are supplied by the calling protocol rather than a separate wire symbol. [standard]

## Receiving one byte at `3C:447E`

`_RecAByteIO = 4F03`, body `3C:443F`, reaches the legacy receiver at `3C:447E` when the model probe does not select link assist. The receiver waits for a single-low state and rejects both-low. [confirmed]

```z80
3C:447E  LD B,8
3C:4486  LD DE,0xFFFF
3C:448B  IN A,(0)
3C:448D  AND 3
3C:448F  JR Z,link_error
3C:4491  CP 3
3C:4493  JP NZ,decode_bit
3C:4496  IN A,(0)
3C:4498  AND 3
3C:449A  JR Z,link_error
3C:449C  CP 3
3C:449E  JP NZ,decode_bit
```

Only read values `1` and `2` reach `decode_bit`:

| Initial read | Sender drove | Received bit | Receiver acknowledgement |
|--------------|--------------|--------------|--------------------------|
| `2` | line 0 with write `1` | 0 | write `2` |
| `1` | line 1 with write `2` | 1 | write `1` |

The comparison at `3C:44AA` also prepares carry for `RR C`. Read `2` makes carry clear, inserting a zero at bit 7. Read `1` makes carry set, inserting a one. After eight rotations, `C` contains the byte in its original order even though the wire bits arrived least-significant first. [confirmed]

```z80
decode_bit:
3C:44AA  CP 2
3C:44AC  JR Z,received_zero
3C:44AE  LD A,1
3C:44B0  OUT (0),A
3C:44B2  RR C
             ; wait until read 2: sender released line 1
received_zero:
3C:44DE  LD A,2
3C:44E0  OUT (0),A
3C:44E2  RR C
             ; wait until read 1: sender released line 0
```

Once the sender releases, the receiver writes `0`. It samples briefly for idle and uses `DJNZ` to begin the next bit. `_Rec1stByte` at `3C:439C` adds APD and first-activity handling before entering the same decoder. [confirmed]

## Timeouts and malformed states

The raw routines use loop counters, not a wall-clock register. CPU speed and I/O timing therefore affect the elapsed timeout. The fixed count alone does not justify a duration claim. [confirmed]

| Condition | ROM response | Evidence |
|-----------|--------------|----------|
| Sender never sees both-low acknowledgement | exhaust `DE = 0xFFFF`, then jump to `_JErrorNo` | `3C:4216`–`423A` [confirmed] |
| Peer never releases after acknowledgement | exhaust `DE = 0xFFFF`, then share the same `_JErrorNo` edge | `3C:4241`–`424F` [confirmed] |
| Receiver waits too long for a non-idle state | jump to `_ErrLinkXmit` | `3C:4486`–`44A7` [confirmed] |
| Receiver sees both lines low before acknowledging | jump to `_ErrLinkXmit` | `3C:448B`–`449A`, `3C:44F9` [confirmed] |
| Sender fails to release its selected line | exhaust `DE = 0xFFFF`, then jump to `_JErrorNo` | `3C:44B4`–`44C6`, `3C:44E4`–`44F6` [confirmed] |

`_ErrLinkXmit = 44D4`, body `00:278D`, loads error `0x9F` before the common error path. The include file names `0x9F` `E_LnkErr`. `_JErrorNo` at `00:2799` raises the error already stored by the surrounding link operation. [confirmed]

The send acknowledgement loop reads port `0x00` twice before decrementing `DE`. A cycle estimate that treats it as one read per iteration is incorrect. [confirmed]

## Header setup and idle recovery

The packet-header sender at `3C:41C3` prepares the transport before sending its four header bytes. On the raw path it writes `0`, requires low bits `3` for idle, and invokes the receive-status path when a peer already holds a line low. It loads the first header byte at `3C:41F8` and calls the byte sender at `3C:41FB`. [confirmed]

The receiver entry at `3C:43B4` repeatedly samples port `0x00` until the low bits differ from `3`. It then initializes the eight-bit decoder at `3C:43C5`. This separates the unbounded wait for the first activity from the bounded waits inside a byte. [confirmed]

## Background link detection and interrupts

The standard-timer handler contains a raw-line activity check. After its surrounding link-service gates pass, `ram:01B1` calls the hardware-model probe. The legacy branch reads `port 0x00 & 3`; a value other than `3` calls the common link-activity bjump at `ram:3FD5`. The assist branch instead checks `port 0x09 & 0x18`, pulses port `0x08`, and calls the same bjump. [confirmed]

This explains why OS input and timer activity can react to a peer that pulls one raw line low. It does not mean every port transition immediately vectors the Z80. Port `0x03` controls the legacy link-interrupt enable, while this specific silent-link check occurs inside `standard_timer1_irq` at `ram:0167`. [confirmed]

Port-`0x03` bit 4 also keeps link activity available as a wake source in the standard hardware interrupt block. The power-off path writes `0x11` before `HALT`, enabling ON and link wake while disabling the standard timers. [confirmed] for the ROM write; [standard] for the port-bit role.

Port-`0x04` bit 4 has lower OS dispatch priority than the three programmable timers and standard timer 2, but higher priority than ON and standard timer 1. The branch enters the power-restoration path at `ram:01E0`. See [Interrupts (IM1)](interrupts.md#dispatch-order-and-simultaneous-sources) for acknowledgement and simultaneous-source behavior. [confirmed]

## The both-low pulse at `3C:618D`

The routine at `3C:618D` checks `(IY+0x1B)` bit 5. On its raw-link branch it writes `3` to port `0x00`, executes a long nested delay, and writes `0` at `3C:61B3`. Callers occur in link and command paths on pages `05` and `3C`. [confirmed]

The standard DBus description assigns a sustained both-low state to abort signaling. The waveform at `3C:6198`–`61B3` is compatible with that role, but the callers and delay have not been reduced far enough to name this routine as the OS abort primitive. [hypothesis]

## Emulator fidelity

TilEm and Wabbitemu agree on the digital port contract:

- each endpoint stores a two-bit pull-low mask;
- connected masks combine with OR because either endpoint can pull a line low;
- reads invert the combined mask so set bits mean physically high lines;
- read bits 4–5 report the local output latch.

TilEm also implements the four-phase link-assist state machine. Wabbitemu's virtual-cable sender and receiver implement the same LSB-first raw handshake at a higher level. These implementations corroborate the state transitions. They do not establish analog voltage thresholds, pull-up values, connector wear behavior, or edge timing on a physical TI-84 Plus. [standard]

## Reusable debugging tools

`tools/link_port.py` provides the wired-AND model, port-read decoder, byte encoding, receive assembly, and four-phase trace. `tools/describe_link_port.py` exposes those operations as a CLI:

```sh
nix develop -c python tools/describe_link_port.py drive 0x02
nix develop -c python tools/describe_link_port.py wire --local 1 --peer 2
nix develop -c python tools/describe_link_port.py byte 0xA5
nix develop -c python tools/describe_link_port.py receive 1 2 1 2 2 1 2 1
```

Add `--json` before the subcommand for machine-readable output. The model uses neutral line numbers so a trace remains valid even when the physical contact mapping is under review.

## Resolved findings and open hardware tests

- [confirmed] `_SendAByte` writes `1` for bit 0 and `2` for bit 1, least-significant bit first.
- [confirmed] The receiver maps initial read `2` to bit 0 and read `1` to bit 1, then acknowledges on the other line.
- [confirmed] Both-low is the acknowledgement midpoint during a valid transfer, but it is an error when a receiver sees it before choosing a bit.
- [confirmed] The standard-timer path detects non-idle raw lines and routes them to the OS link-activity handler.
- [standard] Port reads use active-high physical levels, writes use active-high pull-low controls, and bits 4–5 reflect the local output latch.
- [standard] Public hardware references map bit 0 to red/tip and bit 1 to white/ring.
- [hypothesis] Physical tests must measure pull-up resistance, high/low thresholds, line rise time, timeout duration at both CPU speeds, and the waveform and purpose of `3C:618D`.

## External references

- [WikiTI port `0x00`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:00) — public bit meanings and output-latch behavior; treated as a secondary source.
- [TI Link Protocol Guide](https://www.ticalc.org/archives/files/fileinfo/247/24750.html) — archived open-collector, contact-name, and four-transition protocol description.
- [TilEm link core](https://github.com/debrouxl/tilem/blob/master/emu/link.c) — emulator implementation used for digital-model comparison.
- [Wabbitemu](https://github.com/sputt/wabbitemu) — independent port and virtual-link implementation used for comparison.
