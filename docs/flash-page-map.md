# Flash page map

What lives on each of the 64 physical flash pages (16 KiB each). OS code occupies pages `00–07` and `33–3D`; pages `08–32` are blank in this image; page `3E` is the certificate sector and `3F` the boot page. On a retail unit the upper pages can also carry Flash Apps, but this dump is OS-only — the page scan below reports zero Flash-App headers. The page roles below are characterized by the named bcall routines that resolve to each page (`tools/bcall_targets.txt`) plus function counts; the `0x8xxx` cert/boot/USB bcalls come instead from `ti83plus.inc` and the retail segment files (`bcall_targets.txt` does not carry the `0x8xxx` targets).

## OS pages (carry bcall entry points)

| Page | Funcs | Role | Representative routines |
|------|------:|------|--------------------------|
| `00` | 928 | **Kernel** — mapped at `0000`; RST vectors, bcall dispatcher, FP core, VAT, memory, integer math | `_JErrorNo`, `_LdHLind`, `_DivHLBy10`, `_FindSym`, `_FPAdd`, `_InsertMem` |
| `01` | 84 | Text display / homescreen | `_PutMap`, `_PutC`, `_PutS`, `_DispHL`, `_NewLine`, `_ClrLCDFull` |
| `02` | 271 | Float transcendentals & advanced math | `_SqRoot`, `_LnX`, `_RnFx`, `_RndGuard` |
| `03` | 23 | Edit-buffer / small font | `_CloseEditBufNoR`, `_Load_SFont`, `_SFont_Len` |
| `04` | 66 | Graph drawing (pixel/line) | `_DarkLine`, `_ILine`, `_IPoint`, `_DarkPnt` |
| `05` | 118 | TABLE editor + Graph-Table split-screen | `table_editor_main`, `table_recompute`, `table_paint_grid` |
| `06` | 49 | Key input & edit/cursor | `_GetKey`, `_CursorOn`, `_CursorOff`, `_PutTokString` (note `_GetCSC`'s body is on page 00) |
| `07` | 44 | Archive / list & matrix ops; error messages; large-font glyph table @ `07:45FF` (7-byte stride) read by `put_glyph_large` (`07:4588`) | `_Arc_Unarc`, `_CleanAll`, `_RedimMat`, `_IncLstSize`, `put_glyph_large` |
| `33` | 70 | Graph coordinate math | `_SetXXOP1`, `_UCLineS` (window↔pixel transforms) |
| `36` | 24 | Mode setters (Func/Param/Polar/Seq) | `_SetFuncM`, `_SetParM`, `_SetPolM`, `_SetSeqM` |
| `37` | 23 | Graph coord convert | `_XftoI`, `_YftoI` |
| `38` | 277 | TI-BASIC parser / evaluator | `_ParseInp`, `_Find_Parse_Formula`, `parse_init` |
| `39` | 153 | Equation pretty-printer (2D MathPrint layout) + menus | `eqdisp_render_entry`, `eqdisp_emit_glyph`, `_DispMenuTitle` |
| `3A` | 85 | Statistics (1/2-var, regressions) + TVM finance | `_OneVar`, `reg_gauss_solve`, `tvm_solve_iterate` |
| `34` | 16 | Crystal timers / clock, token scan | `_CrystalTimerA`, `timer_scan_tbl` |
| `35` | 6 | Memory-reset engine, factorial | `mem_reset_dispatch`, `ram_reset_wipe`, `op1_factorial` |
| `3B` | 39 | bcall jump table + mem utils | (table data) `_MemClear`, `_MemSet`, `_DrawCirc2` |
| `3C` | 72 | Link / variable transfer | `_SendAByte`, `_RecAByteIO`, `_SendVarCmd`, `_Rec1stByte` |
| `3D` | 61 | App management & Flash | `_FindApp`, `_FindAppUp`, `_FindAppDn`, `_FlashToRam` |

## Page byte-scan notes (empty range, boot & system pages)

No Flash-App headers (`80 0F`) appear at any page boundary; the image is OS-only [hypothesis]. Byte-level notes on the empty page range and the boot/system pages (some of which, e.g. `34–39`/`3B`/`3C`, also carry the bcalls listed above):

| Page | Verified contents |
|------|-------------------|
| `08–32` | Blank/unused in this OS image — 100% `0xFF` in `tools/rom.bin`. Page `2F` is the retail USB boot support page, but its code lives in the separate `D84PBE2.8Xv` segment (not in `rom.bin`); the retail page-`3F` boot table maps the `0x8xxx` USB bcalls (`_AttemptUSBOSReceive`, `_ReceiveOS_USB`, `_USBErrorCleanup`, `_InitUSB`, `_KillUSB`) into page `2F`. No app headers. |
| `34–39` | More OS code (graph/mode/menu/timers); fill 0.2–17% `0xFF`. |
| `3B` | **bcall jump table** — starts `99 27 00` = entry 0 (`_JErrorNo`→`ram:2799`). |
| `3C` | Link code + the OS version string — page starts with ASCII `32 2E 35 35 4D 50` = `"2.55MP"`. |
| `3E` | **Certification page** — the per-calculator certificate sector (84+ cert page is `3E`, not `3F`). Blank (99% `0xFF`) in this OS-only image, since the cert is written per-device. The OS reads this sector through the `ti83plus.inc` cert bcalls: `_GetCertificateStart` (bcall `0x8057`) and `_GetCertificateEnd` (bcall `0x802D`) bound the sector, and `_FindFirstCertField` (bcall `0x8027`) / `_FindNextCertField` (bcall `0x8078`) walk its TLV fields. |
| `3F` | **Retail boot page** — supplied by local `D84PBE1.8Xv`; starts `3E 07 D3 04 3E 7F D3 06 3E 03 D3 0E C3 2C 81`, carries boot version `1.03`, and hosts the `0x8xxx` boot bcall table. Boot/hardware-version bcalls now resolve to `_getBootVer` `3F:477C` (`0x80B7`) and `_getHardwareVersion` `3F:4781` (`0x80BA`). |

The large-font glyph table is on page 0x07 (see [Display / LCD](display-lcd.md#fonts-confirmed)). Alternate large fonts live on pages 1 and 0x36 (selected by `(IY+0x35)` bits 5/1). Page 7 is the busiest data page (archive code, list/matrix, error messages, *and* the large font). [confirmed]

## Takeaway
The OS is page-specialized: kernel + math on page 0, one subsystem per low page. A bcall is really "run subsystem X's routine on its page" — the page map *is* the subsystem decomposition, physically.
