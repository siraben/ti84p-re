# LCD controller and display bus

*TI-84 Plus OS 2.55MP — Controller commands, video RAM, bus timing, initialization, blits, reads, contrast, and emulator fidelity.*

The TI-84 Plus drives a 96×64 monochrome panel through an external LCD controller on ports `0x10` and `0x11`. This page separates the visible panel from controller video RAM, reconstructs the OS command and transfer paths, traces initialization and clearing, and identifies behavior that varies across Toshiba and Novatek controller revisions.

## Evidence layers

The local ROM establishes what OS 2.55MP sends to the controller. Public hardware tests establish controller behavior that the ROM does not expose, while TilEm supplies an executable model whose choices are identified separately.

| Layer | Main evidence | What it establishes |
|-------|---------------|---------------------|
| TI-OS page 0 | `ram:0CC3`–`ram:0CEA`, `ram:1890`–`ram:18D1`, and `ram:20BF`–`ram:20CD` | ASIC-side wait, block reads/writes, and movement commands [confirmed] |
| TI-OS display code | `01:5A59`–`01:5B4B`, `01:60E4`–`01:612D`, and `01:6934`–`01:6955` | byte I/O, text drawing, and full-screen clearing [confirmed] |
| TI-OS graph code | `04:6071`–`04:620A` | graph-buffer clear and LCD transfer loops [confirmed] |
| TI-OS initialization | `_LCD_DRIVERON` at `06:4D02`–`06:4D3A` | mode, enable, power, and contrast command sequence [confirmed] |
| Dynamic execution | resolved `home-2plus3` trace filtered to ports `0x10`–`0x13` and `0x2F` | exact initialization and clear transactions in TilEm [confirmed] |
| Toshiba T6A04A datasheet | controller block diagram, command table, and timing specification | 120×64 display RAM, 80-series bus, counters, read latch, busy formula, and analog-drive controls [standard] |
| Public hardware notes | WikiTI ports `0x02`, `0x10`–`0x13`, and `0x2F` | status bits, command meanings, controller variants, transfer timing, and hardware quirks [standard] |
| Emulator model | Upstream TilEm `lcd.c`, `x4_io.c`, and `x4_init.c` at commit `f56ad63` | implemented video RAM, latches, delays, aliases, and fidelity limits [standard] |

## Panel, controller, and video RAM

The panel exposes 96 horizontal pixels and 64 vertical pixels. In 8-bit transfer mode, one controller byte holds eight adjacent horizontal pixels, so the visible row occupies 12 bytes. The visible image therefore contains:

$$
12 \times 64 = 768\text{ bytes}
$$

The controller can contain more video RAM than the panel displays. WikiTI reports 15 bytes per row, or 120 pixels, for T6A04/T6A04A controllers and 16 bytes per row, or 128 pixels, for T6K04 controllers. Later Novatek replacements may omit the off-screen area. [standard]

The local ROM uses only visible columns `0`–`11` in its full-screen clear and graph blit loops. It therefore does not identify which controller is fitted to a particular calculator. [confirmed]

### Coordinate vocabulary

Toshiba documentation names the pixel row *X* and the byte column *Y*. Software often uses the opposite convention. This page uses *row* for `0`–`63` vertically and *byte column* for the horizontal group selected by commands `0x20`–`0x3F`.

| Quantity | Command or transfer | Visible range |
|----------|---------------------|--------------:|
| Row | command `0x80 + row` | `0x80`–`0xBF` |
| Byte column | command `0x20 + column` | `0x20`–`0x2B` |
| Pixel within a byte | data bit 7 through bit 0 | left to right [standard] |
| Visible storage | 12 byte columns × 64 rows | 768 bytes |

The Z-address command `0x40 + shift` changes which controller row appears at the top of the panel. It does not copy video RAM. Rows wrap modulo 64 when displayed. [standard]

## Port interface

