# Shell loaders and writeback

Ion, MirageOS, Doors CS, and zStart all place assembly code at `userMem`
(`0x9D95`), but they do not preserve the source variable in the same way. This
page compares their RAM cost, writeback policy, lookup behavior, and cleanup
contract using identified original releases.

## Comparison

| Launcher | RAM-resident input | Archived input | Archive writeback | Error cleanup |
|---|---|---|---|---|
| Ion 1.6 | Moves the original body | Unarchives the original, then moves its body | Always rearchives | No Ion-owned error handler |
| MirageOS 1.2 | Uses a symmetric move loader | Keeps an archived source and a RAM execution form [hypothesis] | Rewrites only if changed | Installs an OS error handler |
| Doors CS 7.4 | Moves the original body | Creates a complete, uniquely named RAM temporary variable | Compares the temporary variable with the archive; replaces the archive only if changed | Routes OS errors through reverse-swap cleanup |
| zStart 1.3.013 | Moves the original body | Copies the body into a raw `userMem` allocation | Uses a 16-bit checksum; replaces the archive only if changed | Routes OS errors through local cleanup |

The three source-available launchers confirm that “run at `userMem`” does not
imply “make a second complete copy.” Their RAM-resident paths move the body in
chunks through a 768-byte shuttle. Archived inputs differ more substantially:
Ion first unarchives the original, Doors CS builds a named temporary variable,
and zStart builds an unnamed execution allocation. [confirmed]

The source identity, execution strategy, and open evidence boundary for each
row are also recorded in `tools/data/shell-loader-observations.csv`.

## The move-loader pattern

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

## Ion 1.6

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

The loader stages code in `appBackupScreen` (`0x9872`) and `cmdShadow`
(`0x966E`) and uses `plotSScreen` during both the forward and reverse moves. A
client may reuse the graph buffer after entry only if it restores any state
required before normal return. [confirmed]

## MirageOS 1.2

MirageOS 1.2 is a one-page, binary-only Flash App. Static disassembly of the
original App shows a symmetric loader at mapped addresses `0x75CF`–`0x76C0`. It
uses `saveSScreen` as a 768-byte shuttle, calls `_DelMem` and `_InsertMem`, and
moves the client to `0x9D95`. [confirmed]

The writeback path at mapped addresses `0x77D5`–`0x7870` compares RAM bytes with
archive bytes through a temporary page-read thunk. It replaces and rearchives
the program only when the comparison differs. The release changelog describes
the same smart-writeback policy. [confirmed]

The launch wrapper installs an OS error handler and conditionally prepares the
MirageOS tasker before calling the client. With tasker flag bit 6 at `0x9689`
set, mapped `0x7176`–`0x71E9` installs IM2 and writes timers, code, and a vector
table across `0x8A3A`–`0x8C1B`. The wrapper selects IM1 after the client
returns. It uses `0x966F` as the custom-interrupt entry when that option is
enabled. These `statVars` ranges are not client scratch while the tasker or
custom interrupt is active. [confirmed]

The changelog also states that ON+`^` quits immediately without writeback.
Whether that path restores every intermediate body and mapping, and what
`_ChkFindSym` returns for the archived program name while the client runs,
remain dynamic-trace questions. The archive-plus-RAM staging description in
the comparison table is therefore marked `[hypothesis]` even though the move
and compare routines themselves are confirmed.

## Doors CS 7.4

Doors CS classifies TI-OS assembly, Ion, MirageOS, Doors CS assembly, BASIC,
and associated program types in `runprog.asm`. For a RAM-resident assembly
program, `hook1` and the `swap1` through `swap4` routines move its body between
the variable and `0x9D95` through `plotSScreen`. [confirmed]

For an archived assembly program, `initTmpASM` checks available memory,
creates a complete RAM temporary variable under a unique name, and calls
`_FlashToRAM` before invoking the same move loader. This path needs space for
one complete RAM variable plus loader state; it does not retain another
complete execution copy after the move. [confirmed]

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

## zStart 1.3.013

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

## Lookup and persistence consequences

Self-lookup has three distinct outcomes across these loaders:

- A RAM-resident input can remain named in the VAT while its body is moved and
  is not a valid contiguous self-image.
- A Doors CS archived input has an immutable archived original plus a named
  temporary variable whose body is moved during execution.
- A zStart archived input has an immutable archived original plus an unnamed
  execution allocation.

MirageOS's exact name-to-image contract is still unmeasured. Code that needs
its running image should use a shell-defined pointer or a position-independent
scheme rather than assume that `_ChkFindSym` returns it.

Writeback also changes the persistence guarantee. Ion writes every originally
archived input back to Flash; MirageOS, Doors CS, and zStart avoid a Flash
rewrite on their confirmed unchanged paths. Forced shell exits can bypass
writeback under at least the documented MirageOS ON+`^` path, and nonlocal
exit behavior remains launcher-specific.

## Evidence limits

The Ion, Doors CS, and zStart results above come from source included in an
identified release or from an identified source commit. MirageOS results come
from its identified original binary and release changelog. These artifacts
confirm static control flow and data movement, not peak free-RAM measurements
or the machine state after every abnormal exit.

The following questions still require a common instrumented payload under all
four launchers:

- the exact peak RAM cost for RAM-resident and archived inputs;
- `_ChkFindSym` results and pointed-to bytes while each client is running;
- self-modification persistence on normal return, OS error, ON+`^`, and
  shell-to-shell exit;
- restoration of the stack, interrupt mode, page mapping, and scratch RAM on
  every abnormal path.

## Source provenance

| Artifact | Exact identity | Source |
|---|---|---|
| Ion 1.6 release archive | SHA-256 `b5a5ba97f325f8779aa35cda23e38152087930298ff8b7b8573905710230e6e6` | [ion.zip](https://www.ticalc.org/pub/83plus/asm/shells/ion.zip) |
| MirageOS 1.2 release archive | SHA-256 `38dc70173818972de8c5eb78099e8870c7acb9ad4c62d290f6c6f5840c71d43b` | [mirageos.zip](https://www.ticalc.org/pub/83plus/flash/shells/mirageos.zip) |
| Doors CS 7.4 release archive | SHA-256 `3a16161ce1d091438b0ea9f5e72774f8e8b4fdfba9ab1024bad0b55569555230` | [dcs7.zip](https://www.ticalc.org/pub/83plus/flash/shells/dcs7.zip) |
| Doors CS source repository | Commit `33af4f5ede199eee77cf2f89b5463a0a6ec9a1af` | [Doors CS 7 commit](https://github.com/KermMartian/Doors_CS_7/tree/33af4f5ede199eee77cf2f89b5463a0a6ec9a1af) |
| zStart 1.3.013 release archive | SHA-256 `7a1b7c69c85030b412bb6ea11ae71ac608b9882a9de3ab7dbef1faf69519c5e9` | [zstart.zip](https://www.ticalc.org/pub/83plus/flash/shells/zstart.zip) |
