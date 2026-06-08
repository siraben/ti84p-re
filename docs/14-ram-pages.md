# 14 — RAM pages

The TI-84 Plus has banked RAM pages behind the Z80's 16 KiB windows. TI-OS normally
keeps RAM page `81` in `8000-BFFF` and RAM page `80` in `C000-FFFF`, but ROM helpers
temporarily map other pages for paged memory access. On OS 2.55MP, traces show page
`83` writes during boot/home initialization and during homescreen expression entry.
Programs that borrow page `83` must preserve or restore the OS-visible regions below.

## Page selectors [confirmed]

The 84+ memory ports use two encodings:

| Window | Port | Selector encoding | Normal TI-OS value |
|--------|------|-------------------|--------------------|
| `4000-7FFF` | `6` | bit 7 clear selects Flash page `value & 0x3F`; bit 7 set selects RAM page `0x80 \| (value & 7)` | banked Flash page |
| `8000-BFFF` | `7` | bit 7 clear selects Flash page `value & 0x3F`; bit 7 set selects RAM page `0x80 \| (value & 7)` | `81` |
| `C000-FFFF` | `5` | low three bits select RAM page `0x80 \| (value & 7)` | `00` → RAM page `80` |

This rule matches the dynamic resolver, TilEm's `x4` memory mapper, and the OS
trace. In the idle boot/home trace, the RAM-window writes are:

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

The final restore values are therefore `port 7 = 0x81` and `port 5 = 0x00` for
normal OS execution.

## Page map [standard, cross-checked]

WikiTI's [RAM pages](https://wikiti.brandonw.net/index.php?title=83Plus:OS:Ram_Pages)
page is a useful public map, but OS 2.55MP needs the page-`83` warnings to be read
literally. The local dump at `wikiti-dump/main/83Plus:OS:Ram Pages.wiki` carries
the same current page-`83` notes. The local trace and disassembly support this table:

| RAM page | Use |
|----------|-----|
| `80` | Normal `C000-FFFF` RAM page. The boot/home trace restores this with `OUT (5),0`. WikiTI marks it execution-protected. |
| `81` | Normal `8000-BFFF` RAM page. This contains the visible TI-OS RAM variables, OP registers, flags, graph buffers, user heap, and VAT window documented in `tools/ram.txt` and `ti83plus.inc`. |
| `82` | Not a general OS work page under normal execution. The idle trace maps it briefly through port `5` as part of a paged RAM helper, then restores page `80`. WikiTI marks it execution-protected. |
| `83` | Shared OS scratch/state page. OS 2.55MP maps it through port `6` for block copies and LCD capture, and through port `7` for a paged byte-store helper. Homescreen expression entry writes the previous-entry buffer at `577E`. |
| `84` | Not used by TI-OS under typical execution; WikiTI marks it execution-protected. |
| `85` | Not used by TI-OS under typical execution on full-RAM hardware. |
| `86` | Not used by TI-OS under typical execution; WikiTI marks it execution-protected. |
| `87` | Not used by TI-OS under typical execution on full-RAM hardware. |

On newer 48 KiB hardware, WikiTI says RAM pages `82-87` alias the same physical memory.
WikiTI's [port `15`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:15) page
identifies ASIC value `55h` as the 48 KiB TA1 ASIC. Programs that use page `83` must not
treat `82-87` as independent storage on that hardware. [standard]

## Per-page trace coverage [confirmed]

The boot/home and `2+3 ENTER` traces exercise startup, homescreen initialization,
display capture, parsing, evaluation, and previous-entry storage. They do not exercise
app launch, USB transfer, graph drawing, archive cleanup, or a 48 KiB ASIC. Within
that scope, physical RAM-page writes are:

| RAM page | Idle trace writes | `2+3 ENTER` trace writes | Interpretation |
|----------|-------------------|--------------------------|----------------|
| `80` | `256227` writes, all page addresses touched | `345702` writes, all page addresses touched | Normal high RAM page selected by port `5`; contains stack/system/user RAM activity in the `C000-FFFF` window. |
| `81` | `62947` writes, all page addresses touched | `72638` writes, all page addresses touched | Normal `8000-BFFF` RAM page; contains the documented OS variables, flags, OP registers, heap, VAT window, and working buffers. |
| `82` | no writes observed | no writes observed | Port `5` briefly selects raw value `02`, but the observed store is through page `83` in bank B. No page-`82` storage is confirmed by these traces. |
| `83` | `1882` writes to `43D9-44BD` and `5A7E-5DF2` | `3467` writes to `4373-4390`, `43D9-44BD`, `577E-5790`, and `5A7E-5DF2` | Shared OS scratch/state page. See the range table below. |
| `84` | no writes observed | no writes observed | No typical-use OS storage confirmed in these traces. |
| `85` | no writes observed | no writes observed | No typical-use OS storage confirmed in these traces. |
| `86` | no writes observed | no writes observed | No typical-use OS storage confirmed in these traces. |
| `87` | no writes observed | no writes observed | No typical-use OS storage confirmed in these traces. |

The zero-write rows mean "not hit by these scenarios," not a global proof that the
page is never used. On 48 KiB hardware, pages `82-87` alias page `83`, so writes
intended for `84-87` would not be independent storage even if a program can select
those page numbers. [standard]

