;==============================================================================
; ti84plus_extra.inc - symbols mapped by reverse-engineering OS 2.55MP,
; supplementing the 2001-era ti83plus.inc (which predates many 84+ additions).
; Names prefixed by subsystem are RE-INFERRED from behavior, not official TI.
;   _fpx=float/math _grf/_grc=graph _drw=draw _scr=screen _tmr=crystal-timer
;   _lnk=link _app=app-mgmt _dsp=display _arc=archive _mde=mode _sta=stat _edt=editor
;==============================================================================

;--- bcalls present in OS 2.55MP but absent from ti83plus.inc (RE-named) ---
_RclListElemToOP1    .equ 4639h    ; -> 02:47FB  (1 call site)
_RclListElemB        .equ 463Ch    ; -> 02:47FE  (3 call sites)
_CplxOPArrange       .equ 4648h    ; -> 02:494F  (2 call sites)
_RclCListElem        .equ 464Bh    ; -> 02:49A7  (2 call sites)
_RclCListElemB       .equ 464Eh    ; -> 02:49B5  (2 call sites)
_PushZeroOP1         .equ 4651h    ; -> 02:49C0  (1 call site)
_GetPosListElem      .equ 4666h    ; -> 02:5BBB  (3 call sites)
_fpx_5d70            .equ 4669h    ; -> 02:5D70  (1 call site)
_fpx_5dbb            .equ 466Ch    ; -> 02:5DBB  (1 call site)
_grf_7066            .equ 47C5h    ; -> 33:7066  (1 call site)
_GraphTblNext        .equ 47C8h    ; -> 33:707A  (2 call sites)
_GraphTblFind        .equ 47CBh    ; -> 33:7097  (5 call sites)
_drw_5df4            .equ 4825h    ; -> 04:5DF4  (2 call sites)
_DrawZeroOP1         .equ 4873h    ; -> 04:620B  (1 call site)
_drw_638e            .equ 487Ch    ; -> 04:638E  (1 call site)
_OP1IntPartNeg       .equ 489Ah    ; -> 04:74E8  (2 call sites)
_VertSplitDraw       .equ 48DCh    ; -> 05:5D88  (1 call site)
_mde_7da9            .equ 49DBh    ; -> 36:7DA9  (1 call site)
_arc_59f1            .equ 4A68h    ; -> 07:59F1  (1 call site)
_FPSPushReal         .equ 4A83h    ; -> 07:6365  (1 call site)
_CrystalTimerA       .equ 4B49h    ; -> 34:5A99  (1 call site)
_CrystalTimerB       .equ 4B4Ch    ; -> 34:5A9D  (1 call site)
_CrystalTimerC       .equ 4B4Fh    ; -> 34:5AA1  (3 call sites)
_RclVarPush          .equ 4B9Ah    ; -> 3A:5D07  (1 call site)
_sta_5eef            .equ 4B9Dh    ; -> 3A:5EEF  (2 call sites)
_sta_760f            .equ 4BA9h    ; -> 3A:760F  (1 call site)
_dsp_6240            .equ 4C42h    ; -> 01:6240  (1 call site)
_LcdBlitRegion       .equ 4D26h    ; -> 07:5431  (1 call site)
_dsp_65ea            .equ 4D6Bh    ; -> 01:65EA  (1 call site)
_LinkXferOP          .equ 50FBh    ; -> 3C:4DD2  (1 call site)
_CLogPrep            .equ 50FEh    ; -> 02:6F1B  (1 call site)
_fpx_7069            .equ 5101h    ; -> 02:7069  (1 call site)
_GraphParseTok       .equ 510Ah    ; -> 33:5023  (1 call site)
_grf_435f            .equ 5140h    ; -> 33:435F  (1 call site)
_grc_51c2            .equ 517Fh    ; -> 37:51C2  (1 call site)
_lnk_62b0            .equ 5182h    ; -> 3C:62B0  (2 call sites)
_fpx_4a7b            .equ 5185h    ; -> 02:4A7B  (1 call site)
_grc_5223            .equ 51A0h    ; -> 37:5223  (1 call site)
_arc_5936            .equ 51ACh    ; -> 07:5936  (1 call site)
_DispPagedStr        .equ 51CAh    ; -> 01:7C4D  (1 call site)
_grc_5d44            .equ 51D6h    ; -> 37:5D44  (1 call site)
_scr_4619            .equ 51E5h    ; -> 05:4619  (1 call site)
_scr_4056            .equ 51F1h    ; -> 05:4056  (1 call site)
_grc_60cb            .equ 51FAh    ; -> 37:60CB  (1 call site)
_grc_5f42            .equ 5200h    ; -> 37:5F42  (2 call sites)
_sta_5d3c            .equ 5203h    ; -> 35:5D3C  (1 call site)
_ScreenSplit         .equ 5227h    ; -> 05:7712  (1 call site)
_grc_454b            .equ 5263h    ; -> 37:454B  (1 call site)
_grc_4556            .equ 5266h    ; -> 37:4556  (1 call site)
_grc_4575            .equ 5269h    ; -> 37:4575  (1 call site)
_grc_4611            .equ 52FFh    ; -> 37:4611  (1 call site)
_app_5de7            .equ 5326h    ; -> 3D:5DE7  (2 call sites)
_fpx_7dfe            .equ 5338h    ; -> 02:7DFE  (1 call site)
_fpx_7d9d            .equ 533Bh    ; -> 02:7D9D  (1 call site)
_ListIdxTimes9       .equ 53D1h    ; -> 35:79E9  (1 call site)
_drw_5df1            .equ 53F5h    ; -> 04:5DF1  (2 call sites)
_edt_6bd1            .equ 5458h    ; -> 03:6BD1  (1 call site)
_edt_69f8            .equ 5461h    ; -> 03:69F8  (1 call site)
_edt_5d6f            .equ 5464h    ; -> 03:5D6F  (1 call site)
_mnu_6ddb            .equ 5467h    ; -> 39:6DDB  (1 call site)
_grf_5e06            .equ 5476h    ; -> 33:5E06  (1 call site)

;--- 0x8xxx extended bcalls: dispatched via the ID bit-15 path (NOT the
;    page-3Bh jump table); target table not yet located. TODO. ---
; _xbcall_8021   .equ 8021h    ; 2 call sites  [unresolved]
; _xbcall_8027   .equ 8027h    ; 2 call sites  [unresolved]
; _xbcall_8030   .equ 8030h    ; 1 call site  [unresolved]
; _xbcall_8054   .equ 8054h    ; 1 call site  [unresolved]
; _xbcall_8057   .equ 8057h    ; 2 call sites  [unresolved]
; _xbcall_805A   .equ 805Ah    ; 3 call sites  [unresolved]
; _xbcall_805D   .equ 805Dh    ; 1 call site  [unresolved]
; _xbcall_8075   .equ 8075h    ; 2 call sites  [unresolved]
; _xbcall_80B1   .equ 80B1h    ; 1 call site  [unresolved]
; _xbcall_80B7   .equ 80B7h    ; 1 call site  [unresolved]
; _xbcall_80BA   .equ 80BAh    ; 1 call site  [unresolved]
