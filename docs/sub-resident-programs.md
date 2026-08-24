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
`0x9D95`. The handoff has `SP=0xFFCB`; the payload instruction has the same
value because `CALL 07:57FD` and its `JP ram:9D95` leave the return address on
the stack. [confirmed]

| Register | First instruction at `ram:9D95` |
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

This protocol prevents pointer invalidation; it does not make an update
transactional. Persistent data needs a version, length, checksum, and commit
marker. A two-record or copy-on-write design is required to recover from a
reset during an update. [standard]

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
normal cleanup bytes, pointer-repair code, VAT results, and Flash-page copying
on TI-84 Plus OS 2.55MP. They do not establish behavior for `_ExecAsm`, a shell
launcher, another OS version, a 48 KiB ASIC, or a physical calculator.

Useful next fixtures are internal sizes `0x1FFF`, `0x2000`, and `0x2001`; timed
snapshots before insertion, at payload entry, inside a nested bcall, and after
cleanup; an archived variable that crosses a 16 KiB page; and a forced archive
garbage collection followed by a fresh lookup.
