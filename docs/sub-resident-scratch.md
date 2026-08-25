# Resident scratch RAM

Long-running assembly programs cannot treat the usual TI-OS work buffers as
anonymous memory while continuing to call arbitrary OS routines. Two OS
2.55MP traces directly overwrite `OP1`–`OP6`, `iMathPtr1`–`iMathPtr5`,
`textShadow`, and every byte of `saveSScreen`. The remaining advertised ranges
have subsystem owners that make them conditional, even where these traces did
not touch them. [confirmed]

The measurements are in `tools/data/scratch-ram-observations.csv` and
`tools/data/scratch-guard-results.csv`.
Regenerate a row set from a full-range TilEm trace with:

```sh
nix develop --command python3 tools/analyze_scratch_trace.py TRACE \
  --initial-port-5 0 --initial-port-7 0x81 \
  --scenario NAME --model ti84p --os-version 2.55MP --format csv
```

The initial selectors matter when a trace starts after TI-OS established its
normal mapping. A zero result means only that the scenario did not write the
range; it is not evidence that the range is safe.

The launch and interactive trace SHA-256 values are
`e61293d420f92b37dfa0d118f14896287735989c9292210933f1abca4ef6b0fa`
and `23338cdef33bc3f47988a3bf48089f25405205109b83421c3c1a9219f2e90505`.
The recorded rows identify the emulator only as `emulator-unspecified`; the
trace contents are pinned, but the emulator binary and source revision are not.
Each TLMT initial snapshot has fixed Flash page `0x00` SHA-256
`bfc698e445d98d6d0905589ec34a88c9372a90cb0ed2d1fe9aa9b6fca0962fc1`.
That hash matches page `0x00` in both known OS 2.55MP images. [confirmed]
Neither trace has a complete-ROM sidecar, so the hash does not identify the
boot pages or the complete image.

## Observed clobbers [confirmed]

Both scenarios are direct compiled `Asm(` launches of the local `ti84-forth`
runtime. The second continues through cooked-input activity. Counts are memory
writes, followed by the number of distinct bytes touched.

| Buffer | Address range | Launch | Interactive input | Classification |
|---|---|---:|---:|---|
| `OP1`–`OP6` | `ram:8478`–`ram:84B9` | 218 / 44 | 824 / 44 | Unsafe across ordinary parser, VAT, and floating-point calls |
| `iMathPtr1`–`iMathPtr5` | `ram:84D3`–`ram:84DC` | 80 / 8 | 88 / 10 | Unsafe across VAT, graph, table, and link activity |
| `textShadow` | `ram:8508`–`ram:8587` | 442 / 128 | 1,097 / 21 | Unsafe with ordinary text display |
| `saveSScreen` | `ram:86EC`–`ram:89EB` | 2,304 / 768 | 3,072 / 768 | Unsafe in the normal launch state |
| `statVars` | `ram:8A3A`–`ram:8C4C` | 0 / 0 | 0 / 0 | Candidate only after `_DelRes`, with statistics and shell interrupts excluded |
| Table/solver workspace | `ram:91DC`–`ram:9301` | 0 / 0 | 0 / 0 | Candidate only while table, solver, finance, and graph-table contexts are excluded |
| `plotSScreen` | `ram:9340`–`ram:963F` | 0 / 0 | 0 / 0 | Unsafe when graph or buffered-display routines remain available |
| `appBackUpScreen` | `ram:9872`–`ram:9B71` | 0 / 0 | 0 / 0 | Candidate only without app/menu transitions or installed hooks that own the buffer |

The traces include writers at `ram:1F37` and `07:51FA` for operand storage,
`07:4F70`–`07:4F82` for iMath pointers, and `01:617A` and `01:61C2` for text
state. The page-`0x3B` display-save loop writes every byte of `saveSScreen` at
its `3B:69C2` store. [confirmed]

Static ROM ownership disqualifies the zero-write rows as unconditional storage:
`_GrBufClr` clears `plotSScreen`; graph primitives consume it; table, solver,
finance, and graph-table code own the `ram:91DC` workspace; statistics routines
deposit named results in `statVars`; and app/menu state paths use
`appBackUpScreen`. [confirmed]

There is consequently no buffer in this table that remains stable while every
display, keyboard, VAT, archive, graph, table, statistics, app, error, APD,
link, and USB path is allowed. A runtime may borrow a conditional range only by
defining the excluded calls and contexts as part of its ABI.