| Port | Direction | Role |
|-----:|-----------|------|
| `0x10` | read | controller status |
| `0x10` | write | controller command |
| `0x11` | read/write | latched video-RAM data at the current address |
| `0x12` | read/write | second-chip-select mirror of `0x10` on documented ASIC revisions [standard] |
| `0x13` | read/write | second-chip-select mirror of `0x11` on documented ASIC revisions [standard] |
| `0x02` bit 1 | read | ASIC LCD-wait timer ready at high CPU speed |
| `0x2F` | read/write | duration selector for the ASIC LCD-wait timer |

The OS paths decoded here use `0x10` and `0x11`. The resolved calculator trace contains no port-`0x12` or port-`0x13` LCD transaction. [confirmed] for the trace; [standard] for the physical mirrors.

### Controller-side signals

The T6A04A reference controller exposes an 8-bit `DB0`–`DB7` bus for an 80-series processor. Its `D/I` input distinguishes command bytes from display-data bytes, `/WR` selects reading or writing, and `/CE` strobes the transfer. `/RST` resets the controller and `/STB` stops its oscillator and analog drive. The calculator ASIC turns port instructions into these controller-side operations, so Z80 code does not toggle the individual signals. [standard]

The reference chip includes 120 column outputs, 64 row outputs, display RAM, an oscillator, contrast control, a DC–DC converter, and LCD-bias amplifiers. Replacement controllers can expose compatible port behavior without reproducing every internal analog block or off-screen RAM cell. [standard]

### Status read

Reading port `0x10` returns the controller state: [standard]

| Bit | Meaning |
|----:|---------|
| 0 | increment direction when set; decrement when clear |
| 1 | movement affects the byte column when set; row when clear |
| 4 | controller reset state |
| 5 | display enabled |
| 6 | 8-bit transfer mode when set; 6-bit mode when clear |
| 7 | controller busy on controllers that implement a reliable busy flag |

Late replacement controllers can move the internal video-RAM pointer when software reads status. Busy-poll loops that work on Toshiba controllers can therefore corrupt addressing on those units. WikiTI recommends a fixed delay or the ASIC delay mechanism for cross-revision code. [standard]

OS 2.55MP avoids this incompatibility in its common path: `lcd_wait` at `ram:0CC3` reads port `0x02`, not port `0x10`. [confirmed]

## Command set

The table separates public controller behavior from the subset used by this ROM.

| Command | Meaning | OS 2.55MP use |
|---------|---------|---------------|
| `0x00` | select 6-bit transfers | used by some text read/modify/write paths at `01:5AD3` [confirmed] |
| `0x01` | select 8-bit transfers | `_LCD_DRIVERON` and `_PutMap` [confirmed] |
| `0x02` | disable display output while retaining video RAM | `lcd_disable` at `ram:0CD9`; `_PowerOff` calls it [confirmed] |
| `0x03` | enable display output | `_LCD_DRIVERON` [confirmed] |
| `0x04` | decrement row after each data transfer | documented controller mode [standard] |
| `0x05` | increment row after each data transfer | OS vertical byte loops [confirmed] |
| `0x06` | decrement byte column after each data transfer | documented controller mode [standard] |
| `0x07` | increment byte column after each data transfer | OS horizontal row blits [confirmed] |
| `0x08`–`0x0B` | power-supply enhancement | `_LCD_DRIVERON` selects `0x08` or `0x0B` [confirmed]; analog effect is controller-specific [standard] |
| `0x0C`–`0x0F` | mirroring controls on newer controllers | not decoded in the local OS path [standard] |
| `0x10`–`0x17` | power-supply level | `_LCD_DRIVERON` selects `0x16` or `0x17` [confirmed]; analog effect is controller-specific [standard] |
| `0x18` | leave controller test mode | documented hardware command [standard] |
| `0x1C`–`0x1F` | enter high-drive test modes | hardware tests report possible panel damage; the OS path does not use them [standard] |
| `0x20`–`0x3F` | set byte column | visible OS range `0x20`–`0x2B` [confirmed] |
| `0x40`–`0x7F` | set displayed top-row offset | `_LCD_DRIVERON` writes `0x40` [confirmed] |
| `0x80`–`0xBF` | set row | full 64-row range [confirmed] |
| `0xC0`–`0xFF` | set controller contrast `0`–`63` | `_LCD_DRIVERON` derives the command from `contrast` [confirmed] |