The graph scenario in `tools/macros/graph-y1-x2.macro` reaches the graph screen and
still only writes pages `80`, `81`, and `83`. It increases normal page-`80`/`81`
activity but leaves page-`83` at the same confirmed ranges as the idle trace.
It does not hit pages `82` or `84-87`. [confirmed]

## How to hit the confirmed paths

The useful distinction is between "page number can be selected" and "the OS uses it
in a normal workflow." These paths are confirmed or have a concrete next scenario:

| Page/path | How to hit it | Evidence |
|-----------|---------------|----------|
| `80` high RAM | Run any cold-boot, home, expression, or graph trace. | Port `5 = 00` is the normal restore value; every current trace writes all page-`80` addresses. [confirmed] |
| `81` normal bank-B RAM | Run any cold-boot, home, expression, or graph trace. | Port `7 = 81` is the normal restore value; every current trace writes all page-`81` addresses. [confirmed] |
| `83` display capture | Run `boot-idle.macro` or `graph-y1-x2.macro`. | Ghidra shows `_SaveDisp` (`39:5DD8`) calls `lcd_read_block` (`ram:1890`) at the `39:5E03` call site; coverage hits both, and writes `5A7E-5D7D`. [confirmed] |
| `83` homescreen previous-entry history | Run `home-2plus3.macro`. | The trace adds `577E-5790`, advances `lastEntryPTR` from `577E` to `5791`, and sets `numLastEntries` to `01`. [confirmed] |
| `83` expression scratch copy | Run `home-2plus3.macro`. | The trace adds `4373-4390` through `flash_copy_block` at `ram:1868`/`ram:187C`. [confirmed] |
| `83` split-screen/table copy | Enter a split-screen/table workflow that calls `_ScreenSplit`. | Ghidra shows `_ScreenSplit` at `05:7712` calls `flash_copy_block` at `05:772A`; this path is not hit by the current macros. [confirmed] |
| `83` edit-buffer initialization | Enter an edit-buffer workflow that reaches `editbuf_init_buf`. | Ghidra shows `editbuf_init_buf` at `03:6BC4` calls `flash_copy_block` at `03:6BCD`; this path is not hit by the current macros. [confirmed] |
| `83` app-menu state restore | Open an app/menu workflow that reaches `mnu_restore_app_state`. | Ghidra shows `mnu_restore_app_state` at `39:6D96` calls `flash_copy_block` at `39:6DA0`; this path is not hit by the current macros. [confirmed] |
| `84-87` independent pages | Use a forced RAM-page probe or a ROM path that passes pair index `2` or `3` to the computed bank-pair helper. | The ROM can compute these selectors, but raw immediate selector scans and current traces do not show a normal OS path selecting or writing them. [hypothesis] |

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
`port 5 = 02`, `port 7 = 83` sequence. Pages `84–87` are reachable through the
helper but are not selected on any observed OS path [hypothesis]. The `B = 1`
caller pattern is confirmed for the decoded callers above. [confirmed]

## Page `83` use [confirmed and standard]

Page `83` is the page people most often borrow as scratch, but the ROM uses it as
more than anonymous free RAM. Keep the evidence classes separate:

| Range | Use | Evidence |
|-------|-----|----------|
| `4373-4390` | Expression-path page-`83` scratch copy | Added by the `2+3 ENTER` trace. The block write is the `LDIR` at `ram:187E` in the page-`83` copy helper (page `83` mapped via `OUT (6),A` at `ram:187C`); the caller is still unlabeled. [confirmed] |
| `43D9-44BD` | Boot/home page-`83` scratch copy | Present in the idle trace. The block write is the `LDIR` at `ram:187E` in the page-`83` copy helper (page `83` mapped via `OUT (6),A` at `ram:187C`), plus one byte stored at `37:44D8`. [confirmed] |
| `577E-5A7D` | Homescreen previous-entry history | Page `33` references `577E`, the `5A7E` upper bound, `lastEntryPTR` (`0x8DA7`), and `numLastEntries` (`0x8E29`). The `2+3 ENTER` trace writes `577E-5790`, advances `lastEntryPTR` to `5791`, and sets `numLastEntries` to `01`. [confirmed] |
| `5A7E-5DF2` | LCD/home display capture area | Present in the idle trace. The `_SaveDisp` LCD capture (`ram:1890`) fills the first `0x300` bytes, `5A7E-5D7D` (the 96×64 framebuffer); the `5D7E-5DF2` tail is additional page-`83` writes in the same scenario. Ghidra decompiles `ram:1890` as an LCD-read helper that maps page `83` through port `6` and stores bytes read from LCD port `11`. [confirmed] |
| `4000-4080` | App base-page staging before app execution | WikiTI public note; the two traces on this page do not launch an app. [standard, not traced here] |
| `4100-433A` | USB communication buffers | WikiTI public note; the two traces on this page do not exercise USB transfer. [standard, not traced here] |

Ghidra identifies the page-`83` block-copy helper at `ram:1868`. It saves the current
port-`6` value, writes `0x83` to port `6`, runs `LDIR`, and restores the previous page
through the page-set helper:

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
the OS-visible previous-entry count. [standard, address confirmed]

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
`577E-5790` is exactly the bytes between the old and new `lastEntryPTR` values.
[confirmed]

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
