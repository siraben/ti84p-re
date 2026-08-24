# Resident assembly programs

TI-OS copies a compiled assembly program to `userMem` (`0x9D95`), executes it,
and removes that copy when it returns. This page documents the OS 2.55MP launch
path, the memory limit enforced by the ROM, pointer stability during variable
allocation, and archived-data access for long-running runtimes. Third-party
launchers use different movement and archive-writeback policies; see
[Shell loaders and writeback](sub-shell-loaders.md) for a source-based
comparison.

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

The source does not test the returned page byte in `B`. Its direct store is
therefore supported only when lookup returns a RAM source. An archived source
or a shell that moves the named body can produce a Flash pointer or a
shell-defined in-flight representation instead. Persistent self-modification
must follow the launcher's lookup and writeback contract, not merely reuse this
fixed-offset pattern. [confirmed] for the missing guard; [hypothesis] for
untraced launcher outcomes.

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

## Evidence limits

The ROM and traces on this page cover the compiled and text `Asm(` paths,
timed unarchived compiled-launch heap snapshots, normal cleanup bytes,
pointer-repair code, VAT results, and Flash-page copying on TI-84 Plus OS
2.55MP. They do not establish behavior for `_ExecAsm`, an archived launch path,
a shell launcher, another OS version, a 48 KiB ASIC, or a physical calculator.

Useful next fixtures should guard the two-byte over-read, repeat the timed
snapshots for archived, `_ExecAsm`, and shell routes, and force archive garbage
collection followed by a fresh lookup.
