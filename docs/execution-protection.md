# Execution protection

*TI-84 Plus OS 2.55MP — Flash-page and RAM-chunk fetch controls.*

Ports `0x21`–`0x26` define where the ASIC permits instruction fetches. The
retail boot writes five protection registers before it changes the normal
memory map. Emulator source supplies reproducible models for the resulting
checks, but several boundary details still require physical measurement.

## Evidence boundaries

| Evidence | What it establishes | Confidence |
|----------|---------------------|------------|
| Retail boot page `3F` | protected writes, register values, and `_SetFlashLowerBound` behavior | [confirmed] |
| Complete-ROM static I/O scan | one write each to ports `0x21`, `0x22`, `0x25`, and `0x26`; two writes to port `0x23`; no resolved port-`0x24` access | [confirmed] |
| TilEm x4 and Wabbitemu source | two executable software models, including their disagreements | [standard] |
| WikiTI port pages | public inclusive-bound descriptions and the larger-device port-`0x24` extension | [standard] |
| Physical TA2/TA3 behavior | lower-edge, reset, violation, and overlay details | [hypothesis] until measured |

The emulator equations below are source-verified descriptions of those
programs. Agreement between an emulator and a public table does not promote an
unmeasured ASIC behavior to [confirmed].

## Registers and boot values

The boot sequence establishes these values. [confirmed]

| Port | Boot value | Modeled role |
|------|-----------:|--------------|
| `0x21` | `0x00` | bits 4–5 select the repeating RAM address mask; bits 0–1 also select the Flash protection group |
| `0x22` | `0x08` | lower Flash no-execute page |
| `0x23` | `0x29` | upper Flash no-execute page |
| `0x25` | `0x10` | lower executable RAM chunk in 1 KiB units |
| `0x26` | `0x20` | upper executable RAM chunk in 1 KiB units |

The five writes occupy `3F:41D5`–`4206`: [confirmed]

```z80
3F:41D5  ld a,0x00
3F:41D7  nop
3F:41D8  nop
3F:41D9  im 1
3F:41DB  di
3F:41DC  out (0x21),a
3F:41DE  di

3F:41DF  ld a,0x08
3F:41E1  nop
3F:41E2  nop
3F:41E3  im 1
3F:41E5  di
3F:41E6  out (0x22),a
3F:41E8  di

3F:41E9  ld a,0x29
3F:41EB  nop
3F:41EC  nop
3F:41ED  im 1
3F:41EF  di
3F:41F0  out (0x23),a
3F:41F2  di

3F:41F3  ld a,0x10
3F:41F5  nop
3F:41F6  nop
3F:41F7  im 1
3F:41F9  di
3F:41FA  out (0x25),a
3F:41FC  di

3F:41FD  ld a,0x20
3F:41FF  nop
3F:4200  nop
3F:4201  im 1
3F:4203  di
3F:4204  out (0x26),a
3F:4206  di
```

Each output is preceded by fetched bytes `00 00 ED 56 F3 D3`. TilEm advances
its protected-write recognizer only while these bytes come from physical Flash
`0xB0000`–`0xBFFFF` or `0xF0000`–`0xFFFFF`. Wabbitemu does not recognize the
six bytes. It accepts a port-`0x14` lock change whenever the output instruction
executes on one of its privileged pages. Both implementations then accept
writes to ports `0x21`–`0x26` only while Flash is unlocked. [standard]

The ROM proves that it emits the required byte sequence from page `3F`. It does
not by itself prove the complete privileged-page set or the response to an
invalid sequence. [confirmed] for the bytes; [standard] for the differing
emulator gates.

## Flash instruction fetches

TilEm x4 applies the following test after it resolves a logical address to a
physical Flash page $p$: [standard]

$$
\mathit{denied}_{\mathrm{TilEm}} = (\mathtt{port22} \le p \le \mathtt{port23})
$$

The boot values therefore deny pages `0x08`–`0x29`, inclusive. Pages
`0x00`–`0x07` and `0x2A`–`0x3F` remain executable. Reversing the bounds makes
the interval empty in this model. [standard]

Wabbitemu implements a different lower edge: [standard]

```c
return bank->page <= flash_lower || bank->page > flash_upper;
```

Its forbidden interval is `(port22, port23]`. With the boot values, Wabbitemu
allows page `0x08`, while TilEm denies it. Both deny page `0x09` and page
`0x29`. WikiTI describes the lower bound as inclusive, which agrees with TilEm,
but the physical page-`0x08` result remains unmeasured. [standard] for the
published contract and source comparison; [hypothesis] for hardware.

