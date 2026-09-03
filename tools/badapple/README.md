# Bad Apple music and link-port capture

Build [fb39ca4/badapple-ti84](https://github.com/fb39ca4/badapple-ti84), render
the tracker music that feeds its interrupt-driven link-port player, and run the
application under the TI-84+ OS in headless TilEm.

Run `ROM=/path/to/ti84plus.rom ./build_and_capture.sh` (a 1 MB TI-84+ OS image —
the same one Ghidra/TilEm use). The checked-in WAVs are decoded music renders:

- `badapple_music.wav` — the decoded four-channel music, including the
  randomized percussion/noise voice.

The script also emits trace-debug WAVs in `$WORK`:

- `badapple_linkport_15mhz.wav` — debug capture of the raw port-`0x00` writes.
- `badapple_linkport_pitchcorrected.wav` — the same debug capture resampled to
  compensate for this 84+ run's slower interrupt rate.

## How sound is emitted

The TI-83 Plus/TI-84 Plus has no dedicated sound chip. Programs can produce a
differential waveform by toggling the two link lines (bits 0–1 of port `0x00`,
the tip and ring contacts of the I/O jack). Bad Apple's interrupt does this on
every invocation: [standard]

```z80
ld a, b      ; bits toggled by channels 1 (bit1) and 3 (bit0)
or c         ; bits toggled by channels 2 (bit1) and 4 = noise via `ld a,r`
out (0x00),a
```

The port-`0x00` value over time is the link-port drive state. Channel 4 is
randomized (`ld a,r`), so short raw captures can be dominated by noise.
`ti84re.badapple.music` decodes the upstream `.mmp` tracker file with the same
note-count conversion as `util/audio.py`, imports standard MIDI files, writes
the four `track*.asm` files the application includes, and synthesizes all four
interrupt-rate voices. The default `tracker` profile is the listening render.
Use `--profile raw-port` to render the unfiltered link-line differential for
hardware debugging. See [Two-wire link port
hardware](../../docs/link-port-hardware.md#differential-audio-output) for the
line-state model and its electrical evidence limits.

The renderer deliberately retains the upstream encoder's 33,333.3 Hz tuning
constant and the application's $24 \times 75$ interrupt tracker cadence. That
constant is a software assumption, not the rate selected by the timer-register
values. The distinction is detailed under [Sound ISR rate](#sound-isr-rate).
[confirmed]

`ti84re.badapple.extract_linkport_audio` remains a dynamic trace tool. It replays every
`OUT (0x00),A` in the trace, holds each level until the next write (zero-order
hold), and resamples to 44.1 kHz. Use it to verify that the ROM writes the link
port, not as the primary music decoder. [standard]

## How it runs headless

The full app is a 58-page signed Flash application that needs an SE-class
(2 MiB) calculator. On a 1 MiB TI-84 Plus, the OS-only image has 43 erased
pages (`0x08`–`0x32`)—
enough for the first ~2.5 min of the dynamic run. The app is relocatable
(`in a,(0x06)` at entry), so `ti84re.badapple.inject` writes its pages starting at
Flash page `0x08`.

Headless TilEm has no link/file transfer, and the OS app-loader path (page 0x3D)
is fragile to drive, so instead the injector overwrites the entry of `_GetCSC`
(`ram:04B2`, a page-0 key scanner the OS calls at the splash/home wait, after
full RAM, `IY`, and hardware initialization) with `ld a,0x08; out
(0x06),a; jp 0x4080`. The app's entry follows its 128-byte header. [confirmed]

## Flash and RAM execution protection

The launch hook bypasses the OS application loader, so it also bypasses the
loader's normal protection setup. The injector changes three bytes in the
pinned OS 2.55MP boot image before TilEm starts: [confirmed]

| Port | Boot byte | Patched byte | TilEm effect |
|------|----------:|-------------:|--------------|
| `0x22` | `0x08` | `0x40` | reverses the `0x22`–`0x23` Flash no-execute interval, leaving pages `0x00`–`0x3F` executable |
| `0x25` | `0x10` | `0x00` | lowers the first executable 1 KiB RAM chunk |
| `0x26` | `0x20` | `0xFF` | raises the last executable 1 KiB RAM chunk |

With the unmodified boot bytes, TilEm denies Flash pages `0x08`–`0x29` and
allows RAM instruction fetches only when the masked physical RAM offset lies
in 1 KiB chunks `0x10`–`0x20`. These are physical-offset bounds, not a logical
Z80 address interval. The injected app begins on Flash page `0x08`; under the
run's active mapping, its main loop at logical `statVars = 0x8A3A` also resolves
outside the permitted RAM chunks. Both fetch paths would therefore violate
TilEm's initial bounds. [standard]

The protected output instructions in the boot image are preceded by fetched
bytes `00 00 ED 56 F3 D3` (`nop; nop; im 1; di; out`). TilEm uses that sequence
as part of its protected-write gate; Wabbitemu models the gate differently.
The injector reuses the boot's existing output sites rather than treating the
six bytes as a portable unlock recipe. See [Execution
protection](../../docs/execution-protection.md) for the exact emulator
comparison and unresolved physical-hardware boundaries. [standard]

## Sound ISR rate

`out (0x00),a` runs once per interrupt, so the steady port-`0x00` write rate is
the ISR rate. The application programs timer 1 as follows: [confirmed]

```z80
ld a,0x82
out (0x30),a       ; CPU clock divided by 4
ld a,0x03
out (0x31),a       ; loop and request an interrupt
ld a,120
out (0x32),a       ; reload count
```

At the nominal 15 MHz CPU rate selected earlier by the application, those
registers imply

$$
f_{\mathrm{ISR,nominal}} = \frac{15{,}000{,}000}{4 \times 120}
                           = 31{,}250\ \mathrm{Hz}.
$$

The upstream `util/audio.py` instead tunes note counters for 33,333.3 Hz; its
commented alternative is 32,768 Hz. Neither number is derived from the active
`0x82` and 120 register pair. The checked-in renderer preserves 33,333.3 Hz to
reproduce the upstream tracks, while the nominal register calculation predicts
a 6.25% lower pitch and tempo on an exact 15 MHz clock. Physical CPU frequency
varies by unit and ASIC revision, so a physical waveform measurement is still
needed. [confirmed] for the program bytes and encoder constant; [standard] for
the public timer decode and nominal clock; [hypothesis] for physical cadence.

One headless TilEm trace produced only about 4,674 writes/s when its timestamps
were interpreted at 15 MHz. That is evidence about that particular injected
emulator run, not evidence that TI-84 Plus hardware divides this timer by a
further factor of about 7. The optional pitch-corrected trace WAV is therefore
a diagnostic time normalization, not a hardware-accurate render. [standard]

## Verifying the run

The injected app is live in the recorded emulator trace: about 52,000 writes
to LCD data port `0x11`, 28,000 to LCD command port `0x10`, 13,000 Flash bank
swaps through port `0x06`, and 17,000 link-port writes through port `0x00` in
about four interpreted seconds. These counts establish that the injected code
reaches its rendering and audio output paths. They do not establish physical
display output or timer cadence. [standard]

## Files

- [`ti84re/badapple/inject.py`](../ti84re/badapple/inject.py) — inject app + launch hook + open protection.
- [`ti84re/badapple/music.py`](../ti84re/badapple/music.py) — `.mmp`/MIDI/JSON music → track ASM and WAV.
- [`ti84re/badapple/extract_linkport_audio.py`](../ti84re/badapple/extract_linkport_audio.py) — trace → debug link-port WAV.
- [`build_and_capture.sh`](build_and_capture.sh) — the full pipeline.
