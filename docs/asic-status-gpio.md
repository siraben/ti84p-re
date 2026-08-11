# ASIC status, identity, protection, and GPIO

*TI-84 Plus OS 2.55MP — status, battery comparison, protection mode, and GPIO.*

Ports `0x02`, `0x15`, `0x21`, `0x39`, and `0x3A` expose several unrelated
ASIC controls. The ROM establishes how TI-OS uses four of them. Port `0x15`
comes only from public tables and emulator configuration because this ROM does
not read it through an immediate or statically resolved literal-C access.

## Evidence boundaries

The sources answer different questions. Emulator behavior is useful for
constructing tests, but it does not establish electrical behavior on a physical
calculator.

| Source | What it establishes |
|--------|---------------------|
| Retail OS 2.55MP and boot 1.03 bytes | Port operations, masks, branch conditions, bcall targets, and return values [confirmed] |
| Resolved TilEm boot and archive traces | Values observed on port `0x02`, the boot writes to ports `0x21` and `0x39`, and the absence of GPIO-data accesses in those scenarios [confirmed] |
| WikiTI port pages | Public bit names, port-`0x15` identity values, and port-`0x21` size tables [standard] |
| TilEm commit `f56ad63` | One executable model for battery comparison, Flash grouping, and RAM execution masks [standard] for the implementation; [hypothesis] for physical equivalence |
| Wabbitemu commit `48c2dc0` | An independent status and protection model, including implementation defects described below [standard] for the implementation; [hypothesis] for physical equivalence |
| MAME 0.287 | A third implementation with fixed status and identity values, incompatible port-`0x21` masking, and no GPIO ports [standard] |

The static I/O scanner reports candidates from a linear disassembly. Data can
decode as instructions, so a candidate needs control-flow or trace evidence.
The credible code for these ports is concentrated in page `00`, pages `2F`,
`33`, `35`, `37`, and the retail boot page `3F`. [confirmed]

## Port `0x02` status

Port `0x02` combines transient hardware state with model-family bits. The boot
and archive traces return `0xE1`, `0xE3`, and `0xE7`. [confirmed]

| Bit | ROM use or public meaning | Evidence |
|-----|---------------------------|----------|
| 0 | Battery comparator result. `_Chk_Batt_Low` tests it at `00:0D20`; `_Chk_Batt_Level` tests it at `33:4EA3` and `33:4EE8`. | [confirmed] for the tested bit; [standard] for the electrical “battery good” polarity |
| 1 | LCD-ready state. LCD wait loops continue while this bit is zero. | ROM wait helpers and the dynamic `0xE1` → `0xE3` transition [confirmed] |
| 2 | Flash-unlocked state. The archive trace changes `0xE3` to `0xE7` after the port-`0x14` unlock sequence. | [confirmed] |
| 3 | No meaning established for TI-84 Plus OS 2.55MP. | [hypothesis] |
| 4 | No meaning established for TI-84 Plus OS 2.55MP. | [hypothesis] |
| 5 | Publicly documented as USB-capable. Both emulators set it for their TI-84 Plus model. | [standard] |
| 6 | Publicly documented as link-assist available. Both emulators set it for their TI-84 Plus model. | [standard] |
| 7 | Advanced-family/model gate. `ram:1837` tests this bit before several TI-84 Plus-only paths. | [confirmed] for the branch; [standard] for the family label |

| Value | Bit-level interpretation |
|-------|--------------------------|
| `0xE1` | Comparator high, LCD wait active, Flash locked, and bits 5–7 set [confirmed] |
| `0xE3` | Comparator high, LCD ready, Flash locked, and bits 5–7 set [confirmed] |
| `0xE7` | Comparator high, LCD ready, Flash unlocked, and bits 5–7 set [confirmed] |

TilEm computes bits 0–2 from its battery value, LCD wait timer, and Flash lock.
Wabbitemu does the same except that its TI-84 Plus battery result is fixed high.
Their agreement supports the interpretation but does not replace a voltage or
timing measurement. [standard]

MAME returns locked status `0xC3` and adds bit 2 after a Flash-unlock write.
Its comparator and LCD-ready bits are fixed high. Bit 5 is fixed low, so this
TI-84 Plus driver reports link assist but not USB capability. This is an
emulator inconsistency, not evidence for a different ASIC status layout.
[standard]

## Battery comparison

Port `0x04` has two roles on this hardware: its low bits configure mapping and
standard-timer behavior, while bits 6–7 select a battery-comparison setting.
The battery routines keep the low configuration at `0x06` and write `0x46`,
`0x86`, or `0xC6` to change the upper selector. [confirmed] for the writes;
[standard] for the selector interpretation.

### `_Chk_Batt_Low`

The bcall `_Chk_Batt_Low = 0x50B3` resolves to `00:0D07`. A larger entry at
`00:0D04` first runs a RAM-access delay, then performs this sequence: [confirmed]

```z80
00:0D07  IN A,(0x3A)
00:0D09  OR 0x80
00:0D0B  OUT (0x3A),A
00:0D0D  LD A,0x06
00:0D0F  OUT (0x04),A
00:0D11  LD A,0x86
00:0D13  OUT (0x04),A
              ; delay
00:0D20  IN A,(0x02)
00:0D22  BIT 0,A
```

The routine sets `(IY+0x18)` bit 5 before the comparison and clears it when
port `0x02` bit 0 is zero. It restores port `0x04` to `0x06`, writes `0xF0` to
port `0x39`, pulses port-`0x3A` bit 4, clears port-`0x3A` bit 7, then returns
with Z reflecting `(IY+0x18)` bit 5. [confirmed]

| Bcall | ID | Body | Port-`0x04` comparison value |
|-------|---:|------|------------------------------:|
| `_Chk_Batt_Low_B` | `80F0` | `3F:6171` | `0x86` |
| `_Chk_Batt_Low_B2` | `80F3` | `3F:6163` | `0x46` |

Both boot entries set port-`0x3A` bit 7, sample port-`0x02` bit 0, restore
port `0x04 = 0x06`, clear GPIO bit 7, and return Z according to the saved
comparison flag. The public flag file names `(IY+0x18)` as `traceFlags`, so the
bit's wider ownership remains unknown. [confirmed]

### `_Chk_Batt_Level`

The main bcall table resolves `_Chk_Batt_Level = 0x5221` to `33:4E9B`.
The routine returns a value from 0 through 4 in `A`: [confirmed]

| Result | Path |
|-------:|------|
| `0` | The initial port-`0x02` bit-0 test is low, so the routine returns before enabling the GPIO sequence. |
| `4` | The comparison after port `0x04 = 0xC6` is high. |
| `3` | The `0xC6` comparison is low and the `0x86` comparison is high. |
| `2` | The first two comparisons are low and the `0x46` comparison is high. |
| `1` | All three comparisons are low. |

It sets `(IY+0x18)` bit 5 before the first comparison and clears that bit before
the final `0x46` test. Results 1 and 2 therefore leave the bit clear.
The routine restores `0x04 = 0x06`, pulses GPIO bit 4, clears GPIO bit 7, and
returns `C` in `A`. [confirmed]

TilEm maps the two high selector bits to the following thresholds. Its source
labels the table `FIXME: measure actual levels`, so these voltages are emulator
parameters rather than measured ASIC facts. [standard]

| Port-`0x04` value | Selector | TilEm threshold |
|-------------------|---------:|----------------:|
| `0x06` | 0 | 3.3 V |
| `0x46` | 1 | 3.9 V |
| `0x86` | 2 | 3.6 V |
| `0xC6` | 3 | 4.3 V |

This mapping conflicts with the ROM's comparison order. If `0x86` fails at
3.6 V in TilEm, the later 3.9 V comparison at `0x46` cannot succeed. Result 2
is therefore unreachable in that emulator model. Physical measurements must
establish the actual selector ordering, thresholds, hysteresis, and load
conditions. [confirmed] for the code/model comparison; [hypothesis] for the
unmeasured electrical behavior.

## Port `0x15` identity

WikiTI publishes the following read values. They are [standard] because this
OS image does not use the port through an immediate or statically resolved
literal-C I/O instruction.

| Value | Public ASIC reference | USB driver family | Reported RAM |
|-------|-----------------------|-------------------|--------------|
| `0x33` | 83PL2M/TA2 | none | external 128 KiB |
| `0x44` | 83PLUSB/TA2 | old | 128 KiB |
| `0x45` | 84PLUSB/TA3 | new | 128 KiB |
| `0x55` | 84PLC/TA1 | new | 48 KiB |

Wabbitemu returns these values according to its selected model and RAM
revision. TilEm's TI-84 Plus model returns fixed `0x45` with a `???` source
comment. Neither implementation verifies what a particular physical unit
returns. [standard]

MAME's shared TI-83 Plus Silver Edition/TI-84 Plus I/O map returns fixed
`0x33` from port `0x15` for every machine using that map. The TI-84 Plus
configuration therefore identifies itself as the public 83PL2M/TA2 row.
MAME's `MACHINE_NOT_WORKING` declaration and shared handler make this a driver
defect, not an alternate identity claim. [standard]

The complete-ROM scan finds no immediate `IN` or `OUT` instruction for port
`0x15`. The conservative C-register resolver also finds no access after a
straight-line literal load into `C` or `BC`. Computed register-C accesses that
cross calls or control-flow edges remain outside that static proof. [confirmed]

## Port `0x21` Flash grouping and RAM execution mode