### Third-party hook ownership of `appBackUpScreen`

Archived community source and complete TilEm traces identify persistent
raw-key, parser, and IM2 residents as additional owners of
`appBackUpScreen`. The runs use OS 2.55MP image SHA-256
`dbb47afae091ab36f9abe74e32083013fbeff3d7e0516bbf5d1abf4ee57adc09`
and patched TilEm commit `d1bdc58dd321ae462a701e556fcb62bb925a78b1`.
They establish emulator execution, not physical-hardware behavior. [confirmed]

- NoExec copies a raw-key hook to `appBackUpScreen` and a parser hook to
  `appBackUpScreen + 500`. It calls `_EnRawKeyHook` and `_EnParserHook`, then
  returns while the hooks remain installed according to its control flow.
- Plasma 1.4.1 copies its raw-key hook to `0x9872`, installs it with
  bcall `4F66h`, and launches its loader while that hook can receive key and
  **ON** events.
- Remote Control copies a key hook to its `KEYLOC` equate at
  `appBackUpScreen`, installs it with bcall ID `4F66h`, and returns. The hook
  sends bytes through `_SendAByte` when TI-OS invokes it.
- ONBLOCK fills `0x9900`–`0x99FF` with an IM2 vector, copies its handler to
  `0x9A9A`, selects IM2, and returns while both ranges remain live inside
  `appBackUpScreen`. Its handler clears port-`0x03` bit 0 before calling the
  TI-OS IM1 entry at `ram:003A`.

**Dynamic confirmation.** NoExec writes `0x83` at both `ram:9872` and
`ram:9A66`. `_SetGetKeyHook` at `3B:7D00` then stores pointer
`0x9872`, page `0x07`, and sets bit 5 of `IY + 0x34`.
`_SetParserHook` at `3B:7D6E` stores pointer `0x9A66`, page `0x07`, and sets
bit 1 of `IY + 0x36`. Remote Control reaches the same raw-key installer with
pointer `0x9872`, while Plasma stores pointer `0x9872` with its supplied page
byte `0x41`. These runs stop before invoking Remote Control's link sender.
[confirmed]

The ROM installers store each callback as a packed three-byte target:

```c
#pragma pack(push, 1)
typedef struct {
    uint16_t callback_addr;  /* +0x00, little-endian */
    uint8_t page;            /* +0x02 */
} OSHookTarget;              /* 3 bytes */
#pragma pack(pop)
```

The same packed record is used by these audited setters: [confirmed]

| Hook | Target record | Active flag | Setter | Clearer |
|---|---:|---|---|---|
| raw key | `ram:9B84` | bit 5 of `IY + 0x34` | `_SetGetKeyHook = 0x4F66`, body `3B:7D00` | `_ClrRawKeyHook = 0x4F6F`, body `3B:7B88` |
| token | `ram:9BC8` | bit 0 of `IY + 0x35` | `_SetTokenHook = 0x4F99`, body `3B:7D0B` | `_ClearTokenHook` |
| parser | `ram:9BAC` | bit 1 of `IY + 0x36` | `_SetParserHook = 0x5026`, body `3B:7D6E` | `_ClearParserHook = 0x5029`, body `3B:7C3B` |
| silent link | `ram:9BD0` | bit 7 of `IY + 0x36` | `_SetSilentLinkHook = 0x50CE`, body `3B:7DBB` | `_DisableSilentLinkHook` |

Each setter stores `HL` as the callback address, stores `A` as the page byte,
sets only its active bit, and returns. The clear bodies at `3B:7B88` and
`3B:7C3B` only reset their respective active bits; they do not wipe the target
records. A controlled trace additionally installs token target
`{ ram:9872, page 0 }` and silent-link target `{ ram:9875, page 0 }`, observes
their active bits, and restores both records and all affected flag bytes before
halting. The result is in `tools/data/community-bcall-semantics.csv`.
[confirmed] under TilEm.

`_ClrCursorHook = 0x4F69`, body `3B:7AEA`, is not a silent-link clearer. It
only resets bit 7 of `IY + 0x34`. The DisLink source first clears the real
silent-link bit, bit 7 of `IY + 0x36`, itself and then calls `0x4F69` under the
comment “actually uninstall it.” The first instruction disables its silent
hook; the bcall separately disables any cursor hook. A controlled trace seeds
bit 7 of `IY + 0x34`, calls the bcall, observes that bit clear, and restores the
original flag byte. [confirmed]

