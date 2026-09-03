# Interrupts (IM1)

*TI-84 Plus OS 2.55MP — Interrupt masks, status, acknowledgement, dispatch, and low-power wake.*

The TI-84 Plus OS runs the Z80 in interrupt mode 1 (IM1) and polls the ASIC's interrupt status. This page separates the USB event gate from the legacy controller at ports `0x03` and `0x04`, then follows acknowledgement, priority, and `HALT` wake behavior.

## Evidence layers

| Evidence | Scope | Confidence |
|----------|-------|------------|
| Page-0 bytes from `im1_vector` at `ram:0038` through `ram:0244` | IM1 entry, USB and legacy gates, source-test order, handlers, acknowledgement, and exit | [confirmed] |
| Power-cycle trace from `tools/macros/power-cycle.macro` | OS mask writes, low-power `HALT`, ON wake, status read, debounce, and restoration | [confirmed] |
| WikiTI ports `0x03` and `0x04` | Bit-level enable, status, clear-on-zero, timer-rate, mapping, battery-selector, and low-power contract | [standard] |
| TilEm commit `f56ad63` and Wabbitemu commit `48c2dc0` | Two executable interpretations of the registers and their fidelity gaps | [standard] |
| MAME 0.287 `ti84pv3` driver and Lua I/O trace | Third implementation, headless ON-wake execution, and explicit `MACHINE_NOT_WORKING` gaps | [standard] |
| Guarded TilEm direct-core interrupt probe | Stored-mask readback, internal policy, acknowledgement, ON/link edges, timer callbacks, and reset ordering | [standard] |
| Guarded TilEm direct-core link probe | Raw link-activity and assist idle, receive, and error interrupt transitions | [standard] |
| Guarded Wabbitemu interrupt edge probe | Initialized-core mask, timer, acknowledgement, completion, and low-power transitions | [standard] |
| Guarded MAME legacy-interrupt probe | CPU-I/O-space status, mask, ON-edge, fixed-timer, and soft-reset observations | [standard] |

The ROM proves how OS 2.55MP uses the registers. Public notes and emulators describe behavior inside the ASIC that the ROM cannot prove by itself. Emulator agreement is supporting evidence, not physical confirmation.

## IM1 entry and context

IM1 accepts a maskable interrupt at `im1_vector`, the fixed address `ram:0038`.
The vector jumps to `int_entry_save_alt_regs` at `ram:006D`, which swaps `AF`,
`BC`, `DE`, and `HL` with the alternate register set. The normal exit swaps
them back, executes `EI`, and returns with `RETI`. [confirmed]

```z80
ram:0038  jr ram:006D
ram:006D  ex af,af'
ram:006E  exx
ram:006F  in a,(0x55)
ram:0071  xor 0xFF
ram:0073  and 0x1F
ram:0075  jr z,ram:003A
```

The handler uses the alternate general registers as its working context. It assumes `IY = flags` at `0x89F0` and uses the interrupted stack. It does not push `IY`, `IX`, or a complete register frame at entry. [confirmed]

The normal exit restores the standard OS mask after source-specific work: [confirmed]

```z80
ram:00E4  ld a,0x0B
ram:00E6  bit 0,(iy+0x16)
ram:00EA  jr z,ram:00EE
ram:00EC  add a,0x04          ; select 0x0F when timer 2 is wanted
ram:00EE  out (0x03),a
ram:00F0  ex af,af'
ram:00F1  exx
ram:00F2  ei
ram:00F3  reti
```

## USB gate and legacy controller

Port `0x55` is the active-low USB interrupt summary. The three instructions at
`int_entry_save_alt_regs + 0x02` invert and mask its low five bits. A result of
zero jumps directly to `interrupt_legacy_status` at `ram:003A`. A nonzero
result enters the USB activity-hook and port-`0x56` event paths before the
handler considers the legacy controller. [confirmed]

This ordering does not make port `0x55` a summary of ON, standard-timer, or legacy link requests. Those sources appear at port `0x04`. Port `0x56` is a USB line-event bitmap, not the mask for port `0x04`. [confirmed] for the separate ROM paths; [standard] for the register roles.

The disconnected TilEm x4 model returns `0x1F` from port `0x55` and zero from
port `0x56`. Its ordinary trace therefore takes
`int_entry_save_alt_regs + 0x02` → `interrupt_legacy_status` without USB event
work. [standard]