Port `0x21` is a writable protected register, not a read-only ASIC identity.
The retail boot page loads `A=0`, executes the protected-byte sequence, and
writes the value at `3F:41DC`. [confirmed]

```z80
3F:41D5  LD A,0x00
3F:41D7  NOP
3F:41D8  NOP
3F:41D9  IM 1
3F:41DB  DI
3F:41DC  OUT (0x21),A
3F:41DE  DI
```

TilEm stores writes only while Flash is unlocked and exposes `value & 0x33`
on reads. Wabbitemu also marks the port protected and stores the same two
fields. Its read handler shifts the stored mode right by four a second time,
so it loses bits 4–5. [standard]

MAME accepts writes without the protected-byte gate, stores `value & 0x0F`,
and returns that nibble. It can therefore expose undocumented bits 2–3 while
discarding the RAM execution field in bits 4–5. MAME does not implement the
execution-protection ports controlled by that field. [standard]

### Bits 0–1: Flash group

The OS repeatedly reads `port 0x21 & 3` to distinguish the 1 MiB TI-84 Plus
configuration from larger family members. The archive App scan at `3D:726E`
selects top page `0x29` when the field is zero and `0x69` for the remaining
advanced-family branch. [confirmed]

| Field | Public size | Highest boot page |
|------:|------------:|------------------:|
| 0 | 1 MiB | `0x3F` |
| 1 | 2 MiB | `0x7F` |
| 2 | 4 MiB | `0xFF` |
| 3 | 8 MiB | `0x1FF` |

WikiTI supplies these configured sizes. TilEm also uses the field as a
Flash-sector protection override group. The physical relation between the
programmed field and chip capacity has not been tested here. [standard] for
the table and model; [hypothesis] for unmeasured hardware.

### Bits 4–5: RAM execution mode

WikiTI describes this field as RAM chip size. The boot writes mode 0 even on a
128 KiB TI-84 Plus. “RAM execution mode” therefore describes the observed use
more precisely than treating it as detected capacity. [confirmed] for the boot
value; [standard] for the public size labels.

