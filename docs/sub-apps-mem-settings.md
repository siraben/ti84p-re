# Apps, RAM-Clearing / Memory-Reset, and MODE / Settings

How the student-facing parts of the OS work: launching Flash Apps, the **MEM → Reset**
menu (what "RAM Cleared" actually erases), and the **MODE** screen format/mode flags.
Addresses are `space:addr` where `ram`/`page_00`=`0000-3FFF`, flash pages mapped at
`4000-7FFF`. Confidence: **[confirmed]** = read from disassembly, **[likely]** =
strong inference, **[partial]** = code is RAM-resident / cross-page and not fully traced.

Cross-references: doc 11 (contexts, `_AppInit`, event router), doc 12 (RAM heap,
`_CleanAll`), doc 13 (flash page map). Flag bits use the `ti83plus.inc` equates; the
SystemFlags base is `IY = flags = 0x89F0`, so e.g. `(IY+0x0A)` = `flags + fmtFlags`.

---

## 1. Flash Apps — find & launch

This ROM ships with **no bundled apps** (a full page scan found zero `80 0F` headers),
but the entire find/launch machinery is present on **page 0x3D** (`_FindApp*`) and
**page 0x3B** (`_AppInit` glue / app-quit). Apps are TI Flash Applications: a contiguous
run of 16 KiB flash pages whose first page begins with a TLV **app header**.

### 1.1 App header format (TLV) [confirmed]

An app header is a sequence of **type-length-value fields** starting at offset 0 of the
app's first page. Each field begins with an ID byte whose **low nibble encodes the field
length**. The decoder is `app_field_len` (`page_3D:7285`):

| low nibble of ID | field payload size |
|------------------|--------------------|
| `0xD` | 1 byte  |
| `0xE` | 2 bytes |
| `0xF` | 4 bytes |

```
page_3D:7285  AND 0x0F; CP 0x0F -> B=4 ; CP 0x0E -> B=2 ; CP 0x0D -> B=1
```
The signature field at offset 0 is `80 0F …` (field type 0x80, 4-byte value) — this is
what the page-scan keys on to recognise an app. Fields carry the app name, the page count,
flags, the security/signature, etc. The OS reads header fields through RAM-resident flash
helpers (`bcall(0x8040)`, `bcall(0x8070)`, `bcall(0x8080)`) installed by the boot stub.

### 1.2 `_FindApp` / `_FindAppUp` / `_FindAppDn` [confirmed]

- `_FindApp` (`page_3D:5EE3`) — locate an app by name (OP1). Inits the search page,
  then loops `find_next_page (5FB1)` + a header-match step until done, returning the app's
  start page and a found/not-found flag via `RST 28` (bcall) into RAM flash helpers.
  ```
  5EE3 CALL 727D            ; appSearchStart -> appSearchPage (0x82A3)
  5EE6 CALL 5FB1            ; step to next candidate page (DEC appSearchPage)
  5EE9 RET C                ; ran off the end -> not found
  5EEA CALL 5EB2            ; read/compare this page's header
  5EED BIT 3,C; JR Z,5EE6   ; not a match -> keep scanning
  ```
- `find_next_page` (`page_3D:5FB1`) — `appSearchPage (0x82A3) -= 1`; stops at page 7
  (low boundary of the app region); bjumps `appSearchPage:0x4000` to inspect the header.
- `app_search_start` (`page_3D:727D` → helper `726E`) — picks the top page to scan from.
- `_FindAppUp` (`5DDA`) / `_FindAppDn` (`5DE6`) — enumerate the **previous / next** app
  in flash (for the APPS-menu list), both wrapping the common walker `app_5de7` (`5DE7`).
  `app_5de7` keeps two counts in BC (apps before/after) and tracks the current name in OP3.
- `_FindAppNumPages` (`page_3D:4AA3`) — number of contiguous pages an app occupies.

State variables: `appSearchPage` = `0x82A3`, `0x8497`/`0x8481`/`0x9C87` are search-mode
scratch (`0x9C87`='i' selects the in-RAM "temp app" search variant).

### 1.3 Launching an app as a context [confirmed]

`_AppInit` (`ram:0936`, bcall `0x404B`) installs a context from an app header:
```
_AppInit(byte *hdr):                 ; HL -> 13-byte vector block in the header
  copy 12 bytes hdr[0..11] -> cxMain (0x858D)   ; the 6 context vectors
  flags.appFlags (IY+0x0D) = hdr[12]            ; appFlags byte
  cxPage (0x8599) = port_mapBankA               ; remember which flash page we run on
```
The 12 bytes are the 6 little-endian handler pointers (`cxMain`, `cxPPutAway`, `cxPutAway`,
`cxRedisp`, `cxErrorEP`, `cxSizeWind` — see doc 11 §Context block). Example: the OS's own
default app vectors live at `page_3B:7571`:
```
3E 75 | 4B 75 | 9F 74 | 4B 75 | 4B 75 | 4B 75 | 0A
cxMain=753E cxPPutAway=754B cxPutAway=749F cxRedisp=754B cxErrorEP=754B cxSizeWind=754B appFlags=0A
```
`_ReloadAppEntryVecs` (`page_3B:73E4`, bcall `0x4C36`) calls `_AppInit` on that block, then
overrides `cxErrorEP (0x8595)=0x27D9`. After `_AppInit`, the main event loop runs the app
through `call_context_main` (pages in `cxPage`, jumps `(cxMain)` — doc 11).

Because `cxCurApp` (`0x859A`) **is a key code**, pressing a mode key selects the context to
load (doc 11). **App quit** (`page_3B:7412`) restores the saved context (8 bytes
`0x849A→0x84BF`), sets `cxCurApp=0x40` (`kQuit`=`cxCmd`, the homescreen), and re-renders —
i.e. exiting an app drops you back to the home screen.

---

## 2. RAM clearing / Memory reset

The **MEM** menu (`[2nd][+]`, "MEMORY MANAGEMENT/DELETE" + "RESET") and its messages are on
**page 0x01** (text/homescreen page). The reset *engine* is on **page 0x35**; the user-RAM
re-init lands in page-0 boot code.

### 2.1 The user-facing strings (page 0x01) [confirmed]

| Addr | String |
|------|--------|
| `page_01:4076` | `Defragmenting...` |
| `page_01:4098` | `Arc Vars Cleared` |
| `page_01:40A9` | `  Apps Cleared` |
| `page_01:40B8` | `Arc Vars & Apps     Cleared` |
| `page_01:4109` | `Resetting All...` |
| `page_01:4126`+`412E` | `Garbage` + `Collecting...` |
| `page_01:4234` | `Resetting...` |
| `page_01:7425..746E` | menu titles: `RESET MEMORY`, `RESET DEFAULTS`, `RESET ARC VARS`, `RESET ARC APPS`, `RESET ARC BOTH`, `RESET RAM` |
| `page_01:747E` | the long "Resetting ALL / RAM / Vars / Apps / Both …" warning help text |

### 2.2 The reset dispatcher (`mem_reset` @ `page_35:7180`) [confirmed]

Dispatch is on the selected reset item held in `keyExtend` (`0x8446`):

| `keyExtend` | action | message shown |
|-------------|--------|---------------|
| 1 | reset archived **vars** | `Arc Vars Cleared` (path `720B`) |
| 2 | reset archived **apps** | `Apps Cleared` (path `7267`) |
| 3 | reset **both** arc vars+apps | `Arc Vars & Apps Cleared` (path `7275`) |
| 4 | reset **all** (RAM+archive) | `Resetting All...` (path `71F0`) |
| else (0) | **RAM reset** ("RAM Cleared") | wipe + re-init (path `719F`) |

### 2.3 What "RAM Cleared" (RAM reset) actually zeroes [confirmed]

