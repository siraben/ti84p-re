# Interrupts (IM1)

*TI-84 Plus OS 2.55MP — Interrupt masks, status, acknowledgement, dispatch, and low-power wake.*

The TI-84 Plus OS runs the Z80 in interrupt mode 1 (IM1) and polls the ASIC's interrupt status. This page separates the USB event gate from the legacy controller at ports `0x03` and `0x04`, then follows acknowledgement, priority, and `HALT` wake behavior.

## Evidence layers

| Evidence | Scope | Confidence |
|----------|-------|------------|
| Page-0 bytes at `ram:0038`–`ram:0244` | IM1 entry, USB and legacy gates, source-test order, handlers, acknowledgement, and exit | [confirmed] |
| Power-cycle trace from `tools/macros/power-cycle.macro` | OS mask writes, low-power `HALT`, ON wake, status read, debounce, and restoration | [confirmed] |
| WikiTI ports `0x03` and `0x04` | Bit-level enable, status, clear-on-zero, timer-rate, mapping, battery-selector, and low-power contract | [standard] |
| TilEm commit `f56ad63` and Wabbitemu commit `48c2dc0` | Two executable interpretations of the registers and their fidelity gaps | [standard] |
| MAME 0.287 `ti84pv3` driver and Lua I/O trace | Third implementation, headless ON-wake execution, and explicit `MACHINE_NOT_WORKING` gaps | [standard] |

The ROM proves how OS 2.55MP uses the registers. Public notes and emulators describe behavior inside the ASIC that the ROM cannot prove by itself. Emulator agreement is supporting evidence, not physical confirmation.

## IM1 entry and context

IM1 accepts a maskable interrupt at fixed address `ram:0038`. The OS vector jumps to `ram:006D`, where it swaps `AF`, `BC`, `DE`, and `HL` with the alternate register set. The normal exit swaps them back, executes `EI`, and returns with `RETI`. [confirmed]

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

Port `0x55` is the active-low USB interrupt summary. The three instructions at `ram:006F` invert and mask its low five bits. A result of zero jumps directly to the legacy status read at `ram:003A`. A nonzero result enters the USB activity-hook and port-`0x56` event paths before the handler considers the legacy controller. [confirmed]

This ordering does not make port `0x55` a summary of ON, standard-timer, or legacy link requests. Those sources appear at port `0x04`. Port `0x56` is a USB line-event bitmap, not the mask for port `0x04`. [confirmed] for the separate ROM paths; [standard] for the register roles.

The disconnected TilEm x4 model returns `0x1F` from port `0x55` and zero from port `0x56`. Its ordinary trace therefore takes `ram:006F` → `ram:003A` without USB event work. [standard]

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
| 0 | ON request pending | branch to `ram:015B` | ROM test at `ram:00D2`–`ram:00D5` [confirmed]; latch role [standard] |
| 1 | standard timer 1 pending | branch to `ram:0167` | ROM test at `ram:00D6`–`ram:00D9` [confirmed]; pending role [standard] |
| 2 | standard timer 2 pending | branch to `ram:01F1` | ROM test at `ram:00C8`–`ram:00CB` [confirmed]; pending role [standard] |
| 3 | one when ON is released, zero while pressed | debounce reads at `ram:0975` | ROM interpretation [confirmed]; electrical level [standard] |
| 4 | legacy link activity pending | branch to `ram:01E0` | ROM test at `ram:00CD`–`ram:00D0` [confirmed]; pending role [standard] |
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

OS 2.55MP uses programmable timer 1 for its timer bcall state machine and programmable timer 3 for a USB timeout path. Standard timer 1 drives keypad scanning, cursor blink, the run indicator, and Auto Power Down (APD) through `ram:0167`. [confirmed]

See [Clock, timers, and power](clock-timers-power.md) for programmable-timer modes, the bcall ABI, and kernel-tick consumers.

## ON request versus ON level

Port-`0x04` bit 0 is the ON interrupt latch. Bit 3 is the button's current active-low level. The dispatcher selects the ON handler from bit 0, while `on_key_debounce_power` at `ram:0964` repeatedly samples bit 3 to classify a stable press or release. [confirmed]

The power-cycle trace reads `0x01` after the injected ON press. Bit 0 reports the request and bit 3 clear reports the held key. The two meanings coincide in this event but remain independent fields. [confirmed]

TilEm requests an ON interrupt on both press and release transitions when enabled. Wabbitemu latches only a transition into its pressed state. The ROM handles either stable level, but it cannot determine the physical ASIC's edge policy. [standard] for emulator behavior; [hypothesis] for the unmeasured physical policy.

