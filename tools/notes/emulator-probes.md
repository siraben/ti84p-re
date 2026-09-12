# Pinned emulator probes

Native probes that pin emulator behavior to an exact source tree: direct-core
TilEm probes, guarded MAME probes, the Wabbitemu headless adapter, and the
deployed jsTIfied profile. Each probe records the commit, tree, binary hash,
and evidence scope in its manifest so that emulator evidence stays separate
from ROM evidence. See [dynamic-tracing.md](dynamic-tracing.md) for the
trace pipeline these probes complement.

## Pinned TilEm direct-core probes

`tilem_core.py` supplies clean-source validation, source enumeration, compiler
construction, hashing, and captured native execution. `tilem_probe_support.c`
supplies the allocation and diagnostic callbacks needed to link small probes
against the complete core. Each builder requires the clean commit and Git tree
before it compiles any source. Use the repository's locked Nixpkgs revision
when `cc` is unavailable.

### Reset and execution exception

```sh
tilem_reset_tmp=$(mktemp -d /tmp/ti84-tilem-reset.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_reset_tmp/tilem"
git -C "$tilem_reset_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python3 -m ti84re.emulators.tilem.build_probe --probe reset \
  --source "$tilem_reset_tmp/tilem" \
  --output "$tilem_reset_tmp/tilem-reset-probe" --json

tilem_reset_parent=$(mktemp -d /tmp/ti84-tilem-reset-report.XXXXXX)
python3 -m ti84re.emulators.tilem.run_reset_probe \
  --binary "$tilem_reset_tmp/tilem-reset-probe" \
  --expected-binary-sha256 \
    ab0a862b1fbb7f8a09a075fbd0ec61ebb0bab84d12d2a9c2a650813476cc7e5a \
  --output-dir "$tilem_reset_parent/run" --json
```

The source guard requires commit
`f56ad637d0524ee841dd381be6ecbaf5b8975600`, tree
`58316afe35d69e69353f0f743698144153051d4a`, and an unmodified tracked
worktree. The probe seeds all reset components directly. It checks eight reset
groups, nine retained groups, exact TI-84 Plus mapper and register defaults,
and one restricted Flash instruction. That instruction writes a byte to mapped
RAM before TilEm handles its pending exception and performs the full reset.
The manifest labels this initialized-core scope; no TI-OS instruction or
physical reset executes.

### Flash command and status matrix

The Flash probe uses the same guarded source and shared support. It calls the
core's physical-address Flash entry points against synthetic memory. It checks
the command lock, reset, unsupported commands, fast mode, legal and illegal
programming, status toggles, timer deadlines, sector boundaries, and both
protection-override groups:

```sh
tilem_flash_tmp=$(mktemp -d /tmp/ti84-tilem-flash.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_flash_tmp/tilem"
git -C "$tilem_flash_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python3 -m ti84re.emulators.tilem.build_probe --probe flash \
  --source "$tilem_flash_tmp/tilem" \
  --output "$tilem_flash_tmp/tilem-flash-probe" --json

tilem_flash_parent=$(mktemp -d /tmp/ti84-tilem-flash-report.XXXXXX)
python3 -m ti84re.emulators.tilem.run_flash_probe \
  --binary "$tilem_flash_tmp/tilem-flash-probe" \
  --expected-binary-sha256 \
    31f8e15a348d15f876f103b8452340484893987e458023fd913280365db5c51d \
  --output-dir "$tilem_flash_parent/run" --json
```

The scheduler converts TilEm's 7 µs program, 50 µs erase-window, and 200 ms
erase inputs to 42, 300, and 1,200,000 clocks at the reset speed. The probe
reads each status phase and directly invokes the registered Flash callback to
advance between phases. It does not execute the retail ROM or a physical
command.

### Legacy interrupt matrix

The interrupt probe uses the same source guard and shared support. Its Python
oracle reuses the immutable TilEm state in `interrupt_controller.py`. The C
adapter calls the registered port and periodic-timer handlers, keypad and link
entry points, programmable-timer expiry, and full reset:

```sh
tilem_interrupt_tmp=$(mktemp -d /tmp/ti84-tilem-interrupt.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_interrupt_tmp/tilem"
git -C "$tilem_interrupt_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python3 -m ti84re.emulators.tilem.build_probe --probe interrupt \
  --source "$tilem_interrupt_tmp/tilem" \
  --output "$tilem_interrupt_tmp/tilem-interrupt-probe" --json

tilem_interrupt_parent=$(mktemp -d /tmp/ti84-tilem-interrupt-report.XXXXXX)
python3 -m ti84re.emulators.tilem.run_interrupt_probe \
  --binary "$tilem_interrupt_tmp/tilem-interrupt-probe" \
  --expected-binary-sha256 \
    23037df0fee48b3ec15656aae80b6181d97211e8eec325c2be81eef02b1ff840 \
  --output-dir "$tilem_interrupt_parent/run" --json
```

The native matrix checks full port-`0x03` readback; clear-on-zero behavior at
ports `0x02` and `0x03`; ON press and release edges; the three standard-timer
callbacks; current intervals and four selected periods; external link
transitions; programmable-timer completion and CPU requests in halted and
running states; and reset ordering. It exposes TilEm's stored
port-`0x03 = 0x0B` with an internally disabled ON interrupt immediately after
reset. A prior bit-3 write also remains in the internal power policy despite
the reset readback. Writing `0x0B` through the port handler synchronizes both
fields.

Two isolated runs produce identical canonical native JSON with SHA-256
`1c1209e9c3f625b07c42288c21e9a5dbadddb38f12aee995c1fbc8daf1f8e8ad`.
The manifest labels the initialized-core scope. It does not execute TI-OS or
measure interrupt voltage, physical timing, low-power domains, or reset
retention.

### Battery comparator matrix

`battery_hardware.py` encodes the byte-verified `_Chk_Batt_Level` decision
tree and TilEm's four threshold constants. The native adapter sweeps the
emulator's 0.1 V battery field and reads every port-`0x04` selector through the
TI-84 Plus port-`0x02` handler:

```sh
tilem_battery_tmp=$(mktemp -d /tmp/ti84-tilem-battery.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_battery_tmp/tilem"
git -C "$tilem_battery_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python3 -m ti84re.emulators.tilem.build_probe --probe battery \
  --source "$tilem_battery_tmp/tilem" \
  --output "$tilem_battery_tmp/tilem-battery-probe" --json

tilem_battery_parent=$(mktemp -d /tmp/ti84-tilem-battery-report.XXXXXX)
python3 -m ti84re.emulators.tilem.run_battery_probe \
  --binary "$tilem_battery_tmp/tilem-battery-probe" \
  --expected-binary-sha256 \
    47008d660c7ea3e88c07df3d41d5c3e34c51d49850a806d5d2e37d5ca6214029 \
  --output-dir "$tilem_battery_parent/run" --json
```

