# Resident assembly programs

TI-OS copies a compiled assembly program to `userMem` (`0x9D95`), executes it,
and removes that copy when it returns. This page documents the OS 2.55MP launch
path, the memory limit enforced by the ROM, pointer stability during variable
allocation, and archived-data access for long-running runtimes. It also
compares third-party launchers' movement, archive-writeback, and cleanup
policies.

## Compiled `Asm(` launch

The compiled-program path starts at `_ExecutePrgm` (`07:5758`). [confirmed]
The routine finds the program, reads its two-byte internal data size, and
requires the `BB 6D` marker at the start of that data. The following steps are
visible at `07:5762`–`07:57D1`:

1. `07:5766` loads the internal data size into `BC`.
2. `07:576A` and `07:5771` check the `BB 6D` marker.
3. `07:577B` subtracts the internal size from `0x2000` and raises an error on
   borrow.
4. `_ErrNotEnoughMem` at `ram:1735` checks that the complete internal size fits
   in free RAM.
5. `_InsertMem` at `ram:0F81` opens that many bytes at `ram:9D95`.
6. `07:579C` adds the allocation size to the saved source pointer because the
   insertion moved the source variable upward.
7. The `LDIR` at `07:579D` copies to `ram:9D95`.
8. `07:57FD` jumps to `ram:9D95` through the error-context wrapper at
   `ram:27DA`.

The internal size excludes the variable's two-byte size field. It includes the
two-byte `BB 6D` marker. The largest marker-plus-payload value accepted by this
path is therefore `0x2000`, leaving at most `0x1FFE` bytes after the marker.
[confirmed]

| Quantity | Maximum |
|---|---:|
| Internal program-data size | `0x2000` = 8,192 bytes |
| `BB 6D` marker inside that size | 2 bytes |
| Bytes after the marker inside the variable | `0x1FFE` = 8,190 bytes |
| Execution allocation | `0x2000` = 8,192 bytes |
| Last allocated byte | `ram:BD94` |
| Full `ram:9D95`–`ram:BFFF` span | `0x226B` = 8,811 bytes |

The often-quoted 8,811-byte span describes the address range through
`ram:BFFF`; it is not this launcher's accepted-size limit. The launcher leaves
the final 619 bytes of that span outside its maximum allocation. [confirmed]

The copy begins after the `BB 6D` marker but uses the complete internal size as
its length. It consequently reads two bytes beyond the size-described program
data. Those bytes occupy the final two bytes of the execution allocation.
[confirmed] A boundary fixture should place guard bytes after the variable to
record their exact values at `ram:BD93` and `ram:BD94`.

The builders and TilEm runner in `tools/launch-fixtures/` exercise the three
adjacent boundary sizes. Each accepted trace reaches `_ExecutePrgm`, the limit
test, the `_InsertMem` call site, the payload handoff, and `ram:9D95`. The
rejected trace reaches the `E_Invalid` shim at `ram:2729` before insertion.
[confirmed]

`tools/data/launch-boundary-results.csv` records the ROM, fixture, and trace
hashes together with instruction counts and reached checkpoints. [confirmed]

| Internal size | Bytes after marker | TilEm result |
|---:|---:|---|
| `0x1FFF` | 8,189 | Accepted |
| `0x2000` | 8,190 | Accepted |
| `0x2001` | 8,191 | Rejected with `ERR:INVALID` |

Internal sizes of 8,808–8,814 bytes are all above this ROM limit, so they cannot
distinguish the boundary. The fixture uses adjacent sizes instead.

## Text `AsmPrgm` launch

The `BB 6C` text path begins at `07:57D4`. `07:5717`–`07:5731` counts decoded
hex-byte pairs while ignoring `?` separators, then applies the same `0x2000`
limit to the decoded length. `_InsertMem` allocates that decoded length and
`07:5734`–`07:5755` writes the decoded bytes at `ram:9D95`. [confirmed]

The source variable remains in RAM while the execution gap exists. Its hex
text and the decoded copy both consume free memory, so `_EnoughMem` may impose
a lower practical limit than the ROM's 8,192-byte decoded cap. [confirmed]

## Return and error cleanup

`asm_prgm_size` at `0x89EC` records the execution allocation length. Normal
return clears it at `07:57C4`–`07:57CB`, then calls `_DelMem` with
`HL=ram:9D95` at `07:57CE`–`07:57D1`. The error handler at
`07:5800`–`07:581A` performs the same clear and deletion before entering the OS
error path. [confirmed]

An assembly program must not move its execution copy. `_InsertMem` and
`_DelMem` repair OS pointer slots and VAT data pointers, but they cannot repair
the program counter, return addresses, or arbitrary runtime pointers. Cleanup
also assumes that the copy still begins at `ram:9D95`. [confirmed]

## Observed handoff state

A headless TilEm trace of `Asm(prgmASMRET)` on a TI-84 Plus with OS 2.55MP
reaches `asm_payload_handoff` at `07:57B4`, then executes `RET` at logical
`0x9D95`. TLMT instruction records contain the register state after the named
instruction. The `CALL 07:57FD` record at `07:57B4` and the `JP ram:9D95`
record at `07:57FD` both report payload-entry `SP=0xFFC9`. The `RET` record at
`ram:9D95` reports `SP=0xFFCB` after popping the launcher return. [confirmed]

| Register | Post-instruction `RET` record at `ram:9D95` |
|---|---:|
| `AF` | `0x01BB` |
| `BC` | `0xFCCD` |
| `DE` | `0xFFEC` |
| `HL` | `0x57B4` |
| `SP` | `0xFFCB` |

These registers are observations, not an ABI. The payload should initialize
every register it needs and return with the hardware stack balanced.

The trace resolver may label the first instruction `page_??:5D95` when no
port-7 write has occurred since capture began. The logical PC is `0x9D95`, and
the launcher's `JP 0x9D95` establishes that the instruction is in RAM. This is
a trace-reconstruction limitation. [confirmed]

## Timed heap and stack snapshots

The `RTSNAP` fixture records the heap fields from inside the payload, while a
TLMT v2 replay applies every logical-memory write and samples the same fields
at OS-side checkpoints. The trace used TI-84 Plus OS 2.55MP, an unarchived
compiled program launched by `Asm(prgmRTSNAP)`, and the ROM with SHA-256
`dbb47afae091ab36f9abe74e32083013fbeff3d7e0516bbf5d1abf4ee57adc09`.
[confirmed]

That complete-image identity is the BootFree 11.259 variant, not the canonical
retail-boot image. The launch implementation on Flash page `0x07` is
byte-identical in both images; page `0x07` has SHA-256
`6335c5f15cb5d534423b8d018dd412d21905e5ca448cc3f84d6c53d15b3aa60e`.
The trace therefore supports the page-`0x07` launch result, but no retail-boot
claim. [confirmed]

| Checkpoint | `FPS` | `OPS` | `pTemp` | `progPtr` | `SP` | `_MemChk` |
|---|---:|---:|---:|---:|---:|---:|
| `_ExecutePrgm` entry | `0x9FFA` | `0xFCBA` | `0xFCCE` | `0xFD34` | `0xFFD7` | `0x5CC1` |
| First payload instruction | `0xA171` | `0xFCBA` | `0xFCCE` | `0xFD34` | `0xFFC9` | `0x5B4A` |
| Nested `_MemChk` entry | `0xA171` | `0xFCBA` | `0xFCCE` | `0xFD34` | `0xFFC3` | `0x5B4A` |
| Final payload `RET` (post-instruction) | `0xA171` | `0xFCBA` | `0xFCCE` | `0xFD34` | `0xFFCB` | `0x5B4A` |
| Cleanup entry | `0xA171` | `0xFCBA` | `0xFCCE` | `0xFD34` | `0xFFD7` | `0x5B4A` |
| Cleanup return | `0x9FFA` | `0xFCBA` | `0xFCCE` | `0xFD34` | `0xFFD9` | `0x5CC1` |

`fpBase` moves from `0x9FE8` to `0xA15F`, and `FPS` moves from `0x9FFA`
to `0xA171`. Both shifts are the fixture's `0x0177`-byte internal program
size. `OPBase`, `OPS`, `pTemp`, `progPtr`, and `symTable` remain unchanged at
these checkpoints; cleanup restores the two shifted fields. The nested bcall
uses six more stack bytes than payload entry, but does not change the measured
heap pointers or `_MemChk`. [confirmed]

The fixture, decoder, analyzer, capture recipe, and compact provenance rows are
under `tools/launch-probes/` and `tools/data/resident-launch-snapshot.csv`.
These observations do not establish an entry ABI or cover `_ExecAsm`, an
archived launcher path, shell launchers, other OS releases, or hardware.
[confirmed]

## Free RAM and stack headroom

`_MemChk` at `ram:0E20` returns `(OPS - FPS) + 1` when `OPS >= FPS`; otherwise
it returns zero. `_EnoughMem` at `ram:0FA6` compares a request with that result
and may delete reclaimable temporary variables before retrying. [confirmed]

Neither routine reads the hardware `SP`. The launch capacity check therefore
does not reserve hardware-stack headroom or detect a collision between the Z80
stack and OS data. [confirmed] A resident runtime must impose its own stack
limit or guard region. The available margin depends on current VAT and
temporary state, so a single OS-wide stack-headroom number is not supported.

## Variable relocation while resident

`_InsertMem` and `_DelMem` move the OS data region and update a fixed set of
OS-owned pointers. The repair list includes `iMathPtr1`–`iMathPtr5`,
`asm_data_ptr1`, `asm_data_ptr2`, `newDataPtr`, and other delete, edit, and
floating-output pointers. The VAT scan adjusts a data pointer only for a RAM
entry whose data lies on the moved side of the gap. Archived entries are not
RAM-relocated. [confirmed]

