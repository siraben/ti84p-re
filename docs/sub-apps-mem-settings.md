# Apps, memory reset & settings

*TI-84 Plus OS 2.55MP — feature deep dive.*

How the student-facing parts of the OS work: launching Flash Apps, the **MEM → Reset**
menu (what "RAM Cleared" erases), and the **MODE** screen format/mode flags.
Addresses are `space:addr` where `ram`/`page_00`=`0000-3FFF`, flash pages mapped at
`4000-7FFF`. Confidence flags follow [conventions.md](conventions.md): [confirmed] = read
from disassembly; [hypothesis] = strong inference, not yet verified (used below for both
strongly-inferred claims and *partial* traces where the code is RAM-resident / cross-page and
not fully traced).

Cross-references: [doc 11](11-boot-contexts-errors.md) (contexts, `_AppInit`, event router), [doc 12](12-memory-management.md) (RAM heap,
`_CleanAll`), [doc 13](13-flash-page-map.md) (flash page map). Flag bits use the `ti83plus.inc` equates; the
SystemFlags base is `IY = flags = 0x89F0`, so e.g. `(IY+0x0A)` = `flags + fmtFlags`.

---

## 1. Flash Apps — find & launch

This ROM ships with zero bundled apps in the local ROM-byte scan (zero `80 0F` headers found at page starts) [hypothesis],
but the entire find/launch machinery is present on `page 0x3D` (`_FindApp*`) and
`page 0x3B` (`_AppInit` glue / app-quit). Apps are TI Flash Applications: a contiguous
run of 16 KiB flash pages whose first page begins with a TLV app header.

### 1.1 App header format (TLV) [confirmed]

An app header is a sequence of type-length-value fields starting at offset 0 of the
app's first page. Each field begins with two bytes in WikiTI's `TT TS` notation: the high
12 bits are the field number, and the low nibble of the second byte encodes the payload
length. The decoder bytes are around `3D:7285`, but the disassembly does not expose a live function there:

| size nibble | field payload size |
|-------------|--------------------|
| `0xD` | 1 byte  |
| `0xE` | 2 bytes |
| `0xF` | 4 bytes |

```z80
page_3D:7285  AND 0x0F; CP 0x0F -> B=4 ; CP 0x0E -> B=2 ; CP 0x0D -> B=1
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
| `032` | date stamp | six bytes; bytes 1-4 decode as seconds since 1997-01-01 |
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
(`0x8478`) and jumps to OP1. That makes `OUT (6),A; RET` run from RAM after `A`
has been set to the current bank-A page minus one. The preceding `CPIR` searches
from `HL` for a `RET` byte (`0xC9`) and pushes the byte after it as the return
address. The first half preserves the popped registers while it probes caller-owned
bytes and can return early; the later page switch and RAM-thunk behavior are directly
decoded from the sample bytes.

The same sample's conventional entry area at `4080` starts `NOP; JR 408C; JP 4097;
JP 4548`. `tools/app_header_re.py` reproduces this pass: `--fetch-known` downloads a
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
| usb8x | 1 / 1 | `4029` | `00 00 00 00 00 00 00 96` | mostly zero padding, plus `JP 4180h; JP 42EAh` at `4049` |

So `4080` is a common app-entry convention, not the OS's header parser boundary. Some
apps end the parsed header at `4029`, `4070`, or exactly `4080`, and all remain valid
because the `807` final field terminates the header.

The public entry points for walking these fields are bcalls in `ti83plus.inc`:
`_FindAppHeaderSubField` (bcall `0x80AB`) locates a field in an app header, and
`_FindOSHeaderSubField` (bcall `0x8075`) does the same for the OS header. Both build on the
generic walkers `_FindSubField` (bcall `0x805D`), `_FindGroupedField` (bcall `0x8030`), and
`_GetFieldSize` (bcall `0x805A`), which decode the TLV length nibble shown above. These IDs
sit in the boot-page bcall range (`0x8000`+); the `0x8040`/`0x8070`/`0x8080` helpers the OS
also reaches are a distinct group in the same range and are not these field walkers. The body
addresses behind these public entry points are not defined functions in the disassembly.

### 1.2 `_FindApp` / `_FindAppUp` / `_FindAppDn` [confirmed]

- `_FindApp` (`3D:5EE3`) — locate an app by name (OP1). Inits the search page,
  then loops `app_find_next_page (5FB1)` + a header-match step until done, returning the app's
  start page and a found/not-found flag via `RST 28` (bcall) into RAM flash helpers.
  ```z80
  5EE3 CALL 727D            ; flash_set_sector_cnt -> appSearchPage (0x82A3)
  5EE6 CALL 5FB1            ; step to next candidate page (DEC appSearchPage)
  5EE9 RET C                ; ran off the end -> not found
  5EEA CALL 5EB2            ; read/compare this page's header
  5EED BIT 3,C; JR Z,5EE6   ; not a match -> keep scanning
  ```
- `app_find_next_page` (`3D:5FB1`) — `appSearchPage (0x82A3) -= 1`; stops at page 7
  (low boundary of the app region); bjumps `appSearchPage:0x4000` to inspect the header.
- `flash_set_sector_cnt` (`3D:727D` → helper `726E`) — initializes `0x82A3` to the model-selected page base plus one.
- `_FindAppUp` (`5DDA`) / `_FindAppDn` (`5DE6`) — enumerate the previous / next app
  in flash (for the APPS-menu list), both wrapping the common walker `_app_5de7` (`5DE7`).
  `_app_5de7` keeps two counts in BC (apps before/after) and tracks the current name in OP3.
- `_FindAppNumPages` is present in the bcall table (`3D:4AA3`), but the disassembly has no function record at that address.

State variables: `appSearchPage` = `0x82A3`, `0x8497`/`0x8481`/`0x9C87` are search-mode
scratch (`0x9C87`='i' selects the in-RAM "temp app" search variant).

### 1.3 Launching an app as a context [confirmed]

`_AppInit` (`ram:0936`, bcall `0x404B`) installs a context from an app header:
```
_AppInit(byte *hdr):                 ; HL -> 13-byte vector block in the header
  copy 12 bytes hdr[0..11] -> cxMain (0x858D)   ; the 6 context vectors
  flags.appFlags (IY+0x0D) = hdr[12]            ; appFlags byte
  cxPage (0x8599) = port_mapBankA               ; the flash page the handlers run from