After the selected NoExec removal sequence, the resident reaches
`_ClrRawKeyHook` at `3B:7B88` and `_ClearParserHook` at `3B:7C3B`; the two
active bytes at `IY + 0x34` and `IY + 0x36` become zero. Remote Control's
resident removal path was not exercised because its ordinary hook events send
link bytes. [confirmed] for NoExec; [hypothesis] for Remote Control removal.

The ONBLOCK trace writes `0x9A` at `ram:9900` and `ram:9901`, copies byte
`0x08` to its handler entry at `ram:9A9A`, and subsequently executes that
entry 1,303 times. The source handler tail calls the TI-OS IM1 entry at
`ram:003A`. [confirmed]

An assembly runtime must therefore exclude or explicitly remove installed
raw-key, parser, and shell hooks and persistent IM2 residents before borrowing
this buffer. The documented `_DisableApd` and `_DelRes` conditions for other
buffers do not establish that `appBackUpScreen` is unowned.

The pinned include names `0x4F66` `_SetGetKeyHook`; the Plasma and NoExec
sources instead describe raw-key-hook enablement. The ROM target stores the
supplied pointer and page and sets the active flag, so this page records both
names as aliases without deriving the callback ABI from either name.

## Conditional `saveSScreen` and `statVars` claims

Public TI-83 Plus documentation permits `saveSScreen` after `_DisableApd`, and
permits `statVars` after `_DelRes` when statistics code is excluded. `_DelRes`
invalidates existing statistics results; it does not reserve the block against
later statistics commands or third-party interrupt handlers. [standard]

### Direct TI-OS guard

The guarded direct-launch fixture calls `_DisableApd` and `_DelRes`, fills all
768 bytes of `saveSScreen` with `0xA5` and all 531 bytes of `statVars` with
`0x5A`, polls `_GetCSC`, blocks in `_GetKey`, and receives one injected **ON**
event. Both complete checks pass, and the fixture displays `SAVE STAT 1 1`.
This result is limited to TI-OS 2.55MP in one TilEm x4 run. Its trace SHA-256
is `716fe78c274536d2d486d53c2d1b89606c0aafee101c5562202d658250b52508`.
Its TLMT Flash page `0x00` hash matches the launch traces, but it also lacks a
complete-ROM sidecar. The recorded capture context and trace content establish
this emulator result; the trace does not independently identify every ROM page.
[confirmed]

Build the TI-BASIC `Asm(prgmSCRPROBE)` wrapper with
`tools/build_scratch_probe_wrapper.py`; then assemble
`tools/fixtures/scratch_guard_probe.asm` and run
`tools/macros/scratch-guard-probe.macro`. The full trace executes 14,736
instructions in the payload range, including the 767- and 530-byte fill
`LDIR`s and the complete 768- and 531-byte comparison loops. The fixture halts
after rendering the result so a held **ON** key cannot enter another `_GetKey`.

This confirms the documented `saveSScreen` condition for that direct emulator
scenario. It does not cover an APD timeout, error unwinding, physical hardware,
or statistics code after `_DelRes`.

### Additional third-party `saveSScreen` owners

Three older community sources deliberately execute from or overlap
`saveSScreen`. Weird and LCD2 have complete OS 2.55MP emulator traces; GPP
remains a static source finding. [confirmed]

- GPP 1.1 builds IM2 tables at `ram:8600` and `ram:8700`, places interrupt
  code at `ram:8686` and `ram:8787`, and alternates display buffers from the
  handler. Both code ranges overlap `saveSScreen`.
- Weird places a signature at `ram:86EC`, an ISR at `ram:8888`, and an IM2
  table at `ram:8700`. Its handler also reads `apdTimer` and writes the LCD
  through ports `0x10` and `0x11`.
- LCD2 emits a timing routine into `saveSScreen`, calls the buffer as code,
  and uses direct LCD reads to adjust its delay.

The source-built Weird fixture writes its `0xFF` signature at `ram:86EC`,
copies an ISR beginning with `0xF3` to `ram:8888`, fills its table at
`ram:8700` with `0x88`, and executes the ISR entry seven times. LCD2 rewrites
the timing entry at `ram:86EC` during calibration and executes that address
141 times before reaching its result screen. [confirmed]