The guarded run observes masks `0`, `1`, `5`, `7`, and `F` across 3.0–4.5 V.
The shared ROM model maps them to levels 0, 1, 3, 3, and 4. This pins level 2
as unreachable under TilEm's threshold ordering. The manifest labels this as
initialized-core emulator behavior, not a measured calculator voltage.

### Programmable timer and RTC matrix

`tilem_timer.py` derives source periods and expiry outcomes from the reusable
timer model, then adds pinned scheduling, readback, reset, and RTC edge values.
The C adapter replaces `time()` only inside the probe executable, making every
RTC transition and byte-level rollover deterministic:

```sh
tilem_timer_tmp=$(mktemp -d /tmp/ti84-tilem-timer.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_timer_tmp/tilem"
git -C "$tilem_timer_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python3 -m ti84re.emulators.tilem.build_probe --probe timer \
  --source "$tilem_timer_tmp/tilem" \
  --output "$tilem_timer_tmp/tilem-timer-probe" --json

tilem_timer_parent=$(mktemp -d /tmp/ti84-tilem-timer-report.XXXXXX)
python3 -m ti84re.emulators.tilem.run_timer_probe \
  --binary "$tilem_timer_tmp/tilem-timer-probe" \
  --expected-binary-sha256 \
    fa665079fac1ace807930be8a3836385f6821ee9994c6454039b8ca85bb75d77 \
  --output-dir "$tilem_timer_parent/run" --json
```

The probe checks all crystal and CPU divisor selections, three off-family
values, three port-`0x2F` values under source `0xC0`, mode masking, counter
zero, completion, overflow, interrupt generation, acknowledgement, all three
status mappings, source-write retention, and the unacknowledged non-loop
restart period. The RTC cases commit, advance, freeze, re-enable, reset, and
force a rollover between individual current-register reads.

Two isolated runs produce identical canonical native JSON with SHA-256
`0da06edc402dfb14945d28577f212face4c04c22b3b6ffc3e283a70e0ecb4aa5`.
The manifest identifies the substituted time source and initialized-core
scope. The run does not execute the OS, measure the host clock, or establish
physical divisor, power, rollover, or reset behavior.

### Keypad and ON-edge matrix

`tilem_keypad.py` derives ordered matrix cases from the reusable model in
`keypad_hardware.py`. The C adapter uses the initialized core's keypad API and
TI-84 Plus port handlers. It checks transitive closure, all eight rows, exact
group-byte storage, ordinary scancode bounds, duplicate events, the separate
ON path, both enabled ON edges, and keypad reset:

```sh
tilem_keypad_tmp=$(mktemp -d /tmp/ti84-tilem-keypad.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_keypad_tmp/tilem"
git -C "$tilem_keypad_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python3 -m ti84re.emulators.tilem.build_probe --probe keypad \
  --source "$tilem_keypad_tmp/tilem" \
  --output "$tilem_keypad_tmp/tilem-keypad-probe" --json

tilem_keypad_parent=$(mktemp -d /tmp/ti84-tilem-keypad-report.XXXXXX)
python3 -m ti84re.emulators.tilem.run_keypad_probe \
  --binary "$tilem_keypad_tmp/tilem-keypad-probe" \
  --expected-binary-sha256 \
    9553bdafadf042dd9af634221b52b8795b572d0c047f839e119dabc957063323 \
  --output-dir "$tilem_keypad_parent/run" --json
```

The ordered reads are `FF`, `FE`, `FF`, `FE`, `FC`, `F8`, `7F`, `FC`, and
`FE`. They cover an unselected matrix, one selected key, an unselected key,
same-column keys, a rectangle, a transitive chain, column 7, all selected
groups, and row 7. Two isolated builds produce the same binary. Their
canonical native JSON has SHA-256
`1f75a4010773a7c8a108d62239cb937e02aa029affa55263906688eb73ba536c`.
The run does not execute the OS or measure electrical settling, switch bounce,
physical ghosting, or ASIC ON edges.

### MD5-assist edge matrix

`tilem_md5.py` checks an ordered native report against the shared arithmetic
and edge oracle in `md5_hardware.py`. The C adapter calls the TI-84 Plus port
handlers directly. It covers partial and fifth operand writes, control masks,
undefined operand reads, mid-read mutation, modeled clock cost, and full reset:

```sh
tilem_md5_tmp=$(mktemp -d /tmp/ti84-tilem-md5.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_md5_tmp/tilem"
git -C "$tilem_md5_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python3 -m ti84re.emulators.tilem.build_probe --probe md5 \
  --source "$tilem_md5_tmp/tilem" \
  --output "$tilem_md5_tmp/tilem-md5-probe" --json

tilem_md5_parent=$(mktemp -d /tmp/ti84-tilem-md5-report.XXXXXX)
python3 -m ti84re.emulators.tilem.run_md5_probe \
  --binary "$tilem_md5_tmp/tilem-md5-probe" \
  --expected-binary-sha256 \
    b461e9720e0c304b26ab95ca814943eddfba670dd7bd1e41b48d53a0f8c689c5 \
  --output-dir "$tilem_md5_parent/run" --json
```

The partial-write results are `11000000`, `33221100`, `44332211`, and
`55443322`. Raw `FF` control writes store shift 31 and mode 3. Mutating `A`
after reading the low result byte assembles `343F97B4` from old result
`D6D117B4` and new result `343F9701`. Two isolated builds produce binary
SHA-256 `b461e9720e0c304b26ab95ca814943eddfba670dd7bd1e41b48d53a0f8c689c5`.
Their canonical native JSON has SHA-256
`97921226800da92b585b6d16a390355c157bf9aa5976fe47d183e87bbcbad1b8`.

The zero-shift cases exercise a nonportable shift-by-32 expression in TilEm's
C source. The manifest therefore scopes these observations to the locked
compiler and exact binary. The run does not execute TI-OS or establish any
physical ASIC behavior.

### Raw link and assist matrix

`tilem_link.py` validates raw line reads, link-activity interrupts, assist
ports, byte transfers, status acknowledgement, reset retention, and modeled
clock cost against the reusable source model in `link_port.py`. The C adapter
calls the registered TI-84 Plus port handlers and link state machine directly:

```sh
tilem_link_tmp=$(mktemp -d /tmp/ti84-tilem-link.XXXXXX)
git clone https://github.com/debrouxl/tilem.git "$tilem_link_tmp/tilem"
git -C "$tilem_link_tmp/tilem" checkout \
  f56ad637d0524ee841dd381be6ecbaf5b8975600
nix shell \
  github:NixOS/nixpkgs/f13ff45afd1bb73e640eaa08a7066dbed07e3238#gcc \
  --command python3 -m ti84re.emulators.tilem.build_probe --probe link \
  --source "$tilem_link_tmp/tilem" \
  --output "$tilem_link_tmp/tilem-link-probe" --json

tilem_link_parent=$(mktemp -d /tmp/ti84-tilem-link-report.XXXXXX)
python3 -m ti84re.emulators.tilem.run_link_probe \
  --binary "$tilem_link_tmp/tilem-link-probe" \
  --expected-binary-sha256 \
    b878d9be860a92da72c5712e82a4c2974fb3cad125e078e61f8444172b887896 \
  --output-dir "$tilem_link_parent/run" --json
```