```
The 12 bytes are the 6 little-endian handler pointers (`cxMain`, `cxPPutAway`, `cxPutAway`,
`cxRedisp`, `cxErrorEP`, `cxSizeWind` — see [doc 11](11-boot-contexts-errors.md) §Context block). Example: the OS's own
default app vectors live at `3B:7571`:
```
3E 75 | 4B 75 | 9F 74 | 4B 75 | 4B 75 | 4B 75 | 0A
cxMain=753E cxPPutAway=754B cxPutAway=749F cxRedisp=754B cxErrorEP=754B cxSizeWind=754B appFlags=0A
```
`_ReloadAppEntryVecs` (`3B:73E4`, bcall `0x4C36`) calls `_AppInit` on that block, then
overrides `cxErrorEP (0x8595)=0x27D9`. After `_AppInit`, the main event loop runs the app
through `call_context_main` (pages in `cxPage`, jumps `(cxMain)` — [doc 11](11-boot-contexts-errors.md)).

Because `cxCurApp` (`0x859A`) is a key code, pressing a mode key selects the context to
load ([doc 11](11-boot-contexts-errors.md)). The App quit restore-path candidate at
`3B:7412` is not a defined function in the disassembly; the saved-context restore behavior
stands as a byte-trace note (the label is project-local, not a WikiTI or `ti83plus.inc` equate).

---

## 2. RAM clearing / memory reset

The **MEM** menu (`[2nd][+]`, "MEMORY MANAGEMENT/DELETE" + "RESET") and its messages are on
`page 0x01` (text/homescreen page). The reset *engine* is on `page 0x35`; the user-RAM
re-init lands in page-0 boot code.

### 2.1 The user-facing strings (page 0x01) [confirmed]

| Addr | String |
|------|--------|
| `01:4076` | `Defragmenting...` |
| `01:4098` | `Arc Vars Cleared` |
| `01:40A9` | `  Apps Cleared` |
| `01:40B8` | `Arc Vars & Apps     Cleared` |
| `01:4109` | `Resetting All...` |
| `01:4126`+`412E` | `Garbage` + `Collecting...` |
| `01:4234` | `Resetting...` |
| `01:7425..746E` | menu titles: `RESET MEMORY`, `RESET DEFAULTS`, `RESET ARC VARS`, `RESET ARC APPS`, `RESET ARC BOTH`, `RESET RAM` |
| `01:747E` | the long "Resetting ALL / RAM / Vars / Apps / Both …" warning help text |

### 2.2 The reset dispatcher (`mem_reset_dispatch` @ `35:7180`) [confirmed]

Dispatch is on the selected reset item held in `keyExtend` (`0x8446`):

| `keyExtend` | action | message shown |
|-------------|--------|---------------|
| 1 | reset archived vars | `Arc Vars Cleared` (path `720B`) |
| 2 | reset archived apps | `Apps Cleared` (path `7267`) |
| 3 | reset both arc vars+apps | `Arc Vars & Apps Cleared` (path `7275`) |
| 4 | reset all (RAM+archive) | `Resetting All...` (path `71F0`) |
| else (0) | RAM reset ("RAM Cleared") | wipe + re-init (path `719F`) |

### 2.3 What "RAM Cleared" (RAM reset) zeroes [confirmed]

The RAM-reset path (`35:719F`):
```z80
719F BIT 1,(IY+0x35); JP Z,0x0B2F          ; first-stage vs full path select
71A6 LD HL,(0x9B73)                         ; preserve a saved word
71B4 LD A,(IY+0x3F); AND 0x7F               ; keep low 7 bits (clear bit 7) of flag byte 0x3F
71B9 DI
71BA LD HL,0x8000; LD DE,0x8001; LD BC,0x1BC3; LD (HL),0; LDIR   ; *** zero system RAM 0x8000-0x9BC3 ***
71C7 LD (IY+0x3F),A                         ; restore the saved low 7 bits
...   (restore IY+0x34 bit6, IY+0x35 bit0 from the preserved state)
71E0 LD HL,0x9BD0; LD DE,0x9BD1; LD BC,0x642F; LD (HL),0; LDIR   ; *** zero user RAM 0x9BD0-0xFFFF ***
71ED JP 0x0BD9                              ; re-init RAM (page-0 boot init)
```
So a RAM reset clears two blocks to 0:
1. **System RAM** `0x8000–0x9BC3` (~7 KiB: OS scratch, the Context block, system buffers).
2. **User RAM** `0x9BD0–0xFFFF` (`0x6430` = 25648 bytes, ~25 KiB: the VAT and all user variables/programs).

A handful of flag bits are explicitly preserved across the wipe (`IY+0x3F` bit7,
`IY+0x34` bit6, `IY+0x35` bits0/1, and the word at `0x9B73`) so the calculator knows it is
mid-reset. It then `JP 0x0BD9`, the RAM-init entry (`OUT (0)` page select, `LD SP,0xFFF7`,
then `CALL 0x3EC1` — the cross-page trampoline that rebuilds the VAT, system vars, and LCD; see [doc 11](11-boot-contexts-errors.md)), which rebuilds a
clean default VAT and system state and re-enters the homescreen. The Flash archive is not
touched by a plain RAM reset.

### 2.4 Full reset (`page_0/ram:0B27`) [confirmed]

The harder reset (RESET ALL / power-on cold start) is at `ram:0B27`:
```z80
0B27 LD SP,0; ... 0B37 DI; OUT (0),0xC0
0B41 LD HL,0x8000; LD DE,0x8001; LD BC,0x7FFF; LD (HL),0; LDIR   ; zero ALL of 0x8000-0xFFFF (32 KiB)
0B4E ... preserve/inspect IY+0x3F; select sub-path; JP 0x3EA9/0x3EAF
```
This zeroes the *entire* 32 KiB RAM and does the deepest re-init.

### 2.5 `_CleanAll` / `cleanup_temp_ram` (`07:52CF`) — not a reset [confirmed]

Distinct from the MEM reset. `_CleanAll` (bcall `0x4A50`) only compacts temporary RAM
after a command finishes: it shifts the FP stack (`fpBase`/`FPS`) down to `tempMem`, resets
the `OPBase`/`OPS`/`pTemp` scratch pointers, and clears `pTempCnt`/`cleanTmp`. It does not
clear the VAT, user vars, or Flash (see [doc 12](12-memory-management.md)). `_FixTempCnt` (`07:4FEC`) marks temps
≥ a count reclaimable then tail-calls the same compaction.

### 2.6 Flash archive GC — "Defragmenting…" / "Garbage Collecting…" [confirmed behavior; display-label addresses undisassembled]

Separate from RAM reset: when the Flash archive fills, the OS rewrites live archived vars to
fresh sectors and erases the old ones. The display dispatcher sits around `3C:7E23`
(shows `Defragmenting...` `0x4076`) / `7E10`/`7E1C` (shows `Garbage Collecting...` `0x4126`+`412E`);
`3C:7E00` is not a defined function in the disassembly (the label is project-local, not a
WikiTI or `ti83plus.inc` equate).
It clears `0x844B` (`curRow`, the text-row cursor — reset before the banner draws) and runs with the screen frozen (`DI`). The actual
sector erase/write primitives are RAM-resident (flash control port `0x14`) — see [doc 12](12-memory-management.md).

---

## 3. MODE / settings flags

The flag bytes live in the SystemFlags area at `IY = 0x89F0`. The MODE screen (`cxMode =
kMode = 0x45`) is a menu context that flips these bits; the canonical setters below show
exactly which bits.

### 3.1 Angle: Degree vs Radian — `trigFlags` (`IY+0`) [confirmed]

`trigDeg = bit 2` of `trigFlags` (`0x89F0`): 1 = Degrees, 0 = Radians. (Confirmed against WikiTI `Flags:00` and the ROM — `_Sin` (`02:7342`) tests `BIT 2,(IY+0)` to pick the degree path.)
```z80
SET 2,(IY+0)   ; FD CB 00 D6  -> Degree
RES 2,(IY+0)   ; FD CB 00 96  -> Radian
BIT 2,(IY+0)   ; FD CB 00 56  -> tested by _Sin/_Cos/_Tan to select degree vs radian
```
Math routines branch on this bit to choose degree/radian variants (`_SinCosRad` etc. force
radians; the degree paths convert first).

### 3.2 Graph type: Func / Param / Polar / Seq — `grfModeFlags` (`IY+0x02`) [confirmed]

The four graph-mode setters on `page 0x36` are mutually exclusive: each first clears
all four bits via `clr_grfmode (36:7D00)`, then ORs in its own bit, then calls
`_SetTblGraphDraw`. `param_1` is `IY`, so `*(param_1+2)` = `grfModeFlags`.

```
clr_grfmode (page_36:7D00):  grfModeFlags &= 0xEF & 0xDF & 0xBF & 0x7F   ; clear bits 4,5,6,7
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

