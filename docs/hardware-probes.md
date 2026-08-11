# Physical hardware probes

The physical-probe suite builds small `AsmPrgm` programs and decodes their
result AppVars. The sources cover MD5-assist edge behavior, RAM selector
aliasing, execution-protection boundaries, and a read-only ASIC register
snapshot. No exported result from a physical calculator has been recorded, so
the hardware conclusions remain open.

## Measurement status

The builder, link-file containers, entry jumps, bcall ID, frame layouts, and
restoration instruction sequences have byte-level host validation. [confirmed]
Physical execution of any program remains [hypothesis] until an exported
result AppVar is decoded and tied to a calculator and ASIC revision.

| Probe | Program | Result AppVar | Physical status |
|-------|---------|---------------|-----------------|
| MD5 edge behavior | `HWPMD5` | `HWPMD511` | Not run on a recorded unit |
| RAM selector aliasing | `HWPRAM` | `HWPRAM21` | Not run on a recorded unit |
| ASIC register snapshot | `HWASIC` | `HWPASIC1` | Not run on a recorded unit |
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

The command emits the three snapshot and edge probes, ten single-fetch
execution probes, and `manifest.json`. The manifest records every target
selector and scan range. It uses repository-relative source names and output
basenames, so builds made in different checkout directories remain comparable.
The CLI refuses an existing output directory. The hashes identify exact
artifacts; they do not establish that a calculator executed them.

Transfer the `.8xp` files with TI Connect CE or another link program. Make
a calculator backup before the first run. Then:

1. Delete the probe's result AppVar if it already exists.
2. Run `Asm(prgmHWASIC)` for the read-only register snapshot.
3. Run `Asm(prgmHWPMD5)` for the MD5 probe.
4. Run `Asm(prgmHWPRAM)` for the RAM probe only after the earlier transfer and run
   path works on that unit.
5. Run at most one `HWEF...` or `HWER...` execution probe before exporting its
   result. A denied fetch may reset the calculator.
6. Export the new result AppVar to the host.
7. Record the calculator model, PCB or ASIC revision, boot version, OS version,
   and artifact hashes with the exported file.

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
  HWPASIC1.8xv HWPMD511.8xv HWPRAM21.8xv
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
backing for selectors `82`–`87`. Other sequences require separate analysis.
These interpretations follow from the write order; whether either topology
appears on a specific calculator remains [hypothesis].

The decoder reports `restore_matches`. A false value means the post-restore
reads differ from the saved bytes and invalidates a claim of successful cleanup.

## Execution-protection fetch probes

Probe ID 4 tests one bank-A selector per program. It scans the configured range
through data reads for an existing `RET` byte. It creates a result AppVar with a
pending outcome, remaps and verifies that byte, and performs `PUSH DE; JP (HL)`.
A successful fetch executes `RET`, returns to the probe, and changes the AppVar
outcome to `returned`. The program never writes the selected RAM or Flash page.
[confirmed] for the assembled instruction sequence.

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

## Safety boundary

The RAM alias probe is designed to restore its writes, but it has not completed
a physical run. A reset, power loss, assembly defect, or unexpected exception
before the restoration loop can leave a changed byte. Use a backed-up test
calculator and stable power. Do not run the RAM probe on a unit whose contents
cannot be replaced.

The snapshot and alias probes restore interrupt enable state before creating
the result AppVar. A returned execution probe restores port `0x06` and the
interrupt state. A denied fetch may reset before those instructions. None of
the probes modifies Flash directly. The result AppVar is the intended
persistent write. [confirmed] for the source and assembled bytes; [hypothesis]
for unmeasured physical execution and reset retention.

## Source layout

| Path | Purpose |
|------|---------|
| `tools/hardware-probes/common.inc` | OP1 setup, `_CreateAppVar`, and frame copy |
| `tools/hardware-probes/asic-snapshot.asm` | read-only ASIC, timing, and GPIO register snapshot |
| `tools/hardware-probes/md5-edge.asm` | calculator-side MD5 measurements |
| `tools/hardware-probes/ram-alias.asm` | calculator-side RAM alias and restoration measurements |
| `tools/hardware-probes/execution-fetch.asm` | parameterized read-only Flash and RAM fetch measurement |
| `tools/hardware_probe.py` | reusable TI container, frame, and payload library |
| `tools/build_hardware_probes.py` | SPASM runner, artifact validator, packager, and manifest CLI |
| `tools/decode_hardware_probe.py` | text and JSON result CLI |

Generated `.8xp` files are build artifacts and are not required in the
repository. A physical evidence record should retain the exact exported
AppVar, manifest, hashes, and unit metadata together.
