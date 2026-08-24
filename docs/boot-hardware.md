# Retail boot hardware initialization

*TI-84 Plus OS 2.55MP — reset delay, hardware writes, safety checks, and boot diagnostics.*

The retail boot page changes the reset memory map into the OS runtime map,
checks that both RAM windows are writable, programs the ASIC registers, and
selects an OS or recovery path. [Retail boot page](retail-boot.md) maps the
page-level control flow, bcall table, recovery transports, and validation
logic. This page follows `retail_boot_reset_stub` at
`3F:4000` through the first keypad scan at `3F:422D` and decodes
`boot_ram_test` at `3F:461A`. It also documents
`boot_lcd_keypad_diagnostic` at `3F:4658`.

## Evidence boundaries

| Evidence | What it establishes | Confidence |
|----------|---------------------|------------|
| OS 2.55MP page `3F` bytes | instructions, branch targets, port values, safety checks, OS-validity tests, and RAM-test pattern | [confirmed] |
| Rebuilt Ghidra database | function boundaries and cross-references for the keypad, display, OS-validation, and recovery helpers | [confirmed] |
| Full-reset TilEm instruction trace | one executed no-key startup path, ordered I/O values, mapper state, register values, and emulator clocks | [confirmed] for that pinned emulator run |
| Direct-entry Wabbitemu probe | actual page-`3F` LCD helpers executing after a retail boot baseline, plus controller-RAM and contrast effects | [confirmed] for that pinned emulator run; not evidence that retail control flow reaches `3F:4658` |
| Standard Z80 timing tables | instruction timing used for the reset-delay calculation | [standard] |
| Public port descriptions and emulator implementations | proposed electrical roles for the bytes written to link-assist, GPIO, USB, and wait-state ports | [standard] or [hypothesis] as marked on the subsystem pages |
| Physical reset measurements | oscillator startup, electrical register effects, and RAM power-on state | [hypothesis] until measured |

The ROM confirms what software executes. The trace confirms that TilEm follows
one path through those bytes. Neither source measures a physical ASIC reset.

## Reset entry and delay

`retail_boot_reset_stub` at `3F:4000` establishes a paired mapping and jumps to
`boot_os_entry` at `3F:412C`: [confirmed]

```z80
3F:4000  ld a,0x07
3F:4002  out (0x04),a
3F:4004  ld a,0x7F
3F:4006  out (0x06),a
3F:4008  ld a,0x03
3F:400A  out (0x0E),a
3F:400C  jp 0x812C
```

`boot_os_entry` spends 518 outer iterations in a nested delay: [confirmed]

```z80
3F:412C  im 1
3F:412E  ld b,0
3F:4130  ld sp,0xFDFA
3F:4133  djnz 3F:4133
3F:4135  ld ix,1
3F:4139  add ix,sp
3F:413B  ld sp,ix
3F:413D  jr nc,3F:4133
3F:413F  ld sp,0xFFC5
```

`DJNZ` runs 256 times per outer pass because `B` starts at zero. The stack
pointer advances from `0xFDFA` until the 518th addition wraps to zero and sets
carry. The loop executes 132,608 `DJNZ` instructions and 2,072 outer-control
instructions. Including `IM 1`, `LD B,0`, and `LD SP,0xFDFA`, the region
contains 134,683 executed instructions. [confirmed]

Standard Z80 timing gives 1,747,727 T-states for the loop and 1,747,752
including the three setup instructions. At a nominal 6 MHz that is 0.291292
seconds. This conversion assumes that the CPU already runs at 6 MHz; the ROM
bytes do not establish the physical reset oscillator frequency. [standard]

The pinned TilEm trace reports 1,746,716 T-states over the same region. TilEm
charges 13 T-states for `ADD IX,SP`, while the standard Z80 timing is 15.
The two-T-state difference occurs 518 times, accounting for all 1,036 missing
T-states. Emulator clock output should therefore not replace the standard
instruction timing for this delay. [confirmed] for the trace and source model;
[standard] for Z80 timing.

## Mapping transition

After the delay, the boot page moves from paired to independent mapping without
paging out the next instruction: [confirmed]

```z80
3F:4142  ld a,0x03
3F:4144  out (0x0F),a
3F:4146  ld a,0x7F
3F:4148  out (0x07),a
3F:414A  ld a,0x06
3F:414C  out (0x04),a
3F:414E  jp 0x4151
3F:4151  nop                 ; six NOPs through 3F:4156
3F:4157  ld a,0x81
3F:4159  out (0x07),a
```

The write to port `0x07` first places page `3F` in window C under paired mode.
Port `0x04 = 0x06` then selects independent mode, where port `0x06 = 0x7F`
keeps page `3F` in window A. Port `0x07 = 0x81` finally maps RAM page `0x81`
into window B. [confirmed] See [Paging](paging.md#boot-mapping-transition) for
the complete window table and emulator mapper comparisons.

## Flash-gate safety wrapper

Ten page-`3F` sites enable the protected Flash gate through the same 91-byte
wrapper. Sixteen other sites disable it through the same 15-byte checked
wrapper. Exact-byte scanning accounts for all 26 immediate writes to port
`0x14` on the page. [confirmed]

The first enable begins at `3F:415B`: [confirmed]

```z80
3F:415B  push af
3F:415C  ld a,1
3F:415E  nop
3F:415F  nop
3F:4160  im 1
3F:4162  di
3F:4163  out (0x14),a
3F:4165  di
```

The remaining 80 bytes enforce these invariants before restoring `AF` at
`3F:41B5`: [confirmed]

- the saved stack pointer has a high byte in `0xC0`–`0xFF`;
- adding eight to the saved stack pointer does not carry;
- port `0x06 & 0x3F` is page `0x3F` or one of pages `0x2C`–`0x2F`;
- port `0x07` equals `0x81`;
- complementing one byte at `0xC000`, reading it back, and complementing it
  again reproduces the original byte;
- the same complement-write-read-restore test succeeds at `0x8000`.

Every failed test reaches `JP 0x0000`. The two byte probes are destructive for
the interval between the first and second writes, then restore the original
value before continuing. An interrupt or reset between those writes could
leave one byte complemented; the routine executes with interrupts disabled.
[confirmed]

The disable wrapper saves `AF`, clears `A`, emits the protected instruction
sequence, and writes port `0x14`. It then executes:

```z80
OR A
JP NZ,0x0000
```

The wrapper restores `AF` afterward. The test is necessarily zero when normal
sequential execution reaches it. It detects a control-flow or
instruction-corruption error rather than reading the write back. [confirmed]

## Ordered hardware programming

The first guarded enable is followed by the complete initialization sequence
below. The order includes the call from `3F:41BA` into
`boot_link_assist_init` at `3F:6278`. [confirmed]

| Stage | Writes in execution order | ROM evidence |
|-------|---------------------------|--------------|
| Link and low-power setup | `0x2D = 0x02`; `0x00 = 0x00`; `0x09 = 0x97`; `0x0A = 0xB4`; `0x0B = 0xB4`; `0x0C = 0xB4`; `0x08 = 0x80`; `0x08 = 0x00` | `3F:41B6`–`41BA`; `boot_link_assist_init` |
| Bus timing | `0x29 = 0x17`; `0x2A = 0x27`; `0x2B = 0x2F`; `0x2C = 0x3B`; `0x2E = 0x45`; `0x2F = 0x4B` | `boot_bus_timing_init` at `3F:41BD`–`41D3` |
| Execution controls | `0x21 = 0x00`; `0x22 = 0x08`; `0x23 = 0x29`; `0x25 = 0x10`; `0x26 = 0x20` | `boot_execution_protection_init` at `3F:41D5`–`4206` |
| Runtime mapping | `0x0E = 0`; `0x0F = 0`; `0x05 = 0`; `0x06 = 0x3F` | `3F:4207`–`4210` |
| GPIO and USB control | `0x39 = 0xF0`; `0x4A = 0x20` | `3F:4212`–`4218` |
| Gate and final RAM window | protected `0x14 = 0`; `0x07 = 0x80` | `3F:421A`–`422B` |

The bytes and their execution order are [confirmed]. Their subsystem meanings
have separate evidence limits:

- [Bus timing and wait states](bus-timing.md#boot-configuration) decodes the
  wait-state values and distinguishes public timing from emulator models.
- [Execution protection](execution-protection.md#registers-and-boot-values)
  gives the modeled no-execute ranges and unresolved physical boundaries.
- [ASIC status, identity, protection, and GPIO](asic-status-gpio.md) separates
  the ROM's `0x21` and `0x39` use from conflicting GPIO implementations.
- [USB ASIC and link assist](sub-usb-asic.md#observed-port-map-confirmed)
  distinguishes ROM use of ports `0x08`–`0x0C` and `0x4A` from public and
  emulator interpretations.

## First boot decision

The raw keypad scanner at `3F:6503` returns a scan code to `3F:422D`.
The reset dispatcher assigns boot actions only to **DEL** (`0x38`) and
**STAT** (`0x20`). Every other result, including **MODE** (`0x37`), takes the
installed-OS check below. A reset-origin MODE trace confirms that behavior.
[confirmed]

Without those keys, the normal path checks two page-0 values: [confirmed]

```z80
3F:4238  ld a,(0x0038)
3F:423B  cp 0xFF
3F:423F  ld hl,(0x0056)
3F:4242  ld bc,0xA55A
3F:4246  sbc hl,bc
3F:4248  jp z,0x0053
```

The jump requires byte `0x0038 != 0xFF` and word `0x0056 = 0xA55A`.
Page-0 entry `00:0053` is `JP 0x0C4F`, which begins the OS handoff. A failed
check instead initializes display and RAM state through `3F:42B3`, selects CPU
speed zero, polls the ON-key state, restores speed one, and enters the receive
flow. [confirmed] The electrical ON-key polarity and oscillator frequencies
remain subject to the evidence limits on
[Keypad and ON-key hardware](keypad-on-hardware.md) and
[Clock, timers, and power](clock-timers-power.md). The DEL/STAT transport split
and trace results are detailed on [Retail boot page](retail-boot.md#reset-dispatch).

## Destructive RAM diagnostic

The unreferenced dispatcher at `3F:427E` contains a second raw key scan. If
entered directly with **MODE** (`0x37`), it jumps to
`boot_flash_ram_diagnostic` at `3F:4504`. No direct page-`3F` caller or
reset-origin trace reaches `3F:427E`; MODE at the first reset scan instead
takes the installed-OS check. [confirmed] An undiscovered computed entry is
[hypothesis].

The diagnostic's later RAM-test path calls `boot_ram_test` at `3F:461A` to
test main RAM and banked RAM. [confirmed]

`boot_ram_test` takes the start address in `DE`, computes length
`0x10000 - DE`, writes a repeating byte pattern, rewinds, and verifies the same
pattern. The pattern is `0x00`, `0x01`, …, `0xFA`, then repeats at `0x00`.
[confirmed]

The first call uses `DE = 0x8A52`, covering `0x8A52`–`0xFFFF`. The caller then
clears port `0x27` and tests RAM pages selected by port `0x05 = 2` through `7`,
each from `0xC000`–`0xFFFF`. A mismatch clears port `0x05`, selects the error
text at `3F:4800`, and jumps to the diagnostic display path. A successful pass
calls the raw key reader at `3F:6569` before returning. A zero scan continues
the RAM-page loop. A nonzero scan aborts it through `3F:460F`. [confirmed]

This test overwrites every byte in each range and leaves the test pattern in
place. It is suitable only for the boot diagnostic path, not for checking RAM
that contains live state. [confirmed]

## Dormant LCD and keypad diagnostic

The retail ROM contains `boot_lcd_keypad_diagnostic` at `3F:4658`, a complete
LCD pattern, contrast, and keypad test. Its only incoming branch,
`boot_diagnostic_gate` at `3F:4615`, is constant-false. The complete predecessor
is: [confirmed]

```z80
3F:4610  xor a
3F:4611  out (0x05),a
3F:4613  cp 0x09
3F:4615  jr z,3F:4658
3F:4617  jp 3F:4510
```

`OUT` preserves `A`. The `XOR A` therefore makes `CP 0x09` nonzero, and the
conditional branch cannot be taken under Z80 semantics. A key read performed
by the RAM worker can reach `3F:4610`, but `XOR A` discards that scan code
before the compare. **MODE** can reach the RAM diagnostic; it does not make
the LCD/keypad diagnostic reachable. [confirmed]

The remaining subsections describe the dormant bytes. Dynamic results use an
explicit RAM-harness entry and do not represent ordinary boot behavior.

### LCD pattern helpers

`boot_lcd_fill_pattern` at `3F:46EF` takes alternating row bytes in `D` and `E`.
It selects row command `0x80` and each visible byte-column command from `0x20`
through `0x2B`, then writes 64 data bytes per column. One call emits 24 command
writes and 768 data writes. [confirmed]

`boot_lcd_write_row` at `3F:472E` takes a row command in `B` and a data byte in
`D`. It writes the value once in each of the 12 visible byte columns. One call
emits 24 command writes and 12 data writes. [confirmed]

The diagnostic presents these six screens: [confirmed]

| Order | Visible screen | Construction |
|------:|----------------|--------------|
| 1 | `0x81` in every visible byte, with rows 0 and 63 set to `0xFF` | one `boot_lcd_fill_pattern` call plus two `boot_lcd_write_row` calls |
| 2 | all `0xFF` | equal-byte fill |
| 3 | all `0x00` | equal-byte fill |
| 4 | alternating `0x55` and `0xAA` rows | alternating-byte fill |
| 5 | alternating `0x00` and `0xFF` rows | alternating-byte fill |
| 6 | all `0xAA` | equal-byte fill |

The six stages emit 192 command writes and 4,632 data writes. After each stage,
`3F:471A` selects CPU-speed value `0`, polls `3F:6569` until a key appears,
restores CPU-speed value `1`, and returns Z for scan code `0x09` (**ENTER**).
**ENTER** skips the remaining screen or contrast stages and advances to the
keypad test. Other nonzero scan codes advance one stage. [confirmed]

### Contrast sweep

The contrast loop passes values `0x27` down through `0x01` to
`boot_lcd_write_contrast` at `3F:74F8`. The helper adds `0x18`, forces bits 7–6,
waits for the LCD, and writes the result to port `0x10`. The emitted commands
descend from `0xFF` through
`0xD9`, covering controller contrast arguments 63 through 25 in 39
key-advanced steps. [confirmed]

Toshiba defines the larger T6K04 argument as darker. This direction comes from
the controller data sheet, not from the ROM arithmetic. [standard] The routine
clears the LCD after the sweep and calls `boot_lcd_restore_contrast` at
`3F:74F5` to restore the contrast stored at `0x8447`. [confirmed]

### Keypad sequence

The table at `3F:478D` contains 49 two-byte entries. Each pair holds an expected
scan code and a decimal position label. `3F:73A2` converts the label for
display. The labels cover `11`–`15`, `21`–`26`, `31`–`34`, the five-entry rows
`41`–`45` through `91`–`95`, and `102`–`105`. The first entry expects **Y=**
(`0x35`) at position `11`; the final entry expects **ENTER** (`0x09`) at
position `105`. All 49 scan codes are unique. [confirmed]

For each entry, the loop ignores wrong keys and continues polling. **ENTER**
aborts unless it is the final expected key. Successful completion clears the
LCD, displays `OK` from `3F:4807`, waits for a non-**MODE** key, then jumps to
`3F:424B`. [confirmed]

### Direct-entry emulator validation

The guarded Wabbitemu probe boots until the retail protection bounds are
established, maps page `3F`, and injects a 30-byte RAM harness. The harness
calls `boot_lcd_initialize` (`3F:74C6`), `boot_lcd_fill_pattern` (`3F:46EF`),
`boot_lcd_write_row` (`3F:472E`), and `boot_lcd_write_contrast` (`3F:74F8`).
It does not patch the constant-false branch. [confirmed] for the harness and
pinned emulator run.

The native run executes 8,040 probe instructions and retains only helper-visit
counters, transfer counts, two visible-screen hashes, boundary cells, and the
final contrast field. It observes: [confirmed] for pinned Wabbitemu commit
`48c2dc0`.

- `boot_lcd_initialize` emits seven commands and falls through
  `boot_lcd_restore_contrast` into `boot_lcd_write_contrast`;
- `boot_lcd_fill_pattern` emits 24 command and 768 data writes for alternating
  `0x55`/`0xAA` rows;
- `boot_lcd_write_row` emits 24 command and 12 data writes, changing all 12
  bytes of row 63 to `0xFF`;
- an explicit `A = 0x27` call to `boot_lcd_write_contrast` emits `0xFF`, which
  Wabbitemu stores as its adjusted contrast level 39.

These observations validate retail-ROM execution against Wabbitemu's
controller model. They do not establish normal boot execution, analog
contrast, controller timing, or panel appearance. Physical behavior remains
unmeasured. [hypothesis]

## Reproducing the checks

`tools/boot_hardware.py` contains the timing arithmetic, ordered write
manifest, exact Flash-gate wrapper classifier, and RAM-test pattern model.
`tools/describe_boot_hardware.py` exposes guarded text and JSON reports:

```sh
python tools/describe_boot_hardware.py delay
python tools/describe_boot_hardware.py --json manifest
python tools/describe_boot_hardware.py protected-writes
python tools/describe_boot_hardware.py trace /path/to/full-reset.trace
python tools/describe_boot_hardware.py ram-pattern 0x200
python tools/describe_boot_hardware.py --json lcd-diagnostic
```

The trace analyzer reads binary TLMT records in one streaming pass, retains
only counters and the 35 selected output events, and stops after the final
boot write at `3F:422B`. It does not construct a text line or retain a register
snapshot for every executed instruction. [confirmed]

The saved full-reset TilEm trace matches all 35 ordered output events from
`retail_boot_reset_stub + 0x02` through `3F:422B`, including the call to
`boot_link_assist_init`. The trace starts
at logical `0x8000` under the TI-84 Plus reset mapping and resolves every
banked instruction in this interval. [confirmed] for the pinned emulator run.

`tools/run_wabbitemu_lcd_diagnostic_probe.py` builds a hash-bearing evidence
manifest for the explicit helper calls. It requires the pinned native runner
and exact OS 2.55MP ROM:

```sh
python tools/run_wabbitemu_lcd_diagnostic_probe.py \
  --binary /path/to/wabbitemu-headless \
  --output-dir /tmp/ti84-lcd-diagnostic --json
```

## Remaining physical tests

- Measure the time from reset assertion to `3F:413F` on calculators with known
  ASIC and oscillator revisions.
- Observe whether the protected writes produce any externally measurable
  transient and whether an interrupted complement test can leave RAM changed.
- Measure the effects and reset readback of each initialized register instead
  of inferring electrical behavior from public names or emulator fields.
- Record cold-start RAM contents before the boot wrapper probes `0x8000` and
  `0xC000`.
- Enter the dormant LCD helper sequence on identified physical controller
  revisions and capture port timing, contrast voltage, and panel output.

These measurements remain [hypothesis].
