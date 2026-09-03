# Flash emulator comparison

*TI-84 Plus OS 2.55MP — pinned TilEm, Wabbitemu, MAME, and jsTIfied Flash behavior beside the ROM.*

The four inspected emulators agree on the command bytes and top-boot sector
boundaries used by the ROM. They differ at the points most useful for negative
tests: illegal bit transitions, completion timing, status reads, and ASIC
access control. [standard]

| Behavior | TilEm `f56ad63` | Wabbitemu `48c2dc0` | MAME 0.287 | jsTIfied `20170706a` |
|----------|-----------------|------------------------|------------|-----------------------|
| Unlock addresses | low 12 bits `0xAAA`, `0x555` | low 12 bits `0xAAA`, `0x555` | accepts several AMD address conventions, including the ROM's low-12-bit form | low 12 bits `0xAAA`, `0x555` |
| Byte mutation | `old &= requested` | `old &= requested` | `old = requested` | `old &= requested` |
| Successful program | 7 µs real-time timer; 42 clocks at the 6 MHz reset speed | immediate array data | immediate array data | immediate array data |
| Illegal `0→1` request | error state | one transient error read | writes the requested one bit | leaves the zero bit unchanged without an error state |
| Sector erase | 50 µs command window, then 200 ms erase timer; 300 and 1,200,000 clocks at 6 MHz | immediate | immediate data mutation followed by a timer | immediate; protected sector-table entries are skipped |
| Autoselect | incomplete | modeled AMD manufacturer `0x01`, device `0xDA` | IDs at offsets `0`/`1`; no compatible protection read | manufacturer `0xC2` and device `0xDA`; each recognized read exits ID mode |
| Chip erase | writable sectors only; final status follows the last sector | immediate full-array fill, including boot | immediate full-array fill; stale/default busy range | immediate erase of unprotected sector-table entries |
| Fast program | command flow present; fidelity unresolved | implemented for TI-84 Plus Flash version 3 | entry accepted, but `A0` excludes the AMD maker ID | absent |
| Erase suspend/resume | absent | absent | absent | absent |
| CFI query | absent | absent | absent for `AMD_29F800T` | absent |
| Sector-protection autoselect read | unavailable with missing autoselect | offset `4` always returns zero | no data-sheet-compatible protection read | absent |
| ASIC write gate | protected-byte sequence, lock, and sector groups | privileged-page port-`0x14` gate and boot-page flags | no effective Flash-write gate | protected-byte port-`0x14` gate; sector flag affects erase but not program |

The table combines source results with guarded runtime checks described below.
MAME marks the complete TI-84 Plus driver `MACHINE_NOT_WORKING`. None of the
divergences resolves physical behavior. [standard] for the source models;
[confirmed] for the pinned runtime observations.

The emulator autoselect rows differ from the photographed Fujitsu part's data
sheet, which specifies `0x04/0xDA`. Matching device code `0xDA` establishes a
compatible top-boot command family; manufacturer `0x01` does not identify the
photographed package. [standard]

## TilEm behavior and limits

TilEm implements the same command progression used by the ROM: `AA`, `55`, then `A0` for program, or `80`, `AA`, `55`, `30` for sector erase. It matches command addresses by physical low 12 bits `0xAAA` and `0x555`. [standard]

Its program operation computes `stored_byte &= requested_byte`. A requested
`0→1` transition leaves the zero bit unchanged and enters the emulator's error
state. During program busy, DQ7 is complemented and DQ6 toggles. The delay
argument is 7 µs, not seven CPU cycles. TilEm's real-time scheduler converts it
to 42 clocks at the 6 MHz reset speed. [standard]

During erase, DQ6 and DQ2 toggle. DQ3 distinguishes a 50 µs command window
from the modeled 200 ms erase operation. Those deadlines are 300 and 1,200,000
clocks at 6 MHz. The ROM's erase worker polls DQ7 and DQ5 rather than those
toggle bits. [standard]

TilEm's source comment lists fast program among unfinished work, but the state
machine implements part of it. `AA 55 20` enters fast mode, `A0` selects one
program operation, and the next write calls the ordinary byte-program helper.
The state then returns to fast mode. `90`, followed by `F0`, exits. This is an
implemented command flow with unresolved hardware fidelity. Autoselect logs
that it is unimplemented; erase suspend and CFI have no states. [standard]

