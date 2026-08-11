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
| Native Wabbitemu execution | reset state, speed masks and frequencies, all seven delay latches, wait-gate selection, and port-`0x2D` side effects | [standard] |
| MAME 0.287 source | binary CPU-speed selection and absence of the delay-register block | [standard] |
| Guarded MAME ASIC-control run | raw speed readback, measured 6:15 instruction throughput, absent delay ports, and soft-reset retention | [standard] |
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

TilEm reads back the last byte written to ports `0x29`–`0x2C`, `0x2E`, and
`0x2F`. Wabbitemu registers one generic latch handler across the complete
`0x29`–`0x2F` range. Its port `0x2D` therefore stores a raw byte instead of
implementing the separate low-power contract. MAME maps only port `0x20` from
this block; its I/O map has no handler for the six delay-register writes.
[standard]

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

A guarded initialized-core run writes `0xFC`–`0xFF`. The reset
`timer_version = 0` context reads back modes `0/1/1/1` at 6, 15, 15, and
15 MHz. Directly setting `timer_version = 1` produces modes `0/1/2/3` at 6,
15, 20, and 25 MHz. The direct setting represents Wabbitemu front-end state;
it is not a calculator port transition. [standard]

A guarded MAME run writes `00`, `01`, `02`, `03`, and `FF` to port `0x20` and
reads the same five raw bytes back. A 50-T-state RAM counter advances 12,000
times during five 20 ms frames after write zero and 30,000 times after write
one. The exact 2.5 ratio dynamically distinguishes 6 MHz from 15 MHz. A MAME
soft reset retains raw speed `0x03`; this is driver behavior, not a calculator
reset claim. [standard]

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
below. A native patterned-write run reads zero from every port `0x29`–`0x2F`
both before and after the writes. [standard]

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

A CB-, ED-, DD-, or FD-prefixed Z80 instruction performs two M1 fetches. Both
TilEm and Wabbitemu apply the opcode wait to the prefix and following opcode.
A repeated DD or FD prefix adds another M1 fetch in both cores. [standard] for
the Z80 bus cycle and pinned emulator source paths.

Indexed CB instructions expose a model difference. The Z80 fetches DD or FD
and CB with M1 signaling, then reads the displacement and final opcode without
M1. TilEm follows this split in `z80main.h:674` and `z80ddfd.h:301`.
Wabbitemu routes the final opcode through `CPU_opcode_fetch` at `core/core.c:832`,
then decrements `R` at line 836. Its wait model therefore counts three opcode
waits while its visible refresh count remains two. The hash-guarded
`describe_prefix_fetch_models.py` CLI reproduces this result from the pinned
source trees. The exact assembled `HWPFX` program also reproduces the split in
the pinned Wabbitemu runtime: its indexed-CB row adds 30 timer ticks, compared
with 25 for the three ordinary one-prefix rows and 29 for repeated DD.
[confirmed] for the emulator run; physical ASIC placement remains open.

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

The guarded Wabbitemu initialized-core run sets speed mode 1 and field 3, then
writes the LCD at T-state 2,000. Port `0x02` reads `0xE1` at T-state 2,240 and
`0xE3` at 2,241. An accepted status read at 2,241 leaves the write timestamp at
2,000 and leaves port `0x02` at `0xE3`. The comparison is strict rather than
inclusive: readiness requires elapsed time greater than 240 T-states in this
implementation. [standard]

## Programmable-timer mode-3 divisor

Public documentation assigns a second role to the selected port-`0x2F` field.
For programmable-timer sources in the `0xC0` family, the field selects divisor
$f+1$; speed mode 0 applies no divisor. [standard]

With the OS byte `0x4B`, the documented divisors are 1, 4, 3, and 3 for speed
modes 0–3. TilEm treats the `0xC0` family like its ordinary CPU-clock modes,
and Wabbitemu's timer-source update does not use port `0x2F`. The prescaler is
therefore absent from both compared emulator paths. [standard]

