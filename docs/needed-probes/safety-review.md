# Adversarial safety review

This review treats every emulator success as control-flow evidence, not proof
that an unmeasured ASIC, replacement LCD, Flash chip, power source, or external
fixture behaves safely. No physical `HWP1` result is present in the repository.
The classifications below therefore gate first physical runs. [confirmed] for
the source, assembled artifacts, host validators, and emulator executions;
[hypothesis] for real-hardware behavior.

## Release classes

The default build manifest records `physical_use_class`. The physical-evidence
bundler refuses an artifact marked `blocked`. `Laboratory-only` means the
artifact still requires a replaceable, identified calculator, stable power, a
hashed backup attachment, and a restore rehearsal. `Conditional` means the
listed preconditions remain mandatory; it does not mean that physical
execution has been validated.

| Artifact | Class | Adversarial result |
|----------|-------|--------------------|
| `HWASIC` | conditional | Intended writes are limited to result creation and display state. |
| `HWPUSB` | conditional | Performs no I/O write, but unknown read-to-clear behavior remains possible. Start disconnected. |
| `HWPMD5` | conditional | Replaces accelerator operands and control state. Run with no MD5 operation active, then reset before relying on the accelerator. |
| `HWPRAM` | laboratory-only | Guards the direct-`Asm(` mapper context and persists the six original bytes before its first test write. A pending AppVar still depends on RAM surviving the interruption. |
| `HWBATT` | conditional | Restores sampled state, but a controlled-supply run needs a validated unit-specific power procedure. |
| `HWBRAW` | blocked | Fixed-page and mapper guards now precede every write, and cleanup normalizes selector `0x06`. The repository still lacks a device-specific supply range, clamp, current limit, injection-contact procedure, and brownout cutoff. |
| `HWLINK` | conditional | Drives both link lines. Run only with an empty jack unless a separately reviewed high-impedance fixture defines voltage and current limits. |
| `HWKEYS` | conditional | Both operator waits now have watchdogs. A timeout leaves trigger `0xFF`, skips measurement, and restores the keypad selector. |
| `HWBUS` | laboratory-only | Sends locked `0xF0` read-array commands. Restrict physical use to an identified stock AMD-compatible Flash device with stable power and pre/post fixed-page hashes. |
| `HWPFX` | conditional | Restores wait and timer state; a reset during the run can still require recovery. |
| `HWTMR` | conditional | Restores speed, prescaler, timer, and mask state; a reset during mutation remains outside the cleanup path. |
| `HWPRTC` | conditional | Performs no RTC write. Both progress and rollover waits are bounded and report distinct timeout outcomes. |
| `HWPMAP` | blocked | Paired-mode execution assumes the mapping behavior being measured. A different ASIC transition can unmap the worker before cleanup. A pending AppVar records the attempt but cannot recover execution. |
| `HWPLCD` | laboratory-only | Touches one visible cell with its original value. A ready timeout now uses a separately bounded fixed-delay pointer and movement recovery, but the exact controller latch is not readable. |
| `HWPIRQ` | laboratory-only | Guard-only exits perform no timer, mask, `I`, or interrupt-mode write. The mutating path uses a pending frame, watchdog, bounded handler, and verified restoration. |
| `HWEF...`, `HWER...` | laboratory-only | The target is an existing `RET`, but a protection exception can reset before cleanup and its ordering remains the measurement. |
| `HWPLAB` | laboratory-only | Device-specific build and recovery gates reduce known risks, but unknown hidden-column aliasing prevents a universal restoration guarantee. |

## Implemented guards

The raw-battery probe verifies canonical `IY`, the OS 2.55MP reset-tail
signature, both helper entries, and the independent mapper context before its
first `OUT`. Port `0x04` reads interrupt status rather than the write latch.
Successful cleanup explicitly writes selector `0x06` and records that write.
[confirmed]

The interrupt probe uses `state_touched` to keep pre-mutation guard exits
read-only. It verifies that ports `0x03`, `0x04`, `0x30`–`0x32`, and `I`
remain unchanged. [confirmed]

The execution-fetch probe does not treat port-`0x04` status as mapper mode. It
requires ports `0x05 = 0x00`, `0x06 = 0x3F`,
`0x07 = 0x81`, `0x0E = 0x00`, and `0x0F = 0x00`, plus the exact OS
signature, before either target mapping. [confirmed]

The RAM probe applies the same readable context guard. It allocates
`HWPRAM21`, repeats the guard, samples the six original bytes, and copies them
into the resident pending frame before writing any test pattern. Outcome
`0xFF` identifies an interrupted pending frame; outcomes 1 and 2 identify
entry and post-allocation mapping rejection. [confirmed]

RTC and keypad waits now have finite instruction watchdogs. The LCD timeout
path now attempts movement and pointer recovery with bounded fixed delays
instead of letting the sticky timeout suppress all later cleanup commands.
Those changes prevent an emulator or abnormal controller from turning a
documented wait into an unbounded program path. [confirmed]

## Evidence acceptance

`physical_probe_evidence.py` recomputes probe-specific acceptance predicates.
A timeout, unsupported outcome, pending frame, cleanup mismatch, restoration
failure, or incomplete laboratory stage remains preserved as a failed
observation, but `state_coverage.complete` is false. The validator rejects a
bundle that changes that failed classification to complete. [confirmed]

Mutating and reset-capable artifacts require one embedded
`calculator_backup` attachment. Its SHA-256 must match the metadata and a
timezone-stamped, passed restore rehearsal that predates the run. The hidden
LCD manifest must bind the same recovery hash. These checks establish artifact
identity and operator preparation; they cannot prove that volatile ASIC or RAM
state is recoverable from a user-variable backup. [confirmed]

## Remaining blockers

Do not run `HWPMAP` on a physical calculator until execution is moved to a
mapping invariant established independently of the transition under test, or
an external watchdog can restore the mapper without executing the remapped
RAM. Emulator agreement is insufficient because the disputed behavior is the
instruction-fetch mapping itself.

Do not run `HWBRAW`, active GPIO direction tests, loaded-link tests, LCD analog
commands, USB PHY experiments, or Flash command experiments from the current
general runbook. Each needs a device-specific procedure with a verified pin
map, deenergized hookup order, one declared power source, voltage and
common-mode limits, series resistance or current limit, maximum dwell,
automatic cutoff, and post-run recovery checks. The repository deliberately
does not invent numerical limits without a board- and controller-specific
source.

The compact-display emulator adapters intercept `_CreateAppVar`. They execute
the probe, codec, pagination, return path, and Wabbitemu display bcalls, but do
not validate retail VAT allocation or low-memory handling. A direct TilEm
attempt with the real bcall correctly reached `ERR:MEMORY` because raw
injection bypasses the TI-OS program-launch heap setup. A genuine link transfer
and OS launch, or a validated save state, is still required for that end-to-end
case.

The compact pages do not carry page indices. Missing or reordered photographs
are detected by the final envelope length and CRC, but an operator must retain
their order. A code whose length is exactly a multiple of 144 also advances to
a cleared final screen before return. Neither issue loses frame data when all
pages are recorded in order, but both remain user-interface hardening work.
