# Physical hardware probes

The physical-probe suite builds small `AsmPrgm` programs and decodes their
result AppVars. The sources cover MD5-assist edge behavior, RAM selector
aliasing, execution-protection boundaries, repeated battery-level bcalls, raw
battery-comparator selectors, memory-bus and prefix-M1 timing, keypad-matrix
settling, programmable-timer edge behavior, and raw two-wire link readback,
plus read-only ASIC and USB register snapshots. No exported result from a
physical calculator has been recorded, so the hardware conclusions remain
open.

## Measurement status

The builder, link-file containers, entry jumps, bcall ID, frame layouts, and
restoration or cleanup instruction sequences have byte-level host validation.
[confirmed]
Physical execution of any program remains [hypothesis] until an exported
result AppVar is decoded and tied to a calculator and ASIC revision.

| Probe | Program | Result AppVar | Physical status |
|-------|---------|---------------|-----------------|
| MD5 edge behavior | `HWPMD5` | `HWPMD511` | Not run on a recorded unit |
| RAM selector aliasing | `HWPRAM` | `HWPRAM21` | Not run on a recorded unit |
| ASIC register snapshot | `HWASIC` | `HWPASIC1` | Not run on a recorded unit |
| Battery-level stability | `HWBATT` | `HWBATT01` | Not run on a recorded unit |
| Raw battery selectors | `HWBRAW` | `HWBRAW01` | Not run on a recorded unit |
| Raw link readback | `HWLINK` | `HWLINK01` | Not run on a recorded unit |
| Keypad-matrix settling | `HWKEYS` | `HWKEYS01` | Not run on a recorded unit |
| Six memory wait classes | `HWBUS` | `HWBUS001` | Not run on a recorded unit |
| Prefixed RAM M1 placement | `HWPFX` | `HWPFX001` | Not run on a recorded unit |
| Programmable-timer edges | `HWTMR` | `HWTMR001` | Not run on a recorded unit |
| USB control snapshot | `HWPUSB` | `HWPUSB01` | Not run on a recorded unit |
| Flash execution boundaries | `HWEF07`–`HWEF2A` | matching `HWEF...01` names | Not run on a recorded unit |
| RAM execution boundaries | `HWER81`–`HWER84` | matching `HWER...1` names | Not run on a recorded unit |

The eight-character AppVar names are versioned fixture names. Delete an
existing result AppVar before rerunning its probe. `_CreateAppVar = 4E6A` does
not replace a variable with the same name. [confirmed] for the local ROM bcall
path at `00:1129`–`00:112F`.

## Build and transfer

SPASM-ng is part of the Nix development shell. Build all transfer files and a
hash manifest with:

```sh
nix develop -c python tools/build_hardware_probes.py \
  --output-dir /tmp/hardware-probes
```

The command emits the 11 snapshot, edge, and timing probes, ten single-fetch
execution probes, and `manifest.json`. The manifest records every target
selector and scan range. It uses repository-relative source names and output
basenames, so builds made in different checkout directories remain comparable.
The CLI refuses an existing output directory. The hashes identify exact
artifacts; they do not establish that a calculator executed them.

Transfer the `.8xp` files with TI Connect CE or another link program. Make
a calculator backup before the first run. Then:

1. Delete the probe's result AppVar if it already exists.
2. Run `Asm(prgmHWASIC)` for the read-only register snapshot.
3. Disconnect the 2.5 mm link port, then run `Asm(prgmHWLINK)` for the raw-link
   sample with release-to-idle cleanup.
4. Run `Asm(prgmHWKEYS)`, release the launch key, and hold the recorded test key
   or chord until the program returns.
5. Run `Asm(prgmHWBATT)` for the restoring battery-level sample.
6. Run `Asm(prgmHWBRAW)` for the higher-risk direct-selector sample only after
   `HWBATT` succeeds and its result has been exported.
7. Run `Asm(prgmHWPUSB)` for the read-only USB control snapshot.
8. Run `Asm(prgmHWPMD5)` for the MD5 probe.
9. Run `Asm(prgmHWBUS)` on OS 2.55MP for the guarded bus-timing measurement.
   Export its result before another mutating probe.
10. Run `Asm(prgmHWPFX)` for the guarded prefix-M1 timing measurement. Export
    its result before another mutating probe.
11. Run `Asm(prgmHWTMR)` for the guarded programmable-timer edge measurement.
    Export its result before another mutating probe.
12. Run `Asm(prgmHWPRAM)` for the RAM probe only after the earlier transfer and run
    path works on that unit.
13. Run at most one `HWEF...` or `HWER...` execution probe before exporting its
    result. A denied fetch may reset the calculator.
14. Export the new result AppVar to the host.
15. Record the calculator model, PCB or ASIC revision, boot version, OS version,
    exact held keys, and artifact hashes with the exported file.

Do not treat an emulator run as a physical result. TilEm and Wabbitemu are
comparison implementations for the expected edge cases. MAME 0.287 does not
map the MD5 port block. [standard]

## Decode a result

The decoder verifies the TI link checksum, both TI entry lengths, the AppVar's
internal size word, the `HWP1` frame version, and the payload length before it
interprets measurements. [confirmed]

```sh
python tools/decode_hardware_probe.py HWPMD511.8xv
python tools/decode_hardware_probe.py --json \
  HWPASIC1.8xv HWBATT01.8xv HWBRAW01.8xv HWPUSB01.8xv \
  HWLINK01.8xv HWKEYS01.8xv HWBUS001.8xv HWPFX001.8xv HWTMR001.8xv \
  HWPMD511.8xv HWPRAM21.8xv
```

