; Restoring RAM-selector alias probe.
; Result AppVar: HWPRAM21, probe ID 2, payload 19 bytes.

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

    call mapping_context_supported
    jr z,create_pending_result
    ld a,1
    ld (payload_outcome),a
    jp create_final_result

    ; Allocate the pending record before sampling bytes that allocator activity
    ; could change. No selector or target-memory write has occurred.
create_pending_result:
    ld ix,appvar_name
    ld hl,frame
    ld bc,frame_end-frame
    call create_probe_appvar
    ex de,hl
    ld de,-(frame_end-frame)
    add hl,de
    ld (result_frame_ptr),hl
    ld a,1
    ld (result_created),a
    di

    call mapping_context_supported
    jr z,save_original_ready
    ld a,2
    ld (payload_outcome),a
    jr finalize_result

    ; Save the byte visible through each selector after allocation, then copy
    ; those originals into the resident pending frame before the first write.
save_original_ready:
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

    ld a,(saved_port6)
    out ($06),a
    ld de,(result_frame_ptr)
    ld hl,frame
    ld bc,frame_end-frame
    ldir

    ; Write distinct values while interrupts cannot observe bank A.
write_patterns_ready:
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
    xor a
    ld (payload_outcome),a

finalize_result:
    ld a,(result_created)
    or a
    jr z,create_final_result
    ld de,(result_frame_ptr)
    ld hl,frame
    ld bc,frame_end-frame
    ldir
    jr result_ready

create_final_result:
    pop af
    jp po,interrupts_restored
    ei
interrupts_restored:
    ld ix,appvar_name
    ld hl,frame
    ld bc,frame_end-frame
    call create_probe_appvar
    ex de,hl
    ld de,-(frame_end-frame)
    add hl,de
    ld (result_frame_ptr),hl
    jr display_result

result_ready:
    pop af
    jp po,result_interrupts_restored
    ei
result_interrupts_restored:
display_result:
    ld ix,(result_frame_ptr)
    ld bc,frame_end-frame
    ld hl,display_label
    call display_probe_code
    ret

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
    ret nz
    ld hl,$0BD9
    ld de,os_signature
    ld b,8
mapping_os_signature_loop:
    ld a,(de)
    cp (hl)
    ret nz
    inc de
    inc hl
    djnz mapping_os_signature_loop
    xor a
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
result_created:
    .db 0
result_frame_ptr:
    .dw 0
os_signature:
    .db $3E,$C0,$D3,$00,$31,$F7,$FF,$CD

frame:
    .db "HWP1",1,2
    .dw payload_end-payload
frame_asic:
    .db 0
frame_status:
    .db 0
payload:
payload_outcome:
    .db $FF
payload_original:
    .fill 6,0
payload_observed:
    .fill 6,0
payload_restored:
    .fill 6,0
payload_end:
frame_end:
