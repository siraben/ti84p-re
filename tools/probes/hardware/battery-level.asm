; Restoring repeated `_Chk_Batt_Level` probe.
; Result AppVar: HWBATT01, probe ID 6, payload 30 bytes.

.org $9D95
    jp start
#include "common.inc"

_Chk_Batt_Level     .equ $5221

start:
    ld a,i
    push af
    di

    in a,($15)
    ld (frame_asic),a
    in a,($02)
    ld (frame_status),a

    in a,($04)
    ld (payload_pre_port04),a
    in a,($39)
    ld (payload_pre_port39),a
    in a,($3A)
    ld (payload_pre_port3a),a
    ld a,(iy+$18)
    ld (payload_pre_trace),a

    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+0),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+1),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+2),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+3),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+4),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+5),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+6),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+7),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+8),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+9),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+10),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+11),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+12),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+13),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+14),a
    rst $28
    .dw _Chk_Batt_Level
    ld (payload_results+15),a

    in a,($02)
    ld (payload_post_status),a
    in a,($04)
    ld (payload_post_port04),a
    in a,($39)
    ld (payload_post_port39),a
    in a,($3A)
    ld (payload_post_port3a),a
    ld a,(iy+$18)
    ld (payload_post_trace),a

    ld a,(payload_pre_port04)
    out ($04),a
    ld a,(payload_pre_port39)
    out ($39),a
    ld a,(payload_pre_port3a)
    out ($3A),a
    ld a,(payload_pre_trace)
    ld (iy+$18),a

    in a,($04)
    ld (payload_restored_port04),a
    in a,($39)
    ld (payload_restored_port39),a
    in a,($3A)
    ld (payload_restored_port3a),a
    ld a,(iy+$18)
    ld (payload_restored_trace),a
    in a,($02)
    ld (payload_final_status),a

    pop af
    jp po,interrupts_restored
    ei
interrupts_restored:
    ld ix,appvar_name
    ld hl,frame
    ld bc,frame_end-frame
    call create_probe_appvar
    ret

appvar_name:
    .db AppVarObj,"HWBATT01"

frame:
    .db "HWP1",1,6
    .dw payload_end-payload
frame_asic:
    .db 0
frame_status:
    .db 0
payload:
payload_pre_port04:
    .db 0
payload_pre_port39:
    .db 0
payload_pre_port3a:
    .db 0
payload_pre_trace:
    .db 0
payload_results:
    .fill 16,0
payload_post_status:
    .db 0
payload_post_port04:
    .db 0
payload_post_port39:
    .db 0
payload_post_port3a:
    .db 0
payload_post_trace:
    .db 0
payload_restored_port04:
    .db 0
payload_restored_port39:
    .db 0
payload_restored_port3a:
    .db 0
payload_restored_trace:
    .db 0
payload_final_status:
    .db 0
payload_end:
frame_end:
