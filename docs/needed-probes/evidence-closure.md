# Online evidence and physical closure

Public specifications close several logical contracts used by the hardware
probes. They do not identify the ASIC, RAM, Flash, LCD controller, or electrical
behavior fitted to a particular calculator. Emulator results establish each
implementation's prediction and validate probe control flow; they are not
physical observations.

## Evidence classes

The closure audit keeps four source classes separate:

- A manufacturer specification closes behavior for the identified part or
  architecture. It does not identify the part installed in a calculator.
- TI documentation closes the published programming interface. It does not
  specify undocumented TI-84 Plus ASIC registers or electrical limits.
- Pinned emulator source and exact probe runs close that emulator's model.
  Agreement between emulators is not independent silicon evidence.
- WikiTI and similar first-hand reports provide useful historical physical
  measurements. A report without its raw frame, artifact hash, unit metadata,
  and repeated trials does not replace a new evidence bundle.

No public TI-84 Plus ASIC electrical datasheet or complete TI-issued board
schematic was located. TI's [calculator
patent](https://patents.google.com/patent/US20060277233A1/en) corroborates the
product-level processor, memory, display, keypad, and link architecture. It
does not specify comparator thresholds, pull-ups, oscillator components, or
undocumented ports. [standard]

## Calculator-readable probes

| Probe | Question and measurement | Evidence available without a calculator | Closure decision |
|-------|--------------------------|-----------------------------------------|------------------|
| `HWASIC` | Snapshot ASIC identity, status, protection, speed-gate, and GPIO-related ports. | [TilEm](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_io.c) returns model constants. [Wabbitemu](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/hardware/83psehw.c) derives several values from its configured calculator model. | The snapshot path closes in emulation. A physical result remains required for each unit and board revision. |
| `HWPUSB` | Read USB identity, status, endpoint, timer, and FDRC-related ports in disconnected and connected states. | The [TI-84 Plus guidebook](https://education.ti.com/html/eguides/graphing/84Plus/PDFs/TI-84-Plus-guidebook_EN.pdf) documents USB use, not ASIC registers. TilEm labels USB unimplemented. Wabbitemu's `fake_usb` implements a small subset, and [MAME](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85_m.cpp) supplies limited fixed reads. | Physical disconnected and controlled-peer captures remain required. Run disconnected first because undocumented reads may acknowledge state. |
| `HWPMD5` | Exercise partial operand writes, a fifth write, mode and rotation masking, undefined reads, and result-latch mutation. | [RFC 1321](https://www.rfc-editor.org/rfc/rfc1321) closes the MD5 Boolean functions, rotation, modular arithmetic, and test vectors. TilEm and Wabbitemu close their accelerator models. | Valid-round arithmetic closes without hardware. Partial writes, extra writes, masking, undefined reads, and latch behavior remain physical questions. |
| `HWPRAM` | Write and restore markers through selectors `0x82`–`0x87` to identify physical aliases. | TilEm models eight distinct pages. Wabbitemu optionally aliases selectors above page 2. [WikiTI's RAM-page report](https://wikiti.brandonw.net/index.php?title=83Plus:OS:Ram_Pages) records historical 48 KiB and 128 KiB behavior. | A unit-specific physical result remains required. The current artifact is laboratory-only because a reset can strand a changed RAM byte. |
| `HWBATT` | Repeat the OS battery check at known rail conditions and record logical and raw status. | TI documents low-battery warnings and the archive safety check. TilEm's source labels its voltage levels as values that still need measurement. Wabbitemu does not model the comparator. | Thresholds, hysteresis, load, temperature, and revision dependence require a controlled supply and DMM. |
| `HWBRAW` | Step raw selector states to assign individual comparator thresholds and GPIO polarity. | No located TI source specifies the permissible supply fixture, selector thresholds, or GPIO electrical state. | The artifact remains blocked until a unit-specific isolated supply, limits, polarity protection, brownout cutoff, and recovery procedure exist. |
| `HWLINK` | Drive both link lines through digital states and sample readback after 0, 1, 4, and 16 NOPs. | The [TI SDK](https://education.ti.com/download/en/ed-tech/830D08FF31804AEAA2F03B8F5E89AD14/672891A1E98349CAB91C11B4928C253C/sdk83pguide.pdf) documents D0/D1, all four output states, and idle-high behavior. The [Silver Edition addendum](https://education.ti.com/html/eguides/discontinued/computer-software/EN/SDK-TI-83-Developer-Guide-Addendum_EN.pdf) documents active-low assist, both-low abort, and timeout. | The logical protocol closes online. Pull-ups, thresholds, sink strength, cable RC, rise time, and physical settling require a high-impedance capture. |
| `HWKEYS` | Select keypad groups and record repeated matrix samples at four delays for a held key or chord. | The TI SDK closes the scan-code map and ON-key software interface. [TilEm](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/keypad.c) and [Wabbitemu](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/hardware/keys.c) use different idealized chord-closure models. | Settling, bounce, ghosting, rollover, capacitance, and ON-key waveforms remain physical and keypad-revision specific. |
| `HWBUS` | Time Flash and RAM execute, read, and write classes while changing ASIC wait controls. | The [Z80 CPU manual](https://www.zilog.com/docs/z80/UM0080.pdf) closes generic M1, memory-cycle, and WAIT extension. Emulator sources close only their added-delay models. | Real ASIC wait classes and absolute timing require hardware. Restrict the present artifact to an identified compatible stock Flash device. |
| `HWPFX` | Time ordinary, CB, ED, DD/FD, and indexed-CB sequences to locate wait insertion on opcode fetches. | Zilog closes instruction encoding and generic bus cycles. TilEm treats the final indexed-CB opcode as an ordinary read; Wabbitemu treats it as another opcode fetch. | The physical two-M1 versus three-M1 behavior remains open and is a high-value discriminator. |
| `HWTMR` | Record divisor, prescaler, zero-count, status, and first and second expiry behavior. | TilEm and Wabbitemu implement competing policies. [WikiTI's port-`0x30` report](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:30) records a historical `32768/33` source and a HALT-wake observation. | The historical result is a strong prior, not a revision-tagged raw frame. Physical runs remain required for divisor, port-`0x2F` prescaling, zero, expiry, and wake behavior. |
| `HWPRTC` | Read RTC bytes tightly around a natural rollover and compare disabled and active states. | TilEm calls host time separately for component reads, so a torn tuple there describes TilEm. Other emulators use different clocks or omit the ports. | Hardware latching, torn reads, rollover atomicity, disabled-clock behavior, and reset retention remain physical questions. |
| `HWPMAP` | Seed page markers, change independent and paired mappings and overlay bounds, then sample boundary addresses. | TilEm, Wabbitemu, and MAME provide competing routing predictions. No located ASIC specification selects one. | The physical semantics remain open. The current artifact is blocked because an unknown paired-mode transition can unmap its executing worker before cleanup. |
| `HWPLCD` | Use bounded ready polling, same-value visible-cell accesses, status reads, mirror ports, and pointer tests without power or contrast commands. | The [T6K04 datasheet](https://static.datasheets.com/doc/2063408-toshiba-t6k04-uaw-5ns--ds.pdf) specifies 128×64 RAM, status, dummy reads, and busy timing. The [T6A04A datasheet](https://datasheet4u.com/pdf/625711/T6A04A.pdf) specifies 120×64 RAM. The TI SDK documents the published visible interface. | A datasheet closes nominal behavior only after controller identification. Fitted-controller identity, physical busy duration, mirrors, latch behavior, and pointer effects remain physical. |
| `HWPIRQ` | Install a guarded IM2 logger and measure programmable-timer, ON, link, and HALT wake behavior before restoring IM1. | Zilog closes generic HALT wake rules. TilEm, Wabbitemu, and MAME disagree on the ASIC interrupt policy. MAME models ports `0x30`–`0x38`; its mode-`0x02` interpretation suppresses the timer interrupt. | Timer-HALT wake, ON latch and clear policy, source coalescing, and link interrupt routing remain physical and ASIC-revision specific. |
| `HWEF...` and `HWER...` | Execute an existing `RET` at selected Flash or RAM protection boundaries and preserve a pending result across return or reset. | TilEm and Wabbitemu directly disagree on Flash-bound inclusivity and RAM arithmetic. The emulator fixtures close each implementation's boundary and reset policy. | Actual boundaries, overlays, exception ordering, and pending-result retention require a backed-up physical calculator. |
| `HWPLAB` | Snapshot cells, write hidden-column markers, classify alias, wrap, and retention, then restore the touched union. | Manufacturer datasheets close nominal hidden width only for a positively identified controller. Emulators provide three different hidden-storage models. | The experiment remains physical and laboratory-only. Run it after `HWPLCD` on an identified repairable module with verified recovery. |

## External and reset experiments

Several remaining questions start outside an ordinary `Asm(` program or need
an external reference:

- Exact Flash command sequences, DQ polling, rated timing, and low-voltage
  inhibit close online after identifying the installed part. Relevant examples
  include the [Spansion
  S29AL008D](https://www.mouser.com/datasheet/2/100/spansion_inc__s29al008d_00-1161302.pdf),
  [Fujitsu
  MBM29LV800TA](https://www.alldatasheet.com/datasheet-pdf/pdf/61814/FUJITSU/MBM29LV800TA.html),
  and [Macronix
  MX29LV160C](https://www.macronix.com/Lists/Datasheet/Attachments/8515/MX29LV160C%20T-B%2C%203V%2C%2016Mb%2C%20v2.6.pdf).
  Calculator-level interrupted programming and GC journal atomicity still need
  controlled power cuts and full pre/post Flash images.
- Boot ordering, cold RAM, reset retention, and peripheral state before OS
  initialization need boot-stage instrumentation or external bus capture.
  Emulator reset results describe the emulator implementation.
- TI specifies nominal 6 MHz and 15 MHz CPU modes in the Silver Edition
  addendum. Absolute frequency, tolerance, jitter, and voltage or temperature
  dependence require a calibrated external timebase.
- LCD oscillator and busy timing depend on the fitted controller and its
  external components. Link voltage and keypad settling likewise require a
  high-impedance instrument rather than an emulator result.

## Minimum physical closure set

The smallest set that resolves the competing models while controlling risk is:

1. Run `HWASIC` and disconnected `HWPUSB` on identified TA2 and TA3 units.
2. Run `HWTMR`, `HWPFX`, and `HWPLCD` and export each AppVar immediately.
3. Run operator-driven `HWKEYS` and disconnected `HWLINK`; add a
   high-impedance capture for electrical settling.
4. Measure `HWBATT` with an independently monitored supply fixture.
5. Run one execution-protection artifact per backup and export cycle.
6. Keep `HWBRAW` and `HWPMAP` blocked until their safety requirements are met.
7. Keep `HWPRAM`, `HWBUS`, `HWPIRQ`, `HWPLAB`, Flash interruption, and power-cut
   work on identified replaceable laboratory units.

Every run needs the complete `HWP1` AppVar or every `HWPZ1-` page. The evidence
bundle also records model, PCB, ASIC, controller and Flash identity, OS and boot
version, launch conditions, supply, load, temperature, instrument settings,
and restoration outcome. The frame carries probe-defined state; external
metadata and analog captures remain separate.