The repair code does not scan arbitrary memory for pointers. A runtime's
absolute pointer into a program, AppVar, or workspace can become stale after a
create, delete, resize, archive, unarchive, temporary cleanup, variable receive,
or archive garbage collection. [confirmed]

## Explicit source writeback

Changing bytes in the direct `Asm(` execution copy does not change the named
program variable. RUNCOUNT 16, whose release describes itself as
self-modifying, handles that distinction explicitly: it relies on OP1 still
naming the running program, calls `_ChkFindSym`, and increments two BCD counter
bytes through the returned source pointer. It performs a second lookup before
converting the counter to `Ans`. [confirmed] for the identified community
source.

The raw 136-byte source build is SHA-256
`3e506c4330cd5499a031ae56c73d0487f811278b5fc3d52949bc0f56a69b2f05`.
The packaged program body is exactly `BB 6D` followed by that build, so this
writeback design is also confirmed for the identified release binary. The
archive `programs/runcounter16.zip` has SHA-256
`736212242e2e9a97e90908ce42fa051b27dff52a84ef1141546d58cd4e5eaf08`;
member `Source/RunCounter16.z80` has SHA-256
`2ea3efc9d4764813f6f57fa19ae4a3564ef2f3855f4daf997619ff29f54316d5`,
and `RUNCOUNT.8xp` has SHA-256
`41615816759a6cb2df1aee41f906956a6823aa09c19e4ec8e79712868c1d889a`.
[confirmed]

An instrumented TI-84 Plus OS 2.55MP direct `Asm(` run executes this packaged
program twice. Both passes reach the store at `ram:9DAC`; `_ChkFindSym` returns
the named RAM source at `ram:9EC5`, and the attributed writes store `1`, then
`2`, there. The result dynamically confirms explicit source writeback for this
unarchived route rather than mutation of the separate execution copy. The ROM,
program, wrapper, macro, emulator, and trace hashes are pinned in
`tools/data/community-loader-traces.csv`. [confirmed]

The source does not test the returned page byte in `B`. Its direct store is
therefore supported only when lookup returns a RAM source. An archived source
or a shell that moves the named body can produce a Flash pointer or a
shell-defined in-flight representation instead. Persistent self-modification
must follow the launcher's lookup and writeback contract, not merely reuse this
fixed-offset pattern. [confirmed] for the missing guard; [hypothesis] for
untraced launcher outcomes.

Repeating the same link-only fixture with RUNCOUNT's archive flag set does not
reach `ram:9D95` under this OS and headless launch macro. It therefore confirms
non-execution for that exact emulator scenario, not the result of an archived
source store. Shell-mediated archived launches remain open. [confirmed] for
the observed boundary.

## Resident allocation trace

The fixture under `tools/allocation-probes/` calls `_EnoughMem`,
`_CreateAppVar`, `_DelVar`, `_CreateProg`, `_InsertMem`, and `_DelMem` from a
compiled program at `ram:9D95`. Its trace replays RAM writes at ten timed
checkpoints. [confirmed]

A 32-byte AppVar or program moves `FPS` from `0xA076` to `0xA098` and `OPS`,
`OPBase`, and `pTemp` downward by 12 bytes. `_MemChk` falls from `0x5C44` to
`0x5C16`. Deleting either object restores all recorded heap pointers.
[confirmed]

The direct `_InsertMem` probe opens 16 bytes at the source variable's data
pointer. `_ChkFindSym` then returns `0x9F3B` instead of `0x9F2B`. `_DelMem`
restores `0x9F2B`. An eight-byte guard in the execution copy remains unchanged,
and every payload checkpoint remains at its assembled `ram:9D95`-relative
address. TI-OS repairs the source VAT pointer; it does not move the executing
copy. [confirmed]

The ROM repair pass at `ram:11E8`–`ram:128A` conditionally adjusts 24 OS pointer
slots. Named slots include `iMathPtr1`–`iMathPtr5`, `asm_data_ptr1`,
`asm_data_ptr2`, `fmtMatMem`, `newDataPtr`, `EQS`, `insDelPtr`, `editDat`,
`chkDelPtr1`, `chkDelPtr2`, `XOutDat`, `YOutDat`, `fOutDat`, and `inputDat`.
The adjacent pass at `ram:11C7` repairs `basic_start`, `nextParseByte`, and
`basic_end`. The VAT scan at `ram:139D` repairs each affected RAM entry's data
pointer. [confirmed]

The reset-state run, with only the required wrapper and probe variables,
measures `_MemChk=0x5C44` before its maximum AppVar.
For the five-character name `ALMAX`, `_CreateAppVar` consumes a 14-byte
overhead: two data-size bytes plus a 12-byte VAT entry. A payload request of
`0x5C36` succeeds, producing `FPS=0xFCAE`, `OPS=0xFCAD`, and `_MemChk=0`.
The hardware stack remains at `SP=0xFFC9`; the creator does not include that
remaining stack-to-VAT distance in its capacity decision. [confirmed]