GPP's distributed examples require the legacy Ion client environment. No
byte-matched direct-client run is recorded, so execution at `ram:8686` and
`ram:8787` remains unmeasured. [hypothesis]

These examples are evidence of additional third-party ownership, not evidence
that the range is safe on current OS or shell combinations.

### Third-party-owned `statVars` ranges

Common shells and interrupt installers do not share one `statVars` contract.
The table separates static third-party ownership from the direct dynamic guard.
Identified owned ranges come from the release source or binary. [confirmed]
Untraced runtime cells remain open.

| Context | Result | Evidence and boundary |
|---|---|---|
| Direct TI-OS 2.55MP | All 531 bytes pass | One TilEm x4 guard with `_DelRes`, statistics excluded, and IM1; no physical run |
| MirageOS 1.2 with tasker disabled | Candidate only | The setup routine returns while tasker flag bit 6 at `0x9689` is clear; no client guard run |
| MirageOS 1.2 with tasker or custom interrupt active | Unsafe | The original binary installs timers, handler code, and an IM2 vector table inside `statVars` before client execution |
| Doors CS 7.4 | Unsafe as general client storage | Source reserves the block for shell state; its Mirage-compatible interrupt also installs code and vectors there |
| ViewRegs interrupt installed | Unsafe | The release binary dynamically copies code to `ram:8790`, `statVars`, and `ram:8C01`, fills `ram:8B00` with `0x8A`, and executes `ram:8790` 656 times in TilEm; no physical run |
| Ion 1.6 | Unresolved | Source review pins no Ion-owned interrupt in this block; no client guard run |
| zStart 1.3.013 | Unresolved | The launcher selects IM1 for the client and pins no explicit shell owner in this block; no client guard run |

MirageOS's tasker setup at mapped `0x7176`–`0x71E9` writes these ranges:

| Range | MirageOS owner |
|---|---|
| `0x8A3A`–`0x8A3E` | three timer counters and two reload values |
| `0x8A4F`–`0x8A88` | relocated interrupt code |
| `0x8A8A`–`0x8AFE` | relocated interrupt dispatcher |
| `0x8B00`–`0x8C00` | 257-byte IM2 vector table built by `_MemSet = 4C33h` |
| `0x8C01`–`0x8C1B` | relocated timer worker |

The timer worker at mapped `0x7140`–`0x715A` updates the first five bytes. The
launch paths call the setup routine before calling the client at `0x9680` or
`0x9D96`; they select IM1 only after that call returns at mapped `0x7584` or
`0x75A3`. A client can therefore run while the MirageOS IM2 owner is active.
[confirmed]

Doors CS source defines `pendfile = 0x8A3A` and places up to 48 bytes of ALE
vectors after its ten-byte record, occupying `0x8A3A`–`0x8A73`. Its source
also declares the complete 531-byte `statVars`/`anovaf_vars` span as internal
storage. The Mirage-compatible `mos_setupint` routine installs its handler at
`0x8A8A`, its vector table at `0x8B00`–`0x8C00`, and optional timers at
`0x8A3A`–`0x8A3E`. `_DelRes` does not release these shell-owned objects.
[confirmed]

ViewRegs calls `_DelRes`, then copies a 603-byte interrupt block to
`IntAddress = saveSScreen + 767 - 603`. It copies another block to the start of
`statVars`, builds an IM2 vector table at `0x8B00`–`0x8C00`, and places another
handler block at `0x8C01`. Its readme warns that `statVars` must not be accessed
and statistics must not run while the interrupt is active. The trace observes
first writes at `ram:8790`, `ram:8A3A`, `ram:8B00`, and `ram:8C01`, followed
by 656 executions of the resident entry. `_DelRes` therefore does not reserve
either buffer against a subsequently installed third-party interrupt.
[confirmed]

`tools/data/scratch-guard-results.csv` records the direct trace, the exact
MirageOS and Doors CS owned ranges, and explicit `not-run` rows for Ion and
zStart. Dynamic guards under all four shells and physical-calculator runs
remain required before the checklist's common-shell requirement is complete.
The community-program trace identities and exact write observations are in
`tools/data/community-runtime-observations.csv`.

## Page `0x83` during resident execution

Page `0x83` is OS state rather than a spare 16 KiB page. The two resident traces
add the following observations to the boot and expression traces documented in
[RAM pages](ram-pages.md):

