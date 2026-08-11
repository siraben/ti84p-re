# Paging

The ASIC maps four 16 KiB logical windows into Flash and RAM. Port `0x04`
selects one of two mapping modes, ports `0x05`–`0x07` hold the page selectors,
and ports `0x0E`, `0x0F`, `0x27`, and `0x28` modify the selected pages or small
subranges.

This page distinguishes behavior executed by OS 2.55MP from public hardware
descriptions and emulator implementations. The ROM never gives ports `0x27`
or `0x28` a nonzero value, so their physical behavior remains unconfirmed.

## Evidence and scope

| Evidence | What it establishes | Confidence |
|----------|---------------------|------------|
| ROM bytes at `00:0000`–`029C`, `3F:4000`–`4210`, and the paged-RAM helpers | exact selector writes, boot transitions, and OS restore values | [confirmed] |
| Resolved TilEm boot and homescreen traces | executed page transitions and logical-to-physical page resolution | [confirmed] |
| TilEm `x4_io.c` and `x4_memory.c` | one emulator's paired mode, selector masks, forced overlays, and protection order | [standard] |
| Wabbitemu `83psehw.c` and `core.c` | an independent implementation, including extended Flash pages and different overlay rules | [standard] |
| Public port descriptions | intended family-wide contracts for ports `0x04`–`0x07`, `0x0E`, `0x0F`, `0x27`, and `0x28` | [standard] |

The target ROM runs on a TI-84 Plus with 64 Flash pages and eight RAM page
selectors. Family members with more Flash need the extended selector bits in
ports `0x0E` and `0x0F`.

## The four logical windows

The Z80 supplies a 16-bit address. The top two address bits choose a logical
window; the mapper supplies the physical page.

| Logical range | Window | Base selector in independent mode | Normal OS use |
|---------------|--------|-----------------------------------|---------------|
| `0x0000`–`0x3FFF` | 0 | fixed Flash page `00` | reset vectors, interrupts, and kernel code |
| `0x4000`–`0x7FFF` | A | port `0x06`, extended by `0x0E` for Flash | paged Flash code or temporary banked RAM |
| `0x8000`–`0xBFFF` | B | port `0x07`, extended by `0x0F` for Flash | normally RAM page `81` |
| `0xC000`–`0xFFFF` | C | port `0x05` | normally RAM page `80` |

Window 0 stays fixed in both modes. [standard] The fixed page and the normal
RAM values match the OS trace. [confirmed]

A physical page can appear in more than one window. During boot, Flash page
`3F` is visible through both A and B for part of the transition. Logical
addresses in those windows then alias the same physical bytes at different
offsets. [confirmed]

## Mapping modes — port `0x04` bit 0

Writing port `0x04` changes the memory mode and the standard-timer rate. Its
bit 0 controls the mapper. Reading the same port returns interrupt and key
status, not the last mode byte. See [Clock, timers, and power](clock-timers-power.md)
for the other bits. [standard]

### Independent mode — bit 0 clear

Each banked window has its own selector.

| Window | Source | Result |
|--------|--------|--------|
| A, `0x4000`–`0x7FFF` | ports `0x06` and `0x0E` | one Flash or RAM page |
| B, `0x8000`–`0xBFFF` | ports `0x07` and `0x0F` | one Flash or RAM page |
| C, `0xC000`–`0xFFFF` | port `0x05` | one RAM page |

The OS normally writes `0x06` to port `0x04`, selecting independent mode and
the slowest standard-timer rate. Its bcall dispatcher maps a target Flash page
through port `0x06`. Paged-RAM helpers use ports `0x05` and `0x07` as a pair.
[confirmed]

### Paired mode — bit 0 set

Port `0x06` supplies an adjacent page pair, and port `0x07` moves to window C.
Port `0x05` does not select a visible window in this mode. [standard]

| Window | Source | Page rule |
|--------|--------|-----------|
| A, `0x4000`–`0x7FFF` | port `0x06` | selected physical page with bit 0 cleared |
| B, `0x8000`–`0xBFFF` | port `0x06` | the adjacent page with bit 0 set |
| C, `0xC000`–`0xFFFF` | port `0x07` | the page selected by port `0x07` |

