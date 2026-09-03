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
| Guarded Wabbitemu `--asic-edge-probe` run | Initialized-core status, identity, protected-write, internal-field, readback, and GPIO-map observations [standard] |
| Guarded Wabbitemu `--protection-port-probe` run | Shared write gate and internal-field behavior for ports `0x22`–`0x26` [standard] |
| Guarded MAME ASIC-control run | Raw Flash-gate status, identity, speed, port-`0x21`, missing protection/GPIO ranges, USB constants, and soft-reset retention [standard] |

The static I/O scanner reports candidates from a linear disassembly. Data can
decode as instructions, so a candidate needs control-flow or trace evidence.
The credible code for these ports is concentrated in page `00`, pages `2F`,
`33`, `35`–`37`, `3C`, `3D`, and the retail boot page `3F`. [confirmed]

## Complete ROM I/O candidate audit

### Unlisted immediate ports

A full linear scan of the 1 MiB retail ROM finds 35 aligned immediate-port
candidates whose 21 apparent port values are absent from the project port map.
This count removes inline bcall and bjump descriptors. None establishes an I/O
operation. [confirmed]

| Candidate locations | Apparent ports and directions | Classification |
|---------------------|-------------------------------|----------------|
| `01:4304`, `01:446A`, `01:446E`, `01:4C5A`, `01:556D`, `01:6E55`, `01:6E95`, `01:7CD6` | `0x49` OUT; `0x4E` IN/OUT; `0x5E` IN ×2; `0x6E` IN; `0x70` OUT; `0xFF` OUT | table-shaped data ×8 |
| `03:630B`, `03:6323`, `03:634F`, `03:6367`, `03:656F` | `0xFE` IN ×2/OUT ×2; `0x65` IN | table-shaped data ×5 |
| `03:6DE1` | `0x9C` IN | operand overlap in `LD HL,0x9CDB` at `03:6DE0` |
| `07:4076` | `0xD1` OUT | table-shaped data |
| `33:4010` | `0x6B` OUT | table-shaped data |
| `34:6CF5`, `34:6CF7`, `34:73AB`, `34:73AD` | `0x6D` OUT ×2; `0x73` IN ×2 | table-shaped data ×4 |
| `37:6A9C`, `37:6B14` | `0x6B` IN ×2 | table-shaped data ×2 |
| `38:6A00` | `0xDC` IN | table-shaped data |
| `3A:7D81`, `3A:7FED` | `0x5E` IN; `0xDB` IN | table-shaped data ×2 |
| `3B:47B9`, `3B:4F45`, `3B:52AE`, `3B:535C`, `3B:5467` | `0x6F` OUT; `0x51` OUT; `0x6E` IN; `0x5D` IN; `0x6D` IN | table-shaped data ×5 |
| `3F:40FC`, `3F:4111`, `3F:56F7`, `3F:671B`, `3F:67F7` | `0x5E` OUT; `0x63` IN; `0xD1` IN; `0xE7` OUT; `0xE6` IN | table-shaped data ×5 |

The rebuilt Ghidra database gives the 34 table candidates no containing
function and no xrefs. A page-local direct `CALL`/`JP` scan also finds no
target to any candidate. Ghidra places `03:6DE1` inside
`editbuf_clr_hibit`, but the owning instruction starts at `03:6DE0`; bytes
`DB 9C` are the little-endian operand of `LD HL,0x9CDB`. [confirmed]

A reset/idle TLMT trace executes 1,753,851 instructions and reaches none of the
35 locations. This trace result covers one emulator scenario. The byte and
control-flow classifications, rather than trace absence, establish that these
linear candidates do not add ports to the ROM inventory. [confirmed]

### Register and block I/O

A separate raw-byte scan finds every `ED`-prefixed register and block-I/O
opcode pair. It does not depend on recovering the value of `C` across calls or
control-flow joins. The exact retail ROM contains 37 pairs and no `ED` prefix
at a 16 KiB page boundary. [confirmed]

