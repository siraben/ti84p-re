; Restoring raw battery-comparator selector probe.
; Result AppVar: HWBRAW01, probe ID 7, payload 30 bytes.

.org $9D95
    jp start
#include "common.inc"

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

    call sample_once
    ld (payload_masks+0),a
    call sample_once
    ld (payload_masks+1),a
    call sample_once
    ld (payload_masks+2),a
    call sample_once
    ld (payload_masks+3),a
    call sample_once
    ld (payload_masks+4),a
    call sample_once
    ld (payload_masks+5),a
    call sample_once
    ld (payload_masks+6),a
    call sample_once
    ld (payload_masks+7),a
    call sample_once
    ld (payload_masks+8),a
    call sample_once
    ld (payload_masks+9),a
    call sample_once
    ld (payload_masks+10),a
    call sample_once
    ld (payload_masks+11),a
    call sample_once
    ld (payload_masks+12),a
    call sample_once
    ld (payload_masks+13),a
    call sample_once
    ld (payload_masks+14),a
    call sample_once
    ld (payload_masks+15),a

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
    ld bc,frame_end-frame
    ld hl,display_label
    call display_created_probe_code
    ret

; Record bit 0 for selectors 06, C6, 86, 46 as mask bits 0, 3, 2, 1.
; The initial 06 read precedes the ROM's GPIO bit-7 load enable.
sample_once:
    ld c,0
    ld a,$06
    call read_comparator
    jr z,sample_c6
    set 0,c
sample_c6:
    in a,($3A)
    or $80
    out ($3A),a
    ld a,$C6
    call read_comparator
    jr z,sample_86
    set 3,c
sample_86:
    ld a,$86
    call read_comparator
    jr z,sample_46
    set 2,c
sample_46:
    ld a,$46
    call read_comparator
    jr z,sample_cleanup
    set 1,c

sample_cleanup:
    ld a,$06
    out ($04),a
    in a,($39)
    or $10
    out ($39),a
    in a,($3A)
    or $10
    out ($3A),a
    ld a,$40
    call $0CED
    in a,($3A)
    and $EF
    out ($3A),a
    in a,($3A)
    and $7F
    out ($3A),a
    ld a,c
    ret

read_comparator:
    out ($04),a
    ld b,5
read_delay:
    call $0CEB
    djnz read_delay
    in a,($02)
    and 1
    ret

display_label:
    .db "HWBRAW CODE ",0
#include "display.inc"

appvar_name:
    .db AppVarObj,"HWBRAW01"

frame:
    .db "HWP1",1,7
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
payload_masks:
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
