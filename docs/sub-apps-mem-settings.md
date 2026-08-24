# Apps, memory reset, and settings

This page traces Flash App launch and resident runtime design, the **MEM →
Reset** paths, and the format and graph flags controlled by the **MODE**
screen. Addresses and confidence flags follow
[Conventions and methodology](conventions.md).

Cross-references: [Boot, contexts, and errors](boot-contexts-errors.md)
(contexts, `_AppInit`, event router), [Memory management](memory-management.md)
(RAM heap, `_CleanAll`), and [Flash page map](flash-page-map.md) (Flash page
map). Flag bits use the `ti83plus.inc` equates; the SystemFlags base is
`IY = flags = 0x89F0`, so, for example, `(IY+0x0A)` = `flags + fmtFlags`.

## Flash Apps — find and launch

This ROM ships with zero bundled apps in the local ROM-byte scan (zero `80 0F` headers found at page starts) [hypothesis],
but the entire find/launch machinery is present on `page 0x3D` (`_FindApp*`) and
`page 0x3B` (`_AppInit` glue / app-quit). Apps are TI Flash Applications: a contiguous
run of 16 KiB flash pages whose first page begins with a TLV app header.

### App header format (TLV) [confirmed]

An app header is a sequence of type-length-value fields starting at offset 0 of the
app's first page. Each field begins with two bytes in WikiTI's `TT TS` notation: the high
12 bits are the field number. A low size nibble from `0` through `C` is the
payload length; `D`, `E`, and `F` instead select one, two, or four following
length bytes. The decoder bytes are at `init_flash_page_counter+0x08`
(`3D:7285`), but the disassembly does not expose a separate function there:

| size nibble | following length bytes |
|-------------|--------------------|
| `0xD` | 1 byte  |
| `0xE` | 2 bytes |
| `0xF` | 4 bytes |

```z80
3D:7285  AND 0x0F
         CP 0x0F              ; B=4
         CP 0x0E              ; B=2
         CP 0x0D              ; B=1
```
The master field at offset 0 is usually `80 0F …` (`field 800`, size nibble `F`, followed
by a 4-byte size) — this is what the page-scan keys on to recognise an app. Fields carry
the app name, the page count, flags, the date stamp, and signature-related data.

