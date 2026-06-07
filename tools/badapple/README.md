# Bad Apple music and link-port capture

Build [fb39ca4/badapple-ti84](https://github.com/fb39ca4/badapple-ti84), render
the tracker music that feeds its interrupt-driven link-port player, and run the
application under the TI-84+ OS in headless TilEm.

Run `ROM=/path/to/ti84plus.rom ./build_and_capture.sh` (a 1 MB TI-84+ OS image —
the same one Ghidra/TilEm use). The checked-in WAVs are decoded music renders:

- `badapple_music.wav` — the decoded four-channel music, including the
  randomized percussion/noise voice.

The script also emits trace-debug WAVs in `$WORK`:

- `badapple_linkport_15mhz.wav` — debug capture of the raw port-`$00` writes.
- `badapple_linkport_pitchcorrected.wav` — the same debug capture resampled to
  compensate for this 84+ run's slower interrupt rate.

## How sound is emitted

The TI-83+/84+ has no sound chip; programs play audio by toggling the two link
lines (bits 0/1 of port `$00`, the tip/ring of the I/O jack) with a speaker
across them. Bad Apple's interrupt does, every fire:

```z80
ld a, b      ; bits toggled by channels 1 (bit1) and 3 (bit0)
or c         ; bits toggled by channels 2 (bit1) and 4 = noise via `ld a,r`
out ($00), a
```

The port-`$00` value over time is the link-port drive state. Channel 4 is
randomized (`ld a,r`), so short raw captures can be dominated by noise.
`ti84_music.py` decodes the upstream `.mmp` tracker file with the same
note-count conversion as `util/audio.py`, imports standard MIDI files, writes
the four `track*.asm` files the application includes, and synthesizes all four
interrupt-rate voices. The default `tracker` profile is the listening render.
Use `--profile raw-port` to render the unfiltered link-line differential for
hardware debugging. The renderer uses the app's intended `33333.3 Hz` sound
clock and the `24 * 75` interrupt tracker cadence, so `badapple_music.wav` plays
in real time. [standard]

`extract_linkport_audio.py` remains a dynamic trace tool. It replays every
`OUT ($00),A` in the trace, holds each level until the next write (zero-order
hold), and resamples to 44.1 kHz. Use it to verify that the ROM writes the link
port, not as the primary music decoder. [standard]

## How it runs headless

The full app is a **58-page signed Flash Application** that needs an SE-class
(2 MB) calc. On a 1 MB 84+ the OS-only image has 43 erased pages (`0x08-0x32`) —
enough for the first ~2.5 min of the dynamic run. The app is relocatable
(`in a,($06)` at entry), so `badapple_inject.py` writes its pages starting at
flash page `0x08`.

Headless TilEm has no link/file transfer, and the OS app-loader path (page 0x3D)
is fragile to drive, so instead the injector overwrites the entry of `_GetCSC`
(`ram:04b2`, a page-0 key scanner the OS calls at the splash/home wait, after
full RAM/IY/hardware init) with `ld a,$08; out($06),a; jp $4080` — the app's entry
sits after its 128-byte header.

## Flash/RAM execution protection (84+ "memory mapping")

The 84+ resets if code executes in a forbidden region (emulated in TilEm
`x4_memory.c`):

- **Flash**: reset if `PORT22 ≤ page ≤ PORT23` (a *no-exec* range). Boot sets
  `$22 = 0x08`, and the OS app-loader sets `$23` to bracket a launched app; a
  manual jump leaves page `0x08` forbidden.
- **RAM**: the inverse — executable only within `[$25,$26] × 0x400`. Boot sets
  `$25 = 0x10, $26 = 0x20` (≈ `0x9000–0xA000`), but the app runs its main loop at
  `statVars = 0x8A3A`, just below that window.

These ports are **write-locked**: a write only sticks when the CPU has just
fetched the exact unlock sequence `00 00 ED 56 F3 D3` (`NOP;NOP;IM1;DI;OUT`),
which is why boot wraps every protection `OUT` in it. The injector therefore
patches boot's own immediates (its unlock already runs):

| Port | Boot value | Patched | Effect |
|------|-----------:|--------:|--------|
| `$22` | `0x08` | `0x40` | no flash page in `0x00-0x3F` is forbidden |
| `$25` | `0x10` | `0x00` | RAM exec lower = 0 (covers `statVars`) |
| `$26` | `0x20` | `0xFF` | RAM exec upper = max |

## Sound ISR rate

`out ($00),A` runs once per interrupt, so the port-`$00` write rate equals the
ISR rate: **~4674 Hz** here, against the **33333 Hz** the encoder
(`util/audio.py`) assumes for the SE timer. On this 84+ the timer fires the ISR
~7.1× slower, so the emission is a correct-but-slowed/pitched-down rendition;
the pitch-corrected WAV multiplies the clock by 33333/4674 to restore it.

## Verifying the run

The injected app is fully live in the trace: ~52 k writes to LCD data (`$11`),
~28 k to LCD command (`$10`), ~13 k flash bank swaps (`$06`, video pages), and
~17 k link-port writes (`$00`, audio) per ~4 s. (Headless GIF capture shows a
blank LCD — a TilEm headless readout quirk with the app's column-auto-increment
mode — but the port trace proves the app is rendering and playing.)

## Files

- [`../badapple_inject.py`](../badapple_inject.py) — inject app + launch hook + open protection.
- [`../ti84_music.py`](../ti84_music.py) — `.mmp`/MIDI/JSON music → track ASM and WAV.
- [`../extract_linkport_audio.py`](../extract_linkport_audio.py) — trace → debug link-port WAV.
- [`build_and_capture.sh`](build_and_capture.sh) — the full pipeline.
