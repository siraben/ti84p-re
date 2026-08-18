# RAM pages

The TI-84 Plus maps banked RAM behind the Z80's 16 KiB windows. This page
separates selector values from physical backing, reconciles the reported
128 KiB and 48 KiB revisions, traces OS use of selectors `80`–`83`, and gives
restoration rules for programs that borrow banked RAM.

## Physical integration and capacity revisions

Datamath's March 2004 board photographs show three main integrated circuits:
the `TI REF 83PLUSB/TA2` ASIC, a `29LV800` Flash device, and the LCD driver.
The accompanying board description places the Z80 core and RAM inside the
ASIC. An external SRAM package therefore is not part of that photographed
revision. [standard]

WikiTI's hardware history reports 128 KiB in the original TI-84 Plus design
and a later reduction to 48 KiB. Its RAM-page table says units with port
`0x15 >= 0x55` map selectors `82`–`87` to one physical 16 KiB block. These are
community hardware reports. Neither page supplies a primary TI specification,
a dated transition, or a measurement tied to a photographed board. [standard]

The two reported topologies use the same eight selector values: [standard]

| Reported capacity | Physical backing | Consequence at one page offset |
|------------------:|------------------|--------------------------------|
| 128 KiB | eight independent 16 KiB blocks | selectors `80`–`87` can retain eight different bytes |
| 48 KiB | blocks `80`, `81`, and one block shared by `82`–`87` | the last write through any selector `82`–`87` is visible through all six |

Port `0x15` does not appear in any statically resolved OS 2.55MP I/O
instruction. The public identity table associates `0x44` and `0x45` with
128 KiB and `0x55` with 48 KiB, while Datamath identifies TA2 and TA3 package
families without assigning their RAM capacity. Do not infer capacity from an
ASIC label alone. The restoring probe records the package-independent port
`0x15` byte and the observed selector groups in one frame. [confirmed] for
the ROM scan and probe format; [standard] for the public identities;
[hypothesis] for an unmeasured calculator's topology.

## Page selectors

The public TI-84 Plus register contract uses two selector encodings. The OS trace
confirms the values it executes, but it does not confirm the complete selector
space or the physical storage behind selectors `84`–`87`.

| Window | Port | Selector encoding | Normal TI-OS value |
|--------|------|-------------------|--------------------|
| `4000-7FFF` | `0x06` | Bit 7 clear selects Flash page `value & 0x3F`; bit 7 set selects RAM page `0x80 \| (value & 7)` | Banked Flash page |
| `8000-BFFF` | `0x07` | Bit 7 clear selects Flash page `value & 0x3F`; bit 7 set selects RAM page `0x80 \| (value & 7)` | `81` |
| `C000-FFFF` | `0x05` | The low three bits select RAM page `0x80 \| (value & 7)` | `00` → RAM page `80` |

TilEm implements this eight-page arithmetic. The trace confirms the executed
selector values below. The complete contract is [standard]. The listed OS writes
are [confirmed].

In the idle boot/home trace, the RAM-window writes are:

Ports `0x0E` and `0x0F` extend ports `0x06` and `0x07` only for Flash
selectors. They do not change a selector with bit 7 set for RAM. See
[Paging](paging.md#extended-flash-bits--ports-0x0e-and-0x0f). [standard]

```text
OUT (port 7) <- 0x7f   8000-BFFF = page_3F
OUT (port 7) <- 0x81   8000-BFFF = RAM/0x81
OUT (port 5) <- 0x00   C000-FFFF = RAM/0x80
OUT (port 7) <- 0x80   8000-BFFF = RAM/0x80
OUT (port 7) <- 0x81   8000-BFFF = RAM/0x81
OUT (port 5) <- 0x02   C000-FFFF = RAM/0x82
OUT (port 7) <- 0x83   8000-BFFF = RAM/0x83
OUT (port 7) <- 0x81   8000-BFFF = RAM/0x81
OUT (port 5) <- 0x00   C000-FFFF = RAM/0x80
```

The trace restores port `0x07` to `0x81` and port `0x05` to `0x00` before normal
OS execution resumes. [confirmed]

## Page map

WikiTI's [RAM pages](https://wikiti.brandonw.net/index.php?title=83Plus:OS:Ram_Pages)
page supplies the historical page descriptions. The trace and ROM disassembly
independently support only the entries whose evidence column says [confirmed].

| RAM selector | Use | Evidence |
|--------------|-----|----------|
| `80` | Normal `C000-FFFF` RAM page | The boot/home trace restores it with `OUT (5),0`; WikiTI marks it execution-protected. [confirmed] for the restore; [standard] for the protection claim. |
| `81` | Normal `8000-BFFF` RAM page | The traces access OS variables, OP registers, flags, graph buffers, the user heap, and the VAT window through this selector. [confirmed] |
| `82` | Temporary half of an OS bank pair | The idle trace selects it through port `0x05` as part of a paged RAM helper, then restores selector `80`. No page-`82` store occurs. [confirmed] |
| `83` | Shared OS scratch and state | OS 2.55MP maps it through port `0x06` for block copies and LCD capture, and through port `0x07` for a paged byte-store helper. Homescreen expression entry writes the previous-entry buffer at `577E`. [confirmed] |
| `84` | No use established here | WikiTI marks it execution-protected. [standard] |
| `85` | No use established here | WikiTI describes it as unused under typical TI-OS execution. [standard] |
| `86` | No use established here | WikiTI marks it execution-protected. [standard] |
| `87` | No use established here | WikiTI describes it as unused under typical TI-OS execution. [standard] |

Wabbitemu has an optional `ram_version == 2` branch matching the reported
48 KiB topology. Selected internal pages 3–7 read and write
`ram[2 * PAGE_SIZE]`; internal page 2 already addresses that block. Emulator
agreement with WikiTI does not establish a physical unit's backing. The
[restoring RAM alias probe](hardware-probes.md#ram-alias-probe) records the
original, patterned, and restored bytes for selectors `82`–`87`. No physical
result has been recorded. [standard] for the sources; [confirmed] for the probe
bytes; [hypothesis] for an unmeasured calculator's topology.

## Emulator implementations

The pinned source revisions implement different RAM backing rules. These results
describe software behavior and do not select the correct physical ASIC contract.

| Implementation | Source-verified behavior | Limit |
|----------------|--------------------------|-------|
| TilEm `f56ad637` | [`x4_io.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_io.c) makes RAM selectors flat pages `0x40 \| (value & 7)`; [`x4_memory.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_memory.c) addresses each page independently. This gives eight distinct 16 KiB blocks. [standard] | It has no 48 KiB alias mode in the pinned mapper. |
| Wabbitemu `48c2dc0` | [`core.c`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/core/core.c) redirects reads and writes from selected pages 3–7 to physical page 2 when `ram_version == 2`. [`memory_init_84p`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/hardware/83psehw.c#L1675) zeroes the context and does not enable the branch. [standard] | The selected bank page remains separate from its aliased physical backing. |
| MAME 0.287 | [`ti85_m.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85_m.cpp) retains raw RAM selectors at ports `0x06` and `0x07`. [`ti85.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85.cpp) maps banked RAM across `0x200000`–`0x21BFFF`, exactly seven 16 KiB blocks, so selector `87` resolves beyond the map. [standard] | It neither wraps selector `87` nor implements the six-to-one 48 KiB alias. MAME marks the TI-84 Plus driver `MACHINE_NOT_WORKING`. |

The JSON-capable mapper CLI can reproduce Wabbitemu's optional alias branch:

```sh
python tools/describe_memory_mapping.py --json map \
  --profile wabbitemu --ram-alias-from 2 \
  --write 4=0 --write 5=7 --write 6=0x87 --write 7=0x87
```

The report retains selector readbacks `07`, `87`, and `87` while all three RAM
windows resolve to physical page `82`. `--ram-alias-from` configures a candidate
physical topology; it does not assert that an emulator enables that topology by
default. Run the same sequence with `--profile mame` and no alias option to expose
MAME's unmapped selector `87`. See [Paging](paging.md) for the complete mapper
comparison.

The alias-probe decoder reconstructs equivalence classes from the ordered
patterns. Each selector in one class reads the pattern written through the
highest-numbered selector in that class. The two expected endpoints and a
partial-alias example are reproducible without a calculator:

```sh
python tools/describe_ram_topology.py --observed 112233445566
python tools/describe_ram_topology.py --observed 666666666666
python tools/describe_ram_topology.py \
  --simulate-backings 0,0,1,1,2,3 --json
```

The simulated partial mapping produces `22 22 44 44 55 66` and groups
`82`/`83`, `84`/`85`, `86`, and `87`. This is a decoder test case, not a
reported hardware revision. [confirmed]

## Per-page trace coverage

The boot/home and `2+3 ENTER` traces exercise startup, homescreen initialization,
display capture, parsing, evaluation, and previous-entry storage. They do not exercise
app launch, USB transfer, graph drawing, archive cleanup, or a 48 KiB ASIC. Within
that scope, physical RAM-page writes for the executed selectors are:

| RAM selector | Idle trace writes | `2+3 ENTER` trace writes | Interpretation |
|--------------|-------------------|--------------------------|----------------|
| `80` | `256227` writes, all page addresses touched | `345702` writes, all page addresses touched | Normal high RAM selected by port `0x05`; contains stack, system, and user RAM activity in `C000-FFFF`. [confirmed] |
| `81` | `62947` writes, all page addresses touched | `72638` writes, all page addresses touched | Normal `8000-BFFF` RAM; contains OS variables, flags, OP registers, the heap, the VAT window, and working buffers. [confirmed] |
| `82` | No writes observed | No writes observed | Port `0x05` briefly selects raw value `02`, but the observed store uses selector `83` in bank B. [confirmed] |
| `83` | `1882` writes to `43D9-44BD` and `5A7E-5DF2` | `3467` writes to `4373-4390`, `43D9-44BD`, `577E-5790`, and `5A7E-5DF2` | Shared OS scratch and state. See the range table below. [confirmed] |

The traces never select `84`–`87`. That absence describes these scenarios; it does
not establish how the selectors behave. Under the public 48 KiB contract, selectors
`82`–`87` share one physical block rather than six independent pages. [standard]

The graph scenario in `tools/macros/graph-y1-x2.macro` reaches the graph screen and
still only writes pages `80`, `81`, and `83`. It increases normal page-`80`/`81`
activity but leaves page-`83` at the same confirmed ranges as the idle trace.
It does not write through selector `82` or select `84`–`87`. [confirmed]

## How to hit the confirmed paths

The useful distinction is between "page number can be selected" and "the OS uses it
in a normal workflow." These paths are confirmed or have a concrete next scenario:

| Page/path | How to hit it | Evidence |
|-----------|---------------|----------|
| `80` high RAM | Run any cold-boot, home, expression, or graph trace. | Port `5 = 00` is the normal restore value; every current trace writes all page-`80` addresses. [confirmed] |
| `81` normal bank-B RAM | Run any cold-boot, home, expression, or graph trace. | Port `7 = 81` is the normal restore value; every current trace writes all page-`81` addresses. [confirmed] |
| `83` display capture | Run `boot-idle.macro` or `graph-y1-x2.macro`. | Ghidra shows `_SaveDisp` (`39:5DD8`) calls `lcd_read_block` (`ram:1890`) at the `39:5E03` call site; coverage hits both, and writes `5A7E-5D7D`. [confirmed] |
| `83` homescreen previous-entry history | Run `home-2plus3.macro`. | The trace adds `577E-5790`, advances `lastEntryPTR` from `577E` to `5791`, and sets `numLastEntries` to `01`. [confirmed] |
| `83` expression scratch copy | Run `home-2plus3.macro`. | The trace adds `4373-4390` through `flash_copy_block`; its page-select instruction is at `+0x14` (`ram:187C`). [confirmed] |
| `83` split-screen/table copy | Enter a split-screen/table workflow that calls `screen_split`. | Ghidra shows `screen_split` at `05:7712` calls `flash_copy_block` at `05:772A`; this path is not hit by the current macros. [confirmed] |
| `83` edit-buffer initialization | Enter an edit-buffer workflow that reaches `editbuf_init_buf`. | Ghidra shows `editbuf_init_buf` at `03:6BC4` calls `flash_copy_block` at `03:6BCD`; this path is not hit by the current macros. [confirmed] |
| `83` app-menu state restore | Open an app/menu workflow that reaches `mnu_restore_app_state`. | Ghidra shows `mnu_restore_app_state` at `39:6D96` calls `flash_copy_block` at `39:6DA0`; this path is not hit by the current macros. [confirmed] |
| `84`–`87` independent pages | Use a forced RAM-page probe or a ROM path that passes pair index `2` or `3` to the computed bank-pair helper. | The ROM can compute these selectors, but raw immediate selector scans and current traces do not show a normal OS path selecting or writing them. [hypothesis] |

The computed bank-pair helpers use this selector formula:

```z80
    LD A,B
    SLA A
    OUT (5),A        ; pair index 0/1/2/3 -> pages 80/82/84/86 in bank C
    INC A
    OR 0x80
    OUT (7),A        ; pair index 0/1/2/3 -> pages 81/83/85/87 in bank B
```

Decoded callers set `B = 1`, selecting pages `82/83`; that explains the observed
`port 5 = 02`, `port 7 = 83` sequence. Selectors `84`–`87` are reachable through the
helper but are not selected on any observed OS path [hypothesis]. The `B = 1`
caller pattern is confirmed for the decoded callers above. [confirmed]

## Page `83` use [standard]

Page `83` is the page people most often borrow as scratch, but the ROM uses it as
more than anonymous free RAM. Keep the evidence classes separate:

| Range | Use | Evidence |
|-------|-----|----------|
| `4373-4390` | Expression-path page-`83` scratch copy | Added by the `2+3 ENTER` trace. `flash_copy_block+0x16` (`ram:187E`) performs the `LDIR`; `flash_copy_block+0x14` (`ram:187C`) maps page `83`. The caller is still unlabeled. [confirmed] |
| `43D9-44BD` | Boot/home page-`83` scratch copy | Present in the idle trace. `flash_copy_block+0x16` performs the `LDIR`, and `37:44D8` stores one additional byte. [confirmed] |
| `577E-5A7D` | Homescreen previous-entry history | Page `33` references `577E`, the `5A7E` upper bound, `lastEntryPTR` (`0x8DA7`), and `numLastEntries` (`0x8E29`). The `2+3 ENTER` trace writes `577E-5790`, advances `lastEntryPTR` to `5791`, and sets `numLastEntries` to `01`. [confirmed] |
| `5A7E-5DF2` | LCD/home display capture area | Present in the idle trace. The `_SaveDisp` LCD capture (`ram:1890`) fills the first `0x300` bytes, `5A7E-5D7D` (the 96×64 framebuffer); the `5D7E-5DF2` tail is additional page-`83` writes in the same scenario. Ghidra decompiles `ram:1890` as an LCD-read helper that maps page `83` through port `6` and stores bytes read from LCD port `11`. [confirmed] |
| `4000-4080` | App base-page staging before app execution | WikiTI public note; the two traces on this page do not launch an app. [standard] |
| `4100-433A` | USB communication buffers | WikiTI public note; the two traces on this page do not exercise USB transfer. [standard] |

`flash_copy_block` at `ram:1868` saves the current port-`6` value, writes
`0x83` to port `6`, runs `LDIR`, and restores the previous page through the
page-set helper. The two repeatedly cited instructions are offsets within this
routine rather than separate functions:

```z80
ram:1877  IN A,(6)
ram:1879  PUSH AF
ram:187A  LD A,0x83
ram:187C  OUT (6),A
ram:187E  LDIR
ram:1880  POP AF
ram:1881  CALL 0x181C
```

Ghidra identifies the LCD capture helper at `ram:1890`. It maps page `83`, waits on
the LCD, reads port `11`, and stores each byte through `HL`:

```z80
ram:189F  IN A,(6)
ram:18A1  PUSH AF
ram:18A2  LD A,0x83
ram:18A4  OUT (6),A
ram:18A6  CALL 0x0CC3
ram:18A9  IN A,(0x11)
ram:18AB  LD (HL),A
```

The reset path on page `37` initializes the previous-entry pointers:

```z80
37:6E0D  LD HL,0x577E
37:6E10  LD (lastEntryPTR),HL
37:6E13  LD HL,0x0000
37:6E16  LD (numLastEntries),HL
```

Page `38` has a second clear path with the same pointer reset:

```z80
38:422D  LD HL,0x577E
38:4230  LD (lastEntryPTR),HL
38:4233  LD HL,0x0000
38:4236  LD (numLastEntries),HL
```

The homescreen entry-history code on page `33` uses the same constants and variables:

```z80
33:53D1  LD A,(numLastEntries)
33:53E2  LD HL,0x5A7E
33:53F7  LD HL,0x577E
33:5430  LD A,(numLastEntries)
33:543A  LD DE,0x577E
33:5451  LD DE,0x577E
33:5459  LD (lastEntryPTR),HL
33:5462  LD HL,numLastEntries
33:5465  INC (HL)
```

If a program modifies the history buffer on page `83`, clearing `numLastEntries`
at `0x8E29` prevents the homescreen from scrolling back into invalid entry data.
That is the public WikiTI recovery advice, and the ROM confirms that `0x8E29` is
the OS-visible previous-entry count. [standard]

## Dynamic test scenarios

The trace analyzer maps TilEm memory-write records back to physical RAM pages. Use
it with full-range traces:

```sh
ROM=/path/to/ti84plus_2.55mp_complete.rom
tilem2 --headless --rom "$ROM" --model ti84p --normal-speed --reset \
  --macro tools/macros/boot-idle.macro \
  --trace /tmp/page83-idle.trace --trace-range all
tilem2 --headless --rom "$ROM" --model ti84p --normal-speed --reset \
  --macro tools/macros/home-2plus3.macro \
  --trace /tmp/page83-2plus3.trace --trace-range all
tilem2 --headless --rom "$ROM" --model ti84p --normal-speed --reset \
  --macro tools/macros/graph-y1-x2.macro \
  --trace /tmp/page83-graph.trace --trace-range all
python3 tools/analyze_ram_page_trace.py /tmp/page83-idle.trace --page 0x83
python3 tools/analyze_ram_page_trace.py /tmp/page83-2plus3.trace --page 0x83
python3 tools/analyze_ram_page_trace.py /tmp/page83-graph.trace --page 0x83
```

The baseline idle trace writes:

```text
RAM page 0x83 writes: 1882
unique page addresses: 1114
range 43D9-44BD
range 5A7E-5DF2
```

The `2+3 ENTER` trace writes:

```text
RAM page 0x83 writes: 3467
unique page addresses: 1163
range 4373-4390
range 43D9-44BD
range 577E-5790
range 5A7E-5DF2
```

The before/after RAM variables line up with the previous-entry write:

| Scenario | `lastEntryPTR` (`0x8DA7`) | `numLastEntries` (`0x8E29`) |
|----------|---------------------------|-----------------------------|
| Idle home screen | `577E` | `00` |
| After `2+3 ENTER` | `5791` | `01` |

Those values come from end-of-trace RAM reconstruction. The added page-`83` range
`577E-5790` is exactly the bytes between the old and new `lastEntryPTR` values. [confirmed]

## Restoring after page `83`

Restore the selector for every window you changed. For code entered from normal TI-OS
state that temporarily maps page `83` into bank B (`8000-BFFF`) and page `82` into
bank C (`C000-FFFF`), restore the two RAM windows this way:

```z80
    LD A,0x81
    OUT (7),A        ; 8000-BFFF back to RAM page 81
    XOR A
    OUT (5),A        ; C000-FFFF back to RAM page 80
```

For code that maps page `83` into bank A (`4000-7FFF`), preserve and restore port `6`:

```z80
    IN A,(6)
    PUSH AF

    LD A,0x83
    OUT (6),A        ; map RAM page 83 at 4000-7FFF
    ; use 4000-7FFF here

    POP AF
    OUT (6),A        ; restore previous Flash/RAM page selector
```

Keep the nonstandard mapping inside a short critical section. The OS helper preserves
interrupt state around the temporary RAM-page mapping so the interrupt handler does not
run with bank A or bank B pointing at page `83`.

For code that may be called with nonstandard paging, preserve and restore the selectors
for all touched windows:

```z80
    IN A,(6)
    PUSH AF
    IN A,(7)
    PUSH AF
    IN A,(5)
    PUSH AF

    LD A,0x83
    OUT (7),A        ; map RAM page 83 at 8000-BFFF
    ; use 8000-BFFF here

    POP AF
    OUT (5),A
    POP AF
    OUT (7),A
    POP AF
    OUT (6),A
```

The OS's own paged byte-store helper at `37:44AE` uses the normal restore pattern:

```z80
37:44D0  OUT (5),A        ; A = page index << 1, trace case A = 0x02 (→ RAM page 82)
37:44D2  INC A            ; A = 03
37:44D3  OR 0x80          ; A = 0x83
37:44D5  OUT (7),A        ; trace case: 0x83
37:44D7  LD A,B
37:44D8  LD (DE),A        ; byte store while RAM page 83 is visible
37:44D9  LD A,0x81
37:44DB  OUT (7),A
37:44DD  XOR A
37:44DE  OUT (5),A
```

The dynamic trace resolves the same sequence at instruction indices `712241-712250`,
including the final `port 7 = 81` and `port 5 = 00` writes. [confirmed]

## Sources

| Source | Use here |
|--------|----------|
| [Datamath TI-84 Plus hardware](http://www.datamath.org/Graphing/TI-84PLUS.htm) and [March 2004 board photographs](http://www.datamath.org/Graphing/JPEG_TI-84PLUS_A.htm#PCB) | Three-IC board inventory, ASIC-integrated RAM, and photographed `83PLUSB/TA2` package |
| [WikiTI hardware history, revision 10880](https://wikiti.brandonw.net/index.php?title=83Plus:History_of_TI-8x_hardware&oldid=10880) | Reported 128 KiB design and later 48 KiB revision |
| [WikiTI RAM pages, revision 11670](https://wikiti.brandonw.net/index.php?title=83Plus:OS:Ram_Pages&oldid=11670) | Reported selector uses and `82`–`87` alias threshold |
| [TilEm `x4_io.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_io.c) and [`x4_memory.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_memory.c) | Independent-page emulator mapping |
| [Wabbitemu `core.c`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/core/core.c) and [`83psehw.c`](https://github.com/sputt/wabbitemu/blob/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422/hardware/83psehw.c) | Optional reduced-RAM alias and model identity behavior |
| [MAME 0.287 `ti85.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85.cpp) and [`ti85_m.cpp`](https://github.com/mamedev/mame/blob/mame0287/src/mame/ti/ti85_m.cpp) | Seven-block backing and raw-selector behavior |