| Raw pairs | Classification | Evidence |
|-----------|----------------|----------|
| `37:58A9` (`INI`), `37:5944` (`OUTI`) | resolved instructions ×2 | Straight-line loads select RTC ports `0x48` and `0x44`; both instructions belong to page-`37` functions. |
| `04:4178`, `04:4182`, `04:6F5B`, `05:40E7`, `05:428C`, `05:46E5`, `05:7159`, `05:715F`, `38:57AC`, `38:57D7`, `38:57F5`, `38:589F`, `38:75AF`, `39:73B7`, `3C:4EFE`, `3C:53E2`, `3C:783B`, `3C:7F99`, `3F:540E`, `3F:5C92`, `3F:63E0`, `3F:6C1A`, `3F:6C2A`, `3F:6C37`, `3F:6C54`, `3F:6C70`, `3F:6C90` | operand overlaps ×27 | Each `ED xx` pair straddles a little-endian operand inside an owning `CALL`, `JP`, or `LD` instruction. |
| `01:428C`, `07:4465`, `38:40C4`, `38:48B4`, `39:7268`, `3B:4F15`, `3F:408D`, `3F:567B` | reviewed data ×8 | Rebuilt Ghidra has no containing function or xref, and the page-local direct-target scan finds no target. |

The 27 operand sites include `ED 41` inside `JP Z,0x41ED` at `04:4177`,
`ED 70` inside `CALL 0x70ED` at `04:6F5A`, and `ED 40` inside
`LD HL,0x40ED` at `39:73B6`. The scanner resolves the two aligned
instructions from their preceding literal loads and `DEC C`. No other raw pair
is an I/O instruction, so this ROM has no hidden computed-`C` access to an
unlisted, status, GPIO, or USB port. [confirmed]

`tools/ti84re/rom/io_coverage.py` contains the reusable scanner and review manifest.
The manifest pins retail ROM SHA-256
`7d9a7d96d89fc552ebee6afdbdd011fdc6047be9c16d308245dff07eb1f7bd6d`.
The CLI fails on a different ROM, a missing or duplicate review, a stale
location, or changed instruction bytes. `--trace` uses the constant-memory
point counter instead of constructing an object for every instruction:

```sh
nix develop -c python3 -m ti84re.rom.describe_io_coverage
nix develop -c python3 -m ti84re.rom.describe_io_coverage --json
nix develop -c python3 -m ti84re.rom.describe_io_coverage \
  --trace /tmp/trace-benchmark.tlmt
```

The complete direct result is 34 `reviewed-data` entries and one
`operand-overlap`. The indirect result is 27 `operand-overlap`, eight
`reviewed-data`, and two `resolved-instruction` entries. Both manifests have
zero unresolved candidates. [confirmed]

## Port `0x02` status

Port `0x02` combines transient hardware state with model-family bits. The boot
and archive traces return `0xE1`, `0xE3`, and `0xE7`. [confirmed]

| Bit | ROM use or public meaning | Evidence |
|-----|---------------------------|----------|
| 0 | Battery comparator result. `_Chk_Batt_Low` tests it at `00:0D20`; `_Chk_Batt_Level` tests it at `33:4EA3` and `33:4EE8`. | [confirmed] for the tested bit; [standard] for the electrical “battery good” polarity |
| 1 | LCD-ready state. LCD wait loops continue while this bit is zero. | ROM wait helpers and the dynamic `0xE1` → `0xE3` transition [confirmed] |
| 2 | Flash-unlocked state. The archive trace changes `0xE3` to `0xE7` after the port-`0x14` unlock sequence. No direct status consumer in this ROM tests it. | [confirmed] for the observed state; [hypothesis] for any OS use outside the audited direct reads |
| 3 | No meaning established. No direct status consumer in this ROM tests it. | [hypothesis] |
| 4 | No meaning established. No direct status consumer in this ROM tests it. | [hypothesis] |
| 5 | Publicly documented as USB-capable. Both emulators set it for their TI-84 Plus model, but this ROM does not test it directly. | [standard] |
| 6 | Publicly documented as link-assist available. Both emulators set it for their TI-84 Plus model, but this ROM selects assist code through bit 7. | [standard] for the published field; [confirmed] for the ROM gate |
| 7 | Advanced-family/model gate. `ram:1837` tests this bit before several TI-84 Plus-only paths. The certificate accessor at `3D:5247` selects the App-trial table at offset `0x1E50` when the bit is set and the alternate table at `0x1F18` when clear. | [confirmed] for the branches and table use; [standard] for the family label |

| Value | Bit-level interpretation |
|-------|--------------------------|
| `0xE1` | Comparator high, LCD wait active, Flash locked, and bits 5–7 set [confirmed] |
| `0xE3` | Comparator high, LCD ready, Flash locked, and bits 5–7 set [confirmed] |
| `0xE7` | Comparator high, LCD ready, Flash unlocked, and bits 5–7 set [confirmed] |

