# Shell loaders and writeback

Ion, Plasma, TSE, MirageOS, Doors CS, and zStart all place assembly code at
`userMem` (`0x9D95`), but they do not preserve the source variable in the same
way. This page compares their RAM cost, writeback policy, lookup behavior, and
cleanup contract using identified original releases.

## Comparison

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

The loader stages its preloader in `appBackUpScreen` (`0x9872`) and its move
routine in `cmdShadow` (`0x966E`). It uses `plotSScreen` during the forward and
reverse moves. The client may reuse `plotSScreen` while it runs; the reverse
move overwrites that buffer before Ion redraws its interface. [confirmed]

## Plasma 1.4

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

## TSE 1.5/1.6

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

## MirageOS 1.2

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

## Doors CS 7.4

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

## Evidence limits

The Ion, Plasma, TSE, Doors CS, and zStart results above come from source
included in an identified release, byte-matched release source, or an
identified source commit. MirageOS results come from its identified original
binary and release changelog. These artifacts confirm static control flow and
data movement, not peak free-RAM measurements or the machine state after every
abnormal exit.

The following questions still require a common instrumented payload under all
six launcher and runtime designs:

- the exact peak RAM cost for RAM-resident and archived inputs;
- `_ChkFindSym` results and pointed-to bytes while each client is running;
- self-modification persistence on normal return, OS error, **ON**+**^**, and
  shell-to-shell exit;
- restoration of the stack, interrupt mode, page mapping, and scratch RAM on
  every abnormal path.

## Source provenance

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