`tools/data/resident-allocation.csv` records the checkpoints, ROM and trace
hashes, model, and OS version. This run covers the direct-`Asm(` reset state.
It does not measure representative user-variable populations, shell
move-loaders, Flash Apps, or physical hardware. [confirmed]

## Stable RAM AppVar protocol

A long-running runtime can use a RAM AppVar as a movable workspace if it treats
the VAT lookup as a handle operation:

1. Keep the AppVar name and expected type in program-owned storage.
2. Rebuild OP1 and call `_ChkFindSym` immediately before access.
3. Require carry clear and `B=0`. `DE` points to the two-byte data-size field;
   the payload begins at `DE+2`.
4. Do not retain `DE`, the payload base, or an interior pointer across a call
   that can move variables or reclaim temporaries.
5. Reacquire the base afterward. Store internal references as offsets from the
   payload base.
6. If a stored image contains absolute pointers, relocate every pointer after
   reacquisition and before use.

This protocol keeps no data pointer across a moving operation; it does not make
an update transactional. A reset-tolerant format can add a version, length,
checksum, and commit marker. Two records or copy-on-write storage can preserve
the last committed generation during an interrupted update.

## Archived lookup contract

The VAT scanner reached through `_ChkFindSym` returns the archive page in `B`
and the data pointer in `DE`. [confirmed]

| Result | Meaning |
|---|---|
| Carry set | No matching VAT entry |
| Carry clear, `B=0` | `DE` is a RAM pointer to the two-byte data-size field |
| Carry clear, `B!=0` | `B:DE` identifies Flash data through bank A |

An archived `DE` value is not a flat RAM pointer. Direct access must preserve
port `0x06`, map page `B`, handle the `0x8000` → next-page crossing, and restore
the caller's mapping. Any operation that can run archive garbage collection
invalidates a saved `B:DE`; call `_ChkFindSym` again afterward. [confirmed]

## Streaming archived data

The three useful access strategies have different memory and paging costs:

| Strategy | Full object must fit free RAM | Page crossing | Bank-A restoration |
|---|---|---|---|
| Direct page mapping | No | Caller handles it | Caller handles it |
| Chunked `_FlashToRam` | No | OS handles it | OS restores port `0x06` |
| `_Arc_Unarc`, then RAM access | Yes | OS handles it | Not exposed |

`_FlashToRam` has bcall ID `5017h` and body `3D:6745`. Its copier saves port
`0x06`, maps the source page, advances from `0x8000` to `0x4000` on the next
Flash page, and restores the saved mapping. A streaming interpreter can copy
repeated bounded chunks into a RAM buffer and process a source larger than free
RAM. [confirmed]

`_Arc_Unarc` at `07:6248` enters the unarchive path at `07:61F4` when `B` is
nonzero. Unarchiving requires enough RAM for the complete variable and cannot
stream an object larger than free RAM. [confirmed]

Direct mapping and `_FlashToRam` reads do not themselves make a saved archive
location stable. Reacquire it after an operation that may write or collect the
archive.

## Shell loaders and writeback

Ion, Plasma, TSE, MirageOS, Doors CS, and zStart all place assembly code at
`userMem` (`0x9D95`), but they do not preserve the source variable in the same
way. This section compares their RAM cost, writeback policy, lookup behavior, and
cleanup contract using identified original releases.

### Comparison

| Launcher | RAM-resident input | Archived input | Archive writeback | Error cleanup |
|---|---|---|---|---|
| Ion 1.6 | Moves the original body | Unarchives the original, then moves its body | Always rearchives | No Ion-owned error handler |
| Plasma 1.4 | Copies the body into the current `userMem` execution allocation | Copies the body from Flash with `_FlashToRam` | None; clients can save to an AppVar | No Plasma-owned error handler |
| TSE 1.5/1.6 | Moves the active body and task state between the variable and `userMem` | Unarchives the original, then uses the RAM task path | Leaves the program in RAM | Cooperative switch and exit paths only |
| MirageOS 1.2 | Uses a symmetric move loader | Creates a named `TempProgObj` RAM copy, then moves its body | Rewrites only if changed | Installs an OS error handler |
| Doors CS 7.4 | Moves the original body | Creates a complete RAM variable under a derived temporary name | Compares the temporary variable with the archive; replaces the archive only if changed | Routes OS errors through reverse-swap cleanup |
| zStart 1.3.013 | Moves the original body | Copies the body into a raw `userMem` allocation | Uses a 16-bit checksum; replaces the archive only if changed | Routes OS errors through local cleanup |

The three source-available move loaders show that “run at `userMem`” does not
imply “make a second complete copy.” Ion, Doors CS, and zStart move a
RAM-resident body in chunks through a 768-byte shuttle. Plasma copies the body
and relocates its shell tail around it. TSE moves the body together with an
appended task-state area. Archived inputs also differ: Ion and TSE first
unarchive the original, MirageOS and Doors CS build named temporary variables,
Plasma copies from Flash into its current execution allocation, and zStart
builds an unnamed execution allocation. [confirmed]