| Scenario | Writes | Touched range |
|---|---:|---|
| Direct resident launch | 2,304 | `83:5A7E`–`83:5D7D` |
| Interactive resident input | 3,072 | `83:5A7E`–`83:5D7D` |
| Guarded `_GetKey` wait interrupted by **ON** | 3,893 | `83:4373`–`83:4390`, `83:577E`–`83:5794`, and `83:5A7E`–`83:5D7D` |

The range is the LCD/home-display capture area. Combining these runs with ROM,
boot, and expression evidence gives these known owners:

| Page-`0x83` range | Owner |
|---|---|
| `83:4000`–`83:4080` | App base-page staging [standard] |
| `83:4100`–`83:433A` | USB communication buffers [standard] |
| `83:4373`–`83:4390` | Expression-path block copy [confirmed] |
| `83:43D9`–`83:44BD` | Boot/home block copy [confirmed] |
| `83:577E`–`83:5A7D` | MathPrint previous-entry history [confirmed] |
| `83:5A7E`–`83:5D7D` | LCD/home-display capture [confirmed] |
| `83:5D7E`–`83:5DF2` | Additional boot/home writes in the measured scenario [confirmed] |

All holes are candidates, not safe ranges. A separate direct-TI-OS trace covers
one division-by-zero dialog without adding a range beyond the boot baseline.
Current coverage still omits USB receive, archive garbage collection,
statistics, the program editor, app transitions, APD timeout, and third-party
interrupts. The `_GetKey` guard called `_DisableApd`, so its **ON** event does not
cover APD. [confirmed]

Selectors `0x82`–`0x87` alias one physical RAM page on 48 KiB ASICs. Pages
`0x84`–`0x87` still need forced read/write/hash probes on 128 KiB calculators;
an emulator's unused page is not hardware confirmation. [standard]

## Mapping a RAM page through bank A

The page-zero bcall dispatcher at `ram:2A2F` restores the caller's port-`0x06`
selector on ordinary return. During the bcall, however, the dispatcher maps its
own target into `0x4000`–`0x7FFF`, so a pointer into a borrowed bank-A page is
invalid. An OS error can also bypass caller-owned cleanup. [confirmed]

A bounded copy operation should save the selector and interrupt state, map the
page, copy, and restore before making another bcall:

```z80
    LD A,I
    PUSH AF             ; P/V records IFF2
    DI
    IN A,(0x0E)
    PUSH AF
    IN A,(0x06)
    PUSH AF

    XOR A
    OUT (0x0E),A
    LD A,0x83
    OUT (0x06),A

    ; Copy only. Do not call a bcall with a pointer into bank A.

    POP AF
    OUT (0x06),A
    POP AF
    OUT (0x0E),A
    POP AF
    JP PO,interrupts_were_disabled
    EI
interrupts_were_disabled:
```

Code running in bank A cannot use this sequence to map out its own instruction
stream. Keep interrupts disabled for the entire nonstandard mapping unless the
interrupt handler is proven independent of normal bank-A ROM. Restore both
ports even though port `0x0E` is ignored by TI-84 Plus and TI-84 Plus SE
hardware; doing so keeps the helper transparent and portable to related models.

## Sources

