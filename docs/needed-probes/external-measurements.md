# External measurements

Several open questions concern voltage, current, analog timing, boot state, or
power interruption. Calculator assembly can provide a repeatable trigger and
record CPU-visible state, but it cannot produce the physical observation by
itself.

## Instrumented experiments

| Question | Calculator-side action | External equipment | Required capture |
|----------|------------------------|--------------------|------------------|
| Battery thresholds and hysteresis | run `HWBATT`, then `HWBRAW`, at each stable point | current-limited adjustable supply and calibrated DMM | upward/downward voltage, load current, both AppVars, and settling time |
| Port-`0x39` direction and port-`0x3A` signals | step one candidate bit while preserving the OS GPIO state | high-impedance scope or logic analyzer; current measurement where needed | pin voltage, direction, readback, and USB/battery operating state |
| Two-wire link pull-ups and thresholds | drive port `0x00` states `3`, `0`, `1`, and `2` with a long identifying preamble | scope, logic analyzer, and switched resistor loads | tip/ring voltage, rise time, threshold transition, CPU speed, and AppVar |
| Link abort pulse | enter the ROM abort path with an idle and a stalled peer | scope or logic analyzer | both-low pulse voltage and duration at both CPU speeds |
| Absolute CPU and oscillator frequency | toggle a released link output around a fixed instruction loop | frequency counter or scope | requested port-`0x20` mode, measured frequency, supply voltage, and temperature |
| LCD bus timing | bracket command, data-read, and data-write loops with a trigger | logic analyzer on the LCD bus | `/CE`, read/write strobes, busy/ready intervals, controller revision, and wait-register state |
| LCD analog state | apply one guarded contrast or power setting at a time | DMM/scope on the contrast rail and a camera | rail voltage, visible panel result, command, ambient conditions, and restoration result |
| USB PHY and enable timers | run snapshots or a bounded transfer with a controlled peer | USB protocol analyzer and, for PHY levels, a scope | ports `0x49`–`0x5B`, D+/D− state, packets, timing, role, and cable state |
| Flash command status and duration | execute a RAM-resident worker in an isolated scratch sector | logic analyzer and stable power fixture | command addresses/data, DQ7/DQ5/toggle reads, duration, sector, voltage, and temperature |

Do not drive a pin against an unknown ASIC output. Begin with a high-impedance
measurement and a read-only snapshot. [standard]

## Reset and boot-stage experiments

An ordinary `Asm(` program begins after the reset behavior of interest. These
questions require a boot-stage hook, custom recovery image, hardware debugger,
or external bus capture:

- reset entry and the transition to `3F:413F`;
- cold versus warm RAM contents and reset values before TI-OS writes them;
- reset retention of timers, MD5 state, USB state, protection fields, and
  pending probe markers; and
- protected-write transients during the boot complement tests.

A screen message cannot survive the event reliably. Store a pending marker
before the trigger and recover it through code that runs before normal TI-OS
cleanup, or infer the event from an external trace.

## Flash interruption and destructive tests

Power-loss atomicity must be measured by cutting physical power at each
garbage-collector journal phase and during active program or erase commands.
A link-line edge can trigger the power switch, but it does not prove when the
Flash chip accepted the command; retain the simultaneous bus capture.

Use only a backed-up, expendable calculator. Keep the result record outside
the tested sector. Chip erase, fast-program mode, and forced DQ5 failure are
laboratory procedures, not ordinary distributable `AsmPrgm` files. A failed
run may destroy the OS, certificate data, archive contents, or the recovery
path itself.

Do not distribute a mutating hardware probe until all recovery gates exist.
Verify a complete restorable backup on a second host, reserve an erased scratch
sector that contains no user variables, and reject every address outside that
sector before unlocking Flash. Exclude the OS, certificate, and boot sectors
unconditionally. Use stable external power, keep a known recovery calculator
and cable available, and store the pending/result record outside the sector
under test. Restore the scratch sector after every completed run and verify its
hash. A missing backup, failed restore rehearsal, unexpected sector byte, low
battery indication, or absent external capture must abort before mutation.