The source identity, execution strategy, and open evidence boundary for the
original four comparison rows are also recorded in
`tools/data/shell-loader-observations.csv`. Plasma and TSE are pinned below by
release-archive and member hashes.

### The move-loader pattern

Ion, Doors CS, and zStart use the same broad transformation for a RAM-resident
program:

1. Copy at most 768 bytes of the variable body to a screen buffer.
2. Call `_DelMem` to remove that source chunk.
3. Call `_InsertMem` to open space at the destination.
4. Copy the buffered chunk into the new space.
5. Repeat until the body is at `0x9D95`.
6. Reverse the operation after the program returns.

Ion and Doors CS use `plotSScreen` (`0x9340`) as the shuttle. zStart uses
`saveSScreen` (`0x86EC`). The original-source implementations confirm this
structure. [confirmed]

The operation preserves only one complete body for a RAM-resident input. The
VAT entry and name can remain findable while the bytes described by that entry
are being moved. A successful `_ChkFindSym` therefore does not prove that its
returned data pointer identifies a valid, contiguous copy of the running
program. [confirmed]

### Ion 1.6

Ion's `ionm.z80` first calls `_EnoughRam` and `_Arc_Unarc` for an archived
program. The complete original variable must therefore fit in RAM before the
move loader starts. The loader then moves the body to `0x9D95` through
`plotSScreen`, using `_DelMem` and `_InsertMem` rather than allocating a second
complete execution copy. [confirmed]

On return, Ion reverses the move. If the input was originally archived, it
calls `_Arc_Unarc` again, so modified bytes persist but an archive write occurs
even when the program did not change. [confirmed]

Ion calls the client without installing an Ion-owned OS error handler. The
source therefore provides no cleanup path for an OS error or nonlocal exit
that bypasses the normal return. The resulting calculator state still needs a
dynamic trace; it is not inferred here. [confirmed]

The loader stages its preloader in `appBackUpScreen` (`0x9872`) and its move
routine in `cmdShadow` (`0x966E`). It uses `plotSScreen` during the forward and
reverse moves. The client may reuse `plotSScreen` while it runs; the reverse
move overwrites that buffer before Ion redraws its interface. [confirmed]

### Plasma 1.4

Plasma's documentation says that programs “run right from flash” and that the
shell does not perform program writeback. The first phrase describes the
storage of the source variable, not the address executed by the CPU. The
included `plasma.asm` copies the client into a RAM image at `userMem` and jumps
there. [confirmed]

For an archived input, `exec_prog_real` obtains the page and data pointer from
`_ChkFindSym`. It installs `Prog_Loader` in `saferam3`, prepares
`DE=userMem-2`, and passes the source page, pointer, and size to the loader.
`Prog_Loader` calls `_FlashToRam`, copies the Ion library block after the
client, and jumps to `userMem+1`. The named source remains archived. For a RAM
input, the same path calls `_FlashToRam` with `A=0`; the fixed-RAM source
address is copied without moving the original variable. [confirmed]

Plasma relocates the shell code and Ion-library jump table around the client
inside the current execution allocation. It calls `_InsertMem` only when the
client and library tail need more space than the shell image already occupies.
This is a copy loader, but its peak allocation is not the sum of two fixed,
complete program images. The allocation structure is [confirmed]. The exact
peak still needs a dynamic trace. [hypothesis]

Normal return does not compare or rewrite the source program. Plasma instead
exports `savedata` and `fetchdata`: the first replaces a named AppVar with
`_CreateAppVar`, and the second reads a RAM or archived AppVar through
`_FlashToRam`. A client that needs persistent data must use an explicit storage
path such as this one. [confirmed]

No Plasma-owned OS error handler appears in the release source. The state after
an OS error or nonlocal exit remains a dynamic-trace question. [confirmed]

The release archive has SHA-256
`62965a41fe071902043ebcbbd1254f710d29729bf86a78f20b6f14d6974f5d5a`.
Within it, `Plasma/plasma.asm` has SHA-256
`b424980285adf3f16225239c3ba3f133a42efb38d0666d968eee4b1fe24b810f`,
`Plasma/plasma.txt` has SHA-256
`970ec3908da27bdbabc630c38c9546eade19059a9902f111bd116e3d3c77a750`,
and `Plasma/PLASMA.8XP` has SHA-256
`a55816b3ea9462c4e7ef16750d3ad6f8955b0a51de6a096c8b7e59f1242f0df1`.
SPASM-ng with `TI83P` defined produces a 2,447-byte body that matches the
packaged program byte for byte. [confirmed]

