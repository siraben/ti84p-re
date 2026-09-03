# Flash bcall programming guide

*TI-84 Plus OS 2.55MP — the Flash bcalls a program can call, and what each one checks.*

These bcalls expose the command workers. They do not provide the allocation,
battery policy, ownership checks, transaction journal, or gate management used
by the archive subsystem. A normal program that wants to archive or unarchive
a variable should use `_Arc_Unarc` rather than choose a raw Flash address.
Low-level calls are appropriate only when the caller owns the target region and
also owns the surrounding recovery policy. [confirmed] for the bcall behavior;
[standard] for using the public variable API.

## Shared preconditions and hygiene

Every modifying bcall below has these caller obligations: [confirmed] for the
ROM behavior unless marked otherwise.

- Open the protected port-`0x14` gate before the call and close it on every
  exit. The Flash bcalls do neither operation. Code executing from ordinary RAM
  cannot satisfy the privileged-fetch sequence by copying its bytes into RAM.
- Check battery state before opening the gate. The OS archive path calls
  `_Chk_Batt_Low` before its own Flash transaction, but the boot workers do not.
- Establish ownership of the complete physical sector. Flash programming can
  only clear bits from one to zero. Restoring a zero bit to one requires an
  erase, which affects 64 KiB for ordinary pages and the smaller top-boot
  sectors shown under [Sector geometry](flash-memory.md#sector-geometry). [standard]
- Keep a recovery record outside the sector being changed if interruption must
  be survivable. The raw bcalls have no power-loss journal.
- Use `rst 28h` with the bcall ID. Do not call the page-`3F` body address. The
  raw write and erase cores reject a direct caller whose immediate return
  address is at or above `0x8000`.
- Keep the stack, source, and destination buffers away from `0x8100`–`0x817B`.
  The launcher overwrites that range with the block-program worker. The erase
  worker occupies `0x8100`–`0x8151`. The launcher also writes its saved IFF
  state at `0x82A2`.
- Keep `IY` at the OS `flags` base for the write calls. The accepted block path
  clears `(IY+0x25).1`; its unused low-source branch can set the same unnamed
  scratch bit. `_WriteAByte` additionally overwrites the first byte of `OP1` at
  `0x8478`.
- Treat `A`, `BC`, `DE`, `HL`, flags, `OP1`, and the scratch locations above as
  clobbered when their selected path uses them. The launchers preserve `IX` and
  restore the interrupt-enabled state that existed on entry.
- Validate the arguments before interpreting the result. Several rejected or
  no-op paths return flags that resemble success. After a validated nonempty
  call, require `A=0`, then read back the complete programmed span or erased
  sector. A locked write can return `A=0`, Z in TilEm without changing Flash.

The labels “safe” and “unsafe” describe only the page-`3E` software guard.
Neither safe entry checks the port-`0x14` gate, physical protection, archive
ownership, destination address, length, battery, or power-loss state.
[confirmed]

## Choosing a write bcall

| Need | Entry | Programmer-visible differences |
|------|-------|--------------------------------|
| Program a RAM block outside the certificate and boot pages | `_WriteFlash` | Rejects starting pages `3E` and `3F`; still requires complete span validation. |
| Program a RAM block in certificate page `3E` | `_WriteFlashUnsafe` | Permits starting page `3E`; intended only for an owner of certificate update policy. |
| Clear bits in one ordinary byte | `_WriteAByteSafe` | Copies `B` through `OP1`; rejects pages `3E` and `3F`. |
| Clear bits in one certificate byte | `_WriteAByte` | Copies `B` through `OP1`; permits page `3E` and rejects page `3F`. |

The block worker expects `DE` in `0x4000`–`0x7FFF` and a RAM source with
`HL >= 0x8000`. The ROM does not enforce either condition. For nonzero length
$n$, validate the final target before the call:

$$
p_{final} = p + \left\lfloor
  \frac{(DE - 0x4000) + n - 1}{0x4000}
\right\rfloor
$$

Also require `DE` in the banked window, ensure the RAM source plus $n$ does not
wrap, and keep the source outside the worker and scratch ranges. For
`_WriteFlash`, require every page through $p_{final}$ to stay below `3E`.
Crossing from page `3D` toward `3E` does not stop cleanly: the worker wraps
`DE` to `0x4000` but leaves page `3D` mapped. [confirmed]

## `_WriteFlash`

`_WriteFlash = 80C9h` is the ordinary block entry. Inputs are `A=page`,
`DE=destination`, `BC=length`, and `HL=RAM source`. It masks the page with
`0x3F`, rejects page `3E`, and then enters `_WriteFlashUnsafe`, which rejects
page `3F`. A validated, nonempty successful call returns `A=0`, Z. A worker
failure returns `A=0x3F`, NZ. [confirmed]

On success, `BC=0`, while `HL` and `DE` point one byte beyond the source and
destination spans. On a program failure, `HL` and `DE` identify the failing
bytes and `BC` retains the decrement already performed by `LDI`. The page
guards are exceptional: they return nonzero `A` with Z. A zero-length accepted
call returns the masked page and NZ without launching the worker. [confirmed]

Use this entry only after validating the entire span. Its initial page check
does not protect a call that begins below page `3E` and later crosses a page or
sector boundary.

The executable example programs two bytes from RAM at `08:4100`:

<!-- executable-snippet: write-flash -->
```z80
    ld a,$08
    ld de,$4100
    ld hl,writeflash_payload
    ld bc,writeflash_payload_end-writeflash_payload
    rst $28
    .dw $80C9
    or a
    jp nz,flash_failed
```

The guarded runner seeds both target bytes to `0xFF`, requires `AF=0x0044`,
and verifies `A5 5A` in both the Flash array and a `_FlashToRam` buffer.
[confirmed] for pinned Wabbitemu execution.

## `_WriteFlashUnsafe`

`_WriteFlashUnsafe = 8087h` has the same block ABI and worker results as
`_WriteFlash`. It omits only the page-`3E` rejection. The core still masks
`A` to six bits, rejects page `3F`, checks the call frame, and accepts a zero
length as a no-op. [confirmed]

The guarded retail-ROM usage probe calls this entry with `A=0x3E`, programs
`3C C3` at `3E:4100`, and reads the same pair back through `_FlashToRam`.
The bcall returns `AF=0x0044`. [confirmed] for pinned Wabbitemu execution.

<!-- executable-snippet: write-flash-unsafe -->
```z80
    ld a,$3E
    ld de,$4100
    ld hl,writeflashunsafe_payload
    ld bc,writeflashunsafe_payload_end-writeflashunsafe_payload
    rst $28
    .dw $8087
    or a
    jp nz,flash_failed
```

“Unsafe” does not mean that the routine bypasses physical protection. Port
`0x14`, the port-`0x21` sector group, and the Flash chip still decide whether
the command reaches and changes the array. Its page-`3E` access makes this
entry suitable for OS-owned certificate work, not for ordinary archive data.
[confirmed] for the software entry; [standard] for the hardware gates.

## `_WriteAByteSafe`

`_WriteAByteSafe = 80C6h` takes `A=page`, `DE=destination`, and `B=byte`.
It masks the page, rejects page `3E`, and falls into `_WriteAByte`. The shared
unsafe core later rejects page `3F`. Its accepted path therefore has the same
page exclusions as `_WriteFlash`. [confirmed]

An early page-`3E` rejection leaves `BC`, `DE`, `HL`, and `OP1` untouched.
Page `3F` reaches the byte wrapper first, so that rejection has already stored
`B` at `OP1`, set `BC=1`, and set `HL=0x8478`. This difference matters to a
caller that tries to infer whether scratch state changed from the flags.
[confirmed]

The guarded retail-ROM usage probe exercises the accepted path at `08:4102`.
It programs `0xFE → 0xFC`, returns `AF=0x0044`, and obtains `0xFC` through
`_FlashToRam`. [confirmed] for pinned Wabbitemu execution.

<!-- executable-snippet: write-a-byte-safe -->
```z80
    ld a,$08
    ld de,$4102
    ld b,$FC
    rst $28
    .dw $80C6
    or a
    jp nz,flash_failed
```

## `_WriteAByte`

`_WriteAByte = 8021h` takes `A=page`, `DE=destination`, and `B=byte`.
It stores `B` in `OP1`, sets `HL=0x8478` and `BC=1`, then enters
`_WriteFlashUnsafe`. It permits page `3E` and rejects page `3F`. A successful
call returns `A=0`, Z, `BC=0`, `HL=0x8479`, and `DE` one byte beyond the
target. `OP1` retains the programmed byte. [confirmed]

The guarded retail-ROM usage probe calls this entry on page `3E`, programs
`0xFE → 0xF8` at `3E:4102`, leaves `OP1=0xF8`, and returns `AF=0x0044`.
`_FlashToRam` returns `0xF8`. [confirmed] for pinned Wabbitemu execution.

<!-- executable-snippet: write-a-byte -->
```z80
    ld a,$3E
    ld de,$4102
    ld b,$F8
    rst $28
    .dw $8021
    or a
    jp nz,flash_failed
```

Use the byte entries for monotonic state changes such as `0xFE → 0xFC` or
`0xFC → 0xF0`. A request that needs any `0→1` transition requires sector
erase and reconstruction. A requested byte with the same DQ7 as the stored
byte can produce false success when the ASIC gate blocks the command, so verify
the byte after every call. [confirmed] for the ROM and pinned TilEm result;
[standard] for NOR programming direction.

## `_EraseFlashPage`

`_EraseFlashPage = 8084h` takes `A=page`. It masks the page to six bits,
chooses address `0x4000`, rejects page `3E`, and enters `_EraseFlash`. For page
zero it changes the address to `0x0000`. It does not reject page `3F`.
[confirmed]

The name refers to the logical page used to select a sector. It does not limit
the erase to 16 KiB. On an ordinary archive page, the command erases the
containing 64 KiB sector. Initialize `DE` to a writable Flash address in the
same mapping before the call; the DQ5 failure tail writes reset byte `0xF0`
through undocumented `DE`. [confirmed] for the worker; [standard] for erase
geometry.

A successful erase returns `A=0`, Z. A worker failure returns `A=0xF1`, NZ.
The page-`3E` rejection instead returns `A=0x3E`, Z. Prevalidate the page,
check `A=0`, and verify the complete physical sector. [confirmed]

The guarded retail-ROM usage probe erases through page `0C`, returns
`AF=0x0044`, and reads `0xFF` back at `0C:4000`. [confirmed] for pinned
Wabbitemu execution.

<!-- executable-snippet: erase-flash-page -->
```z80
    ld a,$0C
    ld de,$4000
    rst $28
    .dw $8084
    or a
    jp nz,flash_failed
```

## `_EraseFlash`

`_EraseFlash = 8024h` takes `A=page` and `HL=an address in the selected
sector`. It performs no page mask or page guard. The worker maps `A`, issues a
sector-erase command through `HL`, and returns the same success or failure
values as `_EraseFlashPage`. `BC`, `DE`, and `HL` are otherwise retained by
the erase path, but failure can write `0xF0` to the address in `DE`.
[confirmed]

Choose this entry when the target must be an address other than the page start,
including a top-boot sector boundary. Set `DE=HL` defensively so the failure
reset targets Flash rather than arbitrary RAM. This convention avoids the
worker's underspecified failure write; the public ABI itself does not require
or synthesize it. [confirmed] for the write; [standard] for the Flash reset
command.

The guarded retail-ROM usage probe passes `HL=DE=0x4567` on page `10`.
The bcall returns `AF=0x0044`, and `_FlashToRam` reads `0xFF` from the same
interior sector address. [confirmed] for pinned Wabbitemu execution.

<!-- executable-snippet: erase-flash -->
```z80
    ld a,$10
    ld hl,$4567
    ld de,$4567
    rst $28
    .dw $8024
    or a
    jp nz,flash_failed
```

## `_EraseCertificateSector`

`_EraseCertificateSector = 8060h` accepts any `HL` whose high byte is `0x40`
or `0x60`. It does not require `L=0`. It loads page `3E` and calls
`_EraseFlash`, selecting one of the two 8 KiB certificate sectors. Other high
bytes return without work. [confirmed]

The wrapper restores the caller's `AF` after both accepted and rejected calls.
It therefore hides worker success and failure as well as its own input
rejection. Preserve the certificate through its OS-owned rebuild protocol and
verify the selected sector; flags are not a result channel for this bcall.
[confirmed]

The guarded retail-ROM usage probe seeds `AF=0xA545` and passes `HL=DE=0x6001`.
The returned `AF` remains `0xA545`, while `_FlashToRam` reads `0xFF` from
`3E:6001`. This dynamically exercises the accepted nonzero-`L` path and the
second 8 KiB certificate sector. [confirmed] for pinned Wabbitemu execution.

<!-- executable-snippet: erase-certificate-sector -->
```z80
    ld hl,$A545
    push hl
    pop af
    ld hl,$6001
    ld de,$6001
    rst $28
    .dw $8060
```

## Return and side-effect matrix

| Path | Returned `A` and flags | Other visible state |
|------|------------------------|---------------------|
| block or byte program succeeds | `A=0`, Z | `BC=0`; `HL`/`DE` advanced; page worker ends on page `3F` before bcall mapping restoration |
| block or byte program fails DQ polling | `A=0x3F`, NZ | `HL`/`DE` at failing byte; `BC` already decremented |
| safe write rejects page `3E` | `A=0x3E`, Z | wrapper-specific scratch changes described above |
| unsafe core rejects page `3F` | `A=0x3F`, Z | no worker; byte wrapper may already have changed `OP1`, `BC`, and `HL` |
| accepted zero-length block | masked page, NZ | no worker; write scratch bit unchanged |
| erase succeeds | `A=0`, Z | caller `BC`, `DE`, and `HL` retained by the erase worker |
| erase fails DQ polling | `A=0xF1`, NZ | writes `0xF0` through incoming `DE` |
| `_EraseFlashPage` rejects page `3E` | `A=0x3E`, Z | no worker |
| `_EraseCertificateSector` returns | caller's original `AF` | accepted and rejected cases are indistinguishable through flags |

This matrix explains why `jr z,success` is insufficient. Validate page,
address, span, and nonzero length first. Then test `A=0` and verify the array.

## Checking results

The executable examples above assume that trusted OS or boot code already
opened port `0x14`, checked the battery, established sector ownership and
recovery state, and will relock Flash on every exit. Copying an unlock byte
sequence into RAM does not satisfy the ASIC's privileged-fetch rule.

After a validated nonempty program or erase call, require `A=0`. Save the
target page and address before the call because the write worker advances
registers. Read the programmed span through `_FlashToRam` and compare every
byte with the source. For erase, inspect the complete physical sector, not
only the selected address. Every failure and success path must reach the
trusted owner's relock and recovery epilogue. [confirmed] for the return and
clobber rules; [standard] for physical erase scope.

## Reading back with `_FlashToRam`

`_FlashToRam = 5017h`, body `3D:6745`, copies `BC` bytes from Flash at
`A:HL` to RAM at `DE`. It advances the mapped Flash page when `HL` crosses
`0x8000` and restores the previous port-`0x06` mapping after its RAM worker
returns. It does not need the Flash write gate for ordinary readable pages.
[confirmed]

The call consumes `BC` and advances `HL` and `DE`. It uses worker RAM beginning
at `0x8100` and page scratch at `0x9868`, so a verification buffer must avoid
those locations while the copier runs. Locked certificate-page reads remain
subject to the ASIC's separate read protection. [confirmed] for the ROM
scratch and worker; [standard] for the read gate.

The executable example reads back the complete two-byte `_WriteFlash` vector:

<!-- executable-snippet: flash-to-ram -->
```z80
    ld a,$08
    ld hl,$4100
    ld de,writeflash_copy
    ld bc,writeflash_payload_end-writeflash_payload
    rst $28
    .dw $5017
```

## Executable example validation

`tools/probes/emulator/flash-bcall-usage.asm` is the guarded executable form of
the examples above. It invokes `_WriteFlash`, `_WriteFlashUnsafe`,
`_WriteAByteSafe`, `_WriteAByte`, `_EraseFlashPage`, `_EraseFlash`,
`_EraseCertificateSector`, and `_SetFlashLowerBound`. It reads every changed
location through `_FlashToRam`. The six calls with result-bearing `A` values
branch to a failure loop unless `A=0`; the probe also stores every return so
the runner can check the complete result. [confirmed]

The nine short bcall call sequences on this page carry an
`executable-snippet` tag. The reusable `tools/ti84re/wiki/executable_snippets.py` parser
requires their text to match the same tagged regions in the assembled probe
byte for byte. The `tools/ti84re/wiki/check_executable_snippets.py` CLI exposes that
check. This catches documentation drift; Wabbitemu execution supplies the
runtime result below.

On 2026-08-10, the hash-guarded Wabbitemu adapter booted the exact OS 2.55MP
ROM, established the retail protection state, injected the 264-byte program
into RAM, and opened only Wabbitemu's in-memory Flash gate. The run reached
every named public entry. The shared `_WriteFlashUnsafe` core ran four times,
the `_WriteAByte` body twice, and the `_EraseFlash` core three times because
their safe and specialized wrappers fall through or call into them. Seven
`_FlashToRam` calls brought the total to 14 RAM-worker entries. No execution
violation occurred. [confirmed] for this pinned emulator run.

| Observation | Guarded result |
|-------------|----------------|
| `_WriteFlash` return and readback | `AF=0x0044`; array and copied bytes both `A5 5A` |
| `_WriteFlashUnsafe` page-`3E` return and readback | `AF=0x0044`; array and copied bytes both `3C C3` |
| `_WriteAByteSafe` return and readback | `AF=0x0044`; array and copied byte both `FC` |
| `_WriteAByte` page-`3E` return, scratch, and readback | `AF=0x0044`; `OP1=0xF8`; array and copied byte both `F8` |
| `_EraseFlashPage` return and readback | `AF=0x0044`; `0C:4000` array and copied byte both `FF` |
| `_EraseFlash` return and readback | `AF=0x0044`; `10:4567` array and copied byte both `FF` |
| `_EraseCertificateSector` return and readback | caller `AF=0xA545` preserved; `3E:6001` array and copied byte both `FF` |
| shared write scratch | `(IY+0x25).1` clear after the accepted paths |
| `_SetFlashLowerBound` result | port-`0x23` upper bound `0x2A`; IFF2 clear |

The assembly source SHA-256 was
`ba91fa8a4d1d7c816b742a426dbb0216f927ec209f368534a13748d4683b42e7`;
the assembled machine-code SHA-256 was
`8f9ca5975c418871ba831c3536cba6e7e4f9f368520e1ad37650ef9c54d9249c`.
See “Retail Flash bcall usage probe” in `tools/notes/emulator-probes.md` for the
guarded reproduction command. This execution validates the snippets against
the original ROM bodies under pinned Wabbitemu. It does not validate the
privileged port-`0x14` sequence, allocation or journaling, interruption,
timing, or behavior of a physical Flash device.