### `_NZIf83Plus` model probe [confirmed]

`_NZIf83Plus = 0x50E0`, body `ram:1837`, preserves `BC` and the caller's `A`
while returning its result only in the flags. It reads port `0x02`, masks bit
7, and XORs with `0x80`. Bit 7 set therefore returns Z; bit 7 clear returns NZ.
The historical name should not be read as “NZ on every TI-83 Plus-family
calculator.” OS 2.55MP uses the flag to distinguish the advanced TI-84 Plus
path from the older family path.

A controlled trace enters with `A = 0xA5`, returns with the same `A`, and
records Z set on the TI-84 Plus model. The reduced result is in
`tools/data/community-manual-bcall-traces.csv`. [confirmed] under TilEm.

### Complete direct-consumer audit

The 1 MiB ROM contains exactly 55 raw `DB 02` byte pairs, the opcode and
operand for `IN A,(0x02)`. Every linear-disassembly candidate reaches one of
three conservative A-register consumers within two following instructions:
[confirmed]

| Consumer mask | Sites | ROM role and anchors |
|--------------:|------:|----------------------|
| `0x01` — bit 0 | 8 | battery comparisons, including `_Chk_Batt_Low` at `00:0D20` and `_Chk_Batt_Level` at `33:4E9F` and `33:4EE6` |
| `0x02` — bit 1 | 3 | LCD-ready waits at `00:0CC4`, `00:0CDC`, and `3F:744F` |
| `0x80` — bit 7 | 44 | family-specific paging, keypad, link-assist, Flash, and boot paths; `ram:1839` is the shared model probe |

The `33:4E9F` battery path inserts `LD C,0` before `BIT 0,A`. Every other
candidate tests `A` in the next instruction. The decoder crosses only
instructions that preserve `A`; calls, branches, arithmetic, and unknown
instructions produce an unclassified result. This ROM produces zero
unclassified candidates. [confirmed]

No status read selects bits 2–6. The complete raw register/block-I/O census
finds no port-`0x02` access beyond these 55 immediate reads. This result does
not depend on propagating `C` across a call or control-flow merge. [confirmed]