An instrumented TI-84 Plus OS 2.55MP run reaches the packaged Plasma entry at
`ram:9D95`. The deterministic keyboard macro does not reach the protected Ion
client, so the RAM and archived client-copy paths above remain static results.
It also does not reach the copied raw-key hook's `RST 28h` at `ram:9881` or
`_newContext` at `ram:077E`. The `4030h` nonlocal context transition is
therefore interaction-blocked rather than dynamically confirmed. The trace,
ROM, link-file, macro, and emulator hashes are pinned in
`tools/data/community-loader-traces.csv`. [confirmed] for the observed entry
and boundary.

### TSE 1.5/1.6

TSE is a cooperative task-switching runtime rather than a normal-return shell
loader. Its release README identifies version 1.5, while the byte-matched
kernel source returns version 1.6. The combined label records that release
inconsistency. [confirmed]

`starttask` appends the program's requested external-data area followed by a
62-byte state tail. The tail contains a saved `SP` word and 60 bytes copied
from `flags` at `0x89F0`. It also records the initial code address and stack
pointer. [confirmed]

`cpy_prgm_in` reduces the stored variable to its three-byte `BB 6D C9` header,
then moves the remaining body and task state to `userMem` in chunks no larger
than `0x100`. Each chunk opens the destination with `_InsertMem`, copies the
bytes, and closes the source with `_DelMem`. `cpy_prgm_out` reverses the move.
Only one active body is retained, and the named VAT entry describes the
three-byte dormant header while its task is active. [confirmed]

Before a task switch, TSE stores the live `SP` and flag bytes in the active
task block. The reverse move writes the complete active image back to its RAM
variable, including client modifications. TSE then moves the selected task to
`userMem`, restores its flags and `SP`, and resumes it with `RET`. Ending a task
removes the external-data area and 62-byte state tail. [confirmed]

Utopia handles an archived TSE program by calling `_Arc_Unarc` before
`_tseStartTask`. It does not rearchive that program when the task ends. The
separate `LOADTSE` program can stream the archived `TSEKRNL` and `TSELIBS`
variables into `saferam1` and `saferam2` with `_FlashToRam`; that infrastructure
path does not make an archived client execute in place. [confirmed]

The mover requires a `0x100`-byte free-RAM buffer. The release documentation
warns that a task block can be created when too little memory remains for a
later switch. The buffer requirement is [confirmed]. The exact peak RAM cost,
machine state after an error, and every low-memory failure path still need
dynamic traces. [hypothesis]

The matched release archive `shells/old/tsekrnl.zip` has SHA-256
`d640729fcb4ebf2a166fe37f3ae59741a50a571578e5091863295bb08dba6a3b`;
its `Tse.8xg` member has SHA-256
`4cde52eb0ec37c16a5ac17f2f6eb94c7e3f4ebc4020b577b70d32ac34b29f3cf`.
Its `tse.txt` and `tsedev.txt` members have SHA-256 values
`d0b8e033eef29e370ea8bac145019c5f369a789daf03b753c69b1e83d52f60ae`
and `b8b566b5dac0f7084a7eb0a6cae259b70151bb3457dfe7849f5e708141d75c8e`.
The source archive `source/tsesrc.zip` has SHA-256
`d16407c2125133b24a86ad8e88819b3ae0fcc826a55ded5cb4155c19e6239592`.
Its `tsekrnl.asm`, `loadtse.asm`, and `tselibs.asm` members have SHA-256 values
`02eb4c0723ac5d3a74bcbdd3283c44fb7a87a5e509083aa6e68080398c6a4cc0`,
`34578f59f6324a4e82764ab38d5406eed6591019abf0a8e3bc78130cbe9b9f0e`,
and `ca55ca2ae6bf64dc5f944e79ad9fbc4f23c349c2bb15d88836830d5e3d9d62e2`.
SPASM-ng rejects the unused `kX-1` equate in the release `tse.inc`. Renaming
that unused equate for parser compatibility makes those sources reproduce the
packaged `TSEKRNL`, `LOADTSE`, and `TSELIBS` bodies byte for byte. [confirmed]

The packaged `TSELIBS` entry contains a two-byte internal size and a 391-byte
program body. `LOADTSE` skips the size, `BB 6D`, and leading `C9`, leaving 388
library-code bytes, but loads a fixed 531 bytes into `saferam2` (`ram:8A3A`). It
therefore reads and writes 143 bytes beyond the packaged library code. This is
not merely dead source: two instrumented RAM-path runs enter `loadRAM` four
times, execute 2,598 `LDIR` iterations in total, and record 1,062 writes to the
531-byte `saferam2` range, including 286 writes beyond the 388-byte code extent.
[confirmed]

The archived fixture changes only the archive flags of the byte-identical
`TSEKRNL` and `TSELIBS` entries. Two runs enter `streamFlash` four times, reach
its `_FlashToRam` call site at `ram:9DDD` four times, make the same 1,062 range
writes including 286 beyond-code writes, and enter the packaged kernel at
`ram:9872` twice. The traces confirm both infrastructure loader paths and the
143-byte over-read on each run. They do not start a cooperative client task,
so `cpy_prgm_in`, `cpy_prgm_out`, task writeback, and low-memory switching
remain static results. Hashes and counts are in
`tools/data/community-loader-traces.csv`. [confirmed]