For example, the TI-84 Plus reset selector `0x3F` produces Flash page `3E` in
window A and page `3F` in window B. The boot trace begins at logical `0x8000`,
which therefore executes `3F:4000`. [confirmed]

Changing bit 0 reinterprets all three banked windows at once. Code that changes
the mode must execute from fixed page 0 or from a physical page visible at the
next logical PC under both mappings. The boot transition uses the latter
method. [confirmed]

## Selector encoding

### Ports `0x06` and `0x07`

Bit 7 chooses the memory type. On the TI-84 Plus, these selector rules match
the trace and both emulator implementations: [confirmed] for executed OS
values; [standard] for the complete register contract.

| Selector | Physical page |
|----------|---------------|
| bit 7 clear | Flash page, low six bits on this 64-page calculator |
| bit 7 set | RAM page `0x80 | (value & 7)` |

The hardware-facing `0x80`–`0x87` RAM notation distinguishes RAM selectors
from Flash page numbers. It does not mean that RAM has 128 pages. See
[RAM pages](ram-pages.md) for physical aliasing and OS use.

### Port `0x05`

Port `0x05` always selects RAM. On the TI-84 Plus, its low three bits select
RAM page `0x80 | (value & 7)`. The normal value `0x00` therefore maps RAM page
`80` into window C in independent mode. [confirmed]

TilEm stores four low bits for port readback but uses only three in its page
calculation. Wabbitemu reduces the low seven bits by the model's RAM page
count. Both produce the same eight TI-84 Plus pages. [standard]

### Extended Flash bits — ports `0x0E` and `0x0F`

Public descriptions and Wabbitemu model these registers as two high Flash-page
bits. Port `0x0E` extends port `0x06`; port `0x0F` extends port `0x07`: [standard]

$$
P_A = ((p_6 \bmod 128) + 128(p_{0E} \bmod 4)) \bmod N_F
$$

$$
P_B = ((p_7 \bmod 128) + 128(p_{0F} \bmod 4)) \bmod N_F
$$

Here $N_F$ is the number of physical Flash pages. The high registers apply
only when bit 7 of the corresponding low selector is clear. A RAM selector
ignores them. [standard]

For the 64-page TI-84 Plus, every contribution from ports `0x0E` and `0x0F`
is a multiple of 128 and disappears after the page mask. The boot ROM still
writes `3` to each register while selecting its highest boot page, then clears
both during normal mapper initialization. [confirmed]

TilEm's TI-84 Plus mapper stores and reads the low two bits but does not feed
them into its 64-page calculation. Wabbitemu uses the family-wide formula and
masks the result by the configured Flash size. These implementations agree for
this target. [standard]

## Boot mapping transition

The retail boot page contains a reset stub at `3F:4000`. Under the emulator's
reset mapping it executes at logical `0x8000`: [confirmed]

```z80
3F:4000  LD A,0x07
3F:4002  OUT (0x04),A     ; paired mode
3F:4004  LD A,0x7F
3F:4006  OUT (0x06),A     ; A=page 3E, B=page 3F
3F:4008  LD A,0x03
3F:400A  OUT (0x0E),A
3F:400C  JP 0x812C       ; continue on page 3F in window B
```

Page 0 also contains a restart path at `00:0000` → `00:028C`. It tests port
`0x02` bit 7, writes either `0x1F` or `0x03` to port `0x0E`, writes `0x7F` to
port `0x06`, selects paired mode, and jumps to the same logical `0x812C`.
Both values written to `0x0E` have low two bits equal to three. [confirmed]

The continuation changes to independent mode without paging out its next
instruction: [confirmed]

```z80
3F:412C  IM 1
          ; stack/RAM probe omitted
3F:4142  LD A,0x03
3F:4144  OUT (0x0F),A
3F:4146  LD A,0x7F
3F:4148  OUT (0x07),A     ; C=page 3F while still paired
3F:414A  LD A,0x06
3F:414C  OUT (0x04),A     ; independent: A=3F, B=3F, C=RAM 80
3F:414E  JP 0x4151       ; page 3F remains visible in window A
```