The power and test commands affect analog drive circuitry and vary across controller revisions. TilEm ignores them except for display enable, display disable, and contrast. [standard]

## Data transfers and address movement

Port `0x11` transfers one unit at the current row and byte column, then applies command `0x04`, `0x05`, `0x06`, or `0x07`. [standard]

In 8-bit mode, all eight data bits map to adjacent pixels. In 6-bit mode, only bits 0–5 are significant and the controller packs six-pixel groups. The OS initializes 8-bit mode for ordinary full-screen work but temporarily selects 6-bit mode in large-font edge handling at `01:5AD3`. [confirmed]

### Read latch and dummy reads

Controller reads are one transfer behind the addressed video-RAM byte. After a row or column command, the first port-`0x11` read returns the old output latch; the read loads the newly addressed byte into that latch. Software must discard one dummy read and use the second. Auto-increment or auto-decrement does not require another dummy read between sequential bytes. [standard]

`lcd_read_data` at `01:5A60` performs exactly two reads: [confirmed]

```z80
01:5A60  call ram:0CC3
01:5A63  in a,(0x11)       ; discard stale output latch
01:5A65  call ram:0CC3
01:5A68  in a,(0x11)       ; addressed byte
```

The routine then restores an OS-tracked row command from `0x8451` and selects row-increment mode. `lcd_write_data` at `01:5A59` is the matching wait plus `OUT (0x11),A`. These routines transfer arbitrary pixel data; neither routine sets or reads contrast. [confirmed]

### Bounds and wrap behavior

Public tests report that a Toshiba controller accepts column commands across `0x20`–`0x3F`, but transfers outside the implemented video-RAM width do not change RAM. Auto-movement wraps at the controller-specific last implemented column when the pointer began in range; a pointer explicitly placed beyond that range can continue through the five-bit command field before returning to zero. [standard]

The row coordinate wraps across 64 rows. The controller-specific byte-column width is one reason software should not use off-screen RAM as portable storage. [standard]

## ASIC-side wait timing

At high CPU speed, each access to ports `0x10`–`0x13` clears port-`0x02` bit 1 for a programmable interval. Port `0x2F` selects that interval in nominal 64-T-state steps with values 48, 112, 176, 240, 304, 368, 432, or 496 T-states. CPU-speed value `1` uses bits 0–1; value `2` uses bits 2–4; value `3` uses bits 5–7. CPU-speed value `0` leaves port-`0x02` bit 1 set. [standard]

The retail boot page writes `0x4B` to port `0x2F` at `3F:41D3`. With the OS's normal CPU-speed value `1`, the low field is `3`, selecting 240 T-states. At nominal 15 MHz this interval is 16 µs. [confirmed] for the writes and trace; [standard] for the hardware timer interpretation.

The T6A04A datasheet specifies its internal busy interval as $2/f_{OSC} \leq T \leq 4/f_{OSC}$. It lists oscillator choices from about 26.88 kHz to 430.1 kHz, depending on external components and frequency-select pins. The ROM and emulator trace do not reveal the fitted controller's oscillator network, so the 16 µs ASIC wait cannot by itself identify the controller clock or its worst-case margin. [standard] for the formula and available oscillator settings; [hypothesis] for the unresolved board-specific margin.

`lcd_wait` preserves `AF` and spins on that ASIC-ready bit: [confirmed]