The assist routines therefore use bit 7 as their model-family gate. Public
bit 6 remains a hardware capability field, but OS 2.55MP does not consult it
before the link-assist port accesses described in
[USB ASIC and link assist](sub-usb-asic.md#sending-one-byte-through-the-assist-fifo-confirmed).

TilEm computes bits 0–2 from its battery value, LCD wait timer, and Flash lock.
Wabbitemu does the same except that its TI-84 Plus battery result is fixed high.
Their agreement supports the interpretation but does not replace a voltage or
timing measurement. [standard]

The certificate-tail use gives bit 7 a concrete persistent-data consequence.
The model-selected clear, write, and query paths call `3D:5247`; the helper
calls `ram:1837`, selects offset `0x1E50` for the TI-84 Plus trace values above,
and selects `0x1F18` when bit 7 is clear. Wabbitemu independently makes the
same family split, setting bit 7 for its TI-84 Plus models and clearing it for
its TI-83 Plus family. [confirmed] for the ROM branch and resolved TI-84 Plus
values; [standard] for the emulator family mapping.

MAME returns `0xC3 | (m_flash_unlocked << 2)`, truncated to one byte. Its
comparator and LCD-ready bits are fixed high. The normal gate values zero and
one therefore return `0xC3` and `0xC7`. The handler does not normalize other
bytes: writes `02`, `3F`, `40`, and `FF` return `CB`, `FF`, `C3`, and `FF`.
Port `0x14` remains write-only and reads zero. Bit 5 is fixed low for the
normal locked status, so this TI-84 Plus driver reports link assist but not USB
capability. These are emulator inconsistencies, not evidence for a different
ASIC status layout. [standard]

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

This mapping conflicts with the ROM's comparison order. Whenever the later
`0x46` comparison succeeds at 3.9 V or above, the earlier `0x86` comparison at
3.6 V has already returned level 3. Result 2 is therefore unreachable in that
emulator model. Physical measurements must establish the actual selector
ordering, thresholds, hysteresis, and load conditions. [confirmed] for the
code/model comparison; [hypothesis] for the unmeasured electrical behavior.

### Pinned TilEm comparator sweep

A guarded direct-core run sets TilEm's battery field from 3.0 through 4.5 V in
0.1 V steps. For each value, it writes all four selectors through port `0x04`
and reads port-`0x02` bit 0. The observed comparator mask uses bit order
`0x06`, `0x46`, `0x86`, `0xC6`: [standard]

| Modeled voltage | Comparator mask | ROM bcall result |
|-----------------|----------------:|-----------------:|
| below 3.3 V | `0x0` | 0 |
| 3.3–3.5 V | `0x1` | 1 |
| 3.6–3.8 V | `0x5` | 3 |
| 3.9–4.2 V | `0x7` | 3 |
| 4.3 V and above | `0xF` | 4 |

The native mask transitions match the four source constants. The reusable
model then applies the byte-verified decision tree at `33:4E9B`–`4EDA`.
The combination reaches levels 0, 1, 3, and 4, but not level 2. The probe
binary has SHA-256
`47008d660c7ea3e88c07df3d41d5c3e34c51d49850a806d5d2e37d5ca6214029`.
This run validates TilEm's implementation; it does not measure a calculator's
battery rail. [confirmed] for the ROM tree; [standard] for the emulator run.

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
execution-protection ports controlled by that field. A native locked write of
`0x33` reads back `0x03`; opening the port-`0x14` gate does not change results
for writes `0x30`, `0x03`, `0x33`, or `0xFF`. [standard]

### Complete immediate-I/O audit

The ROM contains 11 raw `DB 21` pairs and three raw `D3 21` pairs. Ten reads
are instructions, and every one immediately executes `AND 0x03`. The boot
write at `3F:41DC` is the only `OUT (0x21),A` instruction. [confirmed]

| Read sites | Consumer |
|------------|----------|
| `00:02AE`, `00:1831`, `00:2B32`, `00:2B5B` | `AND 0x03` |
| `2F:4DD5`, `2F:511D`, `36:5E90` | `AND 0x03` |
| `3C:6BA8`, `3C:7F0C`, `3D:7392` | `AND 0x03` |

The remaining three raw pairs overlap other instructions: [confirmed]

| Raw pair | Owning instruction | Why it is not I/O |
|----------|--------------------|-------------------|
| `06:5A10` — `DB 21` | `06:5A0D: LD (IX-1),0xDB` | The `DB` byte is the stored immediate; `21` begins the following `LD HL` instruction. |
| `05:6C96` — `D3 21` | `05:6C95: JR Z,05:6C6A` | The `D3` byte is the relative displacement; `21` begins the following `LD HL` instruction. |
| `3C:5B91` — `D3 21` | `3C:5B90: JR 3C:5B65` | The `D3` byte is the relative displacement; `21` begins the following `LD HL` instruction. |

The rebuilt Ghidra database confirms instruction ownership for these
boundaries. The raw scanner reports zero unclassified pairs and zero decoded
instructions without a matching opcode pair. The conservative literal-`C`
resolver finds no additional port-`0x21` access. [confirmed]

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

### Complete immediate-I/O audit

Raw-byte coverage separates GPIO code from accidental opcode pairs:
[confirmed]

| Port and direction | Raw pairs | Reviewed instructions | Other raw pairs |
|--------------------|----------:|----------------------:|-----------------|
| `IN (0x39)` | 14 | 13 | `02:5142` is table-shaped data with no function or xrefs. |
| `OUT (0x39)` | 16 | 16 | none |
| `IN (0x3A)` | 21 | 19 | `06:5A8D` and `3C:7365` overlap operands. |
| `OUT (0x3A)` | 17 | 17 | none |

The two `DB 3A` overlaps begin on an `0xDB` operand byte. At `06:5A8C`, the
owner is `CP 0xDB`; at `3C:7364`, the owner is a relative `JR` whose
displacement is `0xDB`. In both cases, `0x3A` begins the following `LD A,(nn)`
instruction. [confirmed]

Of the 13 port-`0x39` reads, every one begins an adjacent read-modify-write.
The 16 writes comprise those 13 updates and three direct `0xF0` writes at
`ram:0D39`, `37:6D10`, and `3F:4214`. Port `0x3A` has 17 adjacent
read-modify-write sequences. Its remaining two reads test bit 3 at `2F:521B`
and `35:402C`. The page-`35` body duplicates the page-`2F` USB implementation.
[confirmed]

TilEm lacks a meaningful TI-84 Plus port-`0x3A` model, Wabbitemu lacks port
`0x39`, and MAME maps neither port. Emulator execution can check control flow
around these instructions, but it cannot validate the paired GPIO state or
electrical effect. The sequences below are byte- and control-flow-validated
against the ROM; their physical signal interpretation remains unmeasured.
[confirmed] for the instructions; [hypothesis] for electrical behavior.

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

**Native Wabbitemu confirmation.** The guarded initialized-core probe reads port `0x02` as `0xE3` while the in-memory Flash gate is locked and as `0xE7` after directly opening that gate. With Wabbitemu's TI-84 Plus model, port `0x15` reads `0x44` at RAM revision 0 and `0x55` at RAM revision 2. [standard]

Port `0x21` is active and protected. A write of `0x33` while Flash remains locked is rejected, leaving both internal fields and readback zero. After the probe directly opens the in-memory gate, writing `0x30` stores internal RAM execution mode 3 but reads back `0x00`. Writing `0x03` stores Flash group 3 and reads `0x03`. Writing `0x33` stores both internal fields while still reading `0x03`. This run exercises the protected device handler, not the retail ROM's port-`0x14` unlock sequence. [standard]

A separate initialized-core run verifies the same locked-write rejection for
every port from `0x22` through `0x26`. It also checks the Flash-bound low-byte
handlers, port-`0x24` high-field clearing, and the 16-bit RAM-bound wrap. See
[Execution protection](execution-protection.md#native-protected-register-confirmation)
for the complete value matrix and evidence limits. [standard]

The same initialized core has no active device at port `0x39`; a read is rejected and produces the device layer's `0xFF` fallback. Port `0x3A` is active, starts at zero, and reads back complete `0xA5` and `0x5A` writes. The run advances zero T-states and does not assign electrical direction or signal meaning to either GPIO port. [standard]

**Native MAME confirmation.** The guarded run reads startup values `C3`, `00`,
`33`, `00`, and `00` from ports `0x02`, `0x14`, `0x15`, `0x20`, and `0x21`.
The raw gate sweep produces `C3 C7 CB FF C3 FF` for writes
`00 01 02 3F 40 FF`. Port `0x14` reads zero after every write. [standard]

Ports `0x22`–`0x2F` and `0x39`–`0x3A` return zero before and after patterned
writes. A 50-T-state counter continues executing from RAM while port `0x21`
reads `0x03` and ports `0x22`–`0x26` retain no written byte. The five-frame
counter records 12,000 iterations at the zero speed value and 30,000 at the
nonzero value. This checks one RAM execution path, not the missing physical
boundary rules. [standard]

A scheduled MAME soft reset begins at `PC = 0x0000` but retains a gate value of
one, raw speed `0x03`, and the port-`0x21` nibble from write `0xAB`. The reads
are consequently `0xC7`, `0x03`, and `0x0B` after reset. The driver reset
routine does not restore these fields. This is MAME reset behavior and does
not establish calculator warm-reset retention. [standard]

## Emulator comparison

The four pinned implementations disagree on several control groups not already
established by ROM use. Their values are test oracles for the software, not
physical ASIC measurements.

| Area | TilEm `f56ad63` | Wabbitemu `48c2dc0` | MAME 0.287 | jsTIfied `20170706a` |
|------|-----------------|----------------------|------------|-----------------------|
| Port `0x02` | dynamic comparator, LCD-ready, and Flash lock; family bits 5–7 set | same layout, with the TI-84 Plus comparator fixed high | `0xC3 | (raw gate << 2)`, truncated to a byte | fixed family/battery baseline plus LCD-ready and Flash-lock fields |
| Port `0x15` | fixed `0x45` | model and RAM-revision dependent | fixed `0x33` | model-dependent identity value |
| Port `0x21` accepted readback | `value & 0x33`, subject to Flash unlock | only bits 0–1 survive its read defect | `value & 0x0F`, without protected-write gating | stored while Flash-unlocked and used for page-level execution groups |
| GPIO | port `0x39` fixed at `0xF0`; no meaningful TI-84 Plus port `0x3A` | port `0x3A` latch; port `0x39` absent | both ports absent | software latches without physical GPIO modeling |
| Driver status | usable model with unmeasured battery thresholds | usable model with implementation-specific defects | TI-84 Plus marked `MACHINE_NOT_WORKING` | browser emulator source model |

## Reusable analysis tools

`tools/ti84re/hardware/asic_control.py` decodes port-`0x02` values, generic immediate-port
consumers and raw-opcode coverage, the public port-`0x15` table, port-`0x21`
modes, TilEm's battery selector, and adjacent GPIO read-modify-write sequences.
Its raw audit distinguishes aligned instructions, operand overlaps, reviewed
data, and unclassified pairs. `tools/ti84re/hardware/describe_asic_control.py` exposes those
operations as text or JSON. `tools/ti84re/emulators/wabbitemu/asic_probe.py` validates
native results against the reusable source model.
`tools/ti84re/rom/io_coverage.py` and `tools/ti84re/rom/describe_io_coverage.py` separately
reconcile every direct candidate for ports absent from the project port map.
`tools/ti84re/emulators/wabbitemu/run_asic_edge_probe.py`
guards the exact ROM and native binary identities and writes a JSON manifest.
`tools/ti84re/emulators/wabbitemu/protection_port_probe.py` applies the adjacent boundary-port
model from `tools/ti84re/hardware/execution_protection.py`; its guarded CLI records the same
two identities. `tools/ti84re/emulators/mame/asic.py` combines the ASIC and bus-timing profiles
with a typed native report. `tools/ti84re/emulators/mame/run_asic_probe.py` guards the MAME,
ROM, and Lua identities and retains the soft-reset output.
`tools/ti84re/hardware/battery.py` formalizes the ROM result tree and threshold
regions. `tools/ti84re/hardware/describe_battery.py` exposes voltage and raw-sample
queries as text or JSON. `tools/ti84re/emulators/tilem/battery.py` validates a typed native
comparator sweep against the same model.
[confirmed] for the ROM-analysis tools; [standard] for the emulator oracle.

```sh
nix develop -c python3 -m ti84re.hardware.describe_asic_control
nix develop -c python3 -m ti84re.hardware.describe_asic_control --status 0xE7 --port21 0x20
nix develop -c python3 -m ti84re.hardware.describe_asic_control --implementations --json
nix develop -c python3 -m ti84re.hardware.describe_asic_control \
  --scan-status-consumers --json
nix develop -c python3 -m ti84re.hardware.describe_asic_control \
  --scan-port21-consumers --scan-gpio --json
nix develop -c python3 -m ti84re.hardware.describe_asic_control \
  --audit-port 0x21 --audit-port 0x39 --audit-port 0x3A
nix develop -c python3 -m ti84re.rom.analyze_io \
  0x02 0x15 0x21 0x39 0x3A --summary
nix develop -c python3 -m ti84re.rom.disassemble 0x33 \
  --start 0x4E9B --end 0x4F02
nix develop -c python3 -m ti84re.hardware.describe_battery --json
nix develop -c python3 -m ti84re.hardware.describe_battery --voltage 3.6
nix develop -c python3 -m ti84re.hardware.describe_battery --samples 1010

asic_probe_parent=$(mktemp -d /tmp/ti84-asic-probe.XXXXXX)
nix develop -c python3 -m ti84re.emulators.wabbitemu.run_asic_edge_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$asic_probe_parent/run" --json

protected_port_parent=$(mktemp -d /tmp/ti84-protected-port.XXXXXX)
nix develop -c python3 -m ti84re.emulators.wabbitemu.run_protection_port_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$protected_port_parent/run" --json

mame_asic_parent=$(mktemp -d /tmp/ti84-mame-asic.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_asic_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_asic_parent/run" --json
```

The I/O and GPIO scans generate candidates. A report becomes evidence for code
only after raw-byte and control-flow review or a resolved execution trace.

## Open physical tests

The read-only [ASIC register snapshot](hardware-probes.md#asic-register-snapshot)
captures ports `0x15`, `0x21`, `0x39`, and `0x3A` without changing GPIO
configuration or data. It provides a baseline, not an electrical direction
test. No physical snapshot is recorded. [confirmed] for the probe bytes;
[hypothesis] for pending readback values.

- Run the restoring [battery-level probe](hardware-probes.md#battery-level-probe)
  across an upward and downward controlled-supply sweep. It records 16 retail
  bcall results per point and verifies port/GPIO/flag cleanup. Run the
  higher-risk [raw battery-selector probe](hardware-probes.md#raw-battery-selector-probe)
  after it at each voltage point. The second result records all four comparator
  bits so the sweep can assign individual selector thresholds and hysteresis.
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
| [jsTIfied deployed `20170706a` artifact](https://www.cemetech.net/projects/jstified/jstified_compressed.js?20170706a) and [readable mirror](https://github.com/Quuxplusone/ti83/blob/56246a1181f90123a843ea17eb9e0f2fcda65113/jstified.js) | fourth status, identity, protected-write, execution-group, and software-GPIO model |
