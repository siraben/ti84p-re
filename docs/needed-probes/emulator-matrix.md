# Emulator comparison matrix

Emulators validate probe control flow and expose useful competing hypotheses.
They do not supply physical results. The repository pins TilEm commit
`f56ad637`, Wabbitemu commit `48c2dc0`, MAME 0.287, and a jsTIfied
`20170706a` source profile. [standard]

## Executed coverage

The guarded runs below use the exact OS 2.55MP ROM with SHA-256
`7d9a7d96d89fc552ebee6afdbdd011fdc6047be9c16d308245dff07eb1f7bd6d`.
The direct-core and Lua cases exercise emulator device handlers. Only cells
marked exact execute assembled physical-probe bytes. [confirmed] for the
executed emulator paths.

| Area | TilEm `f56ad637` | Wabbitemu `48c2dc0` | MAME 0.287 | Physical implication |
|------|------------------|------------------------|------------|----------------------|
| MD5 assist | direct-core pass | direct-core pass; agrees on one-, three-, four-, and five-write edges | pass confirming ports `0x18`–`0x1F` are unmapped | agreement of two implementations remains [hypothesis] for ASIC edges |
| Timers and RTC | direct-core pass; divisor 33 model and separately read RTC bytes | direct-core pass; exact `HWTMR` pass selects divisor 32, no port-`0x2F` prescaler, and first-expiry bit 2 | direct Lua pass; divisor 32 model, different zero and mode behavior, RTC unmapped | `HWTMR` distinguishes timer behavior; `HWPRTC` records RTC rollover coherence |
| Prefix M1 waits | source model predicts the ordinary two-M1 indexed-CB interpretation | exact `HWPFX` pass selects `wabbitemu-three-m1`; all restoration fields match | delay-register block absent | physical indexed-CB timer delta remains open |
| ASIC, protection, and GPIO | battery comparator direct-core pass; other handler behavior is source evidence | ASIC and protection direct-core passes | ASIC Lua pass; protection/GPIO ports absent | constant or absent reads are unsupported cases, not hardware values |
| Mapper overlays | exact `HWPMAP` pass; overlays remain active in paired mode and cutoff starts at `0xFB40` | exact `HWPMAP` pass; overlays are disabled in paired mode and the `0xFB64` cutoff is present | exact execution unsupported; direct Lua pass finds the overlay ports absent | physical paired-mode and cutoff behavior remain open |
| LCD | exact `HWPLCD` pass reports ready counts 2/2/2 and three busy samples | exact `HWPLCD` pass reports ready counts 4/0/3 and busy set/clear/set | direct Lua pass has no busy model, constant ASIC-ready state, and absent delay ports | physical timing and hidden geometry remain open |
| Raw link and assist | direct-core pass | direct-core pass | Lua pass; assist block absent | logic-model results cannot provide voltage or rise time |
| Keypad and ON | direct-core pass | direct-core pass | Lua matrix pass | electrical settling, bounce, and ON waveform remain open |
| Flash | direct-core command/status pass | guarded command and restart runners exist | Lua command/status pass | no backend proves silicon timing or real power-loss atomicity |
| Interrupt `HALT` wake | exact `HWPIRQ` pass wakes on programmable timer 1 | exact `HWPIRQ` pass reaches the standard-timer watchdog | Lua legacy-controller pass; no programmable-timer block | physical wake policy remains open |
| Reset and execution protection | direct-core reset/violation pass; exact boundary fixtures exist | exact boundary fixtures and reset runner exist | protection mechanism absent | physical exception ordering and retention remain open |

jsTIfied is a hash-checked source profile, not a native runner. CEmu targets
the TI-84 Plus CE and is outside this monochrome calculator's hardware scope.

## Exact assembled results

Two generic runners accept all 25 physical-probe definitions. Wabbitemu boots
the retail ROM before injection. TilEm loads the exact ROM and establishes the
guarded direct-`Asm(` core baseline. Both redirect `_CreateAppVar` to a private
RAM buffer, execute the assembly CRC routine, and stop at the first display
bcall. Ordinary probes require the resident buffer to match the staging frame
byte for byte. Execution-fetch probes instead require the immutable header and
configuration to match and validate the resident outcome transition. Their
displayed CRC is checked against that resident frame. The measurement,
cleanup, frame update, and verification-number computation are therefore
exact; OS variable allocation and rendered screen pixels are not. [confirmed]

The exhaustive matrix completed all 24 non-interactive images with zero
failures in each backend. `HWKEYS` is recorded separately as
`interactive-input-required`: its calculator contract waits for the launch key
to be released and then for an operator-held key or chord. The generic
injection adapters do not synthesize that sequence. The guarded direct-core
keypad cases remain the emulator evidence for that device family. The tracked
summary `tools/oracles/hardware/exact-hardware-probe-matrix.json` contains every
completed probe's decimal verification code and both runner hashes.
[confirmed]

| Probe | TilEm result and code | Wabbitemu result and code |
|-------|-----------------------|---------------------------|
| `HWPMAP` | `tilem`; all restore flags set; `58756` | `wabbitemu`; all restore flags set; `21062` |
| `HWPLCD` | ready 2/2/2; busy set/set/set; restore true; `21731` | ready 4/0/3; busy set/clear/set; restore true; `23959` |
| `HWPIRQ` | programmable-timer wake; restore true; `44737` | standard-timer-watchdog wake; restore true; `19672` |
| `HWEF07` | returned; resident-frame code `26515` | returned; resident-frame code `38818` |
| `HWTMR` | completed after 16,855,833 clocks; restore fields pass; `3397` | completed; restore fields pass; `41549` |