The raw truth table is `03 02 01 00`, `12 12 10 10`, `21 20 21 20`, and
`30 30 30 30`. A peer-line transition asserts the enabled activity interrupt.
The disabled assist status is `0x20`; idle-ready is `0x22`; receive completion
is `0x31` before the `0xA5` data read and `0x20` afterward. Illegal both-low
input produces `0x64`; the first status read clears the interrupt but leaves
`0x60`. Reset retains the four auxiliary write registers and external line
state while clearing active assist fields. Direct calls add zero modeled CPU
clocks.

Two isolated builds produce binary SHA-256
`b878d9be860a92da72c5712e82a4c2974fb3cad125e078e61f8444172b887896`.
Their canonical native JSON has SHA-256
`7f649da90850ef5c00bd2472f1cc9772eb6f50b75ed462fc7527bbd7c6a7ce59`.
The manifest limits the result to pinned initialized-core TilEm behavior. The
run does not execute TI-OS, exercise a virtual-cable lifecycle, measure
electrical timing, or establish physical reset retention.

## Pinned MAME Flash probe

`mame_runtime.py` provides shared MAME identity, configuration, isolated
headless-environment, command, process, logging, and manifest helpers. Its
guarded probe operation validates the executable, ROM, and Lua script before
creating the runtime tree. `mame_trace.py` reuses the lower-level library for
I/O traces. The Flash-specific parser and oracle are in
`mame_flash.py`; `run_mame_flash_probe.py` is the guarded CLI. The independent
sector and chip-erase types, parser, and image oracle are in
`mame_flash_erase.py`. `mame_flash_gate.py` provides the typed CPU-visible gate
report and complete-image oracle; `run_mame_flash_gate_probe.py` is its guarded
CLI.

The CLI requires a caller-supplied executable SHA-256 and MAME 0.287. It also
requires the exact local OS 2.55MP ROM. It places the ROM, configuration,
NVRAM, and snapshots under a new output directory, retains standard output and
standard error, and writes a manifest with every input and result identity.
Run the packaged MAME through Nix when it is not installed globally:

```sh
mame_flash_parent=$(mktemp -d /tmp/ti84-mame-flash.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_flash_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_flash_parent/run" --json
```

The Lua adapter writes and reads the `ti84pv3` machine's mapped `:membank0`
Flash interface. It checks autoselect, reset, CFI, unlock bypass, legal and
illegal byte programming, one 8 KiB top-sector erase, the incorrect 64 KiB
busy-read range, and timer completion. The Python oracle compares all reported
fields with the pinned MAME source model. It also compares the complete saved
1 MiB Flash array with its own mutation model and requires output SHA-256
`1dc4eec678252588df24118e96603b6c80806b8b9ea8e0e12b2169ac6aae3935`.
The adapter does not execute a TI-OS Flash routine or a physical command.

The gate adapter maps Flash page `08` into CPU program space, reads gate status
through I/O port `0x02`, and changes port `0x14` between AMD command phases. It
programs the same byte with a complete command while locked, a locked-to-
unlocked transition, and an unlocked-to-locked transition. All three commands
take effect, with final byte `20`; the complete saved image must have SHA-256
`2fd21a6b139a641d40a71a0e68df492e4555e79c6f1cf44858b4dcfd9158bbeb`:

```sh
mame_gate_parent=$(mktemp -d /tmp/ti84-mame-gate.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_flash_gate_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_gate_parent/run" --json
```

The locked, unlocked, and relocked status reads are `C3`, `C7`, and `C3`.
CPU-mapped and direct-device reads agree after each command. This confirms the
MAME driver's missing write gate through its CPU and I/O spaces, but says
nothing about the physical ASIC.

`run_mame_flash_erase_probe.py` uses a separate runtime tree. It seeds each
selected sector and adjacent probe through byte-program commands, waits for
array reads before advancing, and then chip-erases the isolated image. A
periodic callback observes chip completion because erasing boot Flash stops
the calculator driver from producing frame callbacks. The final image must be
exactly one MiB of `FF` with SHA-256
`f5fb04aa5b882706b9309e885f19477261336ef76a150c3b4d3489dfac3953ec`:

```sh
mame_erase_parent=$(mktemp -d /tmp/ti84-mame-erase.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_flash_erase_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_erase_parent/run" --json
```

The native report pins sector completion frames `50`, `75`, `88`, `101`, and
`126`. Chip erase starts at emulated second 2 and exposes array data at second
18. The report oracle also verifies selected mutation ranges, fixed 64 KiB busy
ranges, stale chip-erase status scope, and every boundary byte. This remains
MAME behavior rather than TI-OS or physical evidence.

## Pinned MAME MD5-port probe

`mame_md5.py` parses the native port report and calculates the expected first
padded-`"abc"` result with the independent arithmetic model in
`md5_hardware.py`. `run_mame_md5_probe.py` uses the shared guarded MAME runtime:

```sh
mame_md5_parent=$(mktemp -d /tmp/ti84-mame-md5.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_md5_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_md5_parent/run" --json
```

The Lua adapter reads ports `0x18`–`0x1F`, writes a distinct value to every
port, reads them again, and issues the complete 30-access transaction used by
the first MD5 step. Initial, post-pattern, and post-transaction reads are eight
zero bytes. The result is `0x00000000`; the independent expected result is
`0xD6D117B4`. Two isolated runs produce identical parsed reports. This is
CPU-I/O-space evidence for MAME 0.287's absent MD5 block, not retail-ROM or
physical-hardware evidence.

## Pinned MAME raw-link probe

`mame_link.py` parses raw-write, connector-output, peer-input, and assist-port
cases. Its oracle derives the expected values from `link_port.py` rather than
duplicating the PCR and connector formulas. Run it through the shared guarded
MAME runtime:

```sh
mame_link_parent=$(mktemp -d /tmp/ti84-mame-link.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_link_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_link_parent/run" --json
```

The Lua adapter issues writes `00`, `01`, `02`, `03`, `14`, `28`, and `3C`
through CPU I/O space. It records port-`0x00` readback and the link-port
device's saved tip/ring output fields after each write. It also injects all
four peer pull-low masks through the corresponding saved input fields. Normal
writes produce reads `03`, `12`, `21`, and `30` while releasing both modeled
connector outputs. The peer reads are `03`, `02`, `01`, and `00`.

Port `0x02` returns `C3`. Ports `0x08`–`0x0D` return six zero bytes before and
after patterned writes. Two isolated runs produce identical parsed reports.
This validates MAME's internal CPU, PCR, and connector-facing state. It does
not execute a TI-OS transfer, attach an optional MAME link device, or measure
physical electrical behavior.