### 3.3 Numeric format: Normal/Sci/Eng, Float/Fix, base — `fmtFlags` (`IY+0x0A`) [confirmed (bits from inc)]

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
`0x97B0`: value `0x00–0x09` = Fix-N decimal places, `0xFF` = Float.

### 3.4 MODE screen plumbing

The MODE screen is a menu context (`cxMode`/`kMode`=0x45) reached via the event/key router
([doc 11](11-boot-contexts-errors.md)). Its row strings live as token names on page 0x01 (`RadianN`/`DegreeO`/`NormalP`/
`Float` at `01:49E4..4A06`; trailing letters are token-id bytes) and full-caps menu
labels on page 0x37 (`DEGREE` `4A85`, `RADIAN` `4A8C`). Selecting a row writes the flag bits
documented above directly (`SET/RES (IY+…)`, or stores into `fmtDigits`). [hypothesis] (partial) —
the per-row write table itself is reached through the menu dispatcher and was not traced
line-by-line, but every target bit/byte is confirmed from the setters and inc equates.

---

## 4. Confident `space:addr` index

```
page_3D:5EE3   _FindApp
page_3D:5DDA   _FindAppUp
page_3D:5DE6   _FindAppDn
page_3D:5DE7   _app_5de7
page_3D:5FB1   app_find_next_page
page_3D:727D   flash_set_sector_cnt
page_3D:7285   TLV-length candidate (inferred label); no defined function in live DB
page_3D:4AA3   _FindAppNumPages bcall target; no live function in current DB
ram:0936       _AppInit
ram:08AF       _PutAway
page_3B:73E4   _ReloadAppEntryVecs
page_3B:7571   default app vectors data block (12 bytes + appFlags), not a function
page_3B:7412   app-quit restore candidate (inferred label); no defined function in live DB
page_35:7180   mem_reset_dispatch
page_35:719F   ram_reset_wipe         (zeroes 0x8000-0x9BC3 and 0x9BD0-0xFFFF)
ram:0BD9       ram_init_after_reset
ram:0B27       full_reset_wipe        (zeroes all 0x8000-0xFFFF)
page_3C:7E00   archive-GC-display candidate (inferred label); no defined function in live DB
page_07:52CF   _CleanAll (cleanup_temp_ram)
page_07:4FEC   _FixTempCnt
page_36:7D11   _SetFuncM     (grfModeFlags bit4)
page_36:7D1F   _SetSeqM      (grfModeFlags bit7)
page_36:7D2C   _SetPolM      (grfModeFlags bit5)
page_36:7D39   _SetParM      (grfModeFlags bit6)
page_36:7D00   clr_grfmode   (clears grfModeFlags bits 4-7)
```

### Key SystemFlags / RAM addresses
```
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
0x858D  cxMain ...  0x8599 cxPage  0x859A cxCurApp   (Context block, doc 11)
```