OS 2.55MP's timer API can select `0xC0`-family sources. The prepared
[`HWTMR` probe](hardware-probes.md#programmable-timer-physical-probe) counts
source-`0xE0` expiries against a crystal reference in CPU-speed modes 0–3. Its
exact assembled image completes in pinned Wabbitemu and measures a prescaler
near one, matching that emulator's source implementation. No result from a
physical calculator has been recorded. [confirmed] for the probe and emulator
run; [hypothesis] for the physical divisor.

## Emulator comparison

| Behavior | TilEm | Wabbitemu | MAME 0.287 |
|----------|-------|------------|------------|
| Port-`0x20` write | low two bits select modes 0–3; nonzero runs at 15 MHz | default TI-84 Plus state clamps modes 2–3 to mode 1; external `extraSpeed` enables 20/25 MHz | stores the raw byte; zero selects 6 MHz and any nonzero value selects 15 MHz |
| Active `0x29`–`0x2C` register | indexed by port `0x20 & 3` | indexed by the accepted CPU-speed mode | registers absent |
| LCD instruction addition | active byte shifted right by two | same | absent |
| Memory gates and `0x2E` bits | all six access classes | all six access classes | absent |
| Port `0x2D` | low-power control outside this block | raw fifth delay latch; no timer or low-power transition | absent |
| High-speed ready start | every LCD-port read or write | last successful LCD write | programmable interval absent |
| LCD controller rejection | ready bit and controller model | also has a separate fixed 60-T-state controller-access guard | T6A04 device behavior without the ASIC delay block |
| Mode-3 timer prescaler | not modeled | not modeled in the compared timer path | not modeled |

The matching memory and LCD-instruction decode corroborates the public bit
layout. MAME cannot corroborate that decode because it omits the block. The
readiness, speed, and timer differences remain emulator policy, not proof of
physical timing.

The same guarded Wabbitemu run dynamically checks three linked cases. Port
`0x2A = 0x27` adds nine T-states to a status read. With port `0x2E = 0x45`, the
enabled additions are Flash opcode fetch, Flash write, and RAM write. A write
of speed value 3 reads back mode 1 in the reset TI-84 Plus context because
`timer_version = 0` disables the external extra-speed modes. [standard]

A dedicated speed run reads all seven reset latches as zero and verifies raw
byte readback across ports `0x29`–`0x2F`. With active-register values
`0x00/0x01/0x02/0x03` and port `0x2E = 0x77`, modes 0–3 produce wait masks
`0x00/0x07/0x38/0x3F`: none, all Flash classes, all RAM classes, and all six
classes.
Writing `0x5A` to port `0x2D` changes only that latch. The active wait mask,
CPU frequency, timer version, programmable-timer state, LCD-active state,
`HALT`, interrupt line, and T-state count remain unchanged. These observations
describe Wabbitemu's registered handler, not physical low-power behavior.
[standard]

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

Run the native boundary checks with the pinned Wabbitemu adapter:

```sh
wabbit_lcd_parent=$(mktemp -d /tmp/ti84-wabbit-lcd.XXXXXX)
python tools/run_wabbitemu_lcd_edge_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_lcd_parent/run" --json

wabbit_speed_parent=$(mktemp -d /tmp/ti84-wabbit-speed.XXXXXX)
python tools/run_wabbitemu_speed_edge_probe.py \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_speed_parent/run" --json

mame_asic_parent=$(mktemp -d /tmp/ti84-mame-asic.XXXXXX)
nix shell nixpkgs#mame --command python tools/run_mame_asic_probe.py \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_asic_parent/run" --json
```

The manifest labels the run as initialized-core emulator evidence and records
both input hashes. `tools/wabbitemu_lcd_probe.py` derives its pointer, latch,
ready-hold, delay, wait-bit, and speed-clamp expectations from the reusable LCD
and bus-timing libraries.

`tools/wabbitemu_speed_probe.py` derives speed, latch, and wait-mask
expectations from `tools/bus_timing.py`. Its guarded CLI records both input
hashes and labels the direct `timer_version = 1` configuration explicitly.
`tools/mame_asic.py` reuses the MAME timing profile for raw readback, binary
clock selection, and the absent delay block.

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

The guarded [memory-bus timing probe](hardware-probes.md#memory-bus-timing-probe)
prepares paired timer-2 measurements for all six access classes. Its counted
loops separate fixed-Flash opcode fetches, Flash data reads, safe Flash reset
writes, RAM opcode fetches, RAM non-opcode reads, and idempotent RAM writes.
It restores the entry timing byte and an initially idle timer 2. No exported
physical result has been recorded. [confirmed] for the probe bytes and decoder;
[hypothesis] for pending measurements.

The guarded [prefix-M1 timing probe](hardware-probes.md#prefix-m1-timing-probe)
prepares paired RAM-M1 measurements for unprefixed, CB, ED, DD, repeated-DD,
and indexed-CB shapes. The indexed-CB row distinguishes TilEm and documented
Z80 M1 placement from Wabbitemu's extra wait. The exact image completes through
the cleanup boundary in pinned Wabbitemu and selects its three-wait model. No
physical result has been recorded. [confirmed] for the probe bytes, decoder,
and emulator run; [hypothesis] for pending measurements.

The guarded [programmable-timer probe](hardware-probes.md#programmable-timer-physical-probe)
prepares the port-`0x2F` mode-3 measurement. It also distinguishes crystal
divisor, counter-zero, and expiry-status models while timers 1 and 2 are idle.
The exact image completes through cleanup in pinned Wabbitemu. No exported
physical result has been recorded. [confirmed] for the probe bytes, decoder,
and emulator run; [hypothesis] for pending measurements.

- Run all three prepared timing matrices on TA2 and TA3 units.
- Repeat the loop test with active-register gate bits 0 and 1 cleared to verify
  whether they disable all corresponding `0x2E` effects.
- Measure the interval from LCD writes and reads to port-`0x02` bit 1 becoming
  ready. This distinguishes TilEm's every-access restart from Wabbitemu's
  write-based model.
- Find the lowest reliable ports-`0x29`–`0x2C` values for each LCD controller
  revision without assuming the published `0x0C` threshold is universal.
- Compare the `HWTMR` port-`0x2F` results across CPU-speed modes and ASIC
  revisions.
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