Boot then maps `0x81` through port `0x07`, probes writable RAM at `0xC000` and
`0x8000`, and programs the execution-protection registers. At `3F:4208` it
clears ports `0x0E`, `0x0F`, and `0x05`, writes page `0x3F` to port `0x06`,
and later maps RAM through port `0x07`. [confirmed]

The resolved trace records the complete transition:

```text
OUT (0x04) <- 07   paired mode
OUT (0x06) <- 7F   A=page 3E, B=page 3F
OUT (0x0E) <- 03
OUT (0x0F) <- 03
OUT (0x07) <- 7F   C=page 3F
OUT (0x04) <- 06   independent mode
OUT (0x07) <- 81   B=RAM page 81
OUT (0x0E) <- 00
OUT (0x0F) <- 00
OUT (0x05) <- 00   C=RAM page 80
OUT (0x06) <- 3F   A=Flash page 3F
OUT (0x07) <- 80   B=RAM page 80
```

This sequence shows why a mode change cannot be modeled as three independent
port assignments. The meaning of the already-written `0x06` and `0x07`
selectors changes when port `0x04` bit 0 changes.

## Why RAM helpers clear port `0x0F`

Several OS helpers clear port `0x0F` immediately before selecting RAM through
port `0x07`. Representative sites include `ram:0B78`, `05:5B66`, `2F:45A9`,
`36:74F8`, `37:44CA`, and `38:7782`. They then compute a page pair:
[confirmed]

```z80
    XOR A
    OUT (0x0F),A
    LD A,B
    SLA A
    OUT (0x05),A       ; even RAM page in window C
    INC A
    OR 0x80
    OUT (0x07),A       ; odd RAM page in window B
```

Bit 7 of the port-`0x07` value is set, so the extended *Flash* bits do not
participate in the resulting RAM page under the public contract or either
emulator. The clear may be defensive state normalization or compatibility with
another ASIC revision. The ROM does not establish that it is required.
[hypothesis]

## Forced RAM subranges — ports `0x27` and `0x28`

The public descriptions and TilEm implement two 64-byte-granularity overlays.
For a byte value $n$: [standard]

| Port | Forced logical range | Physical page |
|------|----------------------|---------------|
| `0x27` | `0x10000 - 64n` through `0xFFFF` | RAM page `80` |
| `0x28` | `0x8000` through `0x8000 + 64n - 1` | RAM page `81` |

A zero value disables the corresponding overlay. The maximum byte value,
`0xFF`, leaves one 64-byte block of its 16 KiB window outside the forced range.

OS 2.55MP writes zero to both ports in `mode_default_init` at `37:6D3A` and
`37:6D3E`. It also clears port `0x27` before RAM-bank tests at `37:72D3` and
`3F:45F5`. No immediate or dynamic write in the analyzed ROM gives either port
a nonzero value. These writes confirm that the OS disables the feature, but
they do not confirm the nonzero mapping formula. [confirmed]

### Emulator disagreement

The two emulator implementations disagree at the point most useful for a
hardware test: [standard]

| Detail | TilEm | Wabbitemu |
|--------|-------|------------|
| Overlay active in paired mode | yes | no; checks `!boot_mapped` |
| Port `0x28` range | complete formula above | complete formula above in independent mode |
| Port `0x27` range | complete formula above | also requires the logical address to be at least `0xFB64` |
| Read, write, and instruction fetch | all resolve through the overlay | data reads/writes use the overlay; execution checks retain some underlying-bank logic |

WikiTI's historical description says these ports have no effect in paired
mode, which agrees with Wabbitemu and disagrees with TilEm. None of these
software sources proves the ASIC behavior. [hypothesis] for physical paired-mode
behavior.

## Interaction with execution protection

Ports `0x21`–`0x26` control Flash and RAM execution permissions. They do not
select pages; see [Execution protection](execution-protection.md) for their
write gate, equations, and boundary discrepancies.

TilEm first resolves a port-`0x27` or port-`0x28` overlay, then applies the
execution rule for the resulting physical RAM page. A fetch forced from a
Flash-backed window into RAM is therefore checked as RAM in TilEm. [standard]