```z80
ram:0CC3  push af
ram:0CC4  in a,(0x02)
ram:0CC6  and 0x02
ram:0CC8  jr z,ram:0CC4
ram:0CCA  bit 3,(iy+0x41)
ram:0CCE  call nz,ram:0CE6
ram:0CD1  call nz,ram:0CE6
ram:0CD4  call nz,ram:0CE6
ram:0CD7  pop af
ram:0CD8  ret
```

The three optional calls add fixed instruction delay when the OS flag at `IY+0x41` bit 3 is set. That byte is shared with USB state in the published equates; the local code establishes the delay effect but does not establish an LCD-specific public name for the flag. [confirmed]

`lcd_write_command_a` at `ram:0CDB` repeats the port-`0x02` wait and writes `A` to port `0x10`. `lcd_disable` at `ram:0CD9` loads command `0x02` and enters that helper. [confirmed]

## Controller initialization

`_LCD_DRIVERON = 4978` has body `06:4D02`. It sends every command through `lcd_write_command` at `06:4D35`, which calls `lcd_wait` before writing port `0x10`. [confirmed]

| Order | Command | Effect |
|------:|--------:|--------|
| 1 | `0x40` | top displayed row = controller row 0 |
| 2 | `0x05` | increment row after data transfers |
| 3 | `0x01` | select 8-bit transfer mode |
| 4 | `0x03` | enable display output |
| 5 | `0x16` or `0x17` | select power-supply level |
| 6 | `0x08` or `0x0B` | select power-supply enhancement |
| 7 | `0xC0 OR (contrast + 0x18)` | program contrast |

Calls to the hardware test at `ram:1837` choose between the two power values. In the resolved TI-84 Plus TilEm trace, the sequence is:

```text
40 05 01 03 17 0B EF
```

The final `0xEF` means controller contrast `0x2F`. The RAM byte `contrast` at `0x8447` was `0x17`, and `_LCD_DRIVERON` added `0x18`. [confirmed]

The trace records this sequence twice during cold startup before the homescreen clear. This is OS behavior under the traced startup path, not a requirement that user code initialize the controller twice. [confirmed]

## Full-screen clear

`_ClrLCDFull = 4540` has body `01:60E4`. It temporarily clears the run-indicator flag, then invokes `_ClearRow` at `01:6934` for row bases `0xB8`, `0xB0`, …, `0x80`. Each call clears an eight-row band. [confirmed]

For each byte column `0x20`–`0x2B`, `_ClearRow` performs: [confirmed]

1. send command `0x07` through `lcd_mode_column_increment`;
2. restore the band-base row command;
3. send command `0x05` through `lcd_mode_row_increment`;
4. select the current byte column;
5. write eight zero bytes while the row auto-increments;
6. advance to the next byte column.

The arithmetic covers every visible byte exactly once:

$$
8\text{ bands} \times 12\text{ columns} \times 8\text{ rows}
= 768\text{ writes}
$$

The resolved trace shows the first band as row command `0xB8`, column commands `0x20` through `0x2B`, and eight zero data writes after every column command. The next band begins at `0xB0`; the final band begins at `0x80`. [confirmed]

## Graph-buffer transfer

`plotSScreen` at `0x9340` is the 768-byte row-major graph buffer. `_GrBufClr` at `04:6071` clears it with one zero store followed by `LDIR` of `0x02FF` bytes; it does not access the LCD. [confirmed]

`_GrBufCpy` at `04:60A3` enters the controller-transfer core at `04:6176`. The TI-84 Plus direct-RAM path performs these operations for each selected pixel row: [confirmed]

- command `0x07` selects byte-column auto-increment;
- a command in `0x80`–`0xBF` selects the row;
- command `0x20` selects visible byte column 0;
- 12 sequential data writes copy one row from the RAM buffer;
- the source pointer and row command advance.

The caller adjusts the starting row and row count for full-screen and split-screen states. The controller loop therefore treats the transfer extent as state, while the row width remains 12 bytes. [confirmed]

