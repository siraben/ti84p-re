; Restoring raw battery-comparator selector probe.
; Result AppVar: HWBRAW01, probe ID 7, payload 31 bytes.

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

    ; The fixed-page delay entries and traceFlags access are valid only in the
    ; pinned direct-Asm OS context. Reject everything before the first OUT.
    push iy
    pop hl
    ld de,$89F0
    or a
    sbc hl,de
    jp nz,abort_os_context
    ld a,(iy+$18)
    ld (payload_pre_trace),a
    ld hl,$0BD9
    ld de,os_signature
    ld b,8
check_os_signature:
    ld a,(de)
    cp (hl)
    jp nz,abort_os_signature
    inc de
    inc hl
    djnz check_os_signature
    ld hl,$0CEB
    ld de,helper_signature
    ld b,17
check_helper_signature:
    ld a,(de)
    cp (hl)
    jr nz,abort_helper_signature
    inc de
    inc hl
    djnz check_helper_signature
    call mapping_context_supported
    jr nz,abort_mapping_context

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

    jr capture_and_restore

abort_os_context:
    ld a,1
    jr record_guard_failure
abort_helper_signature:
    ld a,2
    jr record_guard_failure
abort_os_signature:
    ld a,3
    jr record_guard_failure
abort_mapping_context:
    ld a,4
record_guard_failure:
    ld (payload_outcome),a
    ; No hardware or traceFlags write occurred. Populate the common state slots
    ; from the entry snapshot without dereferencing an untrusted IY value.
    ld a,(frame_status)
    ld (payload_post_status),a
    ld (payload_final_status),a
    ld hl,payload_pre_port04
    ld de,payload_post_port04
    ld bc,4
    ldir
    ld hl,payload_pre_port04
    ld de,payload_restored_write04
    ld bc,4
    ldir
    ld a,$FF
    ld (payload_restored_write04),a
    jr result_ready

capture_and_restore:
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

    ; Port 04h reads interrupt status rather than its write-side selector.
    ; The guarded direct-Asm context uses selector 06h; normalize explicitly
    ; and record the value written instead of claiming that a readback restored
    ; an unknowable write latch.
    ld a,$06
    out ($04),a
    ld (payload_restored_write04),a
    ld a,(payload_pre_port39)
    out ($39),a
    ld a,(payload_pre_port3a)
    out ($3A),a
    ld a,(payload_pre_trace)
    ld (iy+$18),a

    in a,($39)
    ld (payload_restored_port39),a
    in a,($3A)
    ld (payload_restored_port3a),a
    ld a,(iy+$18)
    ld (payload_restored_trace),a
    in a,($02)
    ld (payload_final_status),a

result_ready:
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

helper_signature:
    .db $3E,$FF,$F5,$CD,$BD,$0D,$F1,$CD,$E6,$0C,$3D,$20,$FA,$CD,$37,$18,$C0
os_signature:
    .db $3E,$C0,$D3,$00,$31,$F7,$FF,$CD

; Return Z only for the exact independent direct-Asm mapping context. Reading
; port 04h cannot establish that context because its read side is status.
mapping_context_supported:
    in a,($05)
    or a
    ret nz
    in a,($06)
    cp $3F
    ret nz
    in a,($07)
    cp $81
    ret nz
    in a,($0E)
    or a
    ret nz
    in a,($0F)
    or a
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
payload_outcome:
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
payload_restored_write04:
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