Wabbitemu's fetch check chooses its Flash-versus-RAM branch from the underlying
window before adjusting a RAM address for the overlay. A forced RAM range over
an underlying Flash page can therefore follow different protection logic from
TilEm. This is an emulator fidelity difference, not evidence for either ASIC
ordering. [standard]

The analyzed OS leaves both overlays disabled before normal execution, so this
difference does not affect the traced boot and homescreen paths. [confirmed]

## Safe mapper use

- Preserve every selector that the routine changes. Ports `0x05`, `0x06`,
  `0x07`, `0x0E`, `0x0F`, `0x27`, and `0x28` have readable state in the public
  contract and both emulators. [standard]
- Do not use `IN A,(0x04)` to save the memory mode. Reads return interrupt
  status. Code entered under TI-OS can rely on its documented normal
  independent mode or must receive the mode from its caller. [standard]
- Disable interrupts around a temporary mapping unless the interrupt path can
  run with that mapping. The OS page-`83` helpers preserve interrupt state for
  this reason. [confirmed]
- When changing paired mode, ensure the next instruction remains mapped. Fixed
  page 0 is the least state-dependent place to perform the transition.
  [standard]
- On family members with more than 128 Flash pages, preserve the matching high
  selector with each low Flash selector. Restoring only port `0x06` or `0x07`
  can restore the wrong physical page. [standard]
- Restore normal TI-84 Plus RAM windows with port `0x07 = 0x81` and port
  `0x05 = 0x00` when the caller follows the ordinary OS convention. For a
  general library, restore the values read on entry instead. See
  [RAM pages](ram-pages.md#restoring-after-page-83).

## Reproducing the mapping

`tools/memory_mapper.py` contains the reusable selector model.
`tools/describe_memory_mapping.py` applies a sequence of writes and prints the
resulting windows. This reproduces the final boot state shown above:

```sh
nix develop -c python tools/describe_memory_mapping.py \
  --write 0x0e=3 --write 6=0x7f \
  --write 0x0f=3 --write 7=0x7f --write 4=6 \
  --write 7=0x81 --write 0x0e=0 --write 0x0f=0 \
  --write 5=0 --write 6=0x3f --write 7=0x80
```

The trace resolver uses the same library. To show the executed boot writes:

```sh
nix develop -c python tools/tilem_trace_resolve.py /tmp/boot.trace \
  --initial-mapping ti84p-reset --page-switches \
  --io-ports 04-07,0e-0f,27-28
```

Static whole-ROM port scans are candidate generators because data can decode as
instructions. Add context and verify control flow before treating a hit as
code:

```sh
nix develop -c python tools/analyze_rom_io.py \
  --before 8 --after 8 0x0e-0x0f,0x27-0x28
```

## Open physical tests

- Write nonzero values to ports `0x27` and `0x28` in independent mode and test
  both range boundaries with reads and writes.
- Repeat the boundary tests in paired mode to distinguish TilEm from
  Wabbitemu and the historical WikiTI claim.
- Execute controlled code on each side of an overlay boundary while varying
  ports `0x21`–`0x26`; record whether protection follows the underlying window
  or the forced RAM page.
- Test port `0x27` below `0xFB64` to determine whether Wabbitemu's additional
  cutoff models hardware or is an emulator-specific restriction.
- Read ports `0x0E` and `0x0F` after writing values with upper bits set on TA2,
  TA3, and larger-Flash family members.

## Sources

| Source | Use |
|--------|-----|
| OS 2.55MP `rom.bin`, especially `00:0000`–`029C`, `3F:4000`–`4210`, `37:44AE`, and `37:6D33` | executed selector sequences and reset values |
| [TilEm `x4_io.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_io.c) and [`x4_memory.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_memory.c) | mapping modes, 64-page masks, overlays, and protection order |
| [Wabbitemu `83psehw.c`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/hardware/83psehw.c) and [`core.c`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/core/core.c) | extended selectors, paired mode, overlays, and independent comparison |
| [WikiTI port `0x04`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:04), [`0x0E`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:0E), [`0x0F`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:0F), [`0x27`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:27), and [`0x28`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:28) | historical public register descriptions checked against ROM and emulators |