The deterministic `HWPMAP` record is
`tools/oracles/hardware/mapper-overlays-emulators.json`. It binds the two exact runs to
the 1,348-byte assembly image and preserves the displayed decimal codes, raw
frames, decoded routing rows, restoration results, emulator revisions, and
runner hashes. Its MAME row labels exact image execution `unsupported` and
keeps the completed direct-handler profile as a different evidence class.
[confirmed]

The exact `HWPLCD` rows use the same 803-byte image. Its SHA-256 is
`fa59b12a0a1e329e23ffc9b84acbd6fc78f4bfbcb83d54813fc1cb3e8da9ec21`.
Both runs matched the AppVar-resident frame and the assembly CRC. Both also
preserved the visible cell, movement bits, and wait-register snapshot.
[confirmed]

MAME 0.287 completed only `tools/ti84re/emulators/mame/run_lcd_probe.py`. That adapter drives
the LCD handlers directly from isolated CPU state. It did not execute the
`HWPLCD` assembly image. Its guarded run reports a 15-byte linear-spill model,
permanent busy-clear status, constant ASIC-ready state, and absent wait ports.
[confirmed]

The TilEm adapter runs in 10,000,000-clock slices until it reaches a display
breakpoint, an exception, an unexpected stop reason, or its 100,000,000-clock
runner limit. An ordinary zero stop reason ends one slice, not the probe. A
runner-limit failure is distinct from the probe's bounded polling outcome.

The exact-runner builds are separate from the older fixed-mode Wabbitemu
adapter, so extending the matrix does not change that evidence binary. The
locally reproduced generic runner hashes are:

- TilEm `f56ad637` runner:
  `ac280251dcda1cda083196abf88032502420351732cb689cac38d20348126408`;
- Wabbitemu `48c2dc0` runner:
  `0f4cb971b3ff1475f2293c2e50db4c6207af92f69e670c0cf0c053901be90569`.

Build either runner from its guarded source tree, then run any probe name
through the normalized CLI:

```sh
nix develop -c python3 -m ti84re.emulators.tilem.build_exact_probe \
  --source /path/to/tilem-f56ad637 --output /tmp/tilem-exact

nix develop -c python3 -m ti84re.emulators.wabbitemu.build_exact_probe \
  --source /path/to/wabbitemu-48c2dc0 --output /tmp/wabbitemu-exact

nix develop -c python3 -m ti84re.hardware.run_exact_probe \
  --backend tilem --binary /tmp/tilem-exact \
  --expected-binary-sha256 \
    ac280251dcda1cda083196abf88032502420351732cb689cac38d20348126408 \
  --probe lcd-controller --output-dir /tmp/tilem-hwplcd --json
```

Run every non-interactive image without allowing one failure to hide later
results:

```sh
nix develop -c python3 -m ti84re.hardware.run_exact_probe_matrix \
  --backend tilem --binary /tmp/tilem-exact \
  --expected-binary-sha256 \
    ac280251dcda1cda083196abf88032502420351732cb689cac38d20348126408 \
  --output-dir /tmp/tilem-hardware-matrix
```

The matrix manifest uses distinct `completed`, `failed`, and
`interactive-input-required` statuses. It keeps each child manifest and both
stdout/stderr streams. A timeout or unsupported handler is therefore never
reported as a physical observation.

The older exact `HWTMR` and `HWPFX` paths provide independent prior evidence
through a pinned Wabbitemu binary with
SHA-256
`3acb6a18280f9c42d6fe324188eab73f87280ee70b973e1251fcfa50f54fb14e`:

```sh
nix develop -c python3 -m ti84re.emulators.wabbitemu.run_timer_physical_probe \
  --binary /path/to/wabbitemu-headless \
  --expected-binary-sha256 \
    3acb6a18280f9c42d6fe324188eab73f87280ee70b973e1251fcfa50f54fb14e \
  --output-dir /tmp/wabbitemu-hwtmr --json

nix develop -c python3 -m ti84re.emulators.wabbitemu.run_prefix_m1_probe \
  --binary /path/to/wabbitemu-headless \
  --expected-binary-sha256 \
    3acb6a18280f9c42d6fe324188eab73f87280ee70b973e1251fcfa50f54fb14e \
  --output-dir /tmp/wabbitemu-hwpfx --json
```

## Reproduction cautions

`nix shell nixpkgs#mame` is not a version pin. As of 25 August 2026 it
resolves MAME 0.289, which the 0.287 guards reject. Use an explicit MAME 0.287
binary, pass its measured SHA-256, and retain that identity in the report.

TilEm and Wabbitemu builds require their exact source commit or tree. Each
builder refuses an unexpected source tree, and each run requires an expected
binary hash, exact ROM hash, and new output directory. The normalized report
retains launch scope, machine-image hash, raw frame, decoded payload, and
verification code.

MAME 0.287 was also run for all three device families through the existing
guarded Lua adapters. Those are direct-handler cases, not executions of the
new assembly images. They confirm that MAME omits mapper overlays, models LCD
addressing as a 15-byte linear spill, lacks LCD busy and wait registers, and
does not provide the programmable-timer block used by `HWPIRQ`. A future exact
MAME injection runner must label absent ports `unsupported` rather than turn
zero readback into a purported hardware observation.