Both emulator paths apply this rule to opcode fetches. Ordinary Flash data
reads use a separate path. The locked certificate-page read censor is also a
separate mechanism. [standard]

WikiTI also says page `0x00` always remains executable and that a forbidden
fetch resets the calculator. Wabbitemu always permits page 0 and resets the CPU
on a violation when no debugger callback is installed. TilEm's interval test
can deny page 0 when port `0x22 = 0`; it raises an execution exception and lets
the frontend handle it. These custom-bound and post-violation behaviors remain
physical test cases. [standard]

## RAM instruction fetches

TilEm x4 reduces a physical RAM byte offset $a$ to a 1 KiB chunk address. For
port-`0x21` mode $t = 0,1,2,3$, it computes: [standard]

$$
\begin{aligned}
M_t &= (\mathtt{0x8000} \ll t) - \mathtt{0x400} \\
m &= a \mathbin{\&} M_t \\
\mathit{allowed} &= \mathtt{port25}\cdot\mathtt{0x400}
                   \le m \le
                   \mathtt{port26}\cdot\mathtt{0x400}
\end{aligned}
$$

The mask clears the low ten address bits, so the comparisons operate at 1 KiB
granularity. The upper comparison is inclusive. A port-`0x26` value of `0x20`
therefore includes the complete `0x8000`–`0x83FF` chunk whenever $M_t$ can
produce `0x8000`. [standard]

### Coverage with the boot bounds

The table covers the TI-84 Plus's eight physical RAM pages. Page notation uses
the ordinary selector spelling `0x80`–`0x87`. “Chunk 0” means the first 1 KiB
at page offset `0x0000`–`0x03FF`. [standard]

| Mode | TilEm mask | Repetition | Fully executable pages | Partly executable pages |
|-----:|-----------:|-----------:|------------------------|-------------------------|
| 0 | `0x7C00` | 32 KiB | `0x81`, `0x83`, `0x85`, `0x87` | none |
| 1 | `0xFC00` | 64 KiB | `0x81`, `0x85` | chunk 0 of `0x82` and `0x86` |
| 2 | `0x1FC00` | 128 KiB | `0x81` | chunk 0 of `0x82` |
| 3 | `0x3FC00` | 256 KiB | `0x81` | chunk 0 of `0x82` |

Modes 2 and 3 have the same coverage within the first 128 KiB. Their masks
diverge only when an address reaches the next 128 KiB. Reversing ports `0x25`
and `0x26` denies every RAM chunk in TilEm because the inclusive interval is
empty. [standard]

### Wabbitemu comparison

Wabbitemu's source comments list the fully executable page pattern implied by
the four modes. Its executable predicate contains this expression: [standard]

```c
if (bank->page & (2 >> (prot_mode + 1)))
    return TRUE;
```

For mode 0, the shifted value is `1`, so every odd RAM page returns early. For
modes 1–3, the shifted value is zero. Those modes fall through to one global
address comparison instead of applying a repeating mask. The default bounds
produce this actual coverage: [standard]

| Mode | Wabbitemu fully executable pages | Partly executable pages |
|-----:|-----------------------------------|-------------------------|
| 0 | `0x81`, `0x83`, `0x85`, `0x87` | chunk 0 of `0x82` |
| 1 | `0x81` | chunk 0 of `0x82` |
| 2 | `0x81` | chunk 0 of `0x82` |
| 3 | `0x81` | chunk 0 of `0x82` |

The extra mode-0 chunk comes from Wabbitemu's inclusive global range check,
not its page shortcut. Its mode-2 and mode-3 coverage happens to match TilEm
within 128 KiB under these bounds. The source arithmetic still differs for
other RAM sizes and bound values. These implementation results are not ASIC
evidence.

## Port `0x24` larger-device extension

WikiTI assigns two high Flash-bound bits to port `0x24`: bit 0 extends port
`0x22`, and bit 1 extends port `0x23`. TilEm's color `xc` model uses exactly
those two bits when it compares pages. Its TI-84 Plus `x4` model has no
port-`0x24` case. [standard]

The complete OS 2.55MP ROM scan finds no direct port-`0x24` instruction and no
access resolved from a nearby literal load into `C` or `BC`. Computed accesses
across calls or control-flow joins remain outside this static proof.
[confirmed]

Port `0x24` is therefore a family extension, not part of the confirmed retail
TI-84 Plus initialization path. Wabbitemu registers it on the TI-84 Plus-family
device, but its two high-bit assignment expressions lack parentheses around
the masked bit before shifting. Both expressions evaluate to zero for an
8-bit bus value under C operator precedence. [standard]