The alternative path calls `lcd_write_block` at `ram:18B1` when the source lives in banked RAM. That helper temporarily maps RAM page `0x83` through port `0x06`, writes `B` bytes to port `0x11`, restores the prior mapping, and restores the caller's interrupt-enable state. [confirmed]

## Text drawing and read-modify-write

Homescreen text does not render through `plotSScreen`. `_PutMap` at `01:5A98` loads an eight-byte large-font record and writes the controller directly. It selects row and byte-column commands from `curRow` and `curCol`, then emits the glyph through port `0x11`. [confirmed]

When a glyph overlaps an existing byte boundary, `_PutMap` reads controller RAM, combines glyph bits with the retained pixels, and writes the result back. The read helpers at `01:5A70` and `01:5A7A` perform the required dummy plus real reads before restoring the row and movement mode. [confirmed]

This creates two independent software representations:

| State | Address | Role |
|-------|---------|------|
| Controller video RAM | external LCD controller | currently scanned panel image |
| `plotSScreen` | `0x9340`–`0x963F` | graph/back buffer; copied explicitly |
| `saveSScreen` | `0x86EC`–`0x89EB` | saved 768-byte display image |
| `textShadow` | `0x8508`–`0x8587` | 16×8 homescreen character shadow |
| `lFont_record` | `0x845A`–`0x8461` | current eight-byte large-font render record |

Changing one RAM buffer does not update the panel until a routine copies or renders it. Direct text writes can likewise change controller RAM without changing `plotSScreen`. [confirmed]

## Screen reads and saved displays

`lcd_read_block` at `ram:1890` reads `B` bytes from port `0x11` into banked RAM. It temporarily maps RAM page `0x83`, preserves the previous port-`0x06` value, and restores the caller's interrupt state. The caller must establish the controller address and consume any required dummy read before a sequential block. [confirmed]

`_SaveDisp` at `39:5DD8` uses this helper to capture controller video RAM into the saved-display RAM page. Dynamic RAM-page traces record writes across the 768-byte capture extent. `_RestoreDisp` later copies the saved image back through the display paths. [confirmed]

## Contrast and power-off

The OS stores its user-facing contrast level at `0x8447`. `_LCD_DRIVERON` adds `0x18`, forces command bits `0xC0`, and sends the result. Code that writes a raw controller contrast command without updating `0x8447` can cause the next OS contrast adjustment or driver initialization to jump to a different level. [confirmed] for OS state; [standard] for direct-hardware callers.

Display-disable command `0x02` blanks the panel but leaves controller video RAM available. The ASIC's low-power transition is separate. `_PowerOff` calls `lcd_disable` at `ram:0CD9`, performs OS cleanup, then uses port `0x03` plus `HALT` to enter low power. See [Clock, timers, and power](clock-timers-power.md). [confirmed]

## Dynamic I/O trace

The trace resolver can print decoded I/O instructions after resolving every banked program counter:

```sh
nix develop -c python tools/tilem_trace_resolve.py \
  /tmp/tilem-validation-home2plus3.trace \
  --initial-mapping ti84p-reset --names tools/names.txt \
  --io-ports 10-13,2f --io-count 360
```

The trace captures three load-bearing sequences: [confirmed]

- boot writes `0x4B` to port `0x2F` at `3F:41D3`;
- `_LCD_DRIVERON` writes `40 05 01 03 17 0B EF` at `06:4D38`;
- `_ClrLCDFull` writes the eight-band, 12-column, eight-byte clear pattern through `01:5A95`, `01:6945`, and `01:694B`.

The trace is an emulator execution record. It proves the ROM path and values but does not prove analog power behavior, physical busy duration, or controller-revision quirks.

## TilEm behavior and fidelity gaps

TilEm models the controller and the ASIC wait timer as separate mechanisms. [standard]