TilEm converts the field to one of four repeating masks. Wabbitemu's intended
page shortcut collapses to zero for modes 1–3, so it does not implement the
same arithmetic. Ports `0x25` and `0x26` add inclusive 1 KiB bounds. See
[Execution protection](execution-protection.md#ram-instruction-fetches) for the
equations, complete page coverage, and physical tests. [standard]

## Ports `0x39` and `0x3A` GPIO

The ROM treats port `0x39` as GPIO direction or configuration and port `0x3A`
as GPIO data. It normally updates `0x3A` with read-modify-write sequences so
unrelated bits retain their values. [confirmed]

The direction polarity is not established by the ROM alone. WikiTI's port
`0x39` page says both that clearing and setting a bit designate output, which
is self-contradictory. Its port-`0x3A` page recommends `0xE0`, but this boot
writes `0xF0` at `3F:4214`, and the archive trace later reads back `0xF0` from
port `0x39`. Those public direction claims remain [hypothesis] pending physical
tests.

### Battery GPIO sequence

`_Chk_Batt_Level` provides the clearest GPIO sequence: [confirmed]

1. Set port-`0x3A` bit 7.
2. Run the port-`0x04` comparator tests.
3. Set port-`0x39` bit 4.
4. Set port-`0x3A` bit 4, delay, and clear it.
5. Clear port-`0x3A` bit 7.

The shorter `_Chk_Batt_Low` path writes `0xF0` directly to port `0x39` before
the bit-4 pulse. The ROM confirms that bits 7 and 4 participate in battery
testing. It does not expose the electrical signal names. [confirmed]

### USB GPIO sequence

The boot USB code on page `2F` and the parallel OS code on page `35` use the
low GPIO bits: [confirmed]

| Location | Operation |
|----------|-----------|
| `2F:5330` | Clear port-`0x3A` bit 1, then set port-`0x39` bit 1. |
| `2F:5353` | Clear port-`0x39` bit 1. |
| `2F:538C` | Set the low data bits to binary `100`, then set port-`0x39` bits 0–2. |
| `2F:53AB` | Clear port-`0x3A` bits 0–2, then set port-`0x39` bits 0–2. |
| `2F:53D5` and `2F:593B` | Clear port-`0x39` bits 0–2 during cleanup. |
| `2F:521B` | Test port-`0x3A` bit 3 while selecting a USB state. |

These operations tie GPIO bits 0–3 to USB setup and state selection. The exact
charge-pump, PHY, or cable signals remain [hypothesis]. See
[USB ASIC and link assist](sub-usb-asic.md) for the controller transaction.

### Dynamic and emulator limits

The boot trace writes `0xF0` to port `0x39` but does not access port `0x3A`.
The archive scenario reads and rewrites `0xF0` through port `0x39`; it also does
not reach port `0x3A`. Those traces cover startup and archive work, not battery
level or connected USB workflows. [confirmed]

TilEm's TI-84 Plus model returns fixed `0xF0` from port `0x39` and has no
meaningful write or port-`0x3A` model. Wabbitemu stores port `0x3A` as a latch
but does not register port `0x39`. Both emulators model a color-calculator
backlight side effect for port-`0x3A` bit 5; that does not validate TI-84 Plus
GPIO wiring. [standard]

MAME maps neither port `0x39` nor port `0x3A`. Battery and USB code can execute
through the driver, but those GPIO reads and writes reach no device handler.
[standard]

## Emulator comparison

The three pinned implementations disagree on every control group not already
established by ROM use. Their values are test oracles for the software, not
physical ASIC measurements.

| Area | TilEm `f56ad63` | Wabbitemu `48c2dc0` | MAME 0.287 |
|------|-----------------|----------------------|------------|
| Port `0x02` | dynamic comparator, LCD-ready, and Flash lock; family bits 5–7 set | same layout, with the TI-84 Plus comparator fixed high | fixed `0xC3` when locked; Flash unlock adds bit 2 |
| Port `0x15` | fixed `0x45` | model and RAM-revision dependent | fixed `0x33` |
| Port `0x21` accepted readback | `value & 0x33`, subject to Flash unlock | only bits 0–1 survive its read defect | `value & 0x0F`, without protected-write gating |
| GPIO | port `0x39` fixed at `0xF0`; no meaningful TI-84 Plus port `0x3A` | port `0x3A` latch; port `0x39` absent | both ports absent |
| Driver status | usable model with unmeasured battery thresholds | usable model with implementation-specific defects | TI-84 Plus marked `MACHINE_NOT_WORKING` |

## Reusable analysis tools

`tools/asic_control.py` decodes port-`0x02` values, the public port-`0x15`
table, port-`0x21` modes, TilEm's battery selector, and adjacent GPIO
read-modify-write sequences. `tools/describe_asic_control.py` exposes those
operations as a CLI. [confirmed]

```sh
nix develop -c python tools/describe_asic_control.py
nix develop -c python tools/describe_asic_control.py --status 0xE7 --port21 0x20
nix develop -c python tools/describe_asic_control.py --implementations --json
nix develop -c python tools/describe_asic_control.py \
  --scan-gpio --page 0x2F --page 0x33 --page 0x35 --page 0x3F
nix develop -c python tools/analyze_rom_io.py \
  0x02 0x15 0x21 0x39 0x3A --summary
nix develop -c python tools/disassemble_rom.py 0x33 \
  --start 0x4E9B --end 0x4F02
```

The I/O and GPIO scans generate candidates. A report becomes evidence for code
only after raw-byte and control-flow review or a resolved execution trace.

## Open physical tests

The read-only [ASIC register snapshot](hardware-probes.md#asic-register-snapshot)
captures ports `0x15`, `0x21`, `0x39`, and `0x3A` without changing GPIO
configuration or data. It provides a baseline, not an electrical direction
test. No physical snapshot is recorded. [confirmed] for the probe bytes;
[hypothesis] for pending readback values.

- Sweep a controlled battery supply for all four port-`0x04` selectors. Record
  the port-`0x02` bit-0 transition in both directions to measure threshold and
  hysteresis.
- Read port `0x15` on known TA1, TA2, and TA3 units and compare the result with
  package markings and installed RAM.
- Program each port-`0x21` field while Flash is unlocked. Test Flash protection
  groups and the execution ranges described in
  [Execution protection](execution-protection.md). Do not rely on emulator
  reset behavior.
- Measure port-`0x39` direction polarity and port-`0x3A` electrical state with
  battery and USB paths active. Preserve the OS configuration and avoid driving
  externally forced pins against the ASIC.

## Sources

| Source | Use |
|--------|-----|
| Retail OS 2.55MP and boot 1.03 ROM bytes | Status branches, battery routines, port-`0x21` boot setup, and GPIO operations |
| [WikiTI port `0x02`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:02) | Public status-bit names |
| [WikiTI port `0x15`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:15) | Public ASIC identity table |
| [WikiTI port `0x21`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:21) | Public Flash/RAM size tables and execution-page description |
| [WikiTI ports `0x39`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:39) and [`0x3A`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:3A) | Historical GPIO interpretation, with the contradictions identified above |
| [TilEm `x4_io.c` at `f56ad63`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_io.c) | Battery table, status read, identity constant, protection mode, and fixed GPIO read |
| [Wabbitemu `83psehw.c` at `48c2dc0`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/hardware/83psehw.c) | Independent port models and the port-`0x21` read defect |
| [MAME 0.287 `ti85.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85.cpp) and [`ti85_m.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85_m.cpp) | shared I/O map, fixed status and identity reads, port-`0x21` mask, missing GPIO, and driver status |
