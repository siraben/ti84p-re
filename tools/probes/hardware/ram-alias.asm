; Restoring RAM-selector alias probe.
; Result AppVar: HWPRAM21, probe ID 2, payload 18 bytes.

.org $9D95
    jp start
#include "common.inc"

probe_address       .equ $7F00

start:
    ld a,i
    push af
    di

    in a,($15)
    ld (frame_asic),a
    in a,($02)
    ld (frame_status),a
    in a,($06)
    ld (saved_port6),a

    ; Save the byte currently visible through each selector.
    ld hl,payload_original
    ld e,$82
    ld d,6
save_original:
    ld a,e
    out ($06),a
    ld a,(probe_address)
    ld (hl),a
    inc hl
    inc e
    dec d
    jr nz,save_original

    ; Write distinct values while interrupts cannot observe bank A.
    ld hl,patterns
    ld e,$82
    ld d,6
write_patterns:
    ld a,e
    out ($06),a
    ld a,(hl)
    ld (probe_address),a
    inc hl
    inc e
    dec d
    jr nz,write_patterns

    ; Full-RAM hardware returns six patterns; aliased hardware repeats 66h.
    ld hl,payload_observed
    ld e,$82
    ld d,6
read_patterns:
    ld a,e
    out ($06),a
    ld a,(probe_address)
    ld (hl),a
    inc hl
    inc e
    dec d
    jr nz,read_patterns

    ; Restore the original byte through every selector.
    ld hl,payload_original
    ld e,$82
    ld d,6
restore_original:
    ld a,e
    out ($06),a
    ld a,(hl)
    ld (probe_address),a
    inc hl
    inc e
    dec d
    jr nz,restore_original

    ; Verify the restored values before restoring the caller's bank A.
    ld hl,payload_restored
    ld e,$82
    ld d,6
read_restored:
    ld a,e
    out ($06),a
    ld a,(probe_address)
    ld (hl),a
    inc hl
    inc e
    dec d
    jr nz,read_restored

    ld a,(saved_port6)
    out ($06),a
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
    .db "HWPRAM CODE ",0
#include "display.inc"

appvar_name:
    .db AppVarObj,"HWPRAM21"

patterns:
    .db $11,$22,$33,$44,$55,$66
saved_port6:
    .db 0

frame:
    .db "HWP1",1,2
    .dw payload_end-payload
frame_asic:
    .db 0
frame_status:
    .db 0
payload:
payload_original:
    .fill 6,0
payload_observed:
    .fill 6,0
payload_restored:
    .fill 6,0
payload_end:
frame_end:
