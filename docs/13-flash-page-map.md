# 13 — Flash page map

What lives on each of the 64 physical flash pages (16 KiB each). The OS itself occupies the low pages; the upper pages hold the certificate, boot code, and fonts. On a retail unit the upper pages can also carry Flash Apps, but this dump is OS-only — the page scan below reports zero Flash-App headers. Characterized by the named bcall routines that resolve to each page (`tools/bcall_targets.txt`) plus function counts.

## OS pages (carry bcall entry points)

| Page | Funcs | Role | Representative routines |
|------|------:|------|--------------------------|
| **00** | 740 | **Kernel** — mapped at `0000`; RST vectors, bcall dispatcher, FP core, VAT, memory, integer math | `_JErrorNo`, `_LdHLind`, `_DivHLBy10`, `_FindSym`, `_FPAdd`, `_InsertMem` |
| **01** | 46 | **Text display** / homescreen | `_PutMap`, `_PutC`, `_PutS`, `_DispHL`, `_NewLine`, `_ClrLCDFull` |
| **02** | 178 | **Float transcendentals & advanced math** | `_SqRoot`, `_LnX`, `_RnFx`, `_RndGuard` |
| **03** | 5 | Edit-buffer / small font | `_CloseEditBuf`, `_Load_SFont`, `_SFont_Len` |
| **04** | 58 | **Graph drawing** (pixel/line) | `_DarkLine`, `_ILine`, `_IPoint`, `_DarkPnt` |
| **05** | ~111 | **TABLE editor** + Graph-Table split-screen | `table_editor_main`, `table_recompute`, `table_paint_grid` |
| **06** | 32 | **Key input** & edit/cursor | `_GetKey`, `_GetCSC`, `_CursorOn/Off`, `_PutTokString` |
| **07** | 21 | **Archive / list & matrix ops**; error messages; **large-font glyph table @ `0x45FF`** (7-byte stride) read by `put_glyph_large` (`07:4588`) | `_Arc_Unarc`, `_CleanAll`, `_RedimMat`, `_IncLstSize`, `put_glyph_large` |
| **33** | 62 | **Graph coordinate math** | `_SetXXOP1`, `_UCLineS` (window↔pixel transforms) |
| **36** | 21 | **Mode setters** (Func/Param/Polar/Seq) | `_SetFuncM`, `_SetParM`, `_SetPolM`, `_SetSeqM` |
| **37** | 5 | Graph coord convert | `_XftoI`, `_YftoI` |
| **38** | 112 | **TI-BASIC parser / evaluator** | `_ParseInp`, `_Find_Parse_Formula`, `parse_init` |
| **39** | ~147 | **Equation pretty-printer** (2D MathPrint layout) + menus | `eqdisp_render_entry`, `eqdisp_emit_glyph`, `_DispMenuTitle` |
| **3A** | ~82 | **Statistics** (1/2-var, regressions) + TVM finance | `_OneVar`, `reg_gauss_solve`, `tvm_solve_iterate` |
| **34** | 13 | Crystal **timers / clock**, token scan | `_CrystalTimerA`, `timer_scan_tbl` |
| **35** | 3 | **Memory-reset** engine, factorial | `mem_reset_dispatch`, `ram_reset_wipe`, `op1_factorial` |
| **3B** | 27 | **bcall jump table** + mem utils | (table data) `_MemClear`, `_MemSet`, `_DrawCirc2` |
| **3C** | 30 | **Link / variable transfer** | `_SendAByte`, `_RecAByteIO`, `_SendVarCmd`, `_Rec1stByte` |
| **3D** | 51 | **App management & Flash** | `_FindApp`, `_FindAppUp/Dn`, `_FlashToRam` |

## Non-OS pages — local ROM-scan results

This image appears **OS-only** in the local ROM-byte scan: scanning every page boundary found **zero Flash-App headers** (`80 0F …`), so no bundled apps are present in that scan. The current MCP interface does not expose raw byte search, so this remains a local scan result rather than an MCP-confirmed claim. The non-bcall pages are OS code/data and the boot/system pages:

| Page | Verified contents |
|------|-------------------|
| `08–32` | OS code/data reached via cross-page jumps (not bcalls), plus **alternate large-font glyph tables** (pages 1 and 0x36, selected by `(IY+0x35)` bits 5/1) and string/help-text tables. No app headers. (The primary large-font glyph table is on page 0x07; see below.) |
| `34–39` | More OS code (graph/mode/menu); mostly full (1–17% `0xFF`). |
| **3B** | **bcall jump table** — starts `99 27 00` = entry 0 (`_JErrorNo`→`00:2799`). |
| **3C** | Link code + the **OS version string** — page starts with ASCII `32 2E 35 35 4D 50` = **"2.55MP"**. |
| **3E** | **Certification page** — the per-calculator certificate sector (84+ cert page is `3E`, not `3F`). Blank (99% `0xFF`) in this OS-only image, since the cert is written per-device. |
| **3F** | **Boot page** — starts `3E 3F D3 06 D3 07` = `LD A,0x3F; OUT (6),A; OUT (7),A` (maps itself into both banks at power-on). Boot code only; the certificate lives on page `3E`. |

The **large-font glyph table is on page 0x07, base `0x45FF`** — `put_glyph_large` (`07:4588`) computes the glyph pointer as `0x45FF + char*7` (**7-byte stride**, via the `07:45EB` adjuster) and copies an 8-byte record via `_Mov8B` to RAM `0x845A`; see [Display/LCD → Fonts](08-display-lcd.md#fonts-confirmed). Alternate large fonts live on pages 1 and 0x36 (selected by `(IY+0x35)` bits 5/1). Page 7 is the busiest data page (archive code, list/matrix, error messages, *and* the large font). **[confirmed]**

## Takeaway
The OS is **page-specialized**: kernel + math on page 0, one subsystem per low page. A bcall is really "run subsystem X's routine on its page" — the page map *is* the subsystem decomposition, physically.