TilEm's chip-erase path iterates over the sector table and calls erase only for
sectors accepted by its protection model. On a TI-84 Plus with default override
group zero, this skips physical `0xB0000`–`0xBFFFF` and
`0xFC000`–`0xFFFFF`. Override group one admits those sectors. Each sector erase
resets the recorded program address and timer, so the final busy status
describes only the last writable sector. This differs from a single physical
chip-erase operation. [standard]

A guarded direct-core run exercises these states through
`tilem_flash_write_byte` and `tilem_flash_read_byte`. It seeds synthetic memory
and enables TilEm's delay model. The timer deadlines come from the scheduler;
the fixture invokes the registered Flash callback directly to cross each
deadline without executing TI-OS. [confirmed]

| Program case | State after write | Busy reads | State after callback | Later reads |
|--------------|-------------------|------------|----------------------|-------------|
| legal `FF → 50` | array read, program busy, 42-clock deadline | `80`, `C0` | array read, idle | `50` |
| illegal `50 → D0` | error, program busy, 42-clock deadline | `00`, `40` | error, idle | `20`, `60` repeatedly |

The illegal request stores `0x50`. Program-busy status takes priority over the
error state until the callback runs. The persistent error reads then set DQ5
and toggle DQ6. A following `F0` write returns to array mode and reads `0x50`.
This differs from Wabbitemu's one-read error lifetime. [confirmed]

The sector case seeds all 65,536 bytes at physical `0x20000`–`0x2FFFF` to
zero. The command changes all of them to `0xFF` immediately and changes no byte
outside that range. Erase-window reads are `00`, `44`; erase-busy reads after
the first callback are `08`, `4C`; the second callback exposes array byte
`0xFF`. [confirmed]

| Chip-erase override | Changed bytes | Bytes left non-`FF` | Last program address |
|--------------------:|--------------:|--------------------:|---------------------:|
| group 0 | 966,656 | 81,920 | `0xFA000` |
| group 1 | 1,048,576 | 0 | `0xFC000` |

Group 0 leaves `0xB0000`–`0xBFFFF` and `0xFC000`–`0xFFFFF` unchanged. Both
runs finish in array state with one 300-clock erase-window deadline for the
last admitted sector. The native matrix also confirms the partial fast-program
flow and its `90 F0` exit. Autoselect logs an unimplemented-command warning;
CFI query does nothing; `B0` in the erase-command window logs an undefined
command and returns to array state without changing memory. [confirmed]

The native binary SHA-256 is
`31f8e15a348d15f876f103b8452340484893987e458023fd913280365db5c51d`.
The build requires clean TilEm commit
`f56ad637d0524ee841dd381be6ecbaf5b8975600` and Git tree
`58316afe35d69e69353f0f743698144153051d4a`. These results describe the
pinned emulator core, not the retail ROM worker or physical Flash. Build and
run commands are under “Flash command and status matrix” in the repository's
`tools/notes/emulator-probes.md`. [confirmed]