| Area | TilEm behavior | Fidelity consequence |
|------|----------------|----------------------|
| Video RAM | fixed 1,024-byte array, 16 bytes × 64 rows | models a 128-pixel-wide controller, not 120-pixel or no-extra-RAM variants |
| Ports `0x12`/`0x13` | aliases command/status and data | models the documented second-chip-select mirrors |
| Controller busy | 50 emulated cycles after an accepted access | direct too-fast accesses are ignored when delay emulation is enabled |
| ASIC wait | port-`0x02` bit 1 remains clear for the port-`0x2F` interval | reproduces the OS wait loop independently of controller busy |
| I/O overhead | adds five emulated CPU cycles per LCD-port access | emulator policy, not a physical bus measurement |
| Read latch | returns `nextbyte`, then loads the addressed byte | reproduces the dummy-read requirement |
| 6-bit mode | packs six-pixel writes into the internal byte array | supports OS edge-rendering paths |
| Z address | displays `(row + shift) mod 64` | reproduces vertical display rotation |
| Power/test/mirror commands | mostly ignored | does not model analog drive, blue test modes, or newer-controller mirroring |
| Status-read pointer quirk | not modeled | cannot reproduce late Novatek corruption from busy polling |
| Out-of-range columns | wraps against the fixed 16-byte stride before transfer | differs from documented behavior on narrower controllers |
| Low power | frame output blanks when the LCD is inactive or the halted ASIC powers down | approximates visible power state rather than electrical retention |

TilEm reset initializes controller contrast to 32, 8-bit mode, byte-column increment, row and column zero, and display disabled. OS initialization then replaces those values. [standard]

## Resolved findings and open hardware questions

- [confirmed] OS 2.55MP waits through port-`0x02` bit 1 and does not busy-poll port `0x10` in `lcd_wait`.
- [confirmed] `01:5A59` and `01:5A60` write and read pixel data; they are not contrast helpers.
- [confirmed] `_LCD_DRIVERON` emits `0x40`, `0x05`, `0x01`, `0x03`, hardware-dependent power commands, and a RAM-derived contrast command.
- [confirmed] `_ClrLCDFull` covers all 768 visible bytes with eight vertical bands.
- [confirmed] `_GrBufClr` changes only RAM, while `_GrBufCpy` performs the controller transfer.
- [confirmed] `_PowerOff` disables display output before the ASIC enters low power.
- [hypothesis] The exact controller family and off-screen RAM width cannot be inferred from this OS image; they must be measured per calculator.
- [hypothesis] The late-controller status-read pointer mutation, power-command analog effects, and off-screen retention need physical tests across TA2/TA3 board revisions.
- [hypothesis] TilEm's five-cycle LCD I/O overhead and 50-cycle controller busy period should be compared with bus captures rather than treated as hardware constants.

## Sources

| Source | Used for |
|--------|----------|
| [WikiTI port `0x02`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:02) | ASIC LCD-ready bit and high-speed behavior |
| [WikiTI port `0x10`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:10) | status bits, commands, addressing, controller variants, busy-poll incompatibility, and power/test cautions |
| [WikiTI port `0x11`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:11) | pixel data, output latch, dummy reads, 6-bit transfers, and transfer delay |
| [WikiTI ports `0x12`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:12) and [`0x13`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:13) | second-chip-select mirrors |
| [WikiTI port `0x2F`](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:2F) | ASIC wait-duration fields and defaults |
| [Toshiba T6A04A datasheet](https://archive.org/details/t6a04a-datasheet) | controller pins and blocks, 120×64 RAM, commands, counters, dummy reads, and busy timing |
| [TilEm `lcd.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/lcd.c), [`x4_io.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_io.c), and [`x4_init.c`](https://github.com/debrouxl/tilem/blob/f56ad637d0524ee841dd381be6ecbaf5b8975600/emu/x4/x4_init.c) | emulator video RAM, command decode, latches, port aliases, wait timers, and reset state |