### MirageOS 1.2

MirageOS 1.2 is a one-page, binary-only Flash App. Static disassembly of the
original App shows a symmetric loader at App addresses `0x75CF`–`0x76C0`. It
uses `saveSScreen` as a 768-byte shuttle, calls `_DelMem` and `_InsertMem`, and
moves the client to `0x9D95`. [confirmed]

For archived input, `0x7899`–`0x78FD` creates a program named `Z,1.`, changes
its VAT type to `TempProgObj` (`0x16`), and copies the archived object into it
with `_FlashToRam`. The original name continues to identify the archived
object while the temporary object's body is moved to `0x9D95`. Before creating
the temporary, the loader deletes any existing `Z,1.` program. [confirmed]

The writeback path at mapped addresses `0x77D5`–`0x7870` compares RAM bytes with
archive bytes through a temporary page-read thunk. It replaces and rearchives
the program only when the comparison differs. The release changelog describes
the same smart-writeback policy. [confirmed]

The launch wrapper installs an OS error handler and conditionally prepares the
MirageOS tasker before calling the client. With tasker flag bit 6 at `0x9689`
set, `0x7176`–`0x71E9` installs IM2. It writes tasker state beginning at
`0x8A3A`, code at `0x8A4F`–`0x8A88` and `0x8A8A`–`0x8AFE`, and an IM2 handler
at `0x8C01`–`0x8C1B`. It also builds the 257-byte IM2 vector table at
`0x8B00`–`0x8C00`. It uses the word at `0x966F` as an optional custom interrupt
target. These `statVars` ranges are not client scratch while the tasker or
custom interrupt is active. [confirmed]

The changelog states that **ON**+**^** quits immediately without writeback.
Whether that path restores every intermediate body and mapping remains a
dynamic-trace question. [confirmed]

### Doors CS 7.4

Doors CS classifies TI-OS assembly, Ion, MirageOS, Doors CS assembly, BASIC,
and associated program types in `runprog.asm`. For a RAM-resident assembly
program, `hook1` and the `swap1`–`swap4` routines move its body between
the variable and `0x9D95` through `plotSScreen`. [confirmed]

For an archived assembly program, `initTmpASM` checks available memory,
creates a complete RAM temporary variable under a derived name, and calls
`_FlashToRam` before invoking the same move loader. The name is made by adding
the program-chain size to the original name's first byte. `initTmpASM` deletes
an existing variable on collision, so the name is not globally unique. This
path needs space for one complete RAM variable plus loader state; it does not
retain another complete execution copy after the move. [confirmed]

The `asmcheckwriteback` path behaves differently according to the original
storage class:

- For a RAM-resident input, the reverse move has already put modified bytes
  back into the original variable.
- For an archived input, it compares the complete RAM temporary variable with
  the archived original page by page. An unchanged temporary variable is
  deleted. A changed one replaces the archive under the original name.

Both behaviors are confirmed by `writeback.asm`. Doors CS also installs
`AppOnErr(hook1reterror)`, which routes an ordinary OS error through the
reverse move. [confirmed]

The shell's `mos_quittoshell` path manually rewrites `SP` and returns through
a thunk in `cmdShadow`. Whether every forced shell-to-shell exit reaches the
archive comparison still needs a dynamic trace. [hypothesis]

### zStart 1.3.013

zStart's `runPrograms.z80` handles archived input without creating a named RAM
temporary variable. It checks space, opens a raw allocation at `0x9D95`, copies
the archived body there, and records a 16-bit additive checksum. The archived
original remains present while this execution image runs. [confirmed]

For RAM-resident input, zStart temporarily reduces the stored body to its
two-byte header and uses `moveMemory` to transfer the rest to `0x9D95` through
`saveSScreen` in chunks no larger than `0x300`. Normal return reverses the move
and restores the stored size. [confirmed]

The client runs inside `errHandOn(programRet)`, so ordinary TI-OS errors reach
the same cleanup path. For an archived input, zStart deletes the raw allocation
when its checksum is unchanged. When it differs, zStart deletes the archived
original, creates a new program containing the `BB 6D` marker and changed
body, then archives the replacement. [confirmed]

zStart also places a shell-call thunk at `0x8000`, installs Ion-compatible
vectors in `cmdShadow`, and selects IM1 for the client. A nonlocal jump into
another shell can bypass the local error frame; that path remains untraced.
[hypothesis]

### Lookup and persistence consequences

Self-lookup has several distinct outcomes across these loaders:

- A RAM-resident input can remain named in the VAT while its body is moved and
  is not a valid contiguous self-image.
- A MirageOS archived input keeps the archived original name and uses the
  `TempProgObj` named `Z,1.` for the RAM body that is moved during execution.
- A Doors CS archived input has an immutable archived original plus a
  derived-name temporary variable whose body is moved during execution. A
  collision with that derived name is deleted during setup.