TilEm's full calculator reset clears the Flash unlock gate, command state, and
busy flag. It retains the last program address and byte, toggle state,
protection-override group, and delay-emulation flags. An execution-protection
exception reaches this reset only after the forbidden opcode completes. A
guarded direct-core fixture executes `LD (0x8000),A` from restricted Flash page
`08`; its RAM write of `0x5A` survives the reset. This ordering is TilEm
behavior, not evidence that the ASIC executes a denied instruction. [standard]
for source; [confirmed] for the pinned run. See
[TilEm reset and exception scope](execution-protection.md#tilem-reset-and-exception-scope).

## Wabbitemu behavior and limits

Wabbitemu recognizes byte program, sector erase, chip erase, autoselect, and
fast-program commands. It applies program data with `stored &= requested`.
Successful programming returns to array mode immediately. [standard]

An illegal `0→1` request sets an error flag. The next read returns complemented
DQ7, set DQ5, and its current DQ6 toggle bit. That same read clears the error
flag, so later reads return array data. This one-read lifetime is Wabbitemu
behavior, not the hardware data-sheet polling contract. The ROM worker tests
DQ7 and DQ5 in that same first byte. [standard] for Wabbitemu source;
[confirmed] for the ROM worker.

Wabbitemu's `CPU_reset` does not reset the Flash command step, error flag,
toggle bit, write byte, delay, lock, or bounds. Its opcode-fetch path separately
ends most non-read command states after an execution violation. A seeded
`FLASH_PROGRAM` violation therefore returns to array mode before executing one
boot instruction. A seeded `FLASH_ERROR` violation retains that command step;
the boot instruction's immediate-byte read consumes status `0xE0` and clears
only the error flag. Both cases finish the same `CPU_step` at `PC=0x0002`.
[standard] for the source paths; [confirmed] for the guarded native run. See
[Wabbitemu reset scope](execution-protection.md#wabbitemu-reset-scope).

A guarded native run exercises seven byte pairs through Wabbitemu's
`CPU_mem_write` and `CPU_mem_read` entry points. Each case issues `AA 55 A0`,
programs page `08` offset `0x0100`, and reads the target twice. The harness
unlocks the in-memory ASIC gate directly and replaces the target's initial byte
before the command. It does not execute the retail ROM worker. [confirmed] for
the pinned Wabbitemu run.

| Initial | Requested | Initial DQ6 | Stored | First read | Second read |
|--------:|----------:|------------:|-------:|-----------:|------------:|
| `FF` | `50` | `00` | `50` | `50` | `50` |
| `50` | `40` | `00` | `40` | `40` | `40` |
| `80` | `00` | `00` | `00` | `00` | `00` |
| `50` | `D0` | `00` | `50` | `20` | `50` |
| `50` | `D0` | `40` | `50` | `60` | `50` |
| `00` | `80` | `00` | `00` | `20` | `00` |
| `00` | `01` | `00` | `00` | `A0` | `00` |

The first three requests are legal and expose array data immediately. The four
illegal requests set the error flag after programming `initial & requested`.
Their first read clears that flag and flips DQ6. Their second read exposes the
stored byte. All seven cases return to `FLASH_READ`; the initialized adapter
adds zero T-states for these accesses, so this run provides no timing evidence.
[confirmed] for the pinned Wabbitemu run.

The native binary SHA-256 is
`67077107b604e97cfb751cadf4392dca53d00d5bbc417b2f48c422eebb9ac560`.
It uses pinned commit `48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422` and the exact
OS 2.55MP image. The guarded CLI checks every native field against the
fixed launch expectations and the independent Python source model before
writing its manifest.

The pinned Wabbitemu source and the ROM worker produce three paths. The first
ROM read consumes Wabbitemu's error status. The worker tests both DQ7 and DQ5
in that byte. Since Wabbitemu sets DQ5, every illegal request proceeds directly
to one final array read. This table models emulator source combined with the
byte-confirmed ROM poll logic. It does not describe physical Flash behavior.
[standard] for Wabbitemu; [confirmed] for the ROM poll logic.

| Program request | Final stored DQ7 | ROM result |
|-----------------|------------------|------------|
| legal | matches requested DQ7 | succeeds on the first array read |
| illegal `0→1` outside DQ7 | matches requested DQ7 | succeeds after the final read even though lower requested bits remain zero |
| illegal DQ7 `0→1` | differs from requested DQ7 | fails after the final read |

Exhaustive enumeration of all 65,536 old/requested byte pairs gives 49,152
successes and 16,384 failures. No pair is nonterminating under this composition.
The successes contain 6,561 legal pairs and 42,591 illegal requests that the
ROM reports as successful. These exhaustive counts are deterministic
consequences of the pinned source model, not an exhaustive Wabbitemu run or
hardware observation. [standard]

A second guarded mode boots the exact retail ROM, injects a four-byte
`rst 28h`/`8087h` harness into RAM page 1, and sets the documented
`_WriteFlashUnsafe` ABI registers. The bcall copies the 124 bytes beginning at
`flash_program_worker_code` to `ramCode` and executes them. The harness directly opens
Wabbitemu's in-memory ASIC gate, so it does not test the protected port-`0x14`
unlock sequence or an OS/UI caller. [confirmed] for the pinned native run.

| Initial | Requested | Initial DQ6 | Worker reads | Stored | Result | `AF` |
|--------:|----------:|------------:|--------------|-------:|--------|-----:|
| `FF` | `50` | `00` | `50` | `50` | success | `0044` |
| `00` | `01` | `00` | `A0`, `00` | `00` | success | `0044` |
| `20` | `A0` | `00` | `20`, `20` | `20` | failure | `3F2C` |
| `50` | `D0` | `00` | `20`, `50` | `50` | failure | `3F2C` |
| `50` | `D0` | `40` | `60`, `50` | `50` | failure | `3F2C` |

All five cases enter the copied worker once and issue one program write. The
legal request takes the success reset at `ram:816B`. The illegal lower-bit
request also takes that path after its final DQ7 read, despite leaving bit 0
clear. Both illegal DQ7 requests take the failure reset at `ram:8175`,
regardless of stored DQ5. DQ6 changes the first status byte but not the return
path. [confirmed] for the pinned native run.

The cold-recovery runner exercises a separate retail path without opening the
gate through emulator state. Startup at `00:0D73` calls the bjump stub at
`00:3EEB`, which resolves to `3D:6098`. The bytes at `3D:609C`–`3D:60A8`
write `1` to port `0x14`; Wabbitemu changes `flash_locked` from true to false
at the `OUT` at `3D:60A6`. The wrapper calls `00:2BAD` at `3D:6101` to enter
`gc_check_interrupted` at `3C:7BC7`. Its return path jumps to the lock sequence
at `3D:5CE6`, and the `OUT` at `3D:5CEF` changes `flash_locked` from false to
true. The static gate scanner classifies both sequences and finds no
unclassified port-`0x14` candidate on page `3D`. [confirmed]

All six reconstructed recovery images take that protected unlock → recovery →
relock path. The observer identifies the public block-program worker by
comparing all 124 bytes at `ramCode` with
`flash_program_worker_code`. Each
`_WriteFlashUnsafe` visit reaches one matching worker entry and one success
tail at `ram:816B`; no run reaches the failure tail at `ram:8175`. [confirmed]

| Input phase | `_WriteFlashUnsafe` / worker entries | Data writes at `ramCode + 0x49` (`ram:8149`) | `_EraseFlash` entries |
|------------:|-------------------------------------:|-------------------------------:|----------------------:|
| `0xFF` | 33 | 48 | 3 |
| `0xFE` | 32 | 47 | 3 |
| `0xFC` | 20 | 20 | 4 |
| `0xF8` | 19 | 19 | 3 |
| `0xF0` | 304 | 65,560 | 3 |
| `0xE0` | 17 | 17 | 2 |

These counts cover the exact public block-program worker. Other internal RAM
workers can issue additional Flash commands during certificate rebuilding.
The run is Wabbitemu evidence for the retail control path, not physical ASIC
or Flash evidence. The observer binary SHA-256 is
`242ca0d3ecab861ce1048285258d1e13ebc18a175bccf016397692fbe0f150db`.
It uses pinned Wabbitemu commit
`48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422`. [confirmed]

Sector erase changes the complete sector to `0xFF` before the next instruction
and exposes no erase-busy interval. Its sector arithmetic matches the physical
64, 32, 8, 8, and 16 KiB top-boot layout. The two 8 KiB sectors are the halves
of page `3E`. [standard]

Wabbitemu also implements chip erase by filling the complete Flash array with
`0xFF`, including page `3F`, without consulting its per-write boot-page gates.
Its TI-84 Plus profile sets Flash version 3, which enables `AA 55 20`, repeated
`A0` program operations, and `90 F0` exit. It has no erase-suspend or CFI state.
Autoselect offset `4` always returns zero, so it reports every sector as
unprotected. [standard]

A guarded native command-family run checks these source claims through
`CPU_mem_write` and `CPU_mem_read`. The adapter loads the exact OS 2.55MP image,
opens Wabbitemu's in-memory gate, and keeps every mutation in the allocated
Flash array. It does not execute a retail-ROM Flash routine. [confirmed] for
the pinned Wabbitemu run.

| Command path | Native observation |
|--------------|--------------------|
| Autoselect | `AA 55 90` enters `FLASH_AUTOSELECT`; offsets `0`, `2`, and `4` return `01`, `DA`, and `00` |
| Array reset | `F0` returns autoselect and a partial `AA` sequence to `FLASH_READ` |
| Fast program | `AA 55 20` enters `FLASH_FASTMODE`; two `A0` operations store `F0 & 50 = 50` and `AA & A0 = A0`, returning to fast mode after each |
| Fast-mode exit | `90` enters `FLASH_FASTMODE_EXIT`; `F0` returns to `FLASH_READ` |
| Sector erase | `AA 55 80 AA 55 30` changes all 65,536 seeded bytes at physical `0x20000`–`0x2FFFF` to `FF`; no byte outside the range changes |
| Chip erase | `AA 55 80 AA 55 10` reduces 322,043 non-`FF` bytes to zero and changes a seeded byte at physical `0xFFFFF` from `00` to `FF` |
| CFI query | `98` from array mode returns to `FLASH_READ` and changes no byte |
| Erase suspend/resume | `B0` in `FLASH_ERASE_55` returns to `FLASH_READ`; the following `30` also leaves the array unchanged |

The sector test seeds the complete 64 KiB sector and two adjacent boundary
bytes before issuing the command. The chip test counts the complete 1 MiB
array and explicitly seeds its final boot-page byte. The adapter records zero
T-states for the direct calls, so the run provides no command-timing evidence.
Its binary SHA-256 is
`41304b9a760438440f60cbfeca394cd37252c929ef2043e692c0254b8d1cb52d`.
[confirmed] for the pinned Wabbitemu run.

Wabbitemu accepts a port-`0x14` write only while the current Flash page passes
its privileged-page predicate. Its source names pages `2F`, `3C`, `3D`, and
`3F` for the TI-84 Plus path; page `3E` does not pass that predicate. A separate
write-validity check requires the resulting unlocked state and applies model
flags to boot-page writes. This approximates the ASIC gates but does not model
TilEm's byte-fetch recognizer. [standard]

## MAME behavior and limits

MAME 0.287 instantiates its generic `AMD_29F800T` device for the TI-84 Plus.
The device has a one-megabyte array, AMD manufacturer ID `0x01`, device ID
`0xDA`, and top-boot sector geometry. [standard]

Its AMD autoselect path returns the configured maker ID at offset `0`, device
ID at offset `1`, and a fixed zero at offset `2`. It does not implement the
Fujitsu byte-mode offsets `0`, `2`, and `4`, including the sector-protection
read at offset `4`. It has no CFI query state for `AMD_29F800T` and no AMD
erase-suspend state. The `0xB0` case in this source is a Sanyo-specific
bank-select command, not erase suspend. [standard]

Its 8-bit byte-program path assigns `stored = requested`. It does not apply NOR
AND semantics. A request to change a stored zero to one therefore succeeds in
MAME, and the first ROM poll reads the assigned byte with matching DQ7. The
program path has no timed busy mode or DQ5 failure state. [standard]

Sector erase fills the selected sector with `0xFF` immediately, then enters a
timed status mode. MAME uses 1,000 ms for a 64 KiB sector, 500 ms for the 32 KiB
and 16 KiB sectors, and 250 ms for either 8 KiB sector. In-sector reads alternate
`0x4C` and `0x08`, toggling DQ6 and DQ2 around a base DQ3 value. DQ5 stays clear.
When the timer expires, reads return the already-erased array. [standard]

The busy-read range has a separate geometry bug. MAME tests a 64 KiB interval
from `m_erase_sector` even when it erased a 32, 16, or 8 KiB top-boot sector.
Erasing the first page-`3E` half at `0xF8000`, for example, returns erase status
for every read through `0xFFFFF` until the 250 ms timer ends. Only the selected
8 KiB array region is changed. [standard]

Chip erase fills the complete array with `0xFF` immediately and starts the
generic 16-second `AMD_29F800T` erase timer. The chip-erase branch does not set
`m_erase_sector`. Busy reads consequently use its stale or initial value and a
64 KiB interval even though the complete array has already changed. [standard]

MAME accepts `AA 55 20` and sets its fast-mode flag. Its subsequent `0xA0`
handler permits fast programming only for Fujitsu and selected ST maker IDs.
The `0x90` fast-exit transition uses the same maker-ID gate. The TI-84 Plus
instance uses maker ID `0x01` for AMD, so `A0` logs an unknown mode byte and
`90 F0` returns to normal reads without clearing the fast-mode flag. MAME
therefore has partial, not working, unlock-bypass support for this device
configuration. [standard]

The TI driver maps every Flash bank directly to the generic device's read and
write methods. Port `0x14` stores `m_flash_unlocked` and updates paging, but no
memory-write path consults that value. The driver also omits ports `0x22`–`0x28`.
MAME therefore accepts command writes without the protected byte sequence,
sector override, or execution-protection state used by the ROM. [standard]

The stored gate is a raw byte rather than a Boolean. A guarded sweep of writes
`00 01 02 3F 40 FF` makes port `0x02` return `C3 C7 CB FF C3 FF`, following
the driver's truncated `0xC3 | (value << 2)` expression. Port `0x14` itself
reads zero. A scheduled soft reset retains write one and consequently returns
`0xC7`; this is MAME reset behavior, not a physical lock-retention result.
[standard]

A separate guarded run maps Flash page `08` into the CPU's `0x4000` window and
issues commands through CPU program space while reading the gate state through
I/O port `0x02`. A complete program while locked reports `C3` and changes the
target from `FF` to `50`. A prefix started while locked and completed after an
unlock reports `C7` and changes it to `D0`. A prefix started while unlocked and
completed after relocking reports `C3` and changes it to `20`. CPU reads and
direct generic-device reads agree after every case. [confirmed]

The saved image differs from the source only at `0x20100` (`FF → 20`) and has
SHA-256
`2fd21a6b139a641d40a71a0e68df492e4555e79c6f1cf44858b4dcfd9158bbeb`.
This CPU/I/O-space result confirms that MAME stores and exposes the port-`0x14`
state without applying it to mapped Flash writes. It describes MAME 0.287, not
the ASIC gate or physical Flash. [confirmed]

A guarded MAME 0.287 run exercises the `ti84pv3` machine's mapped `:membank0`
Flash interface through Lua. It uses the exact OS 2.55MP image but does not
execute TI-OS Flash code. The report oracle checks every field against the
pinned source model, and the image oracle compares the complete saved 1 MiB
array against the expected command mutations. [confirmed]

| Command or read | Runtime observation |
|-----------------|---------------------|
| Autoselect | offsets `0`, `1`, `2`, and `4` return `01`, `DA`, `00`, and `00` |
| Byte program | `FF → 50` stores `50`; the illegal `50 → D0` request stores `D0` |
| Array reset and CFI | `F0` after a partial unlock restores array reads; `98` leaves the programmed `D0` visible |
| Unlock bypass | `AA 55 20` accepts the entry, but its `A0` program does not change `D0`; `90` exposes manufacturer ID `01`, and `F0` restores array byte `D0` |
| 8 KiB top-sector erase | the selected `0xF8000`–`0xF9FFF` array range changes immediately; reads at `0xF8000`, `0xFA000`, and `0xFC000` expose busy status, while `0xE0000` remains an array read |
| Timer completion | selected and adjacent reads return `FF`, boot Flash returns `3E`, and `0xE0000` returns `9F` at frame 20 |

The saved Flash differs from the source ROM only at `0x20100` (`FF → D0`),
`0xF8000` (`00 → FF`), and `0xF9FE0`–`0xF9FE1` (`00 → FF`). Its SHA-256 is
`1dc4eec678252588df24118e96603b6c80806b8b9ea8e0e12b2169ac6aae3935`.
The MAME executable SHA-256 is
`fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91`.
These identities and the retained manifest scope the result to MAME 0.287,
not the retail worker or physical Flash. [confirmed]

A separate guarded run seeds each sector boundary and its adjacent probes with
`00` before issuing five sector erases. Each command changes only its selected
array range. Busy reads cover 64 KiB from the selected start, including bytes
past the 32 KiB and 8 KiB sectors. [confirmed]

| Selected range | Source timer | Completion frame | Out-of-sector read while busy |
|----------------|-------------:|-----------------:|-------------------------------|
| `0xE0000`–`0xEFFFF` | 1,000 ms | 50 | `0xF0000 = 00` |
| `0xF0000`–`0xF7FFF` | 500 ms | 75 | `0xF8000 = 08` |
| `0xF8000`–`0xF9FFF` | 250 ms | 88 | `0xFA000 = 08` |
| `0xFA000`–`0xFBFFF` | 250 ms | 101 | `0xFC000 = 08` |
| `0xFC000`–`0xFFFFF` | 500 ms | 126 | `0xFBFFE = 00` |

The frame deltas are 50, 25, 13, 13, and 25. At 50 frames/s, they match the
source timers. The 250 ms cases appear on the next whole frame. Every seeded
byte immediately outside the selected array range remains `00` after
completion. [confirmed]

Chip erase starts at emulated second 2 after the sector matrix. It immediately
changes the complete array to `FF`, while reads in the last sector's stale busy
range return `4C` and `08`. The periodic state probe observes array reads at
second 18, exactly 16 emulated seconds later. The saved image contains no
non-`FF` byte and has SHA-256
`f5fb04aa5b882706b9309e885f19477261336ef76a150c3b4d3489dfac3953ec`.
[confirmed]

## Reproducing the comparison

`tools/ti84re/flash/hardware.py` contains the photographed-device specification,
reported compatible families, sector table, source-modeled program rules, MAME
erase status, and the ROM worker's DQ7/DQ5 decision. The focused CLI separates
physical and emulator identities and exposes negative cases without modifying
an emulator:

```console
$ python3 -m ti84re.flash.describe_hardware parts
photographed part: Fujitsu MBM29LV800TA-70PFTN
  package marking: 29LV800TA-70PFTN
  board evidence: Datamath March 2004 TI-84 Plus PCB photograph
  data-sheet autoselect: manufacturer=0x04 device=0xDA
  rated byte program: 8 us typical, 300 us maximum
  rated sector erase: 1 s typical, 10 s maximum
reported compatible families: AMIC A29L800A, Fujitsu 29LV800, Spansion S29AL008D, Macronix MX29LV800
```

```console
$ python3 -m ti84re.flash.describe_hardware program --old 0x00 --data 0xFF
program old=0x00 requested=0xFF
  TilEm: stored=0x00 poll=error state
  Wabbitemu: stored=0x00 poll=one transient error-status read
  MAME: stored=0xFF poll=array data
  Wabbitemu error-read values (DQ6=0/1): 0x20 0x60
```

The Wabbitemu/ROM composition is available for one pair or as an exhaustive
summary. The single-pair model defaults the persistent DQ6 toggle bit to clear;
`--dq6` selects a set bit. DQ6 changes the first read value but not the ROM's
DQ7/DQ5 decision.

```console
$ python3 -m ti84re.flash.describe_hardware wabbitemu-poll --old 0x50 --data 0xD0
Wabbitemu/ROM old=0x50 requested=0xD0 stored=0x50
  read 0: DQ7/DQ5 poll=0x20 -> need-final-read
  read 1: final DQ7 poll=0x50 -> failure
  outcome: failure
```

```console
$ python3 -m ti84re.flash.describe_hardware wabbitemu-poll
all byte pairs: 65536
  outcomes: success=49152 failure=16384
  legal successes: 6561
  illegal requests reported successful: 42591
```

```console
$ python3 -m ti84re.flash.describe_hardware mame-erase 0xF9000 --reads 4
sector 0x0F8000-0x0F9FFF, timer=250 ms
busy reads 0x0F8000-0x0FFFFF
status: 0x4C 0x08 0x4C 0x08
```

The command-capability matrix and structural ROM scan are available as JSON:

```sh
python3 -m ti84re.flash.describe_hardware --json commands
nix develop -c python3 -m ti84re.flash.analyze_rom_commands --json
```

The guarded MAME runtime probe requires the exact MAME binary hash and writes
its command, input identities, report, complete NVRAM image comparison, and
captured logs to a new output directory:

```sh
mame_flash_parent=$(mktemp -d /tmp/ti84-mame-flash.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_flash_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_flash_parent/run" --json
```

The CPU-visible gate probe uses the same guarded runtime and changes the gate
between AMD command phases:

```sh
mame_gate_parent=$(mktemp -d /tmp/ti84-mame-gate.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_flash_gate_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_gate_parent/run" --json
```

The independent erase matrix uses the same guards and output contract:

```sh
mame_erase_parent=$(mktemp -d /tmp/ti84-mame-erase.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_flash_erase_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_erase_parent/run" --json
```

The `parts`, `geometry`, `profiles`, `commands`, `poll`, and `wabbitemu-poll`
subcommands support `--json` for scripts. `tools/ti84re/flash/trace.py` imports the
same geometry library, so dynamic trace reports and emulator comparisons use
one sector definition.