See [Keypad and ON-key hardware](keypad-on-hardware.md#on-interrupt-and-level) for debounce timing and the OS ON state machine.

## Link interrupt versus periodic link polling

Port-`0x03` bit 4 controls the legacy link-activity interrupt. The shutdown mask `0x11` uses it as a wake source. The port-`0x04` bit-4 dispatcher branch enters the power restoration path at `ram:01E0`. [confirmed] for OS use; [standard] for the interrupt source.

Normal operation uses mask `0x0B`, so legacy link interrupts are disabled. Standard timer 1 still performs a periodic silent-link check at `ram:01B1`: the raw path reads port `0x00`, and the assist path reads port `0x09`. This polling is separate from a direct port-`0x04` bit-4 request. [confirmed]

See [Two-wire link port hardware](link-port-hardware.md#background-link-detection-and-interrupts) for both detection paths.

## Low-power entry and wake

The shared power-off tail first acknowledges legacy sources with `0x08`. It then writes `0x06` to port `0x04`, writes `0x11` to port `0x03`, enables interrupts, and loops on `HALT`. [confirmed]

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

| Behavior | TilEm x4 | Wabbitemu 83+SE/84+ | Consequence |
|----------|----------|---------------------|-------------|
| Port `0x03` read | returns stored mask | returns stored mask | mask reads agree [standard] |
| Legacy clear-on-zero | clears ON, timer 1, timer 2, and link pending state on port-`0x03` writes | clears ON on port-`0x03`; advances timer phase from its port-`0x02` output handler | Wabbitemu does not reproduce the documented OS acknowledgement path [standard] |
| Link status | implements port-`0x04` bit 4 | omits bit 4 from port-`0x04` reads | link wake cannot be cross-checked there [standard] |
| Standard timers | explicit pending interrupt bits when enabled | derives status from elapsed phase while enabled | simultaneous-source and latch tests can differ [standard] |
| Programmable completion | exposes finished bits 5–7 independently of interrupt mode | exposes timer-underflow bits 5–7 | both separate completion from mode, with different timer cores [standard] |
| `HALT` behavior | port-`0x03` bit 3 selects powered/low-power behavior; standard-timer mask controls programmable wake suppression | approximates low power by changing LCD activity and suppresses programmable-timer requests while halted | neither model proves physical ASIC power domains [standard] |
| USB gate | disconnected fixed values `0x55 = 0x1F`, `0x56 = 0` | partial `Fake USB` event model | connected USB interrupt service needs another test target [standard] |

Wabbitemu's source comments state uncertainty about its standard-interrupt write behavior. Its model is useful as an independent implementation comparison, but disagreement must remain explicit. [standard]

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

## Reusable debugging tools

`tools/interrupt_controller.py` provides typed decoders, exact timer periods, clear-on-zero acknowledgement, ROM status-test order, and USB active-low decoding. `tools/describe_interrupt_controller.py` exposes focused CLI commands: [confirmed]

```sh
nix develop -c python tools/describe_interrupt_controller.py mask 0x0B
nix develop -c python tools/describe_interrupt_controller.py status 0x8B
nix develop -c python tools/describe_interrupt_controller.py config 0x06
nix develop -c python tools/describe_interrupt_controller.py ack 0xF7 0x08
```

The trace command resolves mapper state, restricts output to interrupt ports, annotates each value, and collapses consecutive identical polls: [confirmed]

```sh
nix develop -c python tools/describe_interrupt_controller.py trace \
  /tmp/tilem-power-cycle.trace --clock 97000000-101000000
```

Use `--all` to retain repeated ON-level polling and `--json` for machine-readable output.

`tools/mame_trace.py`, `tools/run_mame_io_trace.py`, and `tools/mame_io_trace.lua` provide the equivalent headless MAME path. The Lua tap accepts comma-separated ports and ranges, collapses identical polls, records post-I/O PCs, and can inject ON at selected video frames: [confirmed]

```sh
nix shell nixpkgs#mame -c python tools/run_mame_io_trace.py \
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
- [hypothesis] Physical TA2 and TA3 tests should measure ON request edges, link wake transitions, simultaneous legacy-source coalescing, programmable-timer wake behavior, and battery-selector thresholds.

## Sources

| Source | Used for |
|--------|----------|
| [WikiTI port `0x03`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:03) | enable mask, clear-on-zero acknowledgement, normal value, and low-power-on-`HALT` contract |
| [WikiTI port `0x04`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:04) | read-status fields, write controls, timer formula, and programmable completion distinction |
| [TilEm `x4_io.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_io.c) and [`timers.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/timers.c) | legacy latches, mask handling, timer completion, `HALT` policy, and disconnected USB values |
| [Wabbitemu `83psehw.c`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/hardware/83psehw.c) | independent standard-interrupt, mapping, ON, timer, and low-power implementation |
| [MAME 0.287 `ti85.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85.cpp) and [`ti85_m.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85_m.cpp) | TI-84 Plus machine status, I/O map, interrupt masks, standard timers, programmable timers, and fixed USB reads |
| Local OS 2.55MP page-0 bytes | entry, gates, test order, handlers, acknowledgement, and exit |
| `/tmp/tilem-power-cycle.trace` | shutdown and ON-wake execution sequence |
