; Raw two-wire link-port readback and settling probe with idle cleanup.
; Result AppVar: HWLINK01, probe ID 8, payload 266 bytes.
; Run only with the 2.5 mm link port disconnected.

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

    in a,($00)
    ld (payload_pre_port00),a
    in a,($03)
    ld (payload_pre_port03),a
    in a,($04)
    ld (payload_pre_port04),a
    in a,($20)
    ld (payload_pre_port20),a

    ld hl,payload_samples
    ld c,0

sample_output:
    ld b,16

sample_trial:
    ; Establish both-low before each target write so releases are edges.
    ld a,3
    out ($00),a
    ld a,c
    out ($00),a
    in a,($00)
    ld (hl),a
    inc hl

    ld a,3
    out ($00),a
    ld a,c
    out ($00),a
    nop
    in a,($00)
    ld (hl),a
    inc hl

    ld a,3
    out ($00),a
    ld a,c
    out ($00),a
    nop
    nop
    nop
    nop
    in a,($00)
    ld (hl),a
    inc hl

    ld a,3
    out ($00),a
    ld a,c
    out ($00),a
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    in a,($00)
    ld (hl),a
    inc hl

    djnz sample_trial
    inc c
    bit 2,c
    jr z,sample_output

    in a,($00)
    ld (payload_post_port00),a
    in a,($03)
    ld (payload_post_port03),a
    in a,($04)
    ld (payload_post_port04),a
    in a,($20)
    ld (payload_post_port20),a

    ; Release both lines rather than trusting unverified latch readback.
    xor a
    out ($00),a

    in a,($00)
    ld (payload_cleanup_port00),a
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

display_label:
    .db "HWLINK CODE ",0
#include "display.inc"

appvar_name:
    .db AppVarObj,"HWLINK01"

frame:
    .db "HWP1",1,8
    .dw payload_end-payload
frame_asic:
    .db 0
frame_status:
    .db 0
payload:
payload_pre_port00:
    .db 0
payload_pre_port03:
    .db 0
payload_pre_port04:
    .db 0
payload_pre_port20:
    .db 0
payload_samples:
    .fill 256,0
payload_post_port00:
    .db 0
payload_post_port03:
    .db 0
payload_post_port04:
    .db 0
payload_post_port20:
    .db 0
payload_cleanup_port00:
    .db 0
payload_final_status:
    .db 0
payload_end:
frame_end:
