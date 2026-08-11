# Bus timing and wait states

The TI-84 Plus ASIC inserts programmable T-states into Flash, RAM, and LCD
transactions. CPU-speed mode selects one of four LCD-delay registers, which
also gates the memory waits in port `0x2E`; port `0x2F` separately controls the
high-speed LCD-ready interval and a documented programmable-timer prescaler.

OS 2.55MP programs this block once during retail boot. The ROM bytes and trace
pin the register values. Public measurements, TilEm, and Wabbitemu supply the
detailed timing contract; MAME provides an explicit omission comparison.

## Evidence and limits

| Evidence | What it establishes | Confidence |
|----------|---------------------|------------|
| `3F:41BD`–`41D3` | exact OS values for ports `0x29`–`0x2C`, `0x2E`, and `0x2F` | [confirmed] |
| Resolved cold-boot trace | all six writes execute in order before normal CPU speed is selected | [confirmed] |
| Whole-ROM immediate-port scan | no second control-flow-verified write to these registers in the analyzed ROM | [confirmed] |
| TilEm and Wabbitemu source | independent decode of speed selection, LCD instruction delays, and memory wait bits | [standard] |
| MAME 0.287 source | binary CPU-speed selection and absence of the delay-register block | [standard] |
| Public hardware tests | intended bit meanings, LCD failure thresholds, and mode-3 timer divisor | [standard] |

The trace proves what the ROM writes and which CPU-speed values execute. It
does not measure the ASIC bus electrically. Emulator-added clock counts are
reported as emulator behavior, not physical measurements.

## Register block

| Port | Role | Selected by |
|------|------|-------------|
| `0x20` | CPU-speed mode | software; low two bits form mode 0–3 |
| `0x29` | LCD instruction delay and memory-wait gates for speed mode 0 | port `0x20 & 3 = 0` |
| `0x2A` | same controls for speed mode 1 | port `0x20 & 3 = 1` |
| `0x2B` | same controls for speed mode 2 | port `0x20 & 3 = 2` |
| `0x2C` | same controls for speed mode 3 | port `0x20 & 3 = 3` |
| `0x2D` | quartz and low-power control | independent block; see [Clock, timers, and power](clock-timers-power.md) |
| `0x2E` | one-T-state Flash and RAM access selectors | gated by bits 0–1 of the active `0x29`–`0x2C` register |
| `0x2F` | high-speed LCD-ready interval and documented mode-3 timer prescaler | field selected by port `0x20` |

TilEm and Wabbitemu read back the last byte written to ports `0x29`–`0x2C`,
`0x2E`, and `0x2F`. Public descriptions give the same contract. MAME maps only
port `0x20` from this block; its I/O map has no handler for the six
delay-register writes. [standard]

## Selection pipeline

Let $s = p_{20} \bmod 4$. The active speed-dependent register is [standard]

$$
D_s = p_{29+s}
$$

That one byte controls two independent effects:

- bits 2–7 select the T-states added to each LCD-port instruction;
- bit 0 enables the Flash bits in port `0x2E`, and bit 1 enables the RAM bits.

Changing port `0x20` changes the active byte immediately in TilEm and
Wabbitemu. The OS does not need to rewrite ports `0x29`–`0x2C` when it moves
between 6 and 15 MHz. Both emulators recompute memory delays on an accepted
speed write. [standard]

Under the public TI-84 Plus contract and TilEm, speed value 0 selects nominal
6 MHz and values 1–3 select nominal 15 MHz. Wabbitemu's default TI-84 Plus
context clamps writes 2–3 to mode 1. Its external `extraSpeed` option instead
assigns 20 and 25 MHz to modes 2 and 3. MAME stores the raw byte and selects
15 MHz for every nonzero value. These are software policies, not evidence for
extra physical TI-84 Plus clocks. OS 2.55MP uses only values 0 and 1 in the
captured workflows. See
[Clock, timers, and power](clock-timers-power.md#cpu-speed) for frequency and
ASIC-revision caveats. [confirmed] for executed values; [standard] for public
and emulator behavior.

## Boot configuration

The retail boot continuation writes the complete block after its RAM probes
and link-assist initialization: [confirmed]

```z80
3F:41BD  LD A,0x17
3F:41BF  OUT (0x29),A
3F:41C1  LD A,0x27
3F:41C3  OUT (0x2A),A
3F:41C5  LD A,0x2F
3F:41C7  OUT (0x2B),A
3F:41C9  LD A,0x3B
3F:41CB  OUT (0x2C),A
3F:41CD  LD A,0x45
3F:41CF  OUT (0x2E),A
3F:41D1  LD A,0x4B
3F:41D3  OUT (0x2F),A
```

The resolved trace executes the writes at clocks 1,747,536 through 1,747,628.
Port `0x20` still reads zero at `3F:653E`. The OS later writes zero at
`ram:0DD5` and selects speed mode 1 at `ram:0C72`. [confirmed]

TilEm resets its internal registers to the older values `0x14`, `0x27`,
`0x2F`, `0x3B`, `0x44`, and `0x4A`. The retail boot writes above replace every
differing value before normal OS operation. Emulator reset defaults therefore
must not be mistaken for TI-84 Plus OS policy. [standard]

MAME accepts the later port-`0x20` speed write but drops all six boot writes to
ports `0x29`–`0x2C`, `0x2E`, and `0x2F`. It therefore runs the ROM at the
selected base clock without the programmable LCD or memory additions described
below. [standard]

## LCD instruction delay — ports `0x29`–`0x2C`

TilEm and Wabbitemu add [standard]

$$
T_{\mathrm{LCD}} = D_s >> 2
$$

T-states to each Z80 `IN` or `OUT` instruction targeting LCD ports `0x10`–`0x13`.
The two low bits do not contribute to this count; they gate memory waits.

The OS bytes decode as follows:

| Speed mode | Active port | OS byte | Added LCD T-states | Low-bit gates |
|------------|-------------|---------|----------------------|---------------|
| 0 | `0x29` | `0x17` | 5 | Flash and RAM |
| 1 | `0x2A` | `0x27` | 9 | Flash and RAM |
| 2 | `0x2B` | `0x2F` | 11 | Flash and RAM |
| 3 | `0x2C` | `0x3B` | 14 | Flash and RAM |

At nominal 6 MHz, five T-states are about 0.833 µs. At nominal 15 MHz, nine
T-states are 0.6 µs. These are additions to the Z80 I/O instruction, not the
complete interval between two LCD transfers. [standard]

Published hardware tests report that values below `0x0C` can make LCD writes
stop responding, while read behavior has a different lower boundary. The
exact threshold and failure mode should be remeasured by controller and ASIC
revision. [standard] for the published observation; [hypothesis] for
cross-revision behavior.

## Memory waits — port `0x2E`

Each selected bit adds one T-state to one memory-access class. Bits 0–2 apply
only when active register $D_s$ has bit 0 set. Bits 4–6 apply only when $D_s$
has bit 1 set. [standard]

| Port-`0x2E` bit | Memory | Access class | Emulator placement |
|-----------------|--------|--------------|--------------------|
| 0 | Flash | opcode/M1 fetch | each fetched opcode or prefix byte |
| 1 | Flash | non-opcode read | operands, data, and stack reads |
| 2 | Flash | attempted write | every CPU write routed to Flash |
| 3 | — | unused by the documented delay block | stored on readback |
| 4 | RAM | opcode/M1 fetch | each fetched opcode or prefix byte |
| 5 | RAM | non-opcode read | operands, data, and stack reads |
| 6 | RAM | write | every CPU write routed to RAM |
| 7 | — | unused by the documented delay block | stored on readback |

The boot value `0x45` sets bits 6, 2, and 0. Because all four active-register
bytes have gate bits 0 and 1 set, the OS policy in every speed mode is:
[confirmed] for register values; [standard] for the access decode.

| Access | Flash addition | RAM addition |
|--------|----------------|--------------|
| opcode/M1 fetch | 1 T-state | 0 |
| non-opcode read | 0 | 0 |
| write | 1 T-state | 1 T-state |

A prefixed Z80 instruction performs more than one M1 fetch. The emulator adds
the Flash opcode delay to the prefix and the following opcode separately. This
matches public reports that the observed addition doubles for a one-prefix
instruction. [standard]

The delay follows the physical page selected by the mapper in TilEm. An opcode
executed from banked RAM uses the RAM M1 bit; the same logical address backed
by Flash uses the Flash bit. See [Paging](paging.md) for physical-page
resolution. [standard]

One T-state is about 0.167 µs at nominal 6 MHz and 0.067 µs at nominal 15 MHz.
The register therefore preserves a *cycle* margin, not a fixed wall-time
margin, when CPU speed changes. [standard]

## LCD-ready interval — port `0x2F`

The LCD instruction delay above slows the I/O instruction itself. Port `0x2F`
controls a second mechanism: at high speed, the ASIC deasserts port-`0x02` bit
1 for a longer programmable interval after an LCD transaction. The OS
`lcd_wait` helper polls that bit before accessing the controller. See
[LCD controller and display bus](lcd-hardware.md#asic-side-wait-timing).
[standard]

Speed mode selects one field: [standard]

| Speed mode | Field | Width |
|------------|-------|-------|
| 0 | no high-speed ready hold | — |
| 1 | bits 0–1 | 2 bits |
| 2 | bits 2–4 | 3 bits |
| 3 | bits 5–7 | 3 bits |

For a selected field $f$, TilEm and Wabbitemu use [standard]

$$
T_{ready} = 48 + 64f
$$

The boot value `0x4B` produces:

| Speed mode | Field value | Ready hold | Nominal interpretation |
|------------|-------------|------------|------------------------|
| 0 | — | none | CPU and per-access delay provide the low-speed spacing |
| 1 | 3 | 240 T-states | 16 µs at 15 MHz |
| 2 | 2 | 176 T-states | mode not used by the traced OS path |
| 3 | 2 | 176 T-states | mode not used by the traced OS path |

TilEm restarts this ready timer on every modeled access to ports `0x10`–`0x13`,
including reads. Wabbitemu derives readiness from the last successful LCD
write. This disagreement matters for read-heavy code and requires a physical
test. [standard] for emulator behavior; [hypothesis] for ASIC read behavior.

## Programmable-timer mode-3 divisor

Public documentation assigns a second role to the selected port-`0x2F` field.
For programmable-timer sources in the `0xC0` family, the field selects divisor
$f+1$; speed mode 0 applies no divisor. [standard]

With the OS byte `0x4B`, the documented divisors are 1, 4, 3, and 3 for speed
modes 0–3. TilEm treats the `0xC0` family like its ordinary CPU-clock modes,
and Wabbitemu's timer-source update does not use port `0x2F`. The prescaler is
therefore absent from both compared emulator paths. [standard]

OS 2.55MP's timer API can select `0xC0`-family sources, but the current traces
do not execute a mode-3 prescaler measurement. The physical divisor remains a
target for a counter-based test. [hypothesis]

## Emulator comparison

| Behavior | TilEm | Wabbitemu | MAME 0.287 |
|----------|-------|------------|------------|
| Port-`0x20` write | low two bits select modes 0–3; nonzero runs at 15 MHz | default TI-84 Plus state clamps modes 2–3 to mode 1; external `extraSpeed` enables 20/25 MHz | stores the raw byte; zero selects 6 MHz and any nonzero value selects 15 MHz |
| Active `0x29`–`0x2C` register | indexed by port `0x20 & 3` | indexed by the accepted CPU-speed mode | registers absent |
| LCD instruction addition | active byte shifted right by two | same | absent |
| Memory gates and `0x2E` bits | all six access classes | all six access classes | absent |
| High-speed ready start | every LCD-port read or write | last successful LCD write | programmable interval absent |
| LCD controller rejection | ready bit and controller model | also has a separate fixed 60-T-state controller-access guard | T6A04 device behavior without the ASIC delay block |
| Mode-3 timer prescaler | not modeled | not modeled in the compared timer path | not modeled |

The matching memory and LCD-instruction decode corroborates the public bit
layout. MAME cannot corroborate that decode because it omits the block. The
readiness, speed, and timer differences remain emulator policy, not proof of
physical timing.

## Reproducing the decode

`tools/bus_timing.py` is a pure register decoder.
`tools/describe_bus_timing.py` prints all four speed modes from the boot values:

```sh
nix develop -c python tools/describe_bus_timing.py
```

The default documented profile reports:

```text
documented (WikiTI pages retrieved 2026-08-09): speed-mode=1 clock=15MHz port20=01/01
  port2e=0x45 port2f=0x4B
  mode  port value  MHz  LCD-I/O  Flash +1T      RAM +1T        LCD-ready  doc-div
   0    0x29  0x17    6      5T     M1,write       write            0T       /1
   1    0x2A  0x27   15      9T     M1,write       write          240T       /4
   2    0x2B  0x2F   15     11T     M1,write       write          176T       /3
   3    0x2C  0x3B   15     14T     M1,write       write          176T       /3
```

`doc-div` is the public port-`0x2F` divisor decode. It is not an emulator claim.
Compare the three pinned implementations, including ignored MAME writes, with:

```sh
nix develop -c python tools/describe_bus_timing.py --compare
nix develop -c python tools/describe_bus_timing.py --compare --json
```

Pass `--extra-speeds` to model Wabbitemu's external 20/25 MHz option. The flag
does not describe the default TI-84 Plus configuration.

Repeated `--write PORT=VALUE` options make altered settings explicit. JSON is
available for scripts:

```sh
nix develop -c python tools/describe_bus_timing.py \
  --write 0x20=0 --write 0x29=0x17 --write 0x2e=0x45 --json
```

The executed initialization can be recovered from a full boot trace:

```sh
nix develop -c python tools/tilem_trace_resolve.py /tmp/boot.trace \
  --initial-mapping ti84p-reset --io-ports 20,29-2f
```

## Open physical tests

The read-only [ASIC register snapshot](hardware-probes.md#asic-register-snapshot)
captures ports `0x20`, `0x29`–`0x2C`, `0x2E`, and `0x2F` before a mutating
timing test. It does not measure any delay. No physical snapshot is recorded.
[confirmed] for the probe bytes; [hypothesis] for pending readback values.

- Count fixed Flash and RAM loops while toggling each port-`0x2E` bit. Separate
  M1 fetches, data reads, and writes, and include one- and two-prefix opcodes.
- Repeat the loop test with active-register gate bits 0 and 1 cleared to verify
  whether they disable all corresponding `0x2E` effects.
- Measure the interval from LCD writes and reads to port-`0x02` bit 1 becoming
  ready. This distinguishes TilEm's every-access restart from Wabbitemu's
  write-based model.
- Find the lowest reliable ports-`0x29`–`0x2C` values for each LCD controller
  revision without assuming the published `0x0C` threshold is universal.
- Drive a programmable timer from a `0xC0`-family source and measure the
  port-`0x2F` divisor in each CPU-speed mode.
- Compare nominal and measured T-state wall times on TA2 and TA3 ASICs.

## Sources

| Source | Use |
|--------|-----|
| OS 2.55MP `3F:41BD`–`41D3` and resolved boot trace | boot register values, write order, and later CPU-speed transitions |
| [WikiTI ports `0x29`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:29), [`0x2A`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:2A), [`0x2B`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:2B), and [`0x2C`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:2C) | speed selection, gate bits, LCD instruction delay, and published failure thresholds |
| [WikiTI port `0x2E`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:2E) | six memory-access classes and prefix observation |
| [WikiTI port `0x2F`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:2F) | LCD-ready intervals and mode-3 timer prescaler |
| [TilEm `x4_io.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_io.c), [`x4_memory.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_memory.c), and [`x4_init.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_init.c) | delay decode, cycle placement, ready timer, and reset defaults |
| [Wabbitemu `83psehw.c`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/hardware/83psehw.c) and [`core.c`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/core/core.c) | independent delay decode, cycle placement, and readiness comparison |
| [MAME 0.287 `ti85.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85.cpp) and [`ti85_m.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85_m.cpp) | mapped I/O ports, raw speed readback, binary clock selection, and absent delay block |