The public header descriptions match the ROM parser and the local app corpus. Useful
references are WikiTI's
[application-header](https://wikiti.brandonw.net/index.php?title=83Plus:OS:Certificate/Headers:Fields:Application_Headers)
and [certificate/header format](https://wikiti.brandonw.net/index.php?title=83Plus:OS:Certificate/Headers)
pages, TI's
[AppHeader guide](https://isa.umh.es/calc/TI/TI83-84SDK/appheaderguide.pdf), and
Tari's [Cemetech disassembly note](https://www.cemetech.net/forum/viewtopic.php?t=20732&highlight=),
which describes `.8xk` data as Intel HEX pages based at `0x4000` and app code as starting
after field `807`.

Common app-header fields in the sample corpus:

| field | meaning | observed payload |
|-------|---------|------------------|
| `800` | master Flash-variable field | `800F` with a four-byte app length at the start of every sampled app |
| `801` | developer/signing key | `0104`, the TI-83+/84+ freeware/shareware app key |
| `802` | program revision | one-byte revision, usually `1` |
| `803` | build number | one-byte build number, usually `1`; MirageOS uses `2` |
| `804` | app name | up to 8 bytes; examples include `Axe`, `MirageOS`, `USBDRV8X`, and `zStart` |
| `808` | page count | one byte; matches the decoded page count for Axe and CtlgHelp's two-page apps |
| `809` | disable TI splash screen | usually zero-length when present; zStart uses a 15-byte app-owned payload |
| `80C` | lowest basecode | usb8x uses `02 1E`, decoded as basecode `2.30` |
| `032` | date stamp | six-byte payload: nested `09 04`, then a four-byte count of seconds since 1997-01-01 |
| `020` | date-stamp signature / unchecked payload | usually 64 bytes; Axe stores executable helper bytes here |
| `807` | final field | terminates the parsed header; the `807F` length bytes are ignored |

The app header is not a fixed 128-byte struct. The `807` final field terminates it. The
common `80 7F 00 00 00 00` form uses size nibble `F` with a four-byte zero, but WikiTI
documents that length as ignored; the shorter `80 70` form is valid. The app body begins
after the final field and any app-controlled padding. Bytes before the conventional
`4080` entry point are not loader magic; they are field payload or padding, and an app can
choose payload bytes that also decode as Z80. [standard]

External sample check (not ROM evidence): the local Axe Parser `Axe.8xk` sample decodes to
a base page whose `020D` date-stamp-signature field starts at `4027` and has a 64-byte
payload. Part of that payload is a Z80 helper at `4037`:

[ti-kid](https://github.com/ti-kid) identified this Axe header case and published an annotated decode in
[Hatchet-Compiler](https://github.com/ti-kid/Hatchet-Compiler/blob/master/Axe0_annotated.asm#L160);
the local decode below uses that lead and verifies it against the extracted `Axe.8xk` bytes.

```z80
4037  POP AF
4038  POP BC
4039  POP DE
403A  POP HL
403B  PUSH HL
403C  PUSH DE
403D  PUSH BC
403E  PUSH AF
; ...
4056  LD A,0C9h
4058  CPIR
405A  PUSH HL
405B  IN A,(6)
405D  DEC A
405E  LD HL,4065h
4061  RST 20h
4062  JP 8478h
4065  OUT (6),A
4067  RET
```

`RST 20h` is `_Mov9ToOP1`, so the helper copies the thunk at `4065` into OP1
(`0x8478`) and jumps to OP1. That makes the following thunk run from RAM after
`A` has been set to the current bank-A page minus one:

```z80
OUT (6),A
RET
```

The preceding `CPIR` searches
from `HL` for a `RET` byte (`0xC9`) and pushes the byte after it as the return
address. The first half preserves the popped registers while it probes caller-owned
bytes and can return early; the later page switch and RAM-thunk behavior are directly
decoded from the sample bytes.

The same sample's conventional entry area at `4080` starts:

```z80
NOP
JR 408C
JP 4097
JP 4548
```

`tools/app_header_re.py` reproduces this pass: `--fetch-known` downloads a
local corpus from ticalc.org into ignored `tools/app-samples/`, and `--markdown` prints
the decoded header table. The corpus keeps the same parser boundary rule:

| app sample | pages field / decoded pages | final field end | entry bytes at `4080` | header-area note |
|------------|-----------------------------|-----------------|-----------------------|------------------|
| Axe | 2 / 2 | `4070` | `00 18 09 C3 97 40 C3 48` | `020` payload contains the `4037` helper; then padding |
| MirageOS | 1 / 1 | `4070` | `C3 D3 65 C3 D9 47 C3 D6` | padding to `4080` |
| Omnicalc | 1 / 1 | `4070` | `C3 8C 40 C3 E5 79 C3 70` | padding to `4080` |
| CalcSys | 1 / 1 | `4070` | `C3 89 40 21 AA 98 CB DE` | padding to `4080` |
| Symbolic | 1 / 1 | `4070` | `18 2E 3A 4A 42 4A 4D 4A` | padding to `4080` |
| BatLib | 1 / 1 | `4070` | `C3 25 61 C3 6E 43 C3 DE` | padding to `4080` |
| BatLib-modified Celtic 3 / Grammer / Omnicalc | 1 / 1 | `4070` | app-specific jump/vector bytes | same boundary; nonzero `807F` size bytes are ignored |
| zStart 1.3.013 / zStart83 | 1 / 1 | `4080` | `18 11 83 C3 ...` | `809D0F` carries a 15-byte Z80 helper at `406B` |
| CtlgHelp / zChem from zStart | 2 / 2 or 1 / 1 | `4070` | app-specific bytes | padding to `4080` |
| usb8x | 1 / 1 | `4029` | `00 00 00 00 00 00 00 96` | mostly zero padding, plus `JP 4180h`<br>`JP 42EAh` at `4049` |

So `4080` is a common app-entry convention, not the OS's header parser boundary. Some
apps end the parsed header at `4029`, `4070`, or exactly `4080`, and all remain valid
because the `807` final field terminates the header.

The public entry points for walking these fields are bcalls in `ti83plus.inc`:
`_FindAppHeaderSubField` (ID `80ABh`, body `3F:500A`) locates a field in an App
header, and `_FindOSHeaderSubField` (ID `8075h`, body `3F:5018`) does the same
for the OS header. Both build on `_FindSubField` (ID `805Dh`, body `3F:4DFB`),
`_FindGroupedField` (ID `8030h`, body `3F:4E8C`), and `_GetFieldSize` (ID
`805Ah`, body `3F:4DB8`), which decode the TLV length nibble shown above. These
retail targets are recorded in `tools/data/boot-page-comparison.csv`.
[confirmed]

### `_FindApp`, `_FindAppUp`, and `_FindAppDn` [confirmed]

- `_FindApp` (`3D:5EE3`) — locate an app by name (OP1). Inits the search page,
  then loops `app_find_next_page (5FB1)` + a header-match step until done, returning the app's
  start page and a found/not-found flag via `RST 28` (bcall) into RAM flash helpers.
  ```z80
  5EE3 CALL 727D            ; init_flash_page_counter -> appSearchPage (0x82A3)
  5EE6 CALL 5FB1            ; step to next candidate page (DEC appSearchPage)
  5EE9 RET C                ; ran off the end -> not found
  5EEA CALL 5EB2            ; read/compare this page's header
  5EED BIT 3,C
       JR Z,5EE6            ; not a match -> keep scanning
  ```
- `app_find_next_page` (`3D:5FB1`) — `appSearchPage (0x82A3) -= 1`; stops at page 7
  (low boundary of the app region); bjumps `appSearchPage:0x4000` to inspect the header.
- `init_flash_page_counter` (`3D:727D` → `model_app_top_page` at `3D:726E`) — initializes `appSearchPage` at `0x82A3` to the model-selected top App page plus one.
- `_FindAppUp` (`3D:5DDA`) / `_FindAppDn` (`3D:5DE6`) — enumerate the previous / next app
  in flash (for the APPS-menu list), both wrapping the common walker `app_5de7` (`3D:5DE7`).
  `app_5de7` keeps two counts in BC (apps before/after) and tracks the current name in OP3.
- `_FindAppNumPages` (ID `509Bh`) maps to `3D:4AA3`; the current Ghidra
  database has no function record at that body address.

State variables: `appSearchPage` = `0x82A3`, `0x8497`/`0x8481`/`0x9C87` are search-mode
scratch (`0x9C87`='i' selects the in-RAM "temp app" search variant).

### Launching an app as a context [confirmed]

`_AppInit` (`ram:0936`, bcall `0x404B`) installs a context from an app header:
```text
_AppInit(byte *hdr):                 # HL -> 13-byte vector block in the header
  copy 12 bytes hdr[0..11] -> cxMain (0x858D)   # the 6 context vectors
  flags.appFlags (IY+0x0D) = hdr[12]            # appFlags byte
  cxPage (0x8599) = port_mapBankA               # the flash page the handlers run from
```
The 12 bytes are the 6 little-endian handler pointers (`cxMain`, `cxPPutAway`, `cxPutAway`,
`cxRedisp`, `cxErrorEP`, `cxSizeWind` — see [Boot contexts & errors](boot-contexts-errors.md) §Context block). Example: the OS's own
default app vectors live at `3B:7571`:
```text
3E 75 | 4B 75 | 9F 74 | 4B 75 | 4B 75 | 4B 75 | 0A
cxMain=753E cxPPutAway=754B cxPutAway=749F cxRedisp=754B cxErrorEP=754B cxSizeWind=754B appFlags=0A
```
`_ReloadAppEntryVecs` (`3B:73E4`, ID `4C36h`) calls `_AppInit` on that block, then
overrides `cxErrorEP (0x8595)=0x27D9`. After `_AppInit`, the main event loop runs the app
through `call_context_main` (pages in `cxPage`, jumps `(cxMain)` — [Boot contexts & errors](boot-contexts-errors.md)).

Because `cxCurApp` (`0x859A`) is a key code, pressing a mode key selects the context to
load ([Boot contexts & errors](boot-contexts-errors.md)). The App quit restore-path candidate at
`3B:7412` is not a defined function in the disassembly; the saved-context restore behavior
is a byte-trace note (the label is project-local, not a WikiTI or `ti83plus.inc` equate).

---

## Flash Apps as resident runtimes

A Flash App can keep its runtime in Flash instead of copying it to `userMem`.
Some Apps instead use Flash as a launcher for generated RAM code. Neither
design turns `ram:9D95`–`ram:BFFF` into private storage; the OS still owns that
range as part of the user heap.

### Code in Flash, state in RAM

The current App page executes in bank A at `0x4000`–`0x7FFF`. An App
therefore avoids the temporary copy that the compiled `Asm(` launcher creates
at `ram:9D95`. The conventional `ram:9D95`–`ram:BFFF` interval contains
8,811 bytes. [confirmed]

That interval remains part of the movable user-data region. Variables,
temporary objects, the FPS/OPS gap, and the VAT determine how much space is
available. An App must reserve mutable storage through the OS or start from a
controlled memory image. It cannot claim 8,811 bytes merely because its code
executes from Flash. [standard]

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

### Community RAM-core launcher

The TruVid App build uses Flash as a wrapper around a RAM playback core. Its
source calls `_InsertMem` for `programEnd - program` bytes at `ram:9D95`, copies
`program` into that allocation, and calls `ram:9D95`. After the RAM core
returns, the Flash wrapper exits through `_JForceCmdNoChar`. App packaging
therefore does not establish that all executable code stays in Flash.
[confirmed] for the identified community source.

The RAM core finds its two-byte settings AppVar through `_ChkFindSym`. It reads
a RAM payload directly. For an archived payload, it normalizes a wrapped
bank-A pointer and page before calling `_LoadCIndPaged` and
`_LoadDEIndPaged`. This is a concrete page-aware archived-data reader, not a
general guarantee that an archived pointer remains valid across memory-moving
calls. [confirmed] for the identified community source.

The AppVar payload has this packed layout:

```c
#pragma pack(push, 1)
typedef struct {
    uint8_t contrast;         /* +0x00 */
    uint8_t delay;            /* +0x01 */
} TruVidSettings;             /* 2 bytes */
#pragma pack(pop)
```

The missing-settings path seeds `contrast` from the OS contrast byte and sets
`delay` to `178`. The save path copies these two bytes from `curContrast` and
`delayValue` into the replacement AppVar. [confirmed] for the identified
community source.

The normal **CLEAR** quit path restores IM 1, the saved stack pointer, mapped
page, display state, several hardware ports, and the OS base-page table. When
the settings are dirty, it deletes any old AppVar, creates a two-byte
replacement, and archives it before returning to the Flash wrapper. No error
frame appears in this source, so it does not establish cleanup after a reset or
an unhandled OS error. [confirmed] for the static source path; reset and error
cleanup remain [hypothesis].

A source-derived App fixture appends one silent same-page frame to the pinned
release source. Its complete TilEm trace reaches `_InsertMem` at `ram:0F81`,
the copied core at `ram:9D95`, the missing-settings branch at `ram:9DCF`, and
the normal quit entry at `ram:9F5F`, each once. The trace SHA-256 is
`c2481399d804a3b5232e9dde99c80fb77a28afc54eaf57ad0f84ed5e89d43b56`;
the generated App SHA-256 is
`11250fda7ce6892c79bcbe44958bd16f77f1faead58ebf99eaf6fa04712f6ab1`.
The run uses OS image SHA-256
`dbb47afae091ab36f9abe74e32083013fbeff3d7e0516bbf5d1abf4ee57adc09`
and patched TilEm commit `d1bdc58dd321ae462a701e556fcb62bb925a78b1`.
[confirmed] for this emulator fixture.

Build the App with `tools/community-probes/truvid_probe.asm` and run
`tools/macros/community-truvid-cleanup.macro`. The wrapper resumes once at
`page_29:4095` after the RAM core returns. The trace does not exercise an
existing archived settings AppVar, the media page-wrap branch, an error, a
reset, or physical hardware. Those paths remain [hypothesis].

### Cross-page code and data

A multi-page App cannot treat bank-A addresses as flat pointers. Mapping
another App or OS page changes the bytes visible at the same logical address.
Any pointer into `0x4000`–`0x7FFF` is valid only while its page remains
mapped. [confirmed]

RPN83P provides a concrete multi-page design. Its page-0 branch table stores
entries in this form:

```z80
.dw target_routine
.db relative_app_page
```

Other App pages call those entries through an App-aware `bcall()` macro. App
page 0 contains the branch table and event handlers, while larger modules live
on later App pages. The identified RPN83P source at commit
`e2ad0bff98c94a13f34ae461b13f79384a75c17f` confirms this layout. [confirmed]

An OS bcall or App-page call may remap bank A. This affects Flash data as well
as code. RPN83P does not pass a Flash string to `_PutS`. Its `putS` helper
reads each byte on the current App page and passes the byte to `_PutC`; its
source comments identify `_PutS` and `_VPutS` as RAM-string routines. [confirmed]
Reacquire or remap the App page before an untested API dereferences a Flash
pointer after a page-changing call. That broader API rule remains a
[hypothesis].

### Context cleanup

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

RPN83P routes both explicit exit and its `cxPutAway` handler through
`mainExit`, which closes its AppVars, saves state, and restores OS settings.
Its identified source does not install `AppOnErr`, so this example does not
cover a TI-OS error that unwinds past the App. A reset or nonlocal jump can also
bypass the App's cleanup. [confirmed]

### Keep persistent state relocatable

RPN83P stores mutable state in four RAM AppVars and uses 1,044–2,545 bytes,
depending on its register count. Its structured variables carry a size,
CRC16, App ID, variable type, and schema version. Startup rejects stale,
truncated, or corrupt structures and initializes the affected state again.
These sizes and checks come from the identified RPN83P source and README.
[confirmed]

Its `RPN83SAV` update is not atomic: `StoreAppState` deletes the old variable
before `_CreateAppVar` creates the replacement. Validation detects corruption
on the next launch, but an interruption can lose the last valid state.
[confirmed]

A runtime that needs the last committed dictionary should use two named slots.
This design remains a fixture target: [hypothesis]

- Store a magic value, format version, generation, payload length, CRC,
  payload, and final commit marker in each slot.
- Write and validate the inactive slot before archiving it.
- Reacquire the archived slot with `_ChkFindSym`, read it with page-aware
  access, then validate the copied record again.
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

### Minimal developer-key fixture

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
not been transferred to physical hardware. The build and decoded header are
confirmed. [confirmed] Physical launch remains untested. [hypothesis]

### Source provenance

| Artifact | Exact identity | Source |
|---|---|---|
| RPN83P source | Commit `e2ad0bff98c94a13f34ae461b13f79384a75c17f` | [RPN83P commit](https://github.com/bxparks/rpn83p/tree/e2ad0bff98c94a13f34ae461b13f79384a75c17f) |
| TruVid release archive | Archive SHA-256 `ea61474625bc56ef1397fd67f978e29e8bd026ffd4ffc9c2f17c3bdc17f25ca9`; member `TruVid/source/truVid.z80`, SHA-256 `2a9a042177197583dae5af51367cfe906e2d7e84f0d15d1e5859a5dd20ee7953` | [truvid.zip](https://www.ticalc.org/pub/83plus/asm/media/sound/truvid.zip) |
| SPASM-ng used for the reference build | Commit `5f0786d38f064835be674d4b7df42969967bb73c` | [SPASM-ng commit](https://github.com/alberthdev/spasm-ng/tree/5f0786d38f064835be674d4b7df42969967bb73c) |

### Remaining measurements

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
not as proof that the complete `ram:9D95`–`ram:BFFF` range is available.

---

## RAM clearing and memory reset

The **MEM** menu (`[2nd][+]`, "MEMORY MANAGEMENT/DELETE" + "RESET") and its messages are on
`page 0x01` (text/homescreen page). The reset *engine* is on `page 0x35`; the user-RAM
re-init lands in page-0 boot code.

### User-facing strings on page `01` [confirmed]

| Addr | String |
|------|--------|
| `01:4076` | `Defragmenting...` |
| `01:4098` | `Arc Vars Cleared` |
| `01:40A9` | `  Apps Cleared` |
| `01:40B8` | `Arc Vars & Apps     Cleared` |
| `01:4109` | `Resetting All...` |
| `01:4126`+`412E` | `Garbage` + `Collecting...` |
| `01:4234` | `Resetting...` |
| `01:7425`–`01:746E` | menu titles: `RESET MEMORY`, `RESET DEFAULTS`, `RESET ARC VARS`, `RESET ARC APPS`, `RESET ARC BOTH`, `RESET RAM` |
| `01:747E` | the long "Resetting ALL / RAM / Vars / Apps / Both …" warning help text |

### Reset dispatcher (`mem_reset_dispatch` at `35:7180`) [confirmed]

Dispatch is on the selected reset item held in `keyExtend` (`0x8446`):

| `keyExtend` | action | message shown |
|-------------|--------|---------------|
| 1 | reset archived vars | `Arc Vars Cleared` (path `720B`) |
| 2 | reset archived apps | `Apps Cleared` (path `7267`) |
| 3 | reset both arc vars+apps | `Arc Vars & Apps Cleared` (path `7275`) |
| 4 | reset all (RAM+archive) | `Resetting All...` (path `71F0`) |
| else (0) | RAM reset ("RAM Cleared") | wipe + re-init (path `719F`) |

### What RAM reset clears [confirmed]

The RAM-reset path (`35:719F`):
```z80
719F BIT 1,(IY+0x35)
     JP Z,0x0B2F                           ; first-stage vs full path select
71A6 LD HL,(0x9B73)                         ; preserve a saved word
71B4 LD A,(IY+0x3F)
     AND 0x7F                              ; keep low 7 bits (clear bit 7) of flag byte 0x3F
71B9 DI
71BA LD HL,0x8000
     LD DE,0x8001
     LD BC,0x1BC3
     LD (HL),0
     LDIR                                  ; *** zero system RAM 0x8000-0x9BC3 ***
71C7 LD (IY+0x3F),A                         ; restore the saved low 7 bits
...   (restore IY+0x34 bit6, IY+0x35 bit0 from the preserved state)
71E0 LD HL,0x9BD0
     LD DE,0x9BD1
     LD BC,0x642F
     LD (HL),0
     LDIR                                  ; *** zero user RAM 0x9BD0-0xFFFF ***
71ED JP 0x0BD9                              ; re-init RAM (page-0 boot init)
```
So a RAM reset clears two blocks to 0:

1. **System RAM:** the half-open interval `[appData, 0x9BC4)`, corresponding
   to `0x8000`–`0x9BC3`.
2. **User RAM:** `[restartClr, 0x10000)`, corresponding to
   `0x9BD0`–`0xFFFF` (`0x6430` bytes).

The first interval contains OS scratch, the context block, and system buffers.
The second contains the VAT and user variables and programs. [confirmed]

A small amount of state survives the wipe. The path restores bits 0–6 of
`IY+0x3F` and clears bit 7. It conditionally restores `IY+0x34` bit 6 and
`IY+0x35` bit 0, sets `IY+0x35` bit 1, and restores `localLanguage` at
`0x9B73`. It then `JP 0x0BD9`, the RAM-init entry (`OUT (0)` page select, `LD SP,0xFFF7`,
then `CALL 0x3EC1` — the cross-page trampoline that rebuilds the VAT, system vars, and LCD; see [Boot contexts & errors](boot-contexts-errors.md)), which rebuilds a
clean default VAT and system state and re-enters the homescreen. The Flash archive is not
touched by a plain RAM reset.

### Full reset (`ram:0B27`) [confirmed]

The harder reset (RESET ALL / power-on cold start) is at `ram:0B27`:
```z80
0B27 LD SP,0
     ...
0B37 DI
     OUT (0),0xC0
0B41 LD HL,0x8000
     LD DE,0x8001
     LD BC,0x7FFF
     LD (HL),0
     LDIR                                  ; zero ALL of 0x8000-0xFFFF (32 KiB)
0B4E ... preserve/inspect IY+0x3F
     ... select sub-path
     JP 0x3EA9/0x3EAF
```
This zeroes the *entire* 32 KiB RAM and does the deepest re-init.

### `_CleanAll` and `cleanup_temp_ram` (`07:52CF`) [confirmed]

Distinct from the MEM reset. `_CleanAll` (bcall `0x4A50`) only compacts temporary RAM
after a command finishes: it shifts the FP stack (`fpBase`/`FPS`) down to `tempMem`, resets
the `OPBase`/`OPS`/`pTemp` scratch pointers, and clears `pTempCnt`/`cleanTmp`. It does not
clear the VAT, user vars, or Flash (see [Memory management](memory-management.md)). `_FixTempCnt` (`07:4FEC`) marks temps
≥ a count reclaimable then tail-calls the same compaction.

### Flash archive garbage collection [confirmed]

Separate from RAM reset: `gc_show_screen` at `3C:7E0D` displays `Garbage Collecting...`, while the
related entry at `3C:7E23` displays `Defragmenting...`. `archive_gc_collect` at `3C:7733` rewrites
live archive records in 64 KiB sector units and journals its phase in the inactive 8 KiB half of
page `3E`. It clears `0x844B` (`curRow`) before drawing the banner and runs with interrupts disabled.
The erase and program workers execute from RAM through Flash-control port `0x14`; see
[Variables, archive and unarchive](sub-vat-archive.md#flash-garbage-collector-confirmed). [confirmed]

---

## MODE settings flags

The flag bytes live in the SystemFlags area at `IY = 0x89F0`. The MODE screen (`cxMode =
kMode = 0x45`) is a menu context that flips these bits; the canonical setters below show
exactly which bits.

### Angle mode in `trigFlags` (`IY+0`) [confirmed]

`trigDeg = bit 2` of `trigFlags` (`0x89F0`): 1 = Degrees, 0 = Radians. (Confirmed against WikiTI `Flags:00` and the ROM — `_Sin` (`02:7342`) tests `BIT 2,(IY+0)` to pick the degree path.)
```z80
SET 2,(IY+0)   ; FD CB 00 D6  -> Degree
RES 2,(IY+0)   ; FD CB 00 96  -> Radian
BIT 2,(IY+0)   ; FD CB 00 56  -> tested by _Sin/_Cos/_Tan to select degree vs radian
```
Math routines branch on this bit to choose degree/radian variants (`_SinCosRad` etc. force
radians; the degree paths convert first).

### Graph type in `grfModeFlags` (`IY+0x02`) [confirmed]

The four graph-mode setters on `page 0x36` are mutually exclusive: each first clears
all four bits via `clr_grfmode (36:7D00)`, then ORs in its own bit, then calls
`_SetTblGraphDraw`. `param_1` is `IY`, so `*(param_1+2)` = `grfModeFlags`.

```text
clr_grfmode (36:7D00):  grfModeFlags &= 0xEF & 0xDF & 0xBF & 0x7F   # clear bits 4,5,6,7
```

| bcall | addr | bit set | flag (inc) |
|-------|------|---------|------------|
| `_SetFuncM` | `36:7D11` | bit 4 (`\|0x10`) | `grfFuncM` (Function) |
| `_SetPolM`  | `36:7D2C` | bit 5 (`\|0x20`) | `grfPolarM` (Polar) |
| `_SetParM`  | `36:7D39` | bit 6 (`\|0x40`) | `grfParamM` (Parametric) |
| `_SetSeqM`  | `36:7D1F` | bit 7 (`\|0x80`) | `grfRecurM` (Sequence/Recursion) |

Each setter first calls a small predicate (`36:0013/0254/0259/025E`) and only re-sets
the mode if the parity/condition flag (`F` bit6) requires it, avoiding needless redraws.

Other `grfModeFlags` bits (from inc, not in the setters above): bit3 `grfPolar`
(rect↔polar coordinate readout). Related graph bytes: `grfDBFlags` (`IY+0x04`) bit0
`grfDot` (line/dot), bit1 `grfSimul` (sequential/simultaneous), bit4 `grfNoCoord`,
bit5 `grfNoAxis`; `seqFlags` (`IY+0x0F`).

### Numeric format in `fmtFlags` (`IY+0x0A`) [confirmed]

`fmtFlags` byte at `0x89FA`:

| bit | name | meaning |
|-----|------|---------|
| 0 | `fmtExponent` | 1 = show exponent (Sci/Eng), 0 = Normal |
| 1 | `fmtEng` | 1 = Engineering, 0 = Scientific (when exponent on) |
| 2-4 | `fmtBaseMask` (`fmtHex`/`fmtOct`/`fmtBin`) | integer base (Dec/Hex/Oct/Bin) |
| 5 | `fmtReal` | real display mode |
| 6 | `fmtRect` | rectangular complex display (a+bi) |
| 7 | `fmtPolar` | polar complex display (re^θi) |

So Normal/Sci/Eng = (bit0, bit1): Normal = `00`, Sci = `01`, Eng = `11`.
`fmtOverride` (`IY+0x0B`, `0x89FB`) is a working copy used during conversions.

Float vs Fix N is not in `fmtFlags` — it is the separate byte `fmtDigits` =
`0x97B0`: value `0x00-0x09` = Fix-N decimal places, `0xFF` = Float.

### MODE screen plumbing

The MODE screen is a menu context (`cxMode`/`kMode`=0x45) reached via the event/key router
([Boot contexts & errors](boot-contexts-errors.md)). Its row strings live as token names on page 0x01 (`RadianN`/`DegreeO`/`NormalP`/
`Float` at `01:49E4`–`01:4A06`; trailing letters are token-id bytes) and full-caps menu
labels on page 0x37 (`DEGREE` `4A85`, `RADIAN` `4A8C`). The setters and inc
equates confirm the target bits and bytes. [confirmed] The per-row path through
the menu dispatcher to the corresponding `SET`/`RES` or `fmtDigits` store has
not been traced line by line. [hypothesis]

---

## Routine index

```text
3D:5EE3   _FindApp
3D:5DDA   _FindAppUp
3D:5DE6   _FindAppDn
3D:5DE7   app_5de7
3D:5FB1   app_find_next_page
3D:727D   init_flash_page_counter
3D:7285   init_flash_page_counter+0x08   ; TLV-length decode block, not a function
3D:4AA3   _FindAppNumPages bcall target; no live function in current DB
ram:0936       _AppInit
ram:08AF       _PutAway
3B:73E4   _ReloadAppEntryVecs
3B:7571   default app vectors data block (12 bytes + appFlags), not a function
3B:7412   app-quit restore candidate (inferred label); no defined function in live DB
35:7180   mem_reset_dispatch
35:719F   ram_reset_wipe         (zeroes [appData,9BC4) and [restartClr,10000))
ram:0BD9       ram_init_after_reset
ram:0B27       full_reset_wipe        (zeroes all 0x8000-0xFFFF)
3C:71F8   gc_command
3C:7733   archive_gc_collect
3C:7E0D   gc_show_screen
07:52CF   _CleanAll (cleanup_temp_ram)
07:4FEC   _FixTempCnt
36:7D11   _SetFuncM     (grfModeFlags bit4)
36:7D1F   _SetSeqM      (grfModeFlags bit7)
36:7D2C   _SetPolM      (grfModeFlags bit5)
36:7D39   _SetParM      (grfModeFlags bit6)
36:7D00   clr_grfmode   (clears grfModeFlags bits 4-7)
```

### Key SystemFlags and RAM addresses

```text
0x89F0  flags (IY base)
 +0x00  trigFlags   (bit2 trigDeg: 1=Degree,0=Radian)
 +0x02  grfModeFlags(bit4 Func,bit5 Polar,bit6 Param,bit7 Seq; bit3 grfPolar)
 +0x04  grfDBFlags  (bit0 Dot, bit1 Simul, bit4 NoCoord, bit5 NoAxis)
 +0x0A  fmtFlags    (bit0 Exponent, bit1 Eng, bit2-4 base, bit5 Real, bit6 Rect, bit7 Polar)
 +0x0B  fmtOverride
 +0x0D  appFlags
0x97B0  fmtDigits   (0-9 = Fix N, 0xFF = Float)
0x82A3  appSearchPage
0x8446  keyExtend   (reset-submenu selector 1..4; extended-key state)
0x858D  cxMain ...  0x8599 cxPage  0x859A cxCurApp   (Context block, see Boot contexts & errors)
```
