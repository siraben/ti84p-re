# Guarded mapper, LCD, and interrupt probes

The three previously missing digital experiments now have SPASM-ng sources,
builder validators, result decoders, and exact-byte emulator runners. Their
AppVars remain physical measurements only after export from an identified
calculator. [confirmed] for the assembled artifacts and emulator executions;
[hypothesis] for physical behavior.

All three programs print `PROGRAM CODE nnnnn` only after cleanup and result
creation. The number is CRC-16/CCITT-FALSE over the complete `HWP1` frame. The
host decoder prints the same decimal value as `verification_code_decimal`.
Matching the two values detects a transcription or file-selection error; it
does not replace the exported AppVar or artifact hashes.

## Mapper overlays — `HWPMAP`

`mapper-overlays.asm` tests port-`0x28 = 1` at `0x8000`, `0x803F`, and
`0x8040`, and port-`0x27 = 0x13` at `0xFB3F`, `0xFB40`, `0xFB63`,
`0xFB64`, `0xFFBF`, and `0xFFC0`. The port-`0x27` values distinguish the
documented/TilEm `0xFB40` boundary from Wabbitemu's additional `0xFB64`
clamp. It repeats reads and writes in independent and paired mapper modes and
records an even-Flash paired-window discriminator. [confirmed]

The entry guard requires the OS 2.55MP direct-`Asm(` mapping: ports `0x05`,
`0x06`, `0x07`, `0x0E`, `0x0F`, `0x27`, and `0x28` must read `0x00`,
`0x3F`, `0x81`, `0x00`, `0x00`, `0x00`, and `0x00`. It also verifies the
fixed-page helper at
`00:0CE6`. Port `0x04` readback is interrupt status, not mapper-mode
readback, so the program does not pretend to save mode from that port. It
normalizes independent mode with port `0x04 = 0x06` during cleanup.

Before any marker write, the program creates a pending `HWPMAP01` AppVar and
repeats every mapping guard. The worker runs through a physical-page-1 alias,
uses no stack instruction while window C is remapped, and keeps either window
B or window C mapped to RAM while changing mapper mode. It backs up every byte
it seeds across RAM pages 0–3, restores them, verifies the restores, restores
every selector, and sets restore flags. A reset between a marker write and
cleanup can still leave changed RAM, so use stable power and a backed-up test
unit.

The 47-byte payload contains nine entry-port bytes, an outcome, independent
read/write rows, paired read/write rows, the even-Flash discriminator, restore
flags, and nine exit-port bytes. The decoder names the closest emulator
profile and separately reports marker and readable-port restoration.

Fresh exact-image runs selected the TilEm profile with decimal verification
code `58756` and the Wabbitemu profile with code `21062`; all four restore
flags and both derived restoration checks passed. The normalized record is
`tools/fixtures/mapper-overlays-emulators.json`. MAME 0.287 completed a
separate direct-handler Lua profile, but exact `HWPMAP` image execution is
unsupported until a guarded MAME injection adapter exists. [confirmed] for
the emulator runs; [hypothesis] for the still-unmeasured physical routing.

## LCD controller edges — `HWPLCD`

`lcd-controller.asm` measures whether command writes, data reads, and data
writes restart the ASIC port-`0x02` ready interval. Separate port-`0x10`
samples record the controller busy bit after each access. [confirmed]

The entry guard rejects controller reset, six-bit mode, and invalid TI-OS
tracked row or column variables. It rejects columns outside visible command
range `0x20`–`0x2B`. It also rejects rows outside `0x80`–`0xBF`. [confirmed]

The default artifact does not address hidden columns. It writes only the
original value of one tracked visible cell. It rereads and restores that cell
before creating `HWPLCD02`. [confirmed]

Every ready poll and measurement counter is bounded. A timeout suppresses the
pending LCD transfer. The measurement sends no display-enable, power, test,
contrast, row-shift, or OPA command. It does not write the ASIC wait ports.
[confirmed]

The controller's exact entry pointer, output latch, contrast, and row shift
are not readable through this interface. The probe therefore restores the
documented OS pointer state. A status read can move the pointer on replacement
controllers. Cleanup therefore restores the guarded pointer after its final
status sample. [confirmed]

The 42-byte payload records entry status and wait registers, three ready
counts, six immediate samples, the visible-cell values, and exit state.
Outcome 5 records a safely rejected hidden pointer. Outcome 6 or
`restore_ok = false` invalidates a physical run. [confirmed]

Pinned exact-byte runs completed with restoration true. TilEm printed
`21731`; Wabbitemu printed `23959`. These codes identify emulator frames, not
physical controller behavior. [confirmed]

The hidden-column models retain three competing behaviors. TilEm uses
16-column rows, Wabbitemu wraps a 15-column sequence, and MAME exposes a
15-byte linear spill. The separate laboratory experiment below tests these
behaviors without changing the default artifact. [confirmed] for the emulator
models; [hypothesis] for physical geometry.

## Recovery-gated hidden-column experiment — `HWPLAB`