## Pinned MAME keypad probe

`mame_keypad.py` parses the ordered live-input matrix and checks it against the
MAME branch of the reusable model in `keypad_hardware.py`. The guarded CLI uses
the shared MAME runtime:

```sh
mame_keypad_parent=$(mktemp -d /tmp/ti84-mame-keypad.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_keypad_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_keypad_parent/run" --json
```

The Lua adapter resolves group masks from MAME's `:BIT0`–`:BIT7` live input
fields. Forced input values cross one video-frame update before the adapter
writes and reads port `0x01` through the main CPU I/O space. The ordered reads
are `FF`, `FF`, `FE`, `FF`, `FF`, `FE`, `7F`, and `FD` for the release-byte,
bit-7-only, single-key, unselected-key, same-column, rectangle, column-7, and
all-selected cases. The same-column `FF` result directly confirms MAME's XOR
cancellation. The rectangle `FE` result confirms that MAME does not apply
TilEm or Wabbitemu matrix closure.

Two isolated runs produce byte-identical native reports with SHA-256
`f684472b1f139b649245f54d140190bd5f91bf2508aa9e4764ddc0ce88079477`.
This validates MAME 0.287's live input fields and keypad handlers. It does not
execute the TI-OS scanner or measure electrical settling, bounce, or a physical
matrix.

## Pinned MAME legacy-interrupt probe

`mame_interrupt.py` parses shared status reads, mask writes, ON transitions,
standard-timer latches, and reset retention. Its oracle uses the immutable MAME
state model in `interrupt_controller.py`. Run it through the shared guarded
runtime:

```sh
mame_interrupt_parent=$(mktemp -d /tmp/ti84-mame-interrupt.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_interrupt_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_interrupt_parent/run" --json
```

The Lua adapter parks the Z80 in `DI` RAM, disables programmable timers, and
uses only CPU-I/O-space accesses for the legacy controller. Ports `0x03` and
`0x04` both read `08` after each mask write in `00 01 02 04 08 10 FF`.
Writing `07` to port `0x02`, then applying port-`0x03` masks `01 06 FF 00`,
produces status `09 0E 0F 08`.

The live ON sequence produces `00 00 08 01 09 08` for masked press,
held-button enable, release, enabled press, enabled release, and
acknowledgement. One frame with timer 1, timer 2, or both enabled produces
`0A`, `0C`, or `0E`. Soft reset retains seeded status `0F`; after direct status
clear, the retained masks regenerate timer status `0E`, and a new ON press
produces `07`.

Two isolated runs produce identical canonical parsed native JSON with SHA-256
`bb4b38d444692b5136d96264fa3acf9fe95ef2f6a1879ab72e9a2ad8077c1def`.
This is MAME legacy-interrupt, input-sampling, scheduler, and reset evidence.
It does not establish physical interrupt edges, timer rates, acknowledgement,
link wake, low power, or reset retention.

## Pinned MAME timer and RTC probe

`mame_timer.py` parses the complete timer, status, auxiliary-port, and RTC-port
report. Its oracle derives source divisors and expiry polarity from
`timer_hardware.py`. Run it through the shared guarded MAME runtime:

```sh
mame_timer_parent=$(mktemp -d /tmp/ti84-mame-timer.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_timer_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_timer_parent/run" --json
```

The Lua adapter maps page-0 RAM at `0xC000` and parks the Z80 in `DI; JR $`.
It then drives ports through the CPU I/O space while MAME's scheduler advances.
Sources `01`, `41`, and `81` each reduce counter `FF` to `EA` during one 20 ms
frame. This is 21 decrements: the initial zero-delay callback plus 20 periods
at 1,024 Hz. The run also records idle counter zero, source-zero disable,
mode-bit masking, inverted interrupt polarity, loop self-clearing, and a mode
write that clears completion for all three timers.

Ports `0x2D`–`0x2F` and `0x40`–`0x48` return zero before and after patterned
writes. Two isolated runs produce byte-identical native reports with SHA-256
`5aab56b737495fef9c953522e1a3eee47d3e96637bc8266ce6258ff10d3e2c26`.
This is MAME 0.287 callback and mapping evidence. It does not execute the TI-OS
timer API or measure physical crystal, RTC, interrupt, or low-power behavior.

## Pinned MAME LCD-controller probe

`mame_lcd.py` parses controller fields, status, pointer walks, read-latch
values, 6-bit packing, and ASIC-port coverage. Its oracle reuses the MAME
profile and pointer/latch models in `lcd_controller.py`:

```sh
mame_lcd_parent=$(mktemp -d /tmp/ti84-mame-lcd.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_lcd_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_lcd_parent/run" --json
```

The Lua adapter parks the Z80 in page-0 RAM. It reads the untouched controller
startup state, then seeds named save items between independent cases. All
controller transfers use the mirrored CPU I/O ports. The run verifies status
`43` at reset, permanent busy-clear status, command decoding, ports `0x12` and
`0x13`, four writes across backing indices 14–17, safe direct indices 15 and
31, the `00 12 34` dummy-read sequence, and `FD 50` from two 6-bit writes.

Port `0x02` returns `C3`. Ports `0x29`–`0x2F` return zero before and after
patterned writes. Two isolated runs produce byte-identical native reports with
SHA-256 `d6930650a96383710be7ebb772675b5a494cba2450827b12a535c963fa464bfc`.
The adapter deliberately omits row 63, column 31 because the source computes
index 976 outside the 960-byte C++ array. This is MAME behavior, not physical
controller or ASIC evidence.

## Pinned MAME ASIC-control probe

`mame_asic.py` combines the reusable ASIC-control and MAME timing profiles with
a typed native report. The Lua adapter drives mapped and absent ports through
the CPU I/O space, runs a fixed RAM counter at both clocks, and schedules one
soft reset:

```sh
mame_asic_parent=$(mktemp -d /tmp/ti84-mame-asic.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_asic_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_asic_parent/run" --json
```

Port-`0x14` writes `00 01 02 3F 40 FF` produce port-`0x02` reads
`C3 C7 CB FF C3 FF`; port `0x14` always reads zero. Port `0x20` retains every
raw byte in `00 01 02 03 FF`. The 50-T-state loop advances 12,000 times in
100 ms at write zero and 30,000 times after write one, matching the source's
6 MHz and 15 MHz clocks.

Port `0x21` accepts writes with the gate closed and reads `value & 0x0F`.
Ports `0x22`–`0x2F` and `0x39`–`0x3A` discard patterned writes. Across
`0x4A`–`0x5B`, only constant reads `0x55 = 0x1F` and `0x56 = 0x00` are mapped.
A soft reset returns to `PC = 0x0000` while retaining gate one, raw speed
`0x03`, and port-`0x21 = 0x0B` from write `0xAB`.

Two isolated runs produce identical canonical parsed native JSON with SHA-256
`bbf6c3c8f05a43daa854f404401aa4d7cd8ed89599c00a2c211541e0416eb3e5`.
This is MAME 0.287 control and reset evidence. It does not establish physical
battery, protection, clock, GPIO, USB, or warm-reset behavior.