The JSON form keeps the raw payload and adds named fields. Preserve the
original exported AppVar even when a report has been generated.

## Result frame

The calculator stores the frame after the AppVar's normal two-byte internal
size word. Multi-byte lengths use little-endian order.

| Offset | Size | Field |
|-------:|-----:|-------|
| `0` | 4 | ASCII magic `HWP1` |
| `4` | 1 | format version, currently `1` |
| `5` | 1 | probe ID |
| `6` | 2 | payload length |
| `8` | 1 | port-`0x15` ASIC identity read |
| `9` | 1 | port-`0x02` status read |
| `10` | variable | probe payload |

`_CreateAppVar` returns `DE` at the internal size word. The shared assembly
routine advances `DE` twice before copying `HWP1`. The builder rejects an
artifact without the byte sequence for this advance. [confirmed] from local
ROM bytes at `00:1129`–`00:112F` and the assembled probe listings.

## MD5 edge probe

Probe ID 1 records five four-byte fields:

| Payload offset | Field | Operation |
|---------------:|-------|-----------|
| `0` | valid result | first MD5 compression step for `"abc"`; expected arithmetic result `0xD6D117B4` |
| `4` | undefined reads | direct reads from ports `0x18`–`0x1B` |
| `8` | fifth-write result | four zero bytes and a fifth `0x12` byte written to operand `A` |
| `12` | high-control result | `0xFF` written to mode and rotate-count ports |
| `16` | mixed result | operand `A` changed after result byte 0 and before bytes 1–3 |

The valid arithmetic vector follows the ROM's operand order and RFC 1321.
[confirmed] for the ROM transaction and arithmetic. The four edge results are
physical [hypothesis]. See [MD5 accelerator and boot API](md5-hardware.md) for
the emulator comparison.

The program disables interrupts while it uses ports `0x18`–`0x1F`. It clears
all six operand registers and both controls before restoring the caller's
interrupt state. It does not preserve an earlier internal MD5-assist state,
which the port interface cannot read back directly. [confirmed] for the
assembled instruction sequence.

## RAM alias probe

Probe ID 2 tests selectors `82`–`87` at bank-A address `0x7F00`. Its 18-byte
payload contains six original bytes, six observed pattern bytes, and six bytes
read after restoration.

The program saves port `0x06`, disables interrupts, and records the byte visible
through each selector. It writes `11 22 33 44 55 66`, rereads all selectors,
restores each saved byte, verifies the restored values, and restores port
`0x06`. [confirmed] for the assembled instruction sequence.

An observed sequence of `11 22 33 44 55 66` distinguishes six independent
selector backings for this address. `66 66 66 66 66 66` distinguishes a shared
backing for selectors `82`–`87`. The decoder also infers partial equivalence
classes. Because writes occur in ascending selector order, every selector in
one class must read the pattern written through the highest-numbered member.
Bytes outside `11 22 33 44 55 66`, or a group whose reported writer is not its
highest member, produce `mixed-or-unexpected`. [confirmed]

The decoder reports `restore_matches`. A false value means the post-restore
reads differ from the saved bytes and invalidates a claim of successful cleanup.

The standalone CLI accepts the six observed bytes or simulates an explicit
selector-to-backing assignment:

```sh
python tools/describe_ram_topology.py --observed 666666666666
python tools/describe_ram_topology.py \
  --simulate-backings 0,0,1,1,2,3 --json
```

The pinned SPASM-ng build produces 214 machine-code bytes with SHA-256
`be8e1dc12060cda657cf076196e9f27302822cf7307935b5bf4056b0c55c548d`.
The packaged 508-byte `HWPRAM.8xp` has SHA-256
`72da5a412b596161b50f03fa5d5f2018d88b26c51207208bdf63335a9c67f6e3`.
[confirmed]

## Execution-protection fetch probes

Probe ID 4 tests one bank-A selector per program. It scans the configured range
through data reads for an existing `RET` byte. It creates a result AppVar with a
pending outcome, remaps and verifies that byte, and performs:

```z80
PUSH DE
JP (HL)
```

A successful fetch executes `RET`, returns to the probe, and changes the AppVar
outcome to `returned`. The program never writes the selected RAM or Flash page.
[confirmed] for the assembled instruction sequence.

The existing `RET` is also the only target opcode. It has no memory-write or
I/O side effect, which limits risk if a protection exception is delivered after
the opcode executes. Pinned TilEm uses that ordering: it completes a forbidden
opcode and resets afterward. A pending result after reset therefore does not
distinguish a suppressed opcode from an executed `RET` followed by reset. The
probe measures return-versus-reset behavior, not the precise exception point.
[standard] for TilEm; [hypothesis] for the physical ASIC.

| Payload offset | Size | Field |
|---------------:|-----:|-------|
| `0` | 1 | target kind: 0 Flash, 1 RAM |
| `1` | 1 | port-`0x06` selector |
| `2` | 2 | logical scan start |
| `4` | 2 | scan length |
| `6` | 2 | selected `RET` address, or `0xFFFF` |
| `8` | 1 | outcome code |
| `9` | 7 | ports `0x04`, `0x06`, `0x21`–`0x23`, `0x25`, and `0x26` |

