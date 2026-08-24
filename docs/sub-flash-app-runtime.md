# Flash Apps as resident runtimes

A Flash App keeps its kernel in Flash instead of copying it to `userMem`.
This removes the normal assembly-program execution copy, but it does not turn
`ram:9D95` through `ram:BFFF` into private storage. The OS still owns that range
as part of the user heap.

This page describes long-running App runtimes. See
[Apps, memory reset & settings](sub-apps-mem-settings.md) for App discovery and
headers, [Boot, contexts & errors](boot-contexts-errors.md) for context
dispatch, and [Memory management](memory-management.md) for the RAM heap.

## Code in Flash, state in RAM

The current App page executes in bank A at `0x4000` through `0x7FFF`. An App
therefore avoids the temporary copy that the compiled `Asm(` launcher creates
at `ram:9D95`. The conventional `ram:9D95` through `ram:BFFF` interval contains
8,811 bytes. [confirmed]

That interval remains part of the movable user-data region. Variables,
temporary objects, the FPS/OPS gap, and the VAT determine how much space is
available. An App must reserve mutable storage with an OS allocation or start
from a controlled memory image. It cannot claim 8,811 bytes merely because its
code executes from Flash. [confirmed]

The practical maximum contiguous allocation depends on the calculator model,
OS version, VAT contents, temporary objects, and current heap pointers. Measure
it with `_MemChk` and a real allocation in each fixture state. Do not use the
address-map span as the capacity result. [confirmed]

Generated native code must also remain in executable physical RAM. Staying
below `ram:C000` matches the retail executable window, but the exact physical
RAM-page rules differ among emulators and remain partly unverified on hardware.
See [RAM execution protection](execution-protection.md). A threaded bytecode or
data image does not require executable RAM, although its interpreter still
does. The map is confirmed. [confirmed] The physical hardware boundary remains
untested. [hypothesis]

## Cross-page code and data

A multi-page App cannot treat bank-A addresses as flat pointers. Mapping
another App or OS page changes the bytes visible at the same logical address.
Any pointer into `0x4000` through `0x7FFF` is valid only while its page remains
mapped. [confirmed]

RPN83P provides a concrete multi-page design. Its page-0 branch table stores
entries in this form:

```z80
.dw target_routine
.db relative_app_page
```

Other App pages call those entries through an App-aware `bcall()` macro. Page
0 remains the stable branch and event-handler page, while larger modules live
on later pages. [confirmed] The checked source is RPN83P commit
`e2ad0bff98c94a13f34ae461b13f79384a75c17f`.

An OS bcall or App-page call may remap bank A. This affects Flash data as well
as code. RPN83P avoids passing a Flash string directly to `_PutS`; its local
display helper reads one byte from the current page and passes that character
to `_PutC`. Apply the same rule to any API that may retain or dereference a
pointer after remapping bank A. Reacquire or remap the page before continuing.
The RPN83P string helpers confirm this failure mode. [confirmed] Applying the
rule to untested APIs remains a [hypothesis].

## Install an App context

`_AppInit` at `ram:0936` copies six 16-bit vectors from the 13-byte block at
`HL` into `cxMain` through `cxSizeWind`. It copies the following byte into
`appFlags` and records the current bank-A page in `cxPage`. The event router can
then map `cxPage` and dispatch the installed handlers. [confirmed]

The block has this layout:

```text
+0x00  cxMain
+0x02  cxPPutAway
+0x04  cxPutAway
+0x06  cxRedisp
+0x08  cxErrorEP
+0x0A  cxSizeWind
+0x0C  appFlags
```

A resident App should make cleanup an explicit part of this context:

1. Save each OS setting that the App changes.
2. Open or validate persistent AppVars.
3. Call `_AppInit` with a `cxPutAway` handler that reaches the normal cleanup
   routine.
4. Install an error frame around each command dispatched by the App.
5. On explicit quit, `PutAway`, or a handled error, close mutable variables,
   persist state, restore settings, and restore the default context.
6. Call `_ReloadAppEntryVecs`, then return through `_JForceCmdNoChar` or
   `_PutAway` as appropriate.

RPN83P follows this lifecycle and routes both its explicit exit and `PutAway`
handler through common cleanup. This is a reusable design example, not an OS
guarantee that cleanup runs for arbitrary Apps. A reset or an unhandled jump
can still bypass the App's code. [confirmed]

## Keep persistent state relocatable

RPN83P stores mutable state in four RAM AppVars and uses between 1,044 and 2,545
bytes, depending on its register count. Its structured variables carry size,
CRC16, App ID, type, and schema version. Startup rejects stale, truncated, or
corrupt structures and falls back to a cold state. [confirmed]

Its `RPN83SAV` update is not atomic: it deletes the old variable before the
replacement exists. Validation detects corruption on the next launch, but an
interruption can lose the last valid state. [confirmed]

A runtime that needs the last committed dictionary should use two named slots.
This design remains a fixture target: [hypothesis]

- Store a magic value, format version, generation, payload length, CRC,
  payload, and final commit marker in each slot.
- Write and validate the inactive slot before archiving it.
- Reacquire the archived slot with `_ChkFindSym`, then validate it again.
- Delete the old slot only after the new archived slot is proven valid.
- At startup, validate both RAM and archived candidates and select the highest
  valid generation.
- Test resets at every write, archive, garbage-collection, and delete boundary.

AppVar data can move during allocation, deletion, archive, unarchive, or
garbage collection. Retain names and offsets, not long-lived absolute payload
pointers. Reacquire a RAM payload after memory-moving calls and an archived
payload after any operation that can collect the archive. See
[Resident assembly programs](sub-resident-programs.md) for the detailed handle
protocol. [confirmed]

## Minimal developer-key fixture

`tools/flash-apps/minimal_flash_app.asm` builds a one-page App named `REPROBE`.
It immediately exits through
`_JForceCmdNoChar`; it is a packaging and launch fixture, not yet a RAM-budget
probe.

The source uses SPASM-ng's `app.inc` and `ti83plus.inc`:

```sh
spasm -N -I path/to/spasm-ng/inc \
  tools/flash-apps/minimal_flash_app.asm /tmp/minimal-flash-app.8xk
```

Use a SPASM-ng build with GMP and OpenSSL App signing enabled. A build compiled
with `NO_APPSIGN=1` can emit raw App bytes, but its `.8xk` wrapper is not a
usable signed developer-key transfer file.

The reference build used SPASM-ng commit
`5f0786d38f064835be674d4b7df42969967bb73c`. It produces 668 bytes with SHA-256
`4dcbd992e71734b2255db34321d6980f5a908f8c0641ad4b79408e68e8334981`.
The repository header decoder reports:

```text
name REPROBE; pages 1/1; final field ends at 4070
entry bytes at 4080: CD 50 00 27 40 02 2D 40
```

The header field `801` contains key ID `0104`, the TI-83+/84+ freeware and
shareware developer key. This fixture has been assembled and decoded. It has
not been transferred to physical hardware. The build is confirmed. [confirmed]
Physical launch remains untested. [hypothesis]

## Remaining measurements

The fixture still needs these extensions:

- reserve generated-code RAM through a named AppVar;
- record `_MemChk`, heap pointers, VAT endpoints, and `SP` before and after the
  allocation;
- compare one-page and multi-page App builds on clean and representative VAT
  states;
- force an error, `PutAway`, reset, and archive garbage collection during
  persistence updates;
- repeat the executable-RAM boundary on identified 48 KiB and 128 KiB physical
  calculators.

Until those runs exist, report Flash residency as removal of the assembly copy,
not as proof that the complete `ram:9D95` through `ram:BFFF` range is available.