## Pinned MAME memory-mapper probe

`mame_mapper.py` parses five fresh-machine reports and checks them against the
MAME profile in `memory_mapper.py`. A fresh process is required for each
fixed-page case because the TI-84 Plus driver does not register `m_booting` as
a saved item. Run the complete guarded matrix through the shared runtime:

```sh
mame_mapper_parent=$(mktemp -d /tmp/ti84-mame-mapper.XXXXXX)
nix shell nixpkgs#mame --command python3 -m ti84re.emulators.mame.run_mapper_probe \
  --expected-mame-sha256 \
    fc5f4aba1aa6eb115d66decad13bb3f5313b9f3be9cff7c785d8d88e3fca0b91 \
  --output-dir "$mame_mapper_parent/run" --json
```

One case reads the untouched reset map through Lua. Lua CPU-program-space
reads carry normal read side effects in this build, so its A read changes the
fixed prefix from page `3F`'s `3E 07` to page `00`'s `DB 02`. Three other
cases execute `LD A,(nn)` from seeded RAM. Independent B leaves page `3F`
fixed; A and paired B select fixed page `00`. The mapping case verifies the
six-bit Flash mask, port-`0x05`'s three-bit mask, adjacent paired pages, and
safe RAM selectors through `0x86`.

Ports `0x0E`, `0x0F`, `0x27`, and `0x28` return zero after patterned writes.
Seeded markers show that reads and writes continue through the underlying B
and C banks. A fetched program returns marker `22` from RAM page 2 rather than
candidate overlay marker `11` from RAM page 1. Selector `0x87` is deliberately
not executed because MAME maps only seven 16 KiB RAM pages.

Two isolated matrices produce identical canonical parsed native JSON with
SHA-256 `6466b5eecedb20332e915337b9e5007a4704af48fc45c26c6ffca1b613910967`.
This is MAME 0.287 mapper evidence. It does not establish physical overlay,
RAM-decoder, or boot-latch behavior.

## Pinned Wabbitemu headless adapter

The repository carries a minimal native adapter rather than a fork of
Wabbitemu. Download and verify the pinned codeload archive, then build through
the guarded CLI. Use `nix develop -c` when `g++` is not installed globally:

```sh
wabbit_tmp=$(mktemp -d /tmp/ti84-wabbitemu.XXXXXX)
curl -L \
  https://codeload.github.com/sputt/wabbitemu/tar.gz/48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422 \
  -o "$wabbit_tmp/wabbitemu.tar.gz"
printf '%s  %s\n' \
  e65e20f5b45dbf5312e92a2619e3fbc0dfe228d4464134753fdc4930b7d12ac4 \
  "$wabbit_tmp/wabbitemu.tar.gz" | sha256sum -c -
tar -xzf "$wabbit_tmp/wabbitemu.tar.gz" -C "$wabbit_tmp"
nix develop -c python3 -m ti84re.emulators.wabbitemu.build_headless \
  --source "$wabbit_tmp/wabbitemu-48c2dc0e6d1d87bb5cf9611efbeb0d048b19c422" \
  --output "$wabbit_tmp/wabbitemu-headless" --json
```

The builder additionally checks the extracted 334-file path-and-content hash
`a8a4f97fc7952770bed317b4a477f80345894da38d14fad8f0bf0ee60aae71ba`
and the translation-unit hashes. It compiles Wabbitemu's TI-84 Plus CPU and
hardware core directly. The adapter removes an MSVC-only `__pragma` construct
at preprocessing time and stubs callbacks used only by the GUI debugger and
disabled audio; it does not patch CPU, Flash, memory, device, keypad,
interrupt, or LCD behavior.

The same binary has an explicit guarded execution-probe mode. The Python CLI
builds exact-ROM fixtures through the shared library, waits for the retail boot
to establish and relock all five protection registers, and then injects the
validated 75-byte probe into physical RAM page 1:

```sh
wabbit_probe_parent=$(mktemp -d)
nix develop -c python3 -m ti84re.emulators.wabbitemu.run_execution_probe \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_probe_parent/run" --json
```

The default page set is `07`, `08`, `09`, `29`, and `2A`. Page `09` separates
Wabbitemu's lower-exclusive Flash predicate from TilEm's inclusive predicate.
The native adapter verifies the marker bytes in the fixture ROM and the
complete logical RAM copy before setting `PC=0x9D95`. Its violation callback
records the event and invokes Wabbitemu's normal `CPU_reset` function. This is
an emulator-core injection, not an OS/UI execution path or physical-hardware
result. The CLI rejects unexpected bounds, mappings, marker values, control
flow, resets, hashes, and classifications.

The binary also exposes a direct Flash byte-program probe. This mode initializes
the core, unlocks its in-memory ASIC gate, and sends `AA 55 A0` plus the target
write through `CPU_mem_write`. It reads the target twice through
`CPU_mem_read`. The guarded CLI requires the exact OS 2.55MP image. It checks
the native report against fixed launch expectations and the independent source
model in `flash_hardware.py`:

```sh
wabbit_program_parent=$(mktemp -d /tmp/ti84-wabbit-program.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_flash_program_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_program_parent/run" --json
```

The default matrix covers three legal requests and four illegal `0→1`
requests, including both initial DQ6 states for one pair. The repeatable
`--case INITIAL:REQUESTED[:TOGGLE]` option replaces the default matrix. The
manifest records the complete native fields plus the ROM and binary hashes.
This mode tests initialized Wabbitemu command-state behavior. It does not run
the retail ROM worker and provides no physical-device or timing evidence.

Run the guarded command-family matrix separately:

```sh
wabbit_command_parent=$(mktemp -d /tmp/ti84-wabbit-command.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_flash_command_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_command_parent/run" --json
```

This mode checks autoselect, reset from autoselect and a partial unlock,
repeated fast programming and exit, one ordinary 64 KiB sector erase, and chip
erase through the native core interfaces. It also verifies that a CFI query
and an erase-suspend/resume attempt create no command state or array mutation.
The sector case seeds its complete expected range plus both adjacent boundary
bytes. The chip case counts the complete array and seeds the last boot-page
byte. All mutations remain in Wabbitemu's allocated Flash array; the source ROM
file is read-only input. The guarded CLI rejects every unexpected state,
identifier, range, mutation count, hash, and T-state count.

Run the guarded retail-worker matrix separately:

```sh
wabbit_worker_parent=$(mktemp -d /tmp/ti84-wabbit-worker.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_flash_worker_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_worker_parent/run" --json
```

This mode boots the exact ROM and injects only `rst 28h`, bcall ID `8087h`,
`HALT`, and one source byte into RAM page 1. It sets the documented ABI
registers and directly opens Wabbitemu's in-memory Flash gate. The retail bcall
copies its original worker from `3F:4CCA` and runs it at `0x8100`. The default
matrix covers legal success, illegal lower-bit false success, illegal DQ7
failure with both stored DQ5 states, and both initial DQ6 states. It does not
exercise the protected unlock sequence, an OS/UI caller, or physical Flash.