The RAM-reset path (`page_35:719F`):
```
719F BIT 1,(IY+0x35); JP Z,0x0B2F          ; first-stage vs full path select
71A6 LD HL,(0x9B73)                         ; preserve a saved word
71B4 LD A,(IY+0x3F); AND 0x7F               ; preserve bit7 of flag byte 0x3F
71B9 DI
71BA LD HL,0x8000; LD DE,0x8001; LD BC,0x1BC3; LD (HL),0; LDIR   ; *** zero system RAM 0x8000-0x9BC3 ***
71C7 LD (IY+0x3F),A                         ; restore preserved flag bit
...   (restore IY+0x34 bit6, IY+0x35 bit0 from the preserved state)
71E0 LD HL,0x9BD0; LD DE,0x9BD1; LD BC,0x642F; LD (HL),0; LDIR   ; *** zero user RAM 0x9BD0-0xFFFE ***
71ED JP 0x0BD9                              ; re-init RAM (page-0 boot init)
```
So a **RAM reset clears two blocks to 0**:
1. **System RAM** `0x8000–0x9BC3` (~7 KiB: OS scratch, the Context block, system buffers).
2. **User RAM** `0x9BD0–0xFFFE` (~25.6 KiB: the VAT and all user variables/programs).

A handful of flag bits are explicitly **preserved** across the wipe (`IY+0x3F` bit7,
`IY+0x34` bit6, `IY+0x35` bits0/1, and the word at `0x9B73`) so the calculator knows it is
mid-reset. It then `JP 0x0BD9`, the **RAM-init** entry (`OUT (0)` page select, `LD SP,0xFFF7`,
`CALL 0x917` = re-build the VAT/system vars, `LD (0x85BC),SP` = set `onSP`), which rebuilds a
clean default VAT and system state and re-enters the homescreen. The Flash **archive is not
touched** by a plain RAM reset.

### 2.4 Full reset (`page_0/ram:0B27`) [confirmed]

The harder reset (RESET ALL / power-on cold start) is at `ram:0B27`:
```
0B27 LD SP,0; ... 0B37 DI; OUT (0),0xC0
0B41 LD HL,0x8000; LD DE,0x8001; LD BC,0x7FFF; LD (HL),0; LDIR   ; zero ALL of 0x8000-0xFFFF (32 KiB)
0B4E ... preserve/inspect IY+0x3F; select sub-path; JP 0x3EA9/0x3EAF
```
This zeroes the **entire** 32 KiB RAM and does the deepest re-init.

### 2.5 `_CleanAll` / `cleanup_temp_ram` (`page_07:52CF`) — NOT a reset [confirmed]

Distinct from the MEM reset. `_CleanAll` (bcall `0x4A50`) only **compacts temporary RAM**
after a command finishes: it shifts the FP stack (`fpBase`/`FPS`) down to `tempMem`, resets
the `OPBase`/`OPS`/`pTemp` scratch pointers, and clears `pTempCnt`/`cleanTmp`. It does **not**
clear the VAT, user vars, or Flash (see doc 12). `_FixTempCnt` (`page_07:4FEC`) marks temps
≥ a count reclaimable then tail-calls the same compaction.

### 2.6 Flash archive GC — "Defragmenting…" / "Garbage Collecting…" (`page_3C:7E00`) [confirmed]

Separate from RAM reset: when the Flash archive fills, the OS rewrites live archived vars to
fresh sectors and erases the old ones. The display dispatcher is `page_3C:7E23` (shows
`Defragmenting...` `0x4076`) / `7E10`/`7E1C` (shows `Garbage Collecting...` `0x4126`+`412E`).
It clears `0x844B` (a progress/word) and runs with the screen frozen (`DI`). The actual
sector erase/write primitives are RAM-resident (flash control port `0x14`) — see doc 12.

---

## 3. MODE / settings flags

The flag bytes live in the SystemFlags area at `IY = 0x89F0`. The MODE screen (`cxMode =
kMode = 0x45`) is a menu context that flips these bits; the canonical setters below show
exactly which bits.

### 3.1 Angle: Degree vs Radian — `trigFlags` (`IY+0`) [confirmed]

`trigDeg = bit 1` of `trigFlags` (`0x89F0`): **1 = Degrees, 0 = Radians**.
```
SET 1,(IY+0)   ; FD CB 00 CE  -> Degree   (e.g. page_3A:7956, page_02:5BE0)
RES 1,(IY+0)   ; FD CB 00 8E  -> Radian   (e.g. page_3A:7935, page_02:5BC2)
```
Math routines branch on this bit to choose degree/radian variants (`_SinCosRad` etc. force
radians; the degree paths convert first).

### 3.2 Graph type: Func / Param / Polar / Seq — `grfModeFlags` (`IY+0x02`) [confirmed]

The four graph-mode setters on **page 0x36** are **mutually exclusive**: each first clears
all four bits via `clr_grfmode (page_36:7D00)`, then ORs in its own bit, then calls
`_SetTblGraphDraw`. `param_1` is `IY`, so `*(param_1+2)` = `grfModeFlags`.

```
clr_grfmode (page_36:7D00):  grfModeFlags &= 0xEF & 0xDF & 0xBF & 0x7F   ; clear bits 4,5,6,7
```

| bcall | addr | bit set | flag (inc) |
|-------|------|---------|------------|
| `_SetFuncM` | `page_36:7D11` | bit 4 (`\|0x10`) | `grfFuncM` (Function) |
| `_SetPolM`  | `page_36:7D2C` | bit 5 (`\|0x20`) | `grfPolarM` (Polar) |
| `_SetParM`  | `page_36:7D39` | bit 6 (`\|0x40`) | `grfParamM` (Parametric) |
| `_SetSeqM`  | `page_36:7D1F` | bit 7 (`\|0x80`) | `grfRecurM` (Sequence/Recursion) |

Each setter first calls a small predicate (`page_36:0013/0254/0259/025E`) and only re-sets
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

**Float vs Fix N** is *not* in `fmtFlags` — it is the separate byte **`fmtDigits` =
`0x97B0`**: value `0x00–0x09` = Fix-N decimal places, `0xFF` = **Float**.

### 3.4 MODE screen plumbing

The MODE screen is a menu context (`cxMode`/`kMode`=0x45) reached via the event/key router
(doc 11). Its row strings live as token names on page 0x01 (`RadianN`/`DegreeO`/`NormalP`/
`Float` at `page_01:49E4..4A06`; trailing letters are token-id bytes) and full-caps menu
labels on page 0x37 (`DEGREE` `4A85`, `RADIAN` `4A8C`). Selecting a row writes the flag bits
documented above directly (`SET/RES (IY+…)`, or stores into `fmtDigits`). **[likely]** —
the per-row write table itself is reached through the menu dispatcher and was not traced
line-by-line, but every target bit/byte is confirmed from the setters and inc equates.

---

## 4. Confident `space:addr` index

```
page_3D:5EE3   _FindApp
page_3D:5DDA   _FindAppUp
page_3D:5DE6   _FindAppDn
page_3D:5DE7   app_find_walker (app_5de7)
page_3D:5FB1   app_find_next_page
page_3D:727D   app_search_start
page_3D:7285   app_header_field_len   (TLV nibble decoder)
page_3D:4AA3   _FindAppNumPages
ram:0936       _AppInit
ram:08AF       _PutAway
page_3B:73E4   _ReloadAppEntryVecs
page_3B:7571   default_app_vectors    (12-byte block + appFlags)
page_3B:7412   app_quit_restore_ctx
page_35:7180   mem_reset_dispatch
page_35:719F   ram_reset_wipe         (zeroes 0x8000-0x9BC3 and 0x9BD0-0xFFFE)
ram:0BD9       ram_init_after_reset
ram:0B27       full_reset_wipe        (zeroes all 0x8000-0xFFFF)
page_3C:7E00   archive_gc_display     ("Defragmenting" / "Garbage Collecting")
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
 +0x00  trigFlags   (bit1 trigDeg: 1=Degree,0=Radian)
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