`lcd-hidden-lab.asm` addresses columns `0x2C`–`0x2F` only after it creates the
pending `HWPLAB01` AppVar. It snapshots all 768 visible bytes and the four
addressed hidden bytes at row command `0xB8`. It then runs independent direct
writes and a two-byte increment from column 14. Each completed stage is copied
to the pending AppVar. [confirmed]

Cleanup restores the visible snapshot and four hidden bytes, rereads them,
and records separate mismatch counts. It also restores the entry read latch,
movement command, and guarded OS pointer. Every ready poll is bounded. A
timeout uses a finite fixed-delay restore attempt. The program sends no power,
test, contrast, row-shift, display-enable, or OPA command. [confirmed]

The source is excluded from `build_hardware_probes.py`. Build it only with
`build_lcd_hidden_lab_probe.py`, which requires:

- the exact acknowledgement string printed by `--help`;
- the expected port-`0x15` ASIC byte;
- an identified LCD module or test-unit label;
- a nonempty backup file and its independently supplied SHA-256;
- recovery notes that state the backup, reset, and restore procedure.

The generated manifest binds those inputs to the exact `.8xp`. The runtime
also checks the ASIC byte, the OS 2.55MP signature at logical `0x0BD9`,
eight-bit LCD mode, reset status, and the OS-tracked pointer range before the
first LCD write or data transfer. [confirmed]

These gates limit known failure modes. They cannot prove that an unknown
controller maps column 15 only into the saved visible or four hidden bytes. A
reset can still be necessary, and an unseen hidden cell can remain changed.
Use an identified, repairable calculator with stable power. Do not distribute
a device-specific build as part of the default probe bundle. [hypothesis] for
unmeasured physical aliasing.

On a normal return the calculator prints `HWPLAB CODE nnnnn`. Export
`HWPLAB01`; `decode_hardware_probe.py` reports the same decimal CRC as
`verification_code_decimal`. A pending outcome or restoration mismatch is a
failed run, even if the calculator later reaches the home screen.

Exact assembly runs completed in both supported cores. TilEm selected the
16-column model, restored every checked byte, and printed `62131`.
Wabbitemu wrapped the second incremented byte into visible index 0, restored
every checked byte, and printed `42103`. The two images differ only in the
compiled expected-ASIC byte. These runs test probe control flow and emulator
models; they do not establish physical safety. [confirmed]

An operator-specific build has this form:

```sh
nix develop -c python tools/build_lcd_hidden_lab_probe.py \
  --output-dir /tmp/hwplab-build \
  --acknowledgement I_UNDERSTAND_HIDDEN_LCD_WRITES_CAN_REQUIRE_A_RESET \
  --expected-asic 0x45 \
  --controller-id CALCULATOR_AND_LCD_MODULE_ID \
  --backup-file /path/to/pre-run-backup.8xg \
  --expected-backup-sha256 64_HEXADECIMAL_DIGITS \
  --recovery-notes /path/to/unit-specific-recovery.txt
```

## Interrupt and `HALT` policy — `HWPIRQ`

`interrupt-halt.asm` asks whether programmable timer 1 can wake powered
`HALT`. It arms source `0x45`, interrupt mode `0x02`, and count 1. Standard
timer 1 is enabled simultaneously as a bounded watchdog. The private handler
records port `0x04`, timer mode, timer count, and handler count, then disables
both sources. The decoder classifies the first wake as programmable timer or
standard-timer watchdog. [confirmed]

A Z80 program cannot read the current interrupt mode. This artifact therefore
requires direct `Asm(` on unmodified OS 2.55MP in IM1; do not launch it through
a shell, hook, or resident interrupt replacement. It guards `IY = 0x89F0`,
the six-byte IM1 vector signature at `00:0038`, enabled entry interrupts, an
unheld ON key, idle programmable timer 1, no pending legacy/completion source,
and an inactive USB interrupt gate.

The program creates pending `HWPIRQ01` before changing interrupt mode and
repeats the live-source guards afterward. Its 257-byte uniform IM2 table makes
every possible data-bus vector resolve to the private handler. Cleanup runs
with interrupts disabled, disarms both timers, and reconstructs the canonical
OS port-`0x03` mask from `(IY+0x16)` bit 0. It does not trust undocumented
bit-3 readback. It then returns to IM1, restores `I`, verifies the documented
readable mask bits, updates the pending frame, and only then restores entry
interrupt enable state.

The watchdog bounds emulator and expected physical runs, but an ASIC that
wakes for neither source can remain halted until reset. In that case the
pending AppVar is the recovery witness and no screen code appears. Export it
before another attempt. Switch bounce, ON waveform, and link-line electrical
edges still need the external measurements described on the next page.

## Remaining RTC mutation

The read-only [`HWPRTC` rollover probe](../hardware-probes.md#rtc-rollover-coherence-probe)
covers natural low-byte carry. Forced `0x00FFFFFF` → `0x01000000` rollover,
disabled-clock reads, staged-register retention, and reset retention still
need a separate guarded mutating artifact because they change or outlive the
user clock state.