Run the bounded failure and restart fixture separately:

```sh
wabbit_failure_parent=$(mktemp -d /tmp/ti84-wabbit-failure.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_flash_failure_fixture \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --expected-binary-sha256 \
    aa3abcc50eb4963a280af9d60c09ed2c260f46709383813b638fbef4c589fed7 \
  --output-dir "$wabbit_failure_parent/run" --json
```

The preflight case calls the exact `ram:02BF` entry with `SP=0xBFFE`. It requires
the gate to remain locked, observes the jump through `ram:02CE` to `ram:0000`,
and compares the complete allocated Flash array with the input before and after
a bounded CPU reset plus retail boot. Numeric status `0` means the expected
failure path, zero Flash differences, and completed restart all passed.

The worker cases have a second guard. They can alter only allocated byte
`0x20100` in the 64 KiB archive sector beginning at `0x20000`. The CLI rejects
targets outside that constant sector and verifies the source-ROM hash again
after execution. The native report also counts changes across the complete
array, the target sector, protected ranges, and all addresses outside the
target byte. It writes only a JSON manifest. Wabbitemu has no byte-program busy
interval, so this is not evidence for an interruption during a physical command.
The required adapter hash rejects any binary other than the documented build.

### Retail Flash bcall usage probe

The programmer-facing examples have a separate assembled probe. The reusable
`flash_bcall_examples.py` library assembles the fixture, parses the native
report, and checks bcall visits, copied-worker entries, return values, scratch
state, array bytes, `_FlashToRam` copies, the port-`0x23` value, and IFF2. The
CLI requires the exact OS 2.55MP ROM and refuses to reuse an output directory:

```sh
python3 -m ti84re.wiki.check_executable_snippets --json

wabbit_bcall_parent=$(mktemp -d /tmp/ti84-wabbit-bcalls.XXXXXX)
nix develop -c python3 -m ti84re.emulators.wabbitemu.run_flash_bcall_probe \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_bcall_parent/run" --json
```

The 2026-08-10 run assembled 264 bytes, booted the retail ROM for 134,845 CPU
steps, and completed the injected probe in 4,346 steps. It visited every public
modifying Flash entry plus `_SetFlashLowerBound`. The shared
`_WriteFlashUnsafe`, `_WriteAByte`, and `_EraseFlash` bodies ran four, two, and
three times as their wrappers converged. Seven `_FlashToRam` calls brought the
RAM-worker-entry count to 14.

Both block writes, both byte writes, `_EraseFlashPage`, and `_EraseFlash`
returned `AF=0x0044`. The safe block stored `A5 5A` at `08:4100`; the unsafe
block stored `3C C3` at `3E:4100`. The byte entries stored `FC` at `08:4102`
and `F8` at `3E:4102`. The page, raw, and certificate erases produced `FF` at
`0C:4000`, `10:4567`, and `3E:6001`. All seven array results matched their
readback buffers. `_EraseCertificateSector` preserved seeded `AF=0xA545` for
`HL=0x6001`; `OP1=0xF8`, the context scratch bit was clear, port `0x23` held
`0x2A`, and IFF2 was clear after `_SetFlashLowerBound`.

The assembly-source SHA-256 was
`ba91fa8a4d1d7c816b742a426dbb0216f927ec209f368534a13748d4683b42e7`,
the machine-code SHA-256 was
`8f9ca5975c418871ba831c3536cba6e7e4f9f368520e1ad37650ef9c54d9249c`,
and the rebuilt adapter SHA-256 was
`6dec9c4f4a87466a27baa5e5e4fc90c644506d0a90baa9278d17407b9bc9dd36`.
The runner directly opens only Wabbitemu's in-memory gate and seeds disposable
array bytes. This is exact retail-ROM execution under a pinned emulator, not a
test of the protected unlock sequence, OS allocation or journaling, power loss,
timing, or physical Flash.

Run the guarded Wabbitemu MD5 edge probe through the same binary:

```sh
wabbit_md5_parent=$(mktemp -d /tmp/ti84-wabbit-md5.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_md5_edge_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_md5_parent/run" --json
```

This direct-core mode reads the fresh operand and result ports, writes one,
three, four, and five bytes to one sliding operand, sends high control bits,
and mutates an operand between result-byte reads. The reusable oracle checks
every result with `md5_assist_value`. This is initialized Wabbitemu device
behavior, not retail-ROM execution, physical ASIC behavior, or timing
evidence.

Run the guarded keypad and ON-edge probe through the same binary:

```sh
wabbit_keypad_parent=$(mktemp -d /tmp/ti84-wabbit-keypad.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_keypad_edge_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_keypad_parent/run" --json
```

This initialized-core mode checks a single key, same-column keys in two
selected rows, a three-key rectangle, a transitive chain, and ignored row 7.
It also reads port `0x04` around ON press, acknowledgement while held, release,
and a second press. The probe invokes Wabbitemu's standard-interrupt device
callback at explicit observation points and advances no T-states. Its results
therefore establish emulator state transitions, not TI-OS execution, physical
electrical behavior, or timing.

Run the guarded programmable-timer and RTC edge probe through the same binary:

```sh
wabbit_timer_parent=$(mktemp -d /tmp/ti84-wabbit-timer.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_timer_edge_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_timer_parent/run" --json
```

This initialized-core mode advances Wabbitemu's emulated crystal ticks,
T-states, and elapsed seconds explicitly. It compares crystal and CPU catch-up,
expires a zero counter, acknowledges completion, observes the interrupt line
during and after `HALT`, and commits, advances, and freezes the RTC. The
reusable oracle derives source divisors and expiry fields from
`timer_hardware.py`. This is emulator state-machine evidence rather than
TI-OS execution, host timing, or physical ASIC behavior.

Run the assembled programmable-timer physical discriminator through the shared
injected-program runner:

```sh
wabbit_timer_physical_parent=$(mktemp -d /tmp/ti84-wabbit-timer-physical.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_timer_physical_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --expected-binary-sha256 \
    3acb6a18280f9c42d6fe324188eab73f87280ee70b973e1251fcfa50f54fb14e \
  --output-dir "$wabbit_timer_physical_parent/run" --json
```

This mode boots the retail OS, injects the exact `HWTMR` image into logical
user RAM, and stops before `_CreateAppVar`. It verifies the probe ID, frame
length, Wabbitemu-specific timer classifications, and complete guarded-state
restoration. The same native runner handles `HWPFX`; its shared injection,
execution-limit, stop-address, frame, and violation-reset checks avoid a second
probe-specific control path. The retained manifest identifies the ROM, binary,
machine code, runtime counters, decoded frame, and evidence scope. No result
from a physical calculator is implied.

Run the controlled retail USB boot paths through the same binary:

```sh
wabbit_usb_rom_parent=$(mktemp -d /tmp/ti84-wabbit-usb-rom.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_usb_rom_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --expected-binary-sha256 \
    3acb6a18280f9c42d6fe324188eab73f87280ee70b973e1251fcfa50f54fb14e \
  --output-dir "$wabbit_usb_rom_parent/run" --json
```

This mode boots the retail ROM and uses short RAM-resident bcall harnesses for
`_InitUSB` and `_AttemptUSBOSReceive`. Controlled handlers replace only the
USB controller and endpoint ports. Four constant-memory summaries report
success, handshake timeout, frame timeout, and event-`0x40` dispatch. The
runner retains counters and at most 128 port writes per case instead of an
instruction log. It also compares the complete Flash image and stops before
endpoint payload handling. The result is controlled ROM-execution evidence,
not connected-device, PHY, or physical-calculator evidence.

Continue into the installer record dispatcher with exact scripted endpoint
packets:

```sh
wabbit_usb_receive_parent=$(mktemp -d /tmp/ti84-wabbit-usb-receive.XXXXXX)
nix develop -c python3 -m ti84re.emulators.wabbitemu.run_usb_receive_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --expected-binary-sha256 \
    3acb6a18280f9c42d6fe324188eab73f87280ee70b973e1251fcfa50f54fb14e \
  --output-dir "$wabbit_usb_receive_parent/run" --json
```

This constant-memory mode validates the ROM's type-`0x04` request, the host
type-`0x05` acknowledgement, service `0x0005`, page `0x3E`, record dispatch,
page rejection, error cleanup, and the complete unchanged Flash array. It
seeds the already-displayed progress page immediately before
`_DisplayOSProgress` to isolate the downstream rejection; the manifest records
that intervention. The adapter retains three received packets, two transmitted
packets, fixed boundary counters, and the final state instead of a textual
instruction log.

## Pinning jsTIfied source behavior

The Cemetech project page identifies jsTIfied, but the reusable profile checks
the deployed JavaScript itself. Download and verify the exact `20170706a`
artifact with:

```sh
nix develop -c curl -L \
  'https://www.cemetech.net/projects/jstified/jstified_compressed.js?20170706a' \
  -o /tmp/jstified_compressed.js
nix develop -c env PYTHONPATH=tools python \
  python3 -m ti84re.emulators.describe_jstified /tmp/jstified_compressed.js --json
```

`tools/ti84re/emulators/jstified.py` requires size 297,128 and SHA-256
`c7325a38f976f64eaa34182da17d838fe4831eece4650b92d5db710cf7a8fc5b`,
then verifies source fingerprints for Flash commands, mapping, execution
protection, timers, LCD, link assist, and fixed USB reads. Its feature profile
is source evidence for a fourth emulator. The readable GitHub mirror at commit
`56246a1181f90123a843ea17eb9e0f2fcda65113` aids review but is explicitly not
treated as byte-identical to the deployed artifact.

Run the guarded ASIC-control edge probe through the same binary:

```sh
wabbit_asic_parent=$(mktemp -d /tmp/ti84-wabbit-asic.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_asic_edge_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_asic_parent/run" --json
```

This initialized-core mode reads port `0x02` across the in-memory Flash gate,
changes Wabbitemu's RAM revision for port `0x15`, and checks port `0x21` while
locked and directly unlocked. It reports both port-`0x21` readback and the
internal Flash-group and RAM-execution fields, making the readback defect
observable. It also distinguishes absent port `0x39` from the byte latch at
port `0x3A`. This is emulator state evidence, not a retail protected-byte
sequence or physical battery, identity, protection, or GPIO evidence.

Run the guarded protected-boundary port probe through the same binary:

```sh
wabbit_protected_port_parent=$(mktemp -d /tmp/ti84-wabbit-protected-port.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_protection_port_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_protected_port_parent/run" --json
```

This initialized-core mode checks registration and the shared locked-write
gate at ports `0x22`–`0x26`. After opening the emulator's in-memory gate, it
checks low-byte preservation, port-`0x24` high-field clearing, and the
`0x3F`/`0x40`/`0x41`/`0xFF` RAM-bound wrap matrix. Its reusable oracle is
backed by `execution_protection.py`. Direct lock and high-field changes isolate
the registered handlers; they do not execute the retail protected-byte
sequence, fetch through the resulting bounds, or measure physical behavior.

Run the guarded LCD-controller and bus-timing edge probe through the same
binary:

```sh
wabbit_lcd_parent=$(mktemp -d /tmp/ti84-wabbit-lcd.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_lcd_edge_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_lcd_parent/run" --json
```

This initialized-core mode checks the fixed controller guard at 59 and 60
T-states, an early rejected write, hidden-column increment and alias behavior,
the data-read latch, absent ports `0x12` and `0x13`, and the reset-status
`word_len` defect. It also checks the strict 240-T-state ready boundary,
read-versus-write timestamp policy, active LCD instruction delay, all six
memory-wait fields, and default speed clamp. The reusable oracle derives the
expected pointer, latch, ready, wait, and speed results from
`lcd_controller.py` and `bus_timing.py`. This is Wabbitemu state-machine
evidence, not TI-OS execution, host timing, or physical LCD/ASIC behavior.

Run the guarded CPU-speed and delay-register edge probe through the same
binary:

```sh
wabbit_speed_parent=$(mktemp -d /tmp/ti84-wabbit-speed.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_speed_edge_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_speed_parent/run" --json
```

This initialized-core mode checks reset readback, the default 6/15 MHz speed
clamp, the internally enabled 20/25 MHz modes, raw readback across ports
`0x29`–`0x2F`, and all four Flash/RAM wait-gate combinations. It also verifies
that Wabbitemu's generic port-`0x2D` latch does not change its timer, LCD,
`HALT`, interrupt, frequency, or T-state state. The reusable oracle derives
speed and wait fields from `bus_timing.py`. Directly setting
`timer_version = 1` represents front-end configuration, not a calculator port.
This is emulator-handler evidence, not TI-OS execution, electrical timing, or
physical low-power behavior.

Run the guarded standard-interrupt and low-power edge probe through the same
binary:

```sh
wabbit_interrupt_parent=$(mktemp -d /tmp/ti84-wabbit-interrupt.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_interrupt_edge_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_interrupt_parent/run" --json
```

This initialized-core mode checks full port-`0x03` readback, ON-latch
acknowledgement, all four standard-timer rates, the strict timer-expiry edge,
port-`0x03` and port-`0x02` timer catch-up, programmable completion bits, and
Wabbitemu's LCD-based low-power approximation. Its reusable oracle derives
mask and status fields from `interrupt_controller.py`. This is emulator
state-machine evidence, not TI-OS execution, host timing, physical interrupt
edges, or ASIC power-domain behavior.

Run the guarded raw-link and link-assist edge probe through the same binary:

```sh
wabbit_link_parent=$(mktemp -d /tmp/ti84-wabbit-link.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_link_edge_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_link_parent/run" --json
```

This initialized-core mode checks all 16 local/peer raw-line combinations,
high write-bit masking, raw transition interrupt omission, assist port
coverage, idle-ready, one complete `0xA5` send and receive, data-register
acknowledgement, and seeded-error read-to-clear behavior. The reusable oracle
derives the raw matrix, LSB-first byte order, and status fields from
`link_port.py`. It does not run TI-OS, exercise virtual-cable lifecycle code,
or measure electrical levels and timing.

Run the guarded Fake USB edge probe through the same binary:

```sh
wabbit_usb_parent=$(mktemp -d /tmp/ti84-wabbit-usb.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_usb_edge_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_usb_parent/run" --json
```

This initialized-core mode checks mapped and absent ports, reset reads and
internal fields, event-mask storage, mask-independent and repeatable line
events, the active-low interrupt-summary matrix, and the protocol-enable and
device-address latches. Direct field seeding isolates the port-`0x4A` and
port-`0x4D` handler arithmetic that registered ports cannot otherwise reach.
The reusable oracle in `wabbitemu_usb_probe.py` derives every expected value
from `usb_hardware.py`. This is pinned Wabbitemu handler evidence, not TI-OS
execution, a connected endpoint transaction, or physical USB behavior.

Run the guarded memory-mapper edge probe through the same binary:

```sh
wabbit_mapper_parent=$(mktemp -d /tmp/ti84-wabbit-mapper.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_mapper_edge_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output-dir "$wabbit_mapper_parent/run" --json
```

This initialized-core mode checks mapper-port registration, reset mapping,
the fixed-page opcode handoff, raw selector storage versus visible readback,
the even-page paired expression, and both forced-RAM ranges. Seeded backing
bytes distinguish boundary reads, low-level write destinations, and fetched
NOP versus HALT bytes in independent and paired modes. The reusable oracle in
`wabbitemu_mapper_probe.py` derives the expected mappings from
`memory_mapper.py`. This is pinned emulator routing evidence, not TI-OS
execution, Flash command acceptance, or physical ASIC behavior.

Run the guarded reset-retention probe through the rebuilt binary:

```sh
wabbit_reset_parent=$(mktemp -d /tmp/ti84-wabbit-reset.XXXXXX)
python3 -m ti84re.emulators.wabbitemu.run_reset_retention_probe \
  --rom tools/rom.bin \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --expected-binary-sha256 \
    386be74e738f2a0f9ad17f12bae4cd44994b5a73835ab10d488c7b8232afd87e \
  --output-dir "$wabbit_reset_parent/run" --json
```

This mode seeds state directly, calls `CPU_reset`, performs the frontend's
`CPU_reset` plus LCD-reset sequence, and triggers two execution violations.
The reusable source model in `wabbitemu_reset.py` separates cleared, rebuilt,
and retained fields. Its oracle checks all 14 retained component groups, the
TI-84 Plus reset mapping, LCD-visible frontend state, and the program/error
Flash-state paths through the remainder of `CPU_step`. The CLI guards the exact
ROM and native-binary hashes. It does not run TI-OS reset code or measure
physical reset and power-loss retention.

Run one replayed image with an input-identity guard and a separate output:

```sh
python3 -m ti84re.emulators.wabbitemu.run_headless "$replay_dir/gc-phase-ff.rom" \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output "$wabbit_tmp/gc-recovered-ff.rom" \
  --expected-input-sha256 \
    4e484ad4b99f07a333ae3845ee795b36cb6181e9a829261b2d52ff7931ac8f05 \
  --expected-output-sha256 \
    8c857701d7da118d5c5f4c240ee21af91a10b95539059e74fb5e423368a683f9 \
  --expect-gate-write '3F:4163:01:1>0' \
  --expect-gate-write '3F:4221:00:0>1' \
  --expect-gate-write '3D:60A6:01:1>0' \
  --expect-gate-write '3D:5CEF:00:0>1' \
  --require-retail-flash-path \
  --json
```

The runner starts with fresh RAM, models the ON press/release used by the TilEm
recovery macro, samples the entire Flash array while executing, and reports
the known page-`0x3C` recovery points it executes. The repeated gate-write
options require the complete ordered list, including the boot-page pair and
the recovery unlock/relock pair. `--require-retail-flash-path` requires an
accepted unlock and relock, matching `_WriteFlashUnsafe` and byte-identical
copied-worker entry counts, at least one program write per worker, one success
tail per worker, and no failure tail. Settling means ten identical samples one
million instructions apart after at least 20 million instructions; it is not
a physical timing claim. Compare the reported complete output hash, not only
the phase byte.

The recovery path begins at the startup call at `00:0D73`. Its bjump stub
enters `3D:6098`, whose protected bytes unlock at `3D:60A6`. The wrapper calls
the `00:2BAD` bjump stub to reach `3C:7BC7`, then jumps to the shared page-`3D`
lock sequence after recovery returns. The native report represents each gate
write and lock transition as typed JSON fields. It also reports separate
counts for public write/erase bcalls, exact block-worker entries, data writes,
and success/failure reset tails.

The reconstructed phase-`0xF0` image executes the `3C:7CE3` branch and settles
after 20,000,000 instructions. Its output SHA-256 is
`39113ee67921340b8817e35576a8f8fda467122af7713b099f399512d65d9bc3`.
Capture and replay the matching TilEm recovery before comparing complete
outputs:

```sh
$TILEM --headless --rom "$phase_dir/gc-phase-f0.rom" \
  --model ti84p --normal-speed --reset \
  --macro tools/macros/boot-recovery.macro \
  --trace /tmp/gcf0-restart.trace --trace-range all

python3 -m ti84re.flash.replay_trace /tmp/gcf0-restart.trace \
  --rom "$phase_dir/gc-phase-f0.rom" \
  --expected-rom-sha256 \
    df49d6ec77483e33944fdbcee969084fc065b01a4e44327f83246a9de363fcb2 \
  --output /tmp/gcf0-recovered-tilem.rom \
  --accept-command-shapes --json

python3 -m ti84re.emulators.wabbitemu.run_headless "$phase_dir/gc-phase-f0.rom" \
  --binary "$wabbit_tmp/wabbitemu-headless" \
  --output "$wabbit_tmp/gc-recovered-f0.rom" \
  --expected-input-sha256 \
    df49d6ec77483e33944fdbcee969084fc065b01a4e44327f83246a9de363fcb2 \
  --json

python3 -m ti84re.flash.compare_images \
  "$wabbit_tmp/gc-recovered-f0.rom" /tmp/gcf0-recovered-tilem.rom \
  --expected-left-sha256 \
    39113ee67921340b8817e35576a8f8fda467122af7713b099f399512d65d9bc3 \
  --expected-right-sha256 \
    39113ee67921340b8817e35576a8f8fda467122af7713b099f399512d65d9bc3 \
  --expect-equal --json
```