## `_SetFlashLowerBound`

The official bcall name does not match the port written by its body.
`_SetFlashLowerBound = 80CF` maps to `3F:4784`, which writes `A` to port
`0x23` — the upper end of the modeled forbidden interval: [confirmed]

```z80
3F:4784  nop
3F:4785  nop
3F:4786  im 1
3F:4788  di
3F:4789  out (0x23),a
3F:478B  di
3F:478C  ret
```

Flash must already be unlocked for either emulator to accept the write. The
routine preserves `A` and leaves interrupts disabled. [confirmed] for the
routine; [standard] for the modeled write gate.

## Mapping and forced overlays

Execution protection runs after logical-to-physical page resolution. TilEm
applies ports `0x27` and `0x28` first, then chooses its Flash or RAM predicate
from the resulting physical page. [standard]

Wabbitemu chooses its Flash-versus-RAM branch from the underlying bank. Its RAM
path also evaluates the page shortcut before replacing the global address for
a forced overlay. The two emulators can therefore disagree when an overlay
forces RAM over a Flash-backed window or substitutes RAM page 0 or 1. See
[Paging](paging.md#interaction-with-execution-protection). [standard]

The normal OS boot and homescreen traces leave both overlays disabled, so this
difference does not affect those executed paths. [confirmed]

## Reproducing the models

`tools/execution_protection.py` contains side-effect-free predicates and RAM
coverage enumeration. The focused CLI prints both emulator results:

```console
$ python tools/describe_execution_protection.py flash
Flash bounds 0x08-0x29
page 0x07: TilEm=allow Wabbitemu=allow
page 0x08: TilEm=deny Wabbitemu=allow
```

```console
$ python tools/describe_execution_protection.py ram --compare-wabbitemu
RAM chunks 0x10-0x20
mode 0 TilEm-mask=0x7C00
  page 0x80: TilEm=- Wabbitemu=-
  page 0x81: TilEm=all Wabbitemu=all
```

Use `--json` for machine-readable output. Custom `--lower`, `--upper`,
`--mode`, and `--ram-pages` values expose boundary cases without modifying an
emulator.

The boot bytes can be recovered independently:

```console
$ python tools/disassemble_rom.py 0x3f --start 0x41d5 --end 0x4206
$ python tools/analyze_rom_io.py 0x21 0x22 0x23 0x24 0x25 0x26 --summary
```

## Resolved findings and open hardware tests

- The boot writes `00`, `08`, `29`, `10`, and `20` to ports `0x21`, `0x22`,
  `0x23`, `0x25`, and `0x26` through protected byte sequences. [confirmed]
- `_SetFlashLowerBound` writes port `0x23`, despite its official name.
  [confirmed]
- TilEm denies the inclusive Flash interval. Wabbitemu allows its programmed
  lower page. [standard]
- TilEm applies a repeating RAM mask and inclusive 1 KiB chunk bounds.
  Wabbitemu's modes 1–3 omit the intended page shortcut. [standard]
- The retail ROM has no statically resolved port-`0x24` access. [confirmed]

Physical tests must determine whether page `0x08` executes, what exception or
reset state follows a violation, and whether lower-greater-than-upper disables
each protection range. Tests should also sweep all 1 KiB RAM boundaries in all
four modes, repeat them with ports `0x27` and `0x28` active, and record the
register state after warm and cold resets. Until then, emulator agreement is
only a test oracle for emulator behavior.

## Sources

| Source | Use |
|--------|-----|
| OS 2.55MP and boot 1.03 ROM, especially `3F:41D5`–`4206` and `3F:4784`–`478C` | protected writes and bcall body |
| [TilEm x4 memory model at `f56ad63`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_memory.c) | Flash and RAM fetch predicates |
| [TilEm x4 I/O model at `f56ad63`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_io.c) | protected register writes and mask updates |
| [TilEm xc memory model at `f56ad63`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/xc/xc_memory.c) | port-`0x24` high-bound bits |
| [Wabbitemu `core.c` at `48c2dc0`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/core/core.c) | Flash and RAM fetch predicates |
| [Wabbitemu `device.c` at `48c2dc0`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/core/device.c) | global protected-port write gate |
| [Wabbitemu `83psehw.c` at `48c2dc0`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/hardware/83psehw.c) | port handlers and port-`0x24` implementation |
| [WikiTI port `0x22`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:22), [`0x23`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:23), [`0x24`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:24), [`0x25`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:25), and [`0x26`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:26) | public register descriptions, treated as secondary evidence |