| Source | Use here |
|--------|----------|
| OS 2.55MP ROM and `tools/analyze_scratch_trace.py` | ROM ownership and trace write attribution |
| `tools/data/scratch-ram-observations.csv` | launch scenarios, selector assumptions, and write counts |
| `tools/data/scratch-guard-results.csv` | guard trace identity, shell-owned ranges, and evidence limits |
| [TI-83 Plus Developer Guide](https://education.ti.com/download/en/ed-tech/830D08FF31804AEAA2F03B8F5E89AD14/672891A1E98349CAB91C11B4928C253C/sdk83pguide.pdf) | documented `saveSScreen`, `statVars`, `_DisableApd`, and `_DelRes` conditions |
| [WikiTI RAM pages, revision 11670](https://wikiti.brandonw.net/index.php?title=83Plus:OS:Ram_Pages&oldid=11670) | public page-`0x83` owners and `0x82`–`0x87` alias behavior |
| [MirageOS 1.2 release archive](https://www.ticalc.org/pub/83plus/flash/shells/mirageos.zip), SHA-256 `38dc70173818972de8c5eb78099e8870c7acb9ad4c62d290f6c6f5840c71d43b` | tasker setup and client-launch control flow |
| [Doors CS source at `33af4f5`](https://github.com/KermMartian/Doors_CS_7/tree/33af4f5ede199eee77cf2f89b5463a0a6ec9a1af) | shell state, ALE vectors, and Mirage-compatible interrupt ownership |
| [Ion 1.6 release archive](https://www.ticalc.org/pub/83plus/asm/shells/ion.zip), SHA-256 `b5a5ba97f325f8779aa35cda23e38152087930298ff8b7b8573905710230e6e6` | source review for the unresolved Ion row |
| [zStart 1.3.013 release archive](https://www.ticalc.org/pub/83plus/flash/shells/zstart.zip), SHA-256 `7a1b7c69c85030b412bb6ea11ae71ac608b9882a9de3ab7dbef1faf69519c5e9` | source review for the unresolved zStart row |
| [NoExec release archive](https://www.ticalc.org/pub/83plus/asm/programs/noexec.zip), SHA-256 `dc3ddf2dd4de8a802a2862d6aaf671a4ff5e618eb98377844eb711b90a443a84`; member `noexec.z80`, SHA-256 `de323ead58eea7b9590865da2694905b775b8f900c798fa438b4aa9b035d58b5` | static raw-key and parser hook placement in `appBackUpScreen` |
| [Plasma 1.4.1 release archive](https://www.ticalc.org/pub/83plus/asm/shells/plasma141.zip), SHA-256 `62965a41fe071902043ebcbbd1254f710d29729bf86a78f20b6f14d6974f5d5a`; member `Plasma/plasma.asm`, SHA-256 `b424980285adf3f16225239c3ba3f133a42efb38d0666d968eee4b1fe24b810f` | static raw-key hook placement in `appBackUpScreen` |
| [Remote Control release archive](https://www.ticalc.org/pub/83plus/asm/programs/remotecontrol.zip), SHA-256 `9eb1d4bb9beabe0ae31e49756c2a23938c6301a27f3d553a5d3381651262e591`; member `RemoteC.z80`, SHA-256 `19eb8c5b8b20a1f9139ac89c8603727f76977ddb9548c8ff318ef5eec07285c4` | static key-hook placement and link-send behavior |
| [ONBLOCK release archive](https://www.ticalc.org/pub/83plus/asm/programs/onblock.zip), SHA-256 `40a5139d378608a303691fb34f3edf79ae4968bf39801b75bc311371b66f69d2`; member `ONBLOCK.asm`, SHA-256 `3023dc7654db87f8f2ea60f54a4b61beba1ca1252cc3fff975409631384ed750` | static persistent IM2 vector and handler placement in `appBackUpScreen` |
| [ViewRegs release archive](https://www.ticalc.org/pub/83plus/asm/programs/viewregs.zip), SHA-256 `84837e779315f799b53f8115e8c4e9563babc5add0541f52d72117d93a68e2b2`; member `ViewRegs/ViewRegs.z80`, SHA-256 `120d8a7845a0f0f7a4f3c32f4f53b1e1f1d5efd210af542e64e1408546bba13b`; member `ViewRegs/readme.txt`, SHA-256 `a4f66bc84f2f7d17e2dbfa5603fb3b65ed57f311e20dbb7143ad95bde20d2cf7` | static IM2 ownership of `saveSScreen` and `statVars`, plus the statistics warning |
| [GPP 1.1 release archive](https://www.ticalc.org/pub/83plus/asm/graphics/ion/gpp11.zip), SHA-256 `08167b71e72cca031782d5154048fdb4b3f2b8a6a088b476936b5abd1f53ed10`; member `graydev/template/graylib.inc`, SHA-256 `2891c83665a136c02fd43df5a5db05ef9be229a5f98263539c4596458f211fa8` | static IM2 table and interrupt-code placement overlapping `saveSScreen` |
| [Weird source](https://www.ticalc.org/pub/83plus/asm/source/weird.z80), SHA-256 `881cb1b39c41da3e2629e8cc39765f4cc8e337e6e5a2b65d0539df2cb9fd8ca4` | static persistent IM2 ownership inside `saveSScreen` |
| [LCD2 release archive](https://www.ticalc.org/pub/83plus/asm/programs/lcd2.zip), SHA-256 `46532d795aadfff782a83ca52001da87ad73cef9e2013c7800291f4b26af94ab`; member `lcd2.asm`, SHA-256 `01033202eb0439a7a6dcdb1b28abf62f2c52aeecc630c4688c8603de75b97780` | static timing-code execution from `saveSScreen` |