See [USB ASIC and link assist](sub-usb-asic.md#interrupt-integration-confirmed) for the port-`0x56` event-bit branches and page-35 handlers.

## Port `0x03`: mask, acknowledgement, and power mode

Port `0x03` controls the four legacy interrupt sources and the ASIC's behavior when the Z80 executes `HALT`. Public notes document readback for enable bits 0, 1, 2, and 4. TilEm and Wabbitemu return the complete stored byte, but physical readback of bit 3 is not documented. [standard] for the public fields and emulator behavior; [hypothesis] for physical bit-3 readback.

| Bit | Meaning | Effect of writing zero | Evidence |
|----:|---------|------------------------|----------|
| 0 | ON interrupt enabled | disable and acknowledge the ON request | Public register contract; OS writes and both emulators [standard] |
| 1 | standard timer 1 enabled | disable and acknowledge timer 1 | Public register contract; OS writes and TilEm [standard] |
| 2 | standard timer 2 enabled | disable and acknowledge timer 2 | Public register contract; OS writes and TilEm [standard] |
| 3 | write control: one keeps hardware powered during `HALT`; zero selects low power on `HALT` | select low power for the next `HALT` | Public register contract; OS shutdown sequence and both emulators [standard] |
| 4 | legacy link-activity interrupt enabled | disable and acknowledge link activity | Public register contract; OS shutdown mask and TilEm [standard] |
| 5–7 | no documented function | — | Public register contract [standard] |

Bit 3 changes what `HALT` does. A write with bit 3 clear does not enter low power by itself. The CPU must execute `HALT`, and an enabled wake source must later request an interrupt. [standard]

The OS uses these values: [confirmed] for each ROM write and branch; [standard] for the hardware effect.

| Value | Enabled legacy sources | `HALT` behavior | OS use |
|------:|------------------------|-----------------|--------|
| `0x08` | none | powered | common clear-on-zero acknowledgement and shutdown cleanup |
| `0x09` | ON | powered | transient standard-timer-1 acknowledgement path |
| `0x0A` | standard timer 1 | powered | transient ON acknowledgement path |
| `0x0B` | ON and standard timer 1 | powered | normal mask |
| `0x0F` | ON and both standard timers | powered | normal exit when `(IY+0x16)` bit 0 requests timer 2 |
| `0x11` | ON and link activity | low power | shutdown and wake loop |

## Port `0x04` read: source and ON status

Reading port `0x04` returns status. Bit 3 is the live active-low ON level; it is not an interrupt request. Bits 5–7 report programmable-timer completion even when the corresponding timer mode did not request a maskable interrupt. [standard]

| Bit | Read meaning | OS use | Evidence |
|----:|--------------|--------|----------|
| 0 | ON request pending | branch to `on_irq` at `ram:015B` | ROM test at `ram:00D2`–`ram:00D5` [confirmed]; latch role [standard] |
| 1 | standard timer 1 pending | branch to `standard_timer1_irq` at `ram:0167` | ROM test at `ram:00D6`–`ram:00D9` [confirmed]; pending role [standard] |
| 2 | standard timer 2 pending | branch to `ram:01F1` | ROM test at `ram:00C8`–`ram:00CB` [confirmed]; pending role [standard] |
| 3 | one when ON is released, zero while pressed | debounce reads at `ram:0975` | ROM interpretation [confirmed]; electrical level [standard] |
| 4 | legacy link activity pending | branch to `legacy_link_irq` at `ram:01E0` | ROM test at `ram:00CD`–`ram:00D0` [confirmed]; pending role [standard] |
| 5 | programmable timer 1 finished | test timer-1 mode at port `0x31` | ROM tests at `ram:0041` and `ram:013A` [confirmed]; completion role [standard] |
| 6 | programmable timer 2 finished | page-35 handler with `A = 0x0B` | ROM tests at `ram:0046` and `ram:0154` [confirmed]; completion role [standard] |
| 7 | programmable timer 3 finished | test timer-3 mode at port `0x37` | ROM tests at `ram:003C` and `ram:012C` [confirmed]; completion role [standard] |

The OS reads one status byte and retains it in `A` while testing the source bits. Programmable timers 1 and 3 receive an extra check of bit 1 in their own mode/status ports before the OS calls their banked handlers. A finished bit can therefore be visible without being eligible for interrupt service. [confirmed]

## Port `0x04` write: three unrelated controls

Writing port `0x04` does not acknowledge the status returned by a read. A write selects the memory-map mode, standard-timer rate, and battery-comparator input. [standard]

| Bits | Write meaning | Evidence |
|-----:|---------------|----------|
| 0 | zero selects independent mapping; one selects paired mapping | OS writes and mapper behavior [confirmed] for use; public contract and emulators [standard] for hardware |
| 2–1 | standard-timer rate index `0`–`3`, fastest to slowest | OS writes `0x06`; public formula and emulators [standard] |
| 5–3 | unused in the public contract | [standard] |
| 7–6 | raw battery-comparator selector | OS battery-test writes; public contract [standard] |

For TI-84 Plus standard timer 1, the published quartz-domain period is

$$
T_1 = \frac{64 + 80i}{32768}\text{ seconds},
$$

where $i$ is bits 2–1. Timer 2 runs at twice that frequency. OS value `0x06` selects independent mapping, rate index 3, and battery selector zero. [confirmed] for the OS value; [standard] for the field meanings and formula.

The battery-selector bits identify comparator configurations. The ROM's write order does not prove that the raw two-bit number is a monotonic voltage level. Physical threshold and bit-order measurements remain open. [hypothesis]

See [Paging](paging.md) for paired mapping and [Clock, timers, and power](clock-timers-power.md#standard-hardware-timers) for exact timer rates.

## Dispatch order and simultaneous sources

The legacy-status path tests port-`0x04` bits in this order: [confirmed]

| Priority | Status bit | Candidate | Additional gate |
|---------:|-----------:|-----------|-----------------|
| 1 | 7 | programmable timer 3 | port `0x37` bit 1 |
| 2 | 5 | programmable timer 1 | port `0x31` bit 1 |
| 3 | 6 | programmable timer 2 | handler selected through `ram:0154` |
| 4 | 2 | standard timer 2 | none in the dispatcher |
| 5 | 4 | legacy link activity | none in the dispatcher |
| 6 | 0 | ON request | none in the dispatcher |
| 7 | 1 | standard timer 1 | none in the dispatcher |

```z80
ram:003A  in a,(0x04)
ram:003C  bit 7,a
ram:0041  bit 5,a
ram:0046  bit 6,a
ram:00C8  bit 2,a
ram:00CD  bit 4,a
ram:00D2  rra                 ; original bit 0 enters carry
ram:00D6  rra                 ; original bit 1 enters carry
```

An eligible handler exits through acknowledgement instead of resuming at the next lower-priority bit. Simultaneous eligible sources are therefore not all dispatched from one port-`0x04` read. A timer-1 or timer-3 completion bit whose mode gate is clear is skipped, allowing the next candidate to be tested. [confirmed]

The common port-`0x03` write of `0x08` clears all four legacy source bits at once under the public clear-on-zero contract and TilEm's model. Simultaneous lower-priority legacy requests can therefore be coalesced by the higher-priority service. A programmable-timer completion is acknowledged separately through its mode/status port. [standard] for latch behavior; [confirmed] for the OS write sequence.

## Clear-on-zero acknowledgement

The common acknowledgement helper preserves the handler-supplied byte in `A`, writes `0x08`, then writes the saved byte: [confirmed]

```z80
ram:00DC  push af
ram:00DD  ld a,0x08
ram:00DF  out (0x03),a
ram:00E1  pop af
ram:00E2  out (0x03),a
```

The first write clears the ON, standard-timer, and link source latches because their enable bits are all zero. Bit 3 remains one, so this acknowledgement does not request low power. The second write exposes the handler-supplied value only until the normal exit writes `0x0B` or `0x0F`. [confirmed] for values and ordering; [standard] for clear-on-zero semantics.

Leaving a legacy pending bit uncleared causes another maskable request after `EI`. Rewriting the same all-enabled mask is not an acknowledgement because each set bit leaves its source enabled and pending. [standard]

Programmable timers use a separate contract. Writing their mode/status ports `0x31`, `0x34`, or `0x37` clears finished/overflow state and removes that timer's request in TilEm and the public hardware description. Port `0x03` does not clear bits 5–7. [standard]

## Standard and programmable timer distinction

The standard timers belong to the legacy mask block. Port-`0x03` bits 1 and 2 enable their interrupt requests, and clearing those bits acknowledges them. Their rate comes from port-`0x04` bits 2–1. [standard]

The three programmable timers have source, mode/status, and counter triplets at ports `0x30`–`0x38`. Their port-`0x04` bits are completion observations, not enable bits. Timer mode bit 1 selects whether completion requests a maskable interrupt. [standard]

OS 2.55MP uses programmable timer 1 for its timer bcall state machine and
programmable timer 3 for a USB timeout path. `standard_timer1_irq` drives keypad
scanning, cursor blink, the run indicator, and Auto Power Down (APD). [confirmed]

See [Clock, timers, and power](clock-timers-power.md) for programmable-timer modes, the bcall ABI, and kernel-tick consumers.

## ON request versus ON level

Port-`0x04` bit 0 is the ON interrupt latch. Bit 3 is the button's current active-low level. The dispatcher selects the ON handler from bit 0, while `on_key_debounce_power` at `ram:0964` repeatedly samples bit 3 to classify a stable press or release. [confirmed]

The power-cycle trace reads `0x01` after the injected ON press. Bit 0 reports the request and bit 3 clear reports the held key. The two meanings coincide in this event but remain independent fields. [confirmed]

TilEm requests an ON interrupt on both press and release transitions when enabled. Wabbitemu latches only a transition into its pressed state. The ROM handles either stable level, but it cannot determine the physical ASIC's edge policy. [standard] for emulator behavior; [hypothesis] for the unmeasured physical policy.

See [Keypad and ON-key hardware](keypad-on-hardware.md#on-interrupt-and-level) for debounce timing and the OS ON state machine.

## Link interrupt versus periodic link polling

Port-`0x03` bit 4 controls the legacy link-activity interrupt. The shutdown
mask `0x11` uses it as a wake source. The port-`0x04` bit-4 dispatcher branch
enters `legacy_link_irq`, the power-restoration path. [confirmed] for OS use;
[standard] for the interrupt source.

Normal operation uses mask `0x0B`, so legacy link interrupts are disabled. Standard timer 1 still performs a periodic silent-link check at `ram:01B1`: the raw path reads port `0x00`, and the assist path reads port `0x09`. This polling is separate from a direct port-`0x04` bit-4 request. [confirmed]

See [Two-wire link port hardware](link-port-hardware.md#background-link-detection-and-interrupts) for both detection paths.

## Low-power entry and wake

`poweroff_shared_tail` at `ram:0A24` first acknowledges legacy sources with
`0x08`. It then writes `0x06` to port `0x04`, writes `0x11` to port `0x03`,
enables interrupts, and reaches `poweroff_halt_loop` at `ram:0A5C`. [confirmed]

```z80
ram:0A4B  out (0x04),a        ; A = 0x06
ram:0A4F  out (0x03),a        ; A = 0x11
ram:0A5B  ei
ram:0A5C  halt
ram:0A5D  jr ram:0A5C
```

Mask `0x11` disables both standard timers, enables ON and link activity, and clears the powered-`HALT` bit. The next `HALT` enters the ASIC low-power mode under the public contract. [confirmed] for the sequence; [standard] for the physical effect.

A resolved TilEm trace records the transition and ON wake: [confirmed]

```text
clk=98010423   ram:0A29 OUT (0x03) <- 0x08
clk=99871166   ram:0A4B OUT (0x04) <- 0x06
clk=99871186   ram:0A4F OUT (0x03) <- 0x11
clk=99871258   ram:0A5C HALT
clk=99915117   ON pressed
clk=99915172   ram:006F IN  (0x55) -> 0x1F
clk=99915213   ram:003A IN  (0x04) -> 0x01
clk=99915377   ram:0964 ON wake/debounce path
clk=100195536  ram:09B5 power-on restoration
```

TilEm prevents programmable timers from waking `HALT` when both standard-timer bits in port `0x03` are clear. A programmable timer can still interrupt a running CPU in that state. This is an emulator policy approximating public reports that programmable timers do not reliably wake a halted CPU; it does not identify the physical ASIC mechanism. [standard]

### MAME ON-wake trace

MAME 0.287 includes the `ti84pv3` machine and accepts a 1 MiB OS 2.55MP image. The repository ROM has SHA-1 `ffddb460d7d4e79cc8fbd288d6895fd113d7f3bf`, while MAME's reference image has SHA-1 `d500540feca974f6e8fa269981cfb25dc951c338`. MAME warns about this difference because the repository image contains locally assembled boot pages. [confirmed]

The Lua tap records the program counter after each I/O instruction. MAME reaches the shutdown mask, accepts an injected ON press, and enters the ROM debounce path: [confirmed]

```text
MAME_IO frame=20 pc_after=0DF3 OUT (0x03) <- 0x08
MAME_IO frame=20 pc_after=0DF6 OUT (0x03) <- 0x00
MAME_IO frame=20 pc_after=0C97 OUT (0x03) <- 0x11
MAME_KEY frame=30 ON press
MAME_IO frame=31 pc_after=0071 IN (0x55) -> 0x1F
MAME_IO frame=31 pc_after=003C IN (0x04) -> 0x01
MAME_IO frame=31 pc_after=0977 IN (0x04) -> 0x01
```

The trace confirms ROM control flow under MAME. It does not confirm MAME's register semantics. The driver itself marks every monochrome TI-84 Plus configuration `MACHINE_NOT_WORKING`. [standard]

## Custom handler rules

A custom IM2 handler, or code that replaces OS interrupt service, must account for each controller independently: [standard]

- Preserve every register and mapping state that interrupted code can observe. The OS shadow-register convention is safe only while the interrupted program leaves those alternate registers to the OS.
- Read port `0x55` as an active-low USB gate and port `0x04` as legacy/completion status. Do not interpret port-`0x04` bit 3 as a pending source.
- Acknowledge legacy sources by clearing their port-`0x03` bits, then restore the intended mask. Acknowledge programmable timers through their own mode/status ports.
- Keep handler code and any data it requires in mapped memory. Banked calls must preserve the interrupted mapping or restore it before returning.
- Service or deliberately disable USB events. A port-`0x03` acknowledgement does not clear port-`0x55`/`0x56` state.
- Enable a source capable of waking the chosen power mode before executing `HALT`.

Chaining to the OS handler also inherits its assumptions: `IY` points to `flags`, normal RAM and page mappings are active, and the alternate general registers are available. [confirmed]

## Emulator comparison

| Behavior | TilEm x4 | Wabbitemu 83+SE/84+ | jsTIfied `20170706a` | Consequence |
|----------|----------|---------------------|-----------------------|-------------|
| Port `0x03` read | returns stored mask | returns stored mask | stores the interrupt mask | mask reads agree [standard] |
| Legacy clear-on-zero | clears ON, timer 1, timer 2, and link pending state on port-`0x03` writes | clears ON directly; disabling an overdue standard timer catches its phase up in the same port-`0x03` handler; port `0x02` can also catch it up | tracks standard-timer and ON latches in emulator state | OS-style acknowledgement is modeled with different internal policies [standard] |
| Link status | implements port-`0x04` bit 4 | omits bit 4 from port-`0x04` reads | link state participates in the interrupt model | software agreement does not establish electrical wake behavior [standard] |
| Standard timers | explicit pending interrupt bits when enabled | derives status from elapsed phase while enabled | schedules timer state in emulator cycle counters | simultaneous-source and latch tests can differ [standard] |
| Programmable completion | exposes finished bits 5–7 independently of interrupt mode | exposes timer-underflow bits 5–7 | retains per-timer completion and loop state | all separate completion from mode, with different timer cores [standard] |
| `HALT` behavior | port-`0x03` bit 3 selects powered/low-power behavior; standard-timer mask controls programmable wake suppression | approximates low power by changing LCD activity and suppresses programmable-timer requests while halted | halted CPU state is part of the browser scheduler | no model proves physical ASIC power domains [standard] |
| USB gate | disconnected fixed values `0x55 = 0x1F`, `0x56 = 0` | partial `Fake USB` event model | fixed disconnected values | connected USB interrupt service needs another test target [standard] |

Wabbitemu's source comments state uncertainty about its standard-interrupt write behavior. Its model is useful as an independent implementation comparison, but disagreement must remain explicit. [standard]

### Native TilEm interrupt edges

A guarded direct-core run compiles the complete TilEm tree at commit
`f56ad637d0524ee841dd381be6ecbaf5b8975600`. It calls the registered x4 port
handlers and timer callbacks, plus the public keypad, link, timer, and reset
functions. It does not execute the ROM. [standard]

Port `0x03` stores all eight written bits. Writes `00`, `01`, `02`, `04`, `08`,
`10`, and `FF` produce identical readback. The same writes select internal ON,
power-on-HALT, and link enables from bits 0, 3, and 4. Either standard-timer bit
clears TilEm's `NO_HALT_INT` flag on all three programmable timers; both bits
clear set that flag. All three timer flags agree in every case. [standard]

The probe seeds all four legacy latches, all three programmable completion
flags, and all three programmable CPU requests. Applying the seven values
above through port `0x03` produces status `E8 E9 EA EC E8 F8 FF`. Applying
them through port `0x02` produces the same sequence. Both paths leave the
three programmable requests at internal mask `0x38`, and port `0x03` leaves
completion bits 5–7 visible. This directly checks TilEm's two clear-on-zero
implementations. [standard]

The ON sequence produces `00 00 09 08 01 00 09 08 00`: masked press, enable
while held, release, acknowledge released, press, acknowledge held, release,
disable, and press while disabled. TilEm therefore latches both enabled
transitions. Timer callbacks with both masks clear remain at `08`. With both
enabled, timer 1, either timer-2 callback, and both sources produce `0A`,
`0C`, `0C`, and `0E`. [standard]

Reset schedules timer 1, timer 2A, and timer 2B at initial delays 1,600,
1,300, and 1,000 µs with 9,277 µs periods. Port-`0x04` writes select periods
`1953`, `4395`, `6836`, and `9277` µs for all three without changing the
current interval. An enabled external link-line transition sets status `18`;
either acknowledgement path clears it to `08`, and a disabled transition does
not latch. [standard]

With the CPU halted and both standard timers disabled, programmable-timer-1
expiry leaves completion status `0x28` but no CPU request. Enabling either
standard timer clears the gate and produces internal request `0x08`; a running
CPU also receives the request when both standard timers are disabled. This is
TilEm's policy, not a physical wake measurement. [standard]

TilEm reset writes stored port `0x03 = 0x0B` directly after the generic keypad
reset clears the internal ON enable. A fresh core therefore reads `0x0B` while
the internal ON enable is zero. Reset also retains `poweronhalt`; after the
probe first clears it, reset again reads `0x0B` while the retained power field
is zero. Writing `0x0B` through the port handler synchronizes both fields to
one. This inconsistency affects experiments that begin at initialized-core
reset without executing the ROM's first mask write. [standard]

A separate guarded link matrix checks the interrupt-facing parts of the same
implementation while exercising complete raw and assist transactions. An
enabled external peer-line transition asserts the raw link-activity request.
Assist idle-ready reports `0x22`, receive-ready reports `0x31`, and both
assert the CPU interrupt. Reading receive data changes status to `0x20`.
Illegal both-low input reports `0x64`; its first status read clears the CPU
request while retaining error status `0x60`. These are direct TilEm handler
results, not physical interrupt-edge or acknowledgement measurements.
[standard]

Two isolated executions produce identical canonical native JSON with SHA-256
`1c1209e9c3f625b07c42288c21e9a5dbadddb38f12aee995c1fbc8daf1f8e8ad`.
The binary SHA-256 is
`23037df0fee48b3ec15656aae80b6181d97211e8eec325c2be81eef02b1ff840`.
[standard]

### Native Wabbitemu interrupt edges

A guarded initialized-core run checks the source model through the registered
port handlers. Port `0x03` resets to `0x00` and stores all eight bits of
`0xFF`. Writing `0xFE` clears a seeded ON latch while preserving `0xFE` as the
mask readback. [standard]

Wabbitemu selects standard-timer-1 rates of 512, 227, 158, and 108 Hz. The
native periods round to 1,953,125, 4,405,286, 6,329,114, and 9,259,259 ns.
Timer 2 at index 3 has a 4,629,630 ns period and starts 2,314,815 ns after
timer 1. These are emulator intervals, not host-clock measurements or the
documented physical formula. [standard]

The expiry comparison is strict. At exactly one 108 Hz timer-1 period, port
`0x04` reads released-ON status `0x08` and the CPU interrupt line remains
clear. At the next representable emulator time, status is `0x0A` and the line
asserts. The sequence `0x0A` → `0x08` → `0x0A` then reads `0x08`: disabling
the overdue timer runs the handler's catch-up loop before re-enabling it. A
port-`0x02` zero write produces the same idle result through Wabbitemu's second
acknowledgement path. [standard]

With all three programmable underflow flags seeded, port `0x04` reads `0xE8`.
With the CPU halted, port-`0x03` bit 3 clear changes Wabbitemu's LCD activity
field from on to off; setting bit 3 restores it. This is its visual low-power
approximation, not evidence that a physical ASIC powers down the controller.
[standard]

### Native Wabbitemu USB interrupt edges

A separate initialized-core run checks Wabbitemu's USB gate. With both USB
request fields clear, port `0x55` reads `0x1F`. Directly selecting line,
protocol, or both requests produces `0x1B`, `0x0F`, and `0x0B`. These values
confirm active-low bits 2 and 4 in this emulator. [standard]

Writing zero to port `0x57` does not mask a line event. A subsequent write of
`0x08` to port `0x4A` raises the CPU interrupt, changes port `0x56` from
`0x50` to `0x58`, and changes port `0x55` from `0x1F` to `0x1B`. Repeating the
same write after clearing only the CPU interrupt raises it again. The run
invokes Wabbitemu's handlers directly; it does not execute the ROM dispatcher
or establish physical interrupt acknowledgement behavior. [standard]

MAME 0.287 provides a third comparison with larger known gaps: [standard]

| Area | MAME `ti84pv3` behavior | Difference from the public contract |
|------|---------------------------|-------------------------------------|
| Port `0x03` read | calls the same status reader used by port `0x04` | returns status and ON level instead of the stored mask |
| Port `0x03` write | masks ON and standard-timer pending fields with the written enable bits | models clear-on-zero for bits 0–2, but omits link bit 4 and low-power bit 3 |
| Port `0x02` write | writes ON and standard-timer status through a handler whose comment says it is being ignored | does not match the documented port-`0x03` acknowledgement ownership |
| Standard timers | allocates fixed 256 Hz and 512 Hz callbacks | port-`0x04` rate writes do not select the published 107.79–512 Hz range |
| Programmable timers | requests an interrupt when mode bit 1 is clear and sets the port-`0x04` completion field on that same branch | reverses the documented interrupt-enable polarity and loses independent completion visibility |
| Link and low power | no legacy link-pending field or ASIC power-domain transition | can execute the ROM wake path but cannot test physical link wake or low-power behavior |
| USB | returns fixed `0x1F` and zero from ports `0x55` and `0x56` | disconnected path only |

### Native MAME interrupt edges

The guarded MAME run parks the Z80 in a `DI` loop on page-0 RAM and disables
the programmable timers. At reset, ports `0x03` and `0x04` both read released
ON status `0x08`. Writes `00`, `01`, `02`, `04`, `08`, `10`, and `FF` to port
`0x03` leave both reads at `0x08`; the driver does not return the written mask.
[standard]

Writing `0x07` to port `0x02` directly creates status `0x0F`. Subsequent
port-`0x03` writes `0x01`, `0x06`, `0xFF`, and `0x00` retain ON only, retain
both standard timers, retain all three fields, and clear all three fields.
Port `0x04` consequently reads `09`, `0E`, `0F`, and `08`. Port `0x02` still
reads ASIC status `0xC3`; its write and read handlers have unrelated meanings.
[standard]

The live-input sequence begins with ON masked. A press, enabling ON while the
button remains held, release, enabled press, enabled release, and bit-0-clear
acknowledgement produce `00`, `00`, `08`, `01`, `09`, and `08`. The adapter
waits through both the video input update and a 256 Hz timer-1 sample after
each forced transition. This confirms MAME's press-only latch and release
rearming without executing the ROM handler. [standard]

One 20 ms frame with only timer 1, only timer 2, or both enabled produces
status `0x0A`, `0x0C`, or `0x0E`. Timer-1 status reaches `0x0A` after both
port-`0x04` configuration writes `0x00` and `0x06`. These frame-level results
show that both callbacks run and that neither configuration suppresses timer
1; the pinned source, rather than this coarse interval, establishes the exact
fixed 256 Hz and 512 Hz rates. [standard]

A scheduled soft reset retains seeded status `0x0F` through the reset callback.
After a port-`0x02` zero write clears pending state, the retained standard-timer
masks regenerate `0x0E`; a new ON press changes the status to `0x07`. MAME's
reset hook restores the mapper but does not restore these interrupt fields.
This is emulator reset behavior, not physical warm-reset evidence. Two isolated
runs produce identical canonical parsed native JSON with SHA-256
`bb4b38d444692b5136d96264fa3acf9fe95ef2f6a1879ab72e9a2ad8077c1def`.
[standard]

## Reusable debugging tools

`tools/ti84re/hardware/interrupt_controller.py` provides typed decoders, exact timer periods,
clear-on-zero acknowledgement, ROM status-test order, USB active-low decoding,
and immutable TilEm and MAME legacy-interrupt state models.
`tools/ti84re/hardware/describe_interrupt_controller.py` exposes focused CLI commands:
[confirmed] for the ROM/public decoders; [standard] for the emulator model.

```sh
nix develop -c python3 -m ti84re.hardware.describe_interrupt_controller mask 0x0B
nix develop -c python3 -m ti84re.hardware.describe_interrupt_controller status 0x8B
nix develop -c python3 -m ti84re.hardware.describe_interrupt_controller config 0x06
nix develop -c python3 -m ti84re.hardware.describe_interrupt_controller ack 0xF7 0x08
```

The trace command resolves mapper state, restricts output to interrupt ports, annotates each value, and collapses consecutive identical polls: [confirmed]

```sh
nix develop -c python3 -m ti84re.hardware.describe_interrupt_controller trace \
  /tmp/tilem-power-cycle.trace --clock 97000000-101000000
```

Use `--all` to retain repeated ON-level polling and `--json` for machine-readable output.

`tools/ti84re/emulators/wabbitemu/interrupt_probe.py` adds the pinned Wabbitemu timer-rate and
edge oracle. Run its exact-ROM, hash-recording CLI with:

```sh
wabbit_interrupt_parent=$(mktemp -d /tmp/ti84-wabbit-interrupt.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_interrupt_edge_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_interrupt_parent/run" --json
```

The ROM is only a core-initialization fixture in this mode. No TI-OS
instruction executes.

`tools/ti84re/emulators/tilem/interrupt.py` supplies the typed direct-core report and checks it
against the reusable TilEm state model. The guarded builder requires the exact
clean source commit and tree. The runner requires the binary SHA-256 and
refuses to reuse an output directory. The “Legacy interrupt matrix” section in
`tools/notes/emulator-probes.md` contains the reproduction commands.

`tools/ti84re/emulators/tilem/link.py` checks the raw-activity and assist-interrupt transitions
against the shared link model in `tools/ti84re/link/port.py`. Its guarded builder and
runner use the same clean-source and binary-hash requirements. The “Raw link
and assist matrix” section in `tools/notes/emulator-probes.md` contains the command.

`tools/ti84re/emulators/mame/interrupt.py` parses the complete MAME report and checks it against
the reusable state model. Its guarded CLI records the exact MAME, ROM, Lua,
logs, and evidence scope:

```sh
mame_interrupt_parent=$(mktemp -d /tmp/ti84-mame-interrupt.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_interrupt_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_interrupt_parent/run" --json
```

`tools/ti84re/emulators/mame/trace.py`, `tools/ti84re/emulators/mame/run_io_trace.py`, and `tools/probes/mame/mame_io_trace.lua` provide the equivalent headless MAME path. The Lua tap accepts comma-separated ports and ranges, collapses identical polls, records post-I/O PCs, and can inject ON at selected video frames: [confirmed]

```sh
nix shell nixpkgs#mame -c python3 -m ti84re.emulators.mame.run_io_trace \
  --seconds 2 --ports 03-04,55-56 \
  --on-press-frame 30 --on-release-frame 34
```

MAME prints a checksum warning for the locally assembled ROM and identifies the expected and actual hashes. Keep that warning with captured evidence.

## Resolved findings and open hardware tests

- [confirmed] OS 2.55MP tests USB activity before reading legacy status, but ports `0x55`/`0x56` remain separate from ports `0x03`/`0x04`.
- [confirmed] The port-`0x04` test order is programmable timer 3, timer 1, timer 2, standard timer 2, link, ON, then standard timer 1.
- [confirmed] The OS acknowledgement sequence is `0x08` → handler-supplied byte → `0x0B` or `0x0F`.
- [confirmed] Shutdown writes `0x11` and executes `HALT`; the trace wakes through port-`0x04` value `0x01` after an ON press.
- [standard] Programmable completion bits remain observable independently of their interrupt-mode bits.
- [standard] The guarded TilEm run verifies stored mask readback, both clear-on-zero paths, ON press and release latches, both timer-2 callbacks, link transitions, programmable-timer HALT gating, and the reset readback/internal-policy mismatch.
- [standard] The guarded TilEm link run independently verifies raw activity, assist idle and receive requests, data acknowledgement, and interrupt-only acknowledgement of a retained error flag.
- [standard] The guarded Wabbitemu run verifies complete mask readback, ON clearing, strict standard-timer expiry, both standard-timer acknowledgement paths, programmable completion readback, and its LCD-based low-power approximation.
- [standard] The guarded Wabbitemu USB run verifies its active-low line/protocol summary, mask-independent line event, and repeat-event path. It does not verify the ROM dispatcher or physical USB interrupt behavior.
- [standard] The guarded MAME run verifies shared status reads, three-bit mask behavior, direct port-`0x02` status injection, press-only ON sampling, both standard-timer pending bits within scheduled frames, and interrupt-field retention across soft reset.
- [hypothesis] Physical TA2 and TA3 tests should measure ON request edges, link wake transitions, simultaneous legacy-source coalescing, programmable-timer wake behavior, and battery-selector thresholds.

## Sources

| Source | Used for |
|--------|----------|
| [WikiTI port `0x03`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:03) | enable mask, clear-on-zero acknowledgement, normal value, and low-power-on-`HALT` contract |
| [WikiTI port `0x04`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:04) | read-status fields, write controls, timer formula, and programmable completion distinction |
| [TilEm `x4_io.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_io.c), [`x4_init.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_init.c), [`keypad.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/keypad.c), [`link.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/link.c), and [`timers.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/timers.c) | legacy latches, reset ordering, ON/link edges, timer completion, `HALT` policy, and disconnected USB values |
| [Wabbitemu `83psehw.c`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/hardware/83psehw.c) | independent standard-interrupt, mapping, ON, timer, and low-power implementation |
| [MAME 0.287 `ti85.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85.cpp) and [`ti85_m.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85_m.cpp) | TI-84 Plus machine status, I/O map, interrupt masks, standard timers, programmable timers, and fixed USB reads |
| [jsTIfied deployed `20170706a` artifact](https://www.cemetech.net/projects/jstified/jstified_compressed.js?20170706a) and [readable mirror](https://github.com/Quuxplusone/ti83/blob/56246a1181f90123a843ea17eb9e0f2fcda65113/jstified.js) | fourth interrupt-mask, timer, ON, link, halted-state, and fixed-USB implementation |
| Local OS 2.55MP page-0 bytes | entry, gates, test order, handlers, acknowledgement, and exit |
| `/tmp/tilem-power-cycle.trace` | shutdown and ON-wake execution sequence |