- A zStart archived input has an immutable archived original plus an unnamed
  execution allocation.
- A Plasma input keeps the complete named source and runs a copied image. The
  source may be in RAM or Flash, but `_ChkFindSym` does not return the execution
  image.
- An active TSE task keeps a named three-byte header in its variable while the
  remaining body and appended task state occupy `userMem`.

Code that needs its running image should use a shell-defined pointer or a
position-independent scheme rather than assume that `_ChkFindSym` returns it.

Writeback also changes the persistence guarantee. Ion writes every originally
archived input back to Flash; MirageOS, Doors CS, and zStart avoid a Flash
rewrite on their confirmed unchanged paths. Plasma never writes the source
program back. TSE writes an active image back to its RAM variable on a
cooperative switch and leaves an automatically unarchived program in RAM.
Forced shell exits can bypass writeback under at least the documented MirageOS
**ON**+**^** path, and nonlocal exit behavior remains launcher-specific.

### Evidence limits

The Ion, Plasma, TSE, Doors CS, and zStart results above come from source
included in an identified release, byte-matched release source, or an
identified source commit. MirageOS results come from its identified original
binary and release changelog. TSE's RAM and archived infrastructure copies and
Plasma's release entry also have the dynamic boundaries described above.
These artifacts do not confirm peak free-RAM measurements or the machine state
after every abnormal exit.

The following questions still require a common instrumented payload under all
six launcher and runtime designs:

- the exact peak RAM cost for RAM-resident and archived inputs;
- `_ChkFindSym` results and pointed-to bytes while each client is running;
- self-modification persistence on normal return, OS error, **ON**+**^**, and
  shell-to-shell exit;
- restoration of the stack, interrupt mode, page mapping, and scratch RAM on
  every abnormal path.

The loader-source numeric bcall scan finds `4F66h` for `_SetGetKeyHook` and
`4030h` for `_newContext` in Plasma. Both IDs already have those names in the
current bcall map. No absent or misnamed numeric bcall was found in Plasma,
TSE, or RUNCOUNT. [confirmed]

### Source provenance

| Artifact | Exact identity | Source |
|---|---|---|
| Ion 1.6 release archive | SHA-256 `b5a5ba97f325f8779aa35cda23e38152087930298ff8b7b8573905710230e6e6` | [ion.zip](https://www.ticalc.org/pub/83plus/asm/shells/ion.zip) |
| Plasma 1.4 release archive | SHA-256 `62965a41fe071902043ebcbbd1254f710d29729bf86a78f20b6f14d6974f5d5a` | [plasma141.zip](https://www.ticalc.org/pub/83plus/asm/shells/plasma141.zip) |
| TSE 1.5/1.6 matched release archive | SHA-256 `d640729fcb4ebf2a166fe37f3ae59741a50a571578e5091863295bb08dba6a3b` | [tsekrnl.zip](https://www.ticalc.org/pub/83plus/asm/shells/old/tsekrnl.zip) |
| TSE matched source archive | SHA-256 `d16407c2125133b24a86ad8e88819b3ae0fcc826a55ded5cb4155c19e6239592` | [tsesrc.zip](https://www.ticalc.org/pub/83plus/asm/source/tsesrc.zip) |
| MirageOS 1.2 release archive | SHA-256 `38dc70173818972de8c5eb78099e8870c7acb9ad4c62d290f6c6f5840c71d43b` | [mirageos.zip](https://www.ticalc.org/pub/83plus/flash/shells/mirageos.zip) |
| Doors CS 7.4 release archive | SHA-256 `3a16161ce1d091438b0ea9f5e72774f8e8b4fdfba9ab1024bad0b55569555230` | [dcs7.zip](https://www.ticalc.org/pub/83plus/flash/shells/dcs7.zip) |
| Doors CS source repository | Commit `33af4f5ede199eee77cf2f89b5463a0a6ec9a1af` | [Doors CS 7 commit](https://github.com/KermMartian/Doors_CS_7/tree/33af4f5ede199eee77cf2f89b5463a0a6ec9a1af) |
| zStart 1.3.013 release archive | SHA-256 `7a1b7c69c85030b412bb6ea11ae71ac608b9882a9de3ab7dbef1faf69519c5e9` | [zstart.zip](https://www.ticalc.org/pub/83plus/flash/shells/zstart.zip) |

## Evidence limits

The ROM and traces on this page cover the compiled and text `Asm(` paths,
timed unarchived compiled-launch heap snapshots, RUNCOUNT's unarchived source
writeback, its archived non-execution boundary, normal cleanup bytes,
pointer-repair code, VAT results, and Flash-page copying on TI-84 Plus OS
2.55MP. They do not establish behavior for `_ExecAsm`, an archived shell
launch, another OS version, a 48 KiB ASIC, or a physical calculator.

Useful next fixtures should guard the two-byte over-read, repeat the timed
snapshots for archived, `_ExecAsm`, and shell routes, and force archive garbage
collection followed by a fresh lookup.