| Program | Result AppVar | Selector and scan range | TilEm x4 | Wabbitemu |
|---------|---------------|-------------------------|----------|------------|
| `HWEF07` | `HWEF0701` | Flash `07`, `0x4000`–`0x7FFF` | returned | returned |
| `HWEF08` | `HWEF0801` | Flash `08`, `0x4000`–`0x7FFF` | violation reset | returned |
| `HWEF09` | `HWEF0901` | Flash `09`, `0x4000`–`0x7FFF` | violation reset | violation reset |
| `HWEF29` | `HWEF2901` | Flash `29`, `0x4000`–`0x7FFF` | violation reset | violation reset |
| `HWEF2A` | `HWEF2A01` | Flash `2A`, `0x4000`–`0x7FFF` | returned | returned |
| `HWER81` | `HWER8101` | RAM selector `81`, `0x4000`–`0x7FFF` | returned | returned |
| `HWER820` | `HWER82A1` | RAM selector `82`, `0x4000`–`0x43FF` | violation reset | returned |
| `HWER821` | `HWER82B1` | RAM selector `82`, `0x4400`–`0x47FF` | violation reset | violation reset |
| `HWER83` | `HWER8301` | RAM selector `83`, `0x4000`–`0x7FFF` | returned | returned |
| `HWER84` | `HWER8401` | RAM selector `84`, `0x4000`–`0x7FFF` | violation reset | violation reset |

These outcomes assume the retail boot values: port `0x21` mode 0, Flash bounds
`08`–`29`, and RAM chunk bounds `10`–`20`. They are predictions from the pinned
emulator predicates, not physical results. The decoder reports ports `0x04`,
`0x06`, `0x21`–`0x23`, `0x25`, and `0x26` from immediately before the test.

In paired mapper mode, a port-`0x06` write remaps bank B with bank A. That can
unmap the running probe. Every artifact therefore records
`unsupported-paired-mapping` without writing port `0x06` or attempting the
fetch when port `0x04` bit 0 is set. [standard] for the emulator predictions;
[confirmed] for the artifact guard.

The other outcomes are `no-ret-found` and `target-changed-before-fetch`.
Neither measures execution protection. A pending AppVar after an observed
reset is evidence only if the AppVar survived that reset unchanged. Export the
file before running another probe, and record whether the calculator visibly
reset. Reset retention and the physical fetch outcomes remain [hypothesis].

## ASIC register snapshot

Probe ID 3 reads ports `0x04`, `0x20`, `0x21`, `0x29`–`0x2C`, `0x2E`, `0x2F`,
`0x39`, and `0x3A`. Port `0x15` identity and port `0x02` status remain in the
common frame header. The payload preserves the listed port order. [confirmed]

The program performs no ASIC register writes. It disables interrupts across
the reads so an interrupt handler cannot change the sampled configuration
between fields. The result AppVar is its only intended persistent change.
[confirmed] for the assembled instruction sequence; [hypothesis] for physical
read values.

