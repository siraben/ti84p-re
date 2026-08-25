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
| Mapper overlays | exact `HWPMAP` pass; overlays remain active in paired mode and cutoff starts at `0xFB40` | exact `HWPMAP` pass; overlays are disabled in paired mode and the `0xFB64` cutoff is present | Lua pass; overlay ports are absent | physical paired-mode and cutoff behavior remain open |
| LCD | exact `HWPLCD` pass selects 16-column rows | exact `HWPLCD` pass selects 15-column wrap | Lua pass selects a 15-byte linear spill, with no busy model and absent delay ports | controller revision and physical timing remain open |
| Raw link and assist | direct-core pass | direct-core pass | Lua pass; assist block absent | logic-model results cannot provide voltage or rise time |
| Keypad and ON | direct-core pass | direct-core pass | Lua matrix pass | electrical settling, bounce, and ON waveform remain open |
| Flash | direct-core command/status pass | guarded command and restart runners exist | Lua command/status pass | no backend proves silicon timing or real power-loss atomicity |
| Interrupt `HALT` wake | exact `HWPIRQ` pass wakes on programmable timer 1 | exact `HWPIRQ` pass reaches the standard-timer watchdog | Lua legacy-controller pass; no programmable-timer block | physical wake policy remains open |
| Reset and execution protection | direct-core reset/violation pass; exact boundary fixtures exist | exact boundary fixtures and reset runner exist | protection mechanism absent | physical exception ordering and retention remain open |

jsTIfied is a hash-checked source profile, not a native runner. CEmu targets
the TI-84 Plus CE and is outside this monochrome calculator's hardware scope.

## Exact assembled results

Two generic runners now execute identical `HWPMAP`, `HWPLCD`, and `HWPIRQ`
machine images. Wabbitemu boots the retail ROM before injection. TilEm loads
the exact ROM and establishes the guarded direct-`Asm(` core baseline. Both
redirect `_CreateAppVar` to a private RAM buffer, execute the assembly CRC
routine, require that buffer to match the staging frame byte for byte, and stop
at the first display bcall. The measurement, cleanup, frame
update, and verification-number computation are therefore exact; OS variable
allocation and rendered screen pixels are not. [confirmed]

| Probe | TilEm result and code | Wabbitemu result and code |
|-------|-----------------------|---------------------------|
| `HWPMAP` | `tilem`; all restore flags set; `58756` | `wabbitemu`; all restore flags set; `21062` |
| `HWPLCD` | `tilem-16-column`; restore true; `43477` | `wabbitemu-15-column-wrap`; restore true; `61237` |
| `HWPIRQ` | programmable-timer wake; restore true; `44737` | standard-timer-watchdog wake; restore true; `19672` |

The exact-runner builds are separate from the older fixed-mode Wabbitemu
adapter, so extending the matrix does not change that evidence binary. The
locally reproduced generic runner hashes are:

- TilEm `f56ad637` runner:
  `a3dfa724f5b56cdc4a0920fe821915adfc82770b7e556fedda061f8a99711aa1`;
- Wabbitemu `48c2dc0` runner:
  `6ab24b1c31d7655426e059c06d511cec12cf0fedf9ad1d0bc87eaa28627defc2`.

Build either runner from its guarded source tree, then run one or all three
probe names through the normalized CLI:

```sh
nix develop -c python3 -m ti84re.emulators.tilem.build_exact_probe \
  --source /path/to/tilem-f56ad637 --output /tmp/tilem-exact

nix develop -c python3 -m ti84re.emulators.wabbitemu.build_exact_probe \
  --source /path/to/wabbitemu-48c2dc0 --output /tmp/wabbitemu-exact

nix develop -c python3 -m ti84re.hardware.run_exact_probe \
  --backend tilem --binary /tmp/tilem-exact \
  --expected-binary-sha256 \
    a3dfa724f5b56cdc4a0920fe821915adfc82770b7e556fedda061f8a99711aa1 \
  --probe lcd-controller --output-dir /tmp/tilem-hwplcd --json
```

The older exact `HWTMR` and `HWPFX` paths use a pinned Wabbitemu binary with
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
