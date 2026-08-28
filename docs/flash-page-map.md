# Flash page map

This page maps the contents of all 64 physical 16 KiB Flash pages. OS code
occupies pages `00`–`07` and `33`–`3D`; page `2F` contains retail USB boot
support, page `3E` holds two certificate sectors, and page `3F` is the retail
boot page. Pages `08`–`2E` and `30`–`32` are blank in this image. [confirmed]

On a retail unit, the blank range stores archived variables and can carry Flash
Apps. [Flash memory](flash-memory.md) describes physical erase-sector geometry
and the dynamic archive/App boundary. The page roles below use resolved bcall
targets. Counts are main-table rows in `tools/symbols/bcall_targets.txt`,
including aliases and inferred names; they are not recovered function counts.

## OS pages (carry bcall entry points)

| Page | Main-table rows | Role | Representative routines |
|------|------:|------|--------------------------|
| `00` | 297 | Kernel — mapped at `0x0000`; RST vectors, bcall dispatcher, FP core, VAT, memory, integer math | `_JErrorNo`, `_LdHLind`, `_DivHLBy10`, `_FindSym`, `_FPAdd`, `_InsertMem` |
| `01` | 31 | Text display / homescreen | `_PutMap`, `_PutC`, `_PutS`, `_DispHL`, `_NewLine`, `_ClrLCDFull` |
| `02` | 76 | Float transcendentals & advanced math | `_SqRoot`, `_LnX`, `_RnFx`, `_RndGuard` |
| `03` | 8 | Edit-buffer / small font | `_CloseEditBufNoR`, `_Load_SFont`, `_SFont_Len` |
| `04` | 38 | Graph drawing (pixel/line) | `_DarkLine`, `_ILine`, `_IPoint`, `_DarkPnt` |
| `05` | 5 | TABLE editor + Graph-Table split-screen | `table_editor_main`, `table_recompute`, `table_paint_grid` |
| `06` | 12 | Key input & edit/cursor | `_GetKey`, `_CursorOn`, `_CursorOff`, `_PutTokString` (note `_GetCSC`'s body is on page 00) |
| `07` | 24 | Archive / list & matrix ops; error messages; large-font glyph table @ `07:45FF` (7-byte stride) read by `put_glyph_large` (`07:4588`) | `_Arc_Unarc`, `_CleanAll`, `_RedimMat`, `_IncLstSize`, `put_glyph_large` |
| `33` | 28 | Graph coordinate math and programmable timer API | `_SetXXOP1`, `_UCLineS`, `_InitTimer`, `_StartTimer`, `timer_irq` |
| `36` | 14 | Mode setters (Func/Param/Polar/Seq) | `_SetFuncM`, `_SetParM`, `_SetPolM`, `_SetSeqM` |
| `37` | 30 | Graph coordinate conversion, RTC, and date/time formatting | `_XftoI`, `_YftoI`, `_getDate`, `_getTime`, `rtc_read_seconds` |
| `38` | 26 | TI-BASIC parser / evaluator | `_ParseInp`, `_Find_Parse_Formula`, `parse_init` |
| `39` | 5 | Equation pretty-printer (2D MathPrint layout) + menus | `eqdisp_render_entry`, `eqdisp_emit_glyph`, `_DispMenuTitle` |
| `3A` | 4 | Statistics (1/2-var, regressions); some iterative numeric callers remain unmapped | `_OneVar`, `reg_gauss_solve`, `numeric_iterate_64` |
| `34` | 3 | Token/parser scanning | `_AHEADEQUAL`, `_PARSAHEADS`, `_PARSAHEAD`, `parse_scan_table` |
| `35` | 3 | USB controller paths, memory-reset engine, factorial | `usb_timeout_irq`, `mem_reset_dispatch`, `ram_reset_wipe`, `op1_factorial` |
| `3B` | 24 | bcall jump table + mem utils | (table data) `_MemClear`, `_MemSet`, `_DrawCirc2` |
| `3C` | 10 | Link / variable transfer | `_SendAByte`, `_RecAByteIO`, `_SendVarCmd`, `_Rec1stByte` |
| `3D` | 7 | App management & Flash | `_FindApp`, `_FindAppUp`, `_FindAppDn`, `_FlashToRam` |

## Blank, boot, and system pages

The complete 1 MiB image contains no `80 0F` Flash App header at any byte
offset, including its 64 page boundaries. The image therefore contains no
bundled Flash App. [confirmed]

Byte-level notes on the empty page range and the boot/system pages, some of
which also carry the bcalls listed above:

| Page | Verified contents |
|------|-------------------|
| `08`–`2E`, `30`–`32` | Blank or unused in this OS image — 100% `0xFF` in `tools/rom.bin`. No app headers. |
| `2F` | Retail USB boot support installed from the checksum- and hash-validated local `D84PBE2.8Xv`. This installation changes 8,615 bytes of the pinned base. The page-`3F` boot table maps `_AttemptUSBOSReceive`, `_ReceiveOS_USB`, `_USBErrorCleanup`, `_InitUSB`, and `_KillUSB` here; `tools/rom.bin` contains the payload and `tools/symbols/bcalls8x_targets.txt` records their bodies. [confirmed] |
| `34`–`39` | More OS code (parser scan, USB, graph, mode, menu, and RTC); approximately 0.2–17.3% of each page's bytes are `0xFF`. |
| `3B` | bcall jump table — starts `99 27 00` = entry 0 (`_JErrorNo` → `ram:2799`). |
| `3C` | Link code, archive garbage collection, and the OS version string — page starts with ASCII `32 2E 35 35 4D 50` = `"2.55MP"`; `archive_gc_collect` is at `3C:7733`. |
| `3E` | Certification page and GC journal — two physical 8 KiB sectors. `_GetCertificateStart` (ID `8057h`) selects the active half; `_GetCertificateEnd` (ID `802Dh`) bounds it; `_FindFirstCertField` (ID `8027h`) and `_FindNextCertField` (ID `8078h`) walk TLV fields. GC transactionally copies the used tail through the inactive half and stores phase bytes near its end. [confirmed] |
| `3F` | Retail boot page — the pinned base matches the checksum- and hash-validated local `D84PBE1.8Xv` payload byte for byte; starts `3E 07 D3 04 3E 7F D3 06 3E 03 D3 0E C3 2C 81`, carries boot version `1.03`, and hosts the boot bcall table. Boot and hardware-version bcalls resolve to `_getBootVer` (ID `80B7h`, body `3F:477C`) and `_getHardwareVersion` (ID `80BAh`, body `3F:4781`). [confirmed] |

The large-font glyph table is on Flash page `07`; see
[Display and LCD](display-lcd.md#large-font-text). Alternate large fonts live
on Flash pages `01` and `36`, selected by `IY+0x35` bits 5 and 1. Flash page
`07` contains archive code, list and matrix code, error messages, and the large
font. [confirmed]

## Page specialization

Related routines often share a page, but subsystem boundaries cross pages.
For example, graph rendering uses pages `04`, `33`, and `37`, and page `07`
combines VAT services with glyph data. The bcall and bjump mechanisms connect
these routines across the fixed and banked windows.