This snapshot establishes a starting configuration for later bus-timing and
GPIO tests. It cannot measure T-state additions, GPIO direction polarity, or
electrical pin levels. Those tests require controlled register writes and
external timing or voltage observations. See [Bus timing and wait
states](bus-timing.md#open-physical-tests) and [ASIC status, identity,
protection, and GPIO](asic-status-gpio.md#open-physical-tests).

## Battery-level probe

Probe ID 6 calls `_Chk_Batt_Level = 5221h` 16 times and records every value
returned in `A`. The result frame also saves state before the first call, after
the final call, and after cleanup: [confirmed]

| Payload range | Contents |
|--------------:|----------|
| `0`–`3` | pre-call ports `0x04`, `0x39`, and `0x3A`, then `(IY+0x18)` `traceFlags` |
| `4`–`19` | 16 `_Chk_Batt_Level` results |
| `20`–`24` | post-call status, ports `0x04`, `0x39`, `0x3A`, and `traceFlags` |
| `25`–`28` | readback after restoring the three ports and `traceFlags` |
| `29` | final port-`0x02` status |

The decoder rejects result bytes outside 0–4. It reports a five-bin histogram,
a stable level only when all 16 samples agree, and `cleanup_matches` only when
the three port readbacks and complete flag byte match their saved values.
The probe restores the caller's interrupt-enable state before creating the
AppVar. [confirmed] for source, assembled bytes, and decoder behavior.

Run the probe at a stable supply voltage, export `HWBATT01`, record the measured
rail voltage and load externally, and delete the AppVar before the next point.
An upward and downward sweep can locate OS-visible transitions and hysteresis.
The result is the retail bcall's level, not a direct voltage measurement or a
raw comparator-bit trace. [hypothesis] for pending physical results.

The pinned SPASM-ng build produces 304 machine-code bytes with SHA-256
`4fcb9e9052fcccad350cd3b7901235a4cb87390eeb764e78e7be0686d0da99ea`.
The packaged 688-byte `HWBATT.8xp` has SHA-256
`9d075837dc399ec0771e563c747e7498b4c260fe6f4fee128f17a57ba238fea0`.
[confirmed]

## Raw battery-selector probe

Probe ID 7 samples the port-`0x02` comparator after each selector used by
`_Chk_Batt_Level`. It runs the sequence 16 times and records one four-bit mask
per sequence. The bit assignment stays in numeric selector order even though
the ROM tests the final three selectors in another order: [confirmed]

| Mask bit | Port-`0x04` selector | Sample order |
|---------:|---------------------:|-------------:|
| 0 | `0x06` | first |
| 1 | `0x46` | fourth |
| 2 | `0x86` | third |
| 3 | `0xC6` | second |

Each selector write executes five calls to `00:0CEB`, then reads comparator bit
0 from port `0x02`. The first `0x06` sample precedes the port-`0x3A` bit-7
enable. The probe then samples `0xC6`, `0x86`, and `0x46`. It continues through
all four selectors even when the initial sample is zero. The retail bcall can
return early instead. [confirmed] from the assembled probe and the ROM path at
`33:4EDC`–`33:4EE8`.

After each sequence, the probe reproduces the cleanup at `33:4EEB`–`33:4F00`:
it sets port-`0x39` bit 4, pulses port-`0x3A` bit 4 around
`CALL 00:0CED` with `A = 0x40`, and clears port-`0x3A` bits 4 and 7. The common 30-byte
state layout matches the battery-level probe, with raw masks at offsets
`4`–`19` and post-sequence state at offsets `20`–`24`. The decoder rejects
masks above `0x0F`. It reports a 16-bin histogram, a stable mask only when all
samples agree, pass counts for each selector, and `cleanup_matches`. [confirmed]

Run `HWBATT` before this probe at each voltage point. Export both AppVars and
record the externally measured rail voltage and load. Sweep upward and downward
slowly enough to distinguish threshold crossings from noise and hysteresis.
`HWBATT01` records the OS-visible result; `HWBRAW01` identifies which selector
comparators passed. Neither AppVar measures voltage. [hypothesis] for pending
physical results.

This probe directly manipulates battery-selection GPIO. An interruption or
reset before cleanup can leave the selection state changed. Use a backed-up
test calculator, stable externally current-limited power, and an independently
verified voltage before running it. Do not run it as the first probe on a unit.

The pinned SPASM-ng build produces 397 machine-code bytes with SHA-256
`d28548e32a53189f32c6ba7f2a4aba85278453ebcf8d1fba8f788f735f24b57c`.
The packaged 874-byte `HWBRAW.8xp` has SHA-256
`c0316a51a5262a32143fa72fe11c8ba510ee9aee1f87f8e28466777c54057586`.
[confirmed]

## USB control snapshot

Probe ID 5 reads ports `0x49`, `0x4A`–`0x4D`, `0x4F`–`0x52`,
`0x54`–`0x57`, `0x5A`, and `0x5B`. Port `0x15` identity and port `0x02`
status remain in the common frame header. The 15-byte payload preserves this
port order. [confirmed]

The program performs no I/O writes. It disables interrupts across the reads so
the OS interrupt handler cannot alter the sampled USB state between fields.
It then restores the caller's interrupt-enable state before creating the
result AppVar. The builder verifies one direct `IN` instruction for every
listed port. [confirmed] for source and assembled bytes; [hypothesis] for
physical read values.

The pinned SPASM-ng build produces 174 machine-code bytes with SHA-256
`8a720e21077a9cad678b20228b5f66c8c7f54a83651989da0fe75b9807dc7e7f`.
The packaged 428-byte `HWPUSB.8xp` has SHA-256
`dc2f769c4b6fc98a9b47f66b7f6acdd9523810956de131aa42079c4cfa25027c`.
[confirmed]

Ports `0x49`, `0x51`, and `0x52` test historical transceiver and enable-timer
claims that have no confirmed OS 2.55MP transaction. Ports `0x4B`, `0x4F`,
`0x50`, and `0x5A` provide readback for controls whose ROM writes are known but
whose physical meanings remain incomplete. The snapshot does not enable USB,
start a timer, or test presentation mirroring. Connected and disconnected
captures on known TA2 and TA3 units are both needed. See [USB ASIC and link
assist](sub-usb-asic.md#transceiver-and-enable-timer-ports-without-confirmed-rom-control-flow).

## Raw two-wire link probe

Probe ID 8 measures CPU-visible port-`0x00` readback with the 2.5 mm connector
disconnected. For each target write `0`, `1`, `2`, and `3`, it first writes `3`
to establish both-low, writes the target, waits for 0, 1, 4, or 16 `NOP`
instructions, and reads the complete port byte. It repeats all 16 points 16
times. [confirmed] for the assembled instruction sequence.

The public disconnected digital contract predicts complete read bytes `0x03`,
`0x12`, `0x21`, and `0x30` for target writes 0–3. The low two bits report the
line levels; bits 4–5 report the local output latch. The decoder checks those
fields separately and also reports exact-byte histograms. This distinction
allows a physical result to preserve unexpected upper bits without losing the
ROM-relevant low-line comparison. [standard] for the predicted table;
[hypothesis] for pending physical values.

| Payload range | Contents |
|--------------:|----------|
| `0`–`3` | pre-sequence ports `0x00`, `0x03`, `0x04`, and `0x20` |
| `4`–`259` | 256 samples in write-major, trial-major, delay-major order |
| `260`–`263` | post-sequence ports `0x00`, `0x03`, `0x04`, and `0x20` |
| `264` | port-`0x00` read after writing zero to release both lines |
| `265` | final port-`0x02` status |

The four `NOP` counts define instruction-spaced sample points, not wall-clock
times. `OUT`, `IN`, and ASIC wait states contribute additional delay. A logic
analyzer or oscilloscope is still required for voltage thresholds, pull-up
resistance, and analog rise time. Comparing stable and unstable sample bins can
nevertheless locate a digital readback change between the tested instruction
gaps. [confirmed] for the code spacing; [hypothesis] for physical settling.

Run this probe only with the link connector empty. It deliberately drives both
lines low before every sample and can leave a link-activity request pending.
It disables interrupts during the matrix, releases both lines, records
port-`0x04` before and after, and restores the caller's interrupt state before
creating the AppVar. Cleanup does not depend on the unverified bits-4–5 latch
readback. A reset or interruption before cleanup can leave a line asserted. Use
a backed-up test calculator. Do not attach another calculator, Graph Link,
TI-Keyboard, speaker, or other peripheral.

The pinned SPASM-ng build produces 482 machine-code bytes with SHA-256
`394b2bc9560f277c293d7257f324439619298d5f12c3a2a16cce00cd5f28a8b2`.
The packaged 1,044-byte `HWLINK.8xp` has SHA-256
`8eb8c9e16899044384efd43a01c29d8eef4ff43c92ce106f04419089a1481025`.
[confirmed]

## Keypad settling probe

Probe ID 9 measures port-`0x01` after keypad group-selection edges. It first
selects all groups and waits for the launch key to be released. It then waits
for any held key or chord and records that all-groups read. A 65,535-iteration
settling loop follows before the timed matrix begins. [confirmed] for the
assembled control flow.

For each group write `0xFE`, `0xFD`, `0xFB`, `0xF7`, `0xEF`, `0xDF`, `0xBF`,
and `0x7F`, the probe first writes `0x00` to select every group, writes the
target, waits for 0, 4, 16, or 64 `NOP` instructions, and reads port `0x01`.
It repeats each group and delay point 16 times. The `0x7F` case also tests the
otherwise unused eighth group-selection bit. [confirmed] for the assembled
instruction sequence; [hypothesis] for its physical effect.

| Payload range | Contents |
|--------------:|----------|
| `0`–`4` | pre-sequence ports `0x01`, `0x02`, `0x03`, `0x04`, and `0x20` |
| `5` | all-groups read that triggered the held-chord delay |
| `6`–`517` | 512 samples in group-major, trial-major, delay-major order |
| `518`–`522` | post-cleanup ports `0x01`, `0x02`, `0x03`, `0x04`, and `0x20` |

The decoder reports raw samples, histograms, stable values, active-low pressed
columns, and comparisons with the same trial's 64-NOP value. It distinguishes
an early sample with additional low columns from any other mismatch. That
comparison can identify a read that has not yet released a column after the
all-groups precondition without assuming which keys the operator held.
[confirmed] for the decoder; [hypothesis] for pending physical samples.

The fixed settling loop before measurement is 1,703,905 base T-states. This is
about 0.284 seconds at nominal 6 MHz or 0.114 seconds at nominal 15 MHz. The
probe records port `0x20` so a result retains the selected speed. These values
exclude the preceding `LD DE,0xFFFF`; the timed sample points remain instruction
gaps rather than wall-clock measurements. [confirmed] for the instruction
count; [standard] for the nominal clock conversion.

Delete `HWKEYS01` before the run. Release the launch key, then hold the exact
test key or chord until the program returns. Record every held key with the
exported AppVar. The probe will wait indefinitely if no key is pressed. It
disables interrupts during the wait and matrix, writes `0xFF` to unselect all
groups before restoring the caller's interrupt state, and records adjacent
status, interrupt, and speed ports before and after. It does not measure switch
bounce, analog voltage, or a logic-analyzer waveform.

The pinned SPASM-ng build produces 822 machine-code bytes with SHA-256
`33936def9f7844131f77b970804e7fd8af79610cc93a041afcfb9fd507555e8e`.
The packaged 1,724-byte `HWKEYS.8xp` has SHA-256
`3479ac8eb426977d088c7587da816bc88a67ded0625962334a0a723ce3424d23`.
[confirmed]

## Memory-bus timing probe

Probe ID 10 measures all six port-`0x2E` memory wait classes with programmable
timer 2. Each class has a baseline run with port `0x2E = 0` and a second run
with only that class enabled. Timer source `0x45` divides the 32.768 kHz crystal
by 16, giving a documented 2,048 Hz sample clock. [confirmed] for the assembled
setup; [standard] for the physical timer source.

The probe runs only when timer-2 source and mode ports `0x33` and `0x34` are
zero, port-`0x02` bit 2 reports a locked Flash gate, all four ports
`0x29`–`0x2C` have both memory-group gates set, and fixed Flash bytes
`00:0CE6`–`00:0CEA` equal `F5 23 2B F1 C9`. A failed guard creates a result
with an outcome code and no measurements. [confirmed] for the control flow and
OS 2.55MP helper signature.

| Outcome | Meaning |
|--------:|---------|
| `0` | all guards passed and 12 measurements completed |
| `1` | timer-2 source was active |
| `2` | timer-2 mode/status was nonzero |
| `3` | Flash gate reported unlocked |
| `4` | at least one Flash/RAM timing gate was disabled |
| `5` | fixed-page helper did not match OS 2.55MP |

Every measurement starts counter `0xFF`, runs a fixed loop, then records the
counter, timer-2 mode/status, and port `0x04`. Mode bit 2 or port-`0x04` bit 6
marks an expired sample invalid. The enabled-minus-baseline counter difference
is the added number of 2,048 Hz timer ticks. [confirmed] for the result decoder;
[standard] for the timer completion bits.

| Case | Port-`0x2E` mask | Iterations | Wait-sensitive accesses | Timed operation |
|------|-----------------:|-----------:|------------------------:|-----------------|
| Flash M1 | `0x01` | 4,096 | 20,480 | five opcode fetches per call to `00:0CE6` |
| Flash read | `0x02` | 16,384 | 16,384 | one fixed-page data read |
| Flash write | `0x04` | 16,384 | 16,384 | one locked `0xF0` reset-command write |
| RAM M1 | `0x10` | 16,384 | 65,537 | four loop opcodes per iteration plus counter-read opcode |
| RAM read | `0x20` | 16,384 | 32,769 | one data read and one branch operand per iteration, plus counter operand |
| RAM write | `0x40` | 16,384 | 16,384 | one idempotent scratch-byte write |

The access counts include every fetch affected before the counter read. They do
not treat the loop body as one abstract access. If a class adds one T-state per
listed access, the decoder estimates the CPU frequency as

$$
f_{\mathrm{CPU}} = \frac{N_{\mathrm{wait}} \times 2048}{\Delta_{\mathrm{timer}}}\\,.
$$

Counter quantization makes each individual estimate coarse. Agreement across
the six independent cases is stronger evidence than any single value. A zero
delta means no wait was observed at this resolution; it does not prove a
fractional or conditional delay is absent. [confirmed] for the arithmetic;
[hypothesis] for pending physical results.

| Payload range | Contents |
|--------------:|----------|
| `0`–`12` | pre-sequence ports `0x02`, `0x03`, `0x04`, `0x20`, `0x29`–`0x2C`, `0x2E`, `0x2F`, and `0x33`–`0x35` |
| `13` | outcome code |
| `14`–`49` | six baseline/enabled pairs of counter, mode/status, and port-`0x04` |
| `50`–`62` | post-cleanup copy of the 13 pre-sequence ports |

The Flash-write loop targets `0x0000` with `0xF0` only. On the documented AMD
command interface, `0xF0` is a read-array reset rather than a program or erase
command. The probe also refuses an entry state that reports the protected gate
open. [confirmed] for the emitted address and byte; [standard] for the Flash
reset command; [hypothesis] for the physical gate readback.

The complete run disables interrupts for about one second at nominal 6 MHz and
less at nominal 15 MHz. Standard-timer requests can coalesce during that window,
so OS tick consumers can miss time. After every measurement the probe stops
timer 2, acknowledges its mode port, and restores port `0x2E`. At the end it
restores the idle counter byte and the caller's interrupt state. A reset during
measurement can leave port `0x2E` or timer 2 changed. Use a backed-up OS 2.55MP
calculator with stable power.

The pinned SPASM-ng build produces 636 machine-code bytes with SHA-256
`46c5f64f5ba720a129a4f889af5757dfb34dbc037a60172669c9ad5dcfb76017`.
The packaged 1,352-byte `HWBUS.8xp` has SHA-256
`b9f66cf6cdc3564c6a4d412c36a9a768be388f45b1eeee558d3351c3a0a4a874`.
[confirmed]

## Prefix-M1 timing probe

Probe ID 11 measures how the RAM opcode-wait bit treats six instruction
shapes. Each shape runs 12,288 times with port `0x2E = 0`, then with only RAM
M1 bit 4 set. The program executes from user RAM and uses timer 2 at 2,048 Hz.
[confirmed] for the assembled loops; [standard] for the timer source.

| Case | Bytes | Instruction | Z80 M1 fetches per iteration | Complete-loop M1 count |
|------|-------|-------------|-----------------------------:|-----------------------:|
| Unprefixed | `00` | `NOP` | 1 | 61,441 |
| CB | `CB 42` | `BIT 0,D` | 2 | 73,729 |
| ED | `ED 44` | `NEG` | 2 | 73,729 |
| DD | `DD 7C` | `LD A,IXH` | 2 | 73,729 |
| Repeated DD | `DD DD 7C` | `LD A,IXH` | 3 | 86,017 |
| Indexed CB | `DD CB 00 46` | `BIT 0,(IX+0)` | 2 | 73,729 |

The complete count includes four loop-control M1 fetches per iteration and the
final timer-counter `IN` opcode. The indexed-CB displacement, final opcode, and
`(IX+0)` data access are non-M1 reads on a Z80. Only port-`0x2E` bit 4 is set,
so those reads do not receive the RAM-read delay. [confirmed] for the emitted
bytes and counts; [standard] for the Z80 bus-cycle classification.

`LD A,IXH` is an undocumented Z80 form chosen because it leaves `IX` intact.
The next `LD A,B` overwrites its result. `NEG` also changes `A`, and each `BIT`
changes flags, but the common loop overwrites those values before its branch.
The indexed-CB case reads the current result slot through `IX`; it does not
write through that pointer. [confirmed]

TilEm counts two M1 fetches for the indexed-CB instruction. Wabbitemu applies
its opcode wait to three bytes, although it decrements `R` after the final
fetch. The reusable source analyzer requires TilEm commit
`f56ad637d0524ee841dd381be6ecbaf5b8975600`, Git tree
`58316afe35d69e69353f0f743698144153051d4a`, and Wabbitemu tree SHA-256
`a8a4f97fc7952770bed317b4a477f80345894da38d14fad8f0bf0ee60aae71ba`.
It reports no physical result. [standard]

```sh
python tools/describe_prefix_fetch_models.py \
  --tilem-source /path/to/tilem \
  --wabbitemu-source /path/to/wabbitemu --json
```

The canonical JSON report has SHA-256
`ac5c618269a5a097b2f23c0ac9fc3ed5ca20b1749673b1020206e5c447fbf61c`.
[confirmed] for the hash-guarded source analysis.

The exact assembled image also completed in the pinned Wabbitemu core after a
retail OS 2.55MP boot. The guarded runner injected all 587 bytes into RAM page
`01` and stopped at `01:9EC2`, immediately before `_CreateAppVar`. It
executed 737,692 probe instructions and 5,669,409 modeled T-states without an
execution-violation reset. The baseline-to-enabled timer deltas were 21, 25,
25, 25, 29, and 30 ticks in table order. The indexed-CB delta is one tick from
the repeated-DD three-wait control and five ticks from the mean of the
single-prefix two-wait controls, so the decoder selects
`wabbitemu-three-m1`. [confirmed] for this emulator execution.

The native adapter was built from Wabbitemu commit
`48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422`; the build has SHA-256
`3acb6a18280f9c42d6fe324188eab73f87280ee70b973e1251fcfa50f54fb14e`.
This run validates the assembled loops, timer sampling, restoration path, and
the pinned emulator's wait model. It does not execute AppVar creation, measure
host wall time or electrical timing, or establish physical ASIC behavior.
[confirmed]

The decoder compares the indexed-CB added ticks with the mean of the CB, ED,
and DD rows and with the repeated-DD row. It reports whether the sample is
closer to the two-M1 Z80/TilEm model or Wabbitemu's three-wait model. Timer
quantization can make the result equidistant; retain all raw triples.
[confirmed] for the decoder; [hypothesis] for pending physical samples.

The entry guards require timer-2 source and mode/status to be zero and RAM gate
bit 1 to be set in ports `0x29`–`0x2C`. Outcomes `1`, `2`, and `3` report an
active source, active mode, or disabled RAM gate. The payload uses the same
13-byte pre/post state and 36-byte measurement layout as `HWBUS`. The probe
restores port `0x2E`, timer source and mode, the idle counter, and interrupt
state. A complete nominal-6-MHz run masks interrupts for about one second.
[confirmed]

Delete `HWPFX001` before running `Asm(prgmHWPFX)`. Retain the exported AppVar,
probe manifest, calculator model, PCB or ASIC revision, and OS version together.

The pinned SPASM-ng build produces 587 machine-code bytes with SHA-256
`5e58ddfb1df820b79446fc10c79b681d0c58f7f16b252d18f1fef44d576a045b`.
The packaged 1,254-byte `HWPFX.8xp` has SHA-256
`724a43e82e81de096025931a1aff052de270185f4c3d7ef856f8efeae76bbc77`.
[confirmed]

## Programmable-timer physical probe

Probe ID 12 separates four programmable-timer edges on a physical ASIC:

- whether crystal source `0x41` divides 32.768 kHz by 33, as published and
  modeled by TilEm, or by 32, as modeled by Wabbitemu and MAME;
- whether the `0xC0` source family applies the speed-selected port-`0x2F`
  prescaler;
- whether counter value zero free-runs through a 256-count period, completes
  immediately, or remains idle; and
- whether mode/status bit 2 appears after the first or second unacknowledged
  expiry.

These alternatives come from the raw WikiTI port descriptions and pinned
TilEm, Wabbitemu, and MAME source. They define the discriminator, not the
physical answer. [standard] for the source-specific models; [hypothesis] for
the pending ASIC behavior.

The entry guards require timer-1 and timer-2 source and mode/status ports to be
zero. Port `0x04` completion bits 5–6 must also be clear. The probe records an
outcome without starting a measurement when a guard fails. Every polling loop
has a `0xFFFF` iteration bound, and outcome 6 reports a measurement timeout.
[confirmed]

| Outcome | Meaning |
|--------:|---------|
| `0` | all guards passed and all measurements completed |
| `1` | timer-1 source was active |
| `2` | timer-1 mode/status was active |
| `3` | timer-2 source was active |
| `4` | timer-2 mode/status was active |
| `5` | a programmable-timer completion bit was pending |
| `6` | a bounded measurement loop timed out |

The four divisor trials run sources `0x41` and `0x45` together. Source `0x45`
is the common 2,048 Hz reference in every compared model. Each trial retains
both start and end counters, and the decoder aggregates the ratio instead of
depending on one quantized sample. The mode-3 matrix writes `0x4B` to port
`0x2F`, then writes CPU-speed requests 0–3, records the readback, and counts
source-`0xE0` expiries against source `0x45`. The target timer uses a
250-count loop so the decoder can reconstruct
more than 255 target ticks. [confirmed] for the assembled measurement and
decoder; [standard] for the named source models.

The zero-counter case compares source `0x45` at counter zero with 31 ticks of
source `0x46`. The expiry case records timer-1 mode/status and port `0x04`
after an ordinary four-count loop expiry and again after the following
unacknowledged 256-count overflow period. The reference timer supplies bounded
completion windows; the program never executes `HALT`. [confirmed]

| Payload range | Contents |
|--------------:|----------|
| `0`–`12` | pre-sequence ports `0x02`, `0x03`, `0x04`, `0x15`, `0x20`, `0x2D`, `0x2F`, and `0x30`–`0x35` |
| `13` | outcome code |
| `14`–`29` | four source-`0x41`/source-`0x45` counter trials |
| `30`–`65` | four nine-byte mode-3 speed and expiry-count cases |
| `66`–`71` | counter-zero case |
| `72`–`77` | first- and second-expiry status case |
| `78`–`90` | post-cleanup copy of the 13 pre-sequence ports |

Run and decode a physical result with:

```sh
python tools/decode_hardware_probe.py --json HWTMR001.8xv
```

The decoder reports raw counters and status bytes alongside the nearest source
model. A nearest-model label describes that sample; it does not establish an
ASIC-wide rule. Retain the exported AppVar, manifest, calculator and ASIC
identity, CPU-speed readbacks, and artifact hashes together.

The exact 835-byte assembled image completed in the pinned Wabbitemu core after
a retail OS 2.55MP boot. The shared injected-program runner stopped at
`01:9EE4`, immediately before `_CreateAppVar`, after 1,645,212 probe
instructions and 12,937,610 modeled T-states. It recorded no
execution-violation reset. [confirmed] for this emulator execution.

The four trials inferred divisor `3568/111`, or about 32.144. The decoder
selected the Wabbitemu/MAME divisor-32 model. Speed requests 0–3 read back as
0, 1, 1, and 1. The nonzero cases inferred a port-`0x2F` prescaler near one,
matching Wabbitemu's omitted prescaler. Counter zero completed with
mode/status `0x04` and port `0x04 = 0x68`. Both expiry samples read
mode/status `0x05`, so bit 2 was present on the first expiry. Every restoration
field compared equal. [confirmed] for the pinned Wabbitemu run.

The native adapter uses Wabbitemu commit
`48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422`, source-tree SHA-256
`a8a4f97fc7952770bed317b4a477f80345894da38d14fad8f0bf0ee60aae71ba`,
and binary SHA-256
`3acb6a18280f9c42d6fe324188eab73f87280ee70b973e1251fcfa50f54fb14e`.
Run the same guarded path with:

```sh
nix develop -c python tools/run_wabbitemu_timer_physical_probe.py \
  --binary /path/to/wabbitemu-headless \
  --expected-binary-sha256 3acb6a18280f9c42d6fe324188eab73f87280ee70b973e1251fcfa50f54fb14e \
  --output-dir /tmp/wabbitemu-timer-physical --json
```

This run validates the assembled control flow, bounded polling, result layout,
cleanup, and decoder against one emulator implementation. It does not execute
AppVar creation, measure wall time or crystal accuracy, or establish physical
ASIC behavior. No `HWTMR001` result from a calculator is available.

The pinned SPASM-ng build produces 835 machine-code bytes with SHA-256
`6767caf1d714bc15e642de2f791151a060015fa0d9faebe1ebddd92d184df68a`.
The packaged 1,750-byte `HWTMR.8xp` has SHA-256
`2182a69520ad1e82e0c7b94ef96c5910ca50727b58c77173c4f428ba95cc329c`.
[confirmed]

## Safety boundary

The RAM alias probe is designed to restore its writes, but it has not completed
a physical run. A reset, power loss, assembly defect, or unexpected exception
before the restoration loop can leave a changed byte. Use a backed-up test
calculator and stable power. Do not run the RAM probe on a unit whose contents
cannot be replaced.

The snapshot, battery, raw-battery, raw-link, keypad, bus-timing, prefix-M1,
programmable-timer, and alias probes restore interrupt enable state before
creating the result AppVar.
Both battery probes restore ports `0x04`, `0x39`, `0x3A`, and the complete
saved `traceFlags` byte.
The raw-battery probe also executes the ROM's selector cleanup after every
sample sequence. The raw-link probe releases both link lines during cleanup. A
returned execution probe restores port `0x06` and the interrupt state. The
keypad probe normalizes port `0x01` to the OS's all-groups-unselected value
`0xFF`. The bus and prefix timing probes restore port `0x2E` and an initially
idle timer 2. The programmable-timer probe restores CPU speed, port `0x2F`,
and the initially idle timer-1 and timer-2 triplets. It snapshots port `0x2D`
but does not write it.
The bus-timing probe's direct Flash writes are `0xF0` read-array resets, not
program or erase sequences. The prefix-M1 probe accesses only user RAM and I/O.
A denied fetch may reset before cleanup instructions. The result AppVar is the
intended persistent data write.
[confirmed] for the source and assembled bytes; [hypothesis] for unmeasured
physical execution and reset retention.

## Source layout

| Path | Purpose |
|------|---------|
| `tools/hardware-probes/common.inc` | OP1 setup, `_CreateAppVar`, and frame copy |
| `tools/hardware-probes/asic-snapshot.asm` | read-only ASIC, timing, and GPIO register snapshot |
| `tools/hardware-probes/battery-level.asm` | repeated retail battery-level bcall and restoring state audit |
| `tools/hardware-probes/battery-raw.asm` | repeated raw comparator-selector sequence and restoring state audit |
| `tools/hardware-probes/link-raw.asm` | disconnected two-wire link readback and instruction-spaced settling matrix |
| `tools/hardware-probes/keypad-settle.asm` | held-key and chord matrix-settling measurements |
| `tools/hardware-probes/bus-timing.asm` | six-class Flash/RAM wait-state timing matrix |
| `tools/hardware-probes/prefix-m1.asm` | prefixed-instruction RAM-M1 timing matrix |
| `tools/hardware-probes/timer-physical.asm` | guarded programmable-timer divisor, prescaler, zero-counter, and expiry matrix |
| `tools/hardware-probes/usb-snapshot.asm` | read-only low-USB control and status snapshot |
| `tools/hardware-probes/md5-edge.asm` | calculator-side MD5 measurements |
| `tools/hardware-probes/ram-alias.asm` | calculator-side RAM alias and restoration measurements |
| `tools/hardware-probes/execution-fetch.asm` | parameterized read-only Flash and RAM fetch measurement |
| `tools/hardware_probe.py` | reusable TI container, frame, and payload library |
| `tools/bus_timing.py` | timing-register models and physical counter-pair decoder |
| `tools/prefix_fetch_models.py` | hash-guarded emulator prefix-fetch source analysis |
| `tools/timer_hardware.py` | reusable source, duration, RTC, and physical timer-result models |
| `tools/describe_prefix_fetch_models.py` | text and JSON prefix-fetch comparison CLI |
| `tools/run_wabbitemu_prefix_m1_probe.py` | exact-ROM guarded assembled-probe execution CLI |
| `tools/run_wabbitemu_timer_physical_probe.py` | exact-ROM guarded assembled timer-probe execution CLI |
| `tools/battery_hardware.py` | ROM decision tree and emulator threshold-region model |
| `tools/describe_battery_hardware.py` | text and JSON threshold/sample model CLI |
| `tools/build_hardware_probes.py` | SPASM runner, artifact validator, packager, and manifest CLI |
| `tools/decode_hardware_probe.py` | text and JSON result CLI |

Generated `.8xp` files are build artifacts and are not required in the
repository. A physical evidence record should retain the exact exported
AppVar, manifest, hashes, and unit metadata together.
