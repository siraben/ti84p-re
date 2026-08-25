# Calculator-readable probes

The prepared `AsmPrgm` artifacts write versioned `HWP1` frames to AppVars.
These frames preserve raw values for export and decoding after the program has
restored its working state. The screen is not the evidence channel because a
reset, LCD refresh, or later OS drawing can erase it.

## Prepared artifacts

All sources use the shared entry and AppVar writer in
`tools/probes/hardware/common.inc`. The builder packages the sources below and
records their machine-code and transfer-file hashes. [confirmed]

| Question | Source | Program | Result AppVar | Physical information still needed |
|----------|--------|---------|---------------|-----------------------------------|
| MD5 operand shifting, control masks, and result latching | `md5-edge.asm` | `HWPMD5` | `HWPMD511` | TA2/TA3 edge values and revision differences |
| RAM selectors `82`–`87` | `ram-alias.asm` | `HWPRAM` | `HWPRAM21` | physical alias classes and successful restoration |
| ASIC identity, timing gates, protection, and GPIO baseline | `asic-snapshot.asm` | `HWASIC` | `HWPASIC1` | reset readback correlated with PCB, ASIC, and installed RAM |
| USB control/status reset state | `usb-snapshot.asm` | `HWPUSB` | `HWPUSB01` | TA2/TA3 values with the USB connector empty and attached |
| Retail battery level stability | `battery-level.asm` | `HWBATT` | `HWBATT01` | level distribution at measured voltage and load |
| Raw battery comparator selectors | `battery-raw.asm` | `HWBRAW` | `HWBRAW01` | threshold and hysteresis masks during an up/down sweep |
| Disconnected two-wire link readback | `link-raw.asm` | `HWLINK` | `HWLINK01` | digital settling at both CPU speeds |
| Keypad group-selection settling | `keypad-settle.asm` | `HWKEYS` | `HWKEYS01` | held-key and chord samples by calculator revision |
| Six memory-access wait classes | `bus-timing.asm` | `HWBUS` | `HWBUS001` | timer deltas on TA2 and TA3 |
| Prefixed-opcode M1 placement | `prefix-m1.asm` | `HWPFX` | `HWPFX001` | indexed-CB result on TA2 and TA3 |
| Programmable-timer divisor, prescaler, zero, and expiry edges | `timer-physical.asm` | `HWTMR` | `HWTMR001` | physical discriminator result by ASIC revision |
| RTC high-to-low rollover coherence | `rtc-rollover.asm` | `HWPRTC` | `HWPRTC01` | natural low-byte carry result on TA2 and TA3 |
| Mapper overlay read/write routing | `mapper-overlays.asm` | `HWPMAP` | `HWPMAP01` | independent/paired routing and port-`0x27` cutoff by ASIC revision |
| LCD hidden columns and ASIC-ready triggers | `lcd-controller.asm` | `HWPLCD` | `HWPLCD01` | controller row width, aliases, and ready counts by module revision |
| Programmable-timer wake from powered `HALT` | `interrupt-halt.asm` | `HWPIRQ` | `HWPIRQ01` | programmable wake versus standard-timer watchdog by ASIC revision |
| Flash and RAM fetch boundaries | `execution-fetch.asm` | `HWEF07`, `HWEF08`, `HWEF09`, `HWEF29`, `HWEF2A`, `HWER81`, `HWER820`, `HWER821`, `HWER83`, `HWER84` | `HWEF0701`, `HWEF0801`, `HWEF0901`, `HWEF2901`, `HWEF2A01`, `HWER8101`, `HWER82A1`, `HWER82B1`, `HWER8301`, `HWER8401` | return/reset result and result retention |

The last row expands one parameterized source into ten artifacts, for a total
of 25 transfer files. `tools/tests/wiki/test_needed_probe_docs.py` checks that this page
names every builder definition, program, result AppVar, and source. [confirmed]

## Build, run, and decode

Build into a new directory:

```sh
probe_parent=$(mktemp -d /tmp/ti84-physical-probes.XXXXXX)
nix develop -c python3 -m ti84re.hardware.build_probes \
  --output-dir "$probe_parent/build"
```

Follow the ordering and safety instructions in [Physical hardware
probes](../hardware-probes.md#build-and-transfer). Delete an older result
AppVar before each run. Export the result before running a reset-capable
artifact.

Decode one or more exported files without changing them:

```sh
python3 -m ti84re.hardware.decode_probe --json \
  HWPASIC1.8xv HWPRAM21.8xv HWTMR001.8xv
```

The decoder validates the TI container, both link lengths, checksum, AppVar
size word, `HWP1` magic, version, probe ID, and payload length. [confirmed]

## Display and persistence

Every normal-return probe creates an AppVar after restoring interrupts and the
ports named by its contract. The result can therefore be viewed indirectly by
exporting and decoding it.

`HWPRTC`, `HWPMAP`, `HWPLCD`, and `HWPIRQ` print a decimal CRC-16 verification
code only after cleanup and AppVar creation. `HWPRTC` skips the display when
entry interrupts were disabled. The decoder reports the same number as
`verification_code_decimal`. Record the displayed number before pressing a
key, then compare it with the exported AppVar. The AppVar remains the
canonical evidence because the screen does not survive a reset.
