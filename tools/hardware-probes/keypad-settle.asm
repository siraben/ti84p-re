; Keypad-matrix selection and settling probe with release cleanup.
; Result AppVar: HWKEYS01, probe ID 9, payload 523 bytes.
; Release the launch key, then hold the test key or chord until return.

.org $9D95
    jp start
#include "common.inc"

start:
    ld a,i
    push af
    di

    in a,($01)
    ld (payload_pre_port01),a
    in a,($02)
    ld (frame_status),a
    ld (payload_pre_port02),a
    in a,($03)
    ld (payload_pre_port03),a
    in a,($04)
    ld (payload_pre_port04),a
    in a,($15)
    ld (frame_asic),a
    in a,($20)
    ld (payload_pre_port20),a

    ; Select every group, wait for the launch key to be released, then wait
    ; for the operator to hold the key or chord under test.
    xor a
    out ($01),a
wait_released:
    in a,($01)
    inc a
    jr nz,wait_released
wait_pressed:
    in a,($01)
    inc a
    jr z,wait_pressed
    dec a
    ld (payload_trigger),a

    ; Let the complete chord settle before testing group-selection edges.
    ld de,$FFFF
settle_chord:
    dec de
    ld a,d
    or e
    jr nz,settle_chord

    ld hl,payload_samples
    ld c,$FE

sample_group:
    ld b,16

sample_trial:
    xor a
    out ($01),a
    ld a,c
    out ($01),a
    in a,($01)
    ld (hl),a
    inc hl

    xor a
    out ($01),a
    ld a,c
    out ($01),a
    nop
    nop
    nop
    nop
    in a,($01)
    ld (hl),a
    inc hl

    xor a
    out ($01),a
    ld a,c
    out ($01),a
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
    in a,($01)
    ld (hl),a
    inc hl

    xor a
    out ($01),a
    ld a,c
    out ($01),a
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
    in a,($01)
    ld (hl),a
    inc hl

    djnz sample_trial
    rlc c
    jp c,sample_group

    ; The OS leaves every group unselected between scans.
    ld a,$FF
    out ($01),a

    in a,($01)
    ld (payload_post_port01),a
    in a,($02)
    ld (payload_post_port02),a
    in a,($03)
    ld (payload_post_port03),a
    in a,($04)
    ld (payload_post_port04),a
    in a,($20)
    ld (payload_post_port20),a

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
    .db AppVarObj,"HWKEYS01"

frame:
    .db "HWP1",1,9
    .dw payload_end-payload
frame_asic:
    .db 0
frame_status:
    .db 0
payload:
payload_pre_port01:
    .db 0
payload_pre_port02:
    .db 0
payload_pre_port03:
    .db 0
payload_pre_port04:
    .db 0
payload_pre_port20:
    .db 0
payload_trigger:
    .db 0
payload_samples:
    .fill 512,0
payload_post_port01:
    .db 0
payload_post_port02:
    .db 0
payload_post_port03:
    .db 0
payload_post_port04:
    .db 0
payload_post_port20:
    .db 0
payload_end:
frame_end:
