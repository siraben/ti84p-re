; Guarded programmable-timer HALT-wake probe with a standard-timer watchdog.
; Result AppVar: HWPIRQ01, probe ID 16, payload 21 bytes.

.org $9D95
    jp start
#include "common.inc"

start:
    ld a,i
    push af
    ld (payload_pre_i),a
    di

    in a,($15)
    ld (frame_asic),a
    in a,($02)
    ld (frame_status),a
    in a,($03)
    ld (payload_pre_port03),a
    in a,($04)
    ld (payload_pre_port04),a
    in a,($30)
    ld (payload_pre_port30),a
    in a,($31)
    ld (payload_pre_port31),a
    in a,($32)
    ld (payload_pre_port32),a

    push iy
    pop hl
    ld de,$89F0
    or a
    sbc hl,de
    jp nz,abort_os_context
    ; Port-0x03 bit-3 readback is not documented. Reconstruct the OS mask
    ; from the timer-2 flag instead of later writing the entry readback.
    ld a,$0B
    bit 0,(iy+$16)
    jr z,restore_mask_ready
    or $04
restore_mask_ready:
    ld (restore_mask),a
    ld hl,$0038
    ld de,im1_signature
    ld b,6
check_im1_signature:
    ld a,(de)
    cp (hl)
    jp nz,abort_vector_signature
    inc de
    inc hl
    djnz check_im1_signature
    in a,($55)
    and $1F
    cp $1F
    jp nz,abort_usb_source

    ld a,(payload_pre_port04)
    and $F7
    jp nz,abort_pending_source
    ld a,(payload_pre_port04)
    bit 3,a
    jp z,abort_on_held
    ld a,(payload_pre_port30)
    or a
    jp nz,abort_timer_source
    ld a,(payload_pre_port31)
    or a
    jp nz,abort_timer_mode
    pop af
    push af
    jp po,abort_interrupts_disabled

    ; Create a pending frame before replacing IM1 or arming any source. A reset
    ; or failed wake therefore leaves an identifiable AppVar.
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

    ; AppVar allocation can run OS code, so repeat every live-source guard.
    di
    in a,($04)
    and $F7
    jr nz,post_create_guard_failed
    in a,($30)
    or a
    jr nz,post_create_guard_failed
    in a,($31)
    or a
    jr nz,post_create_guard_failed

    xor a
    ld (irq_count),a
    ld (irq_status04),a
    ld (irq_mode31),a
    ld (irq_counter32),a

    ; A 257-byte uniform IM2 table covers every vector byte. The table points
    ; to the handler at 0xA3A3 and remains in the program's RAM page.
    ld a,$A2
    ld i,a
    im 2

    ; Clear guarded-empty legacy latches, then enable powered HALT and standard
    ; timer 1 as the watchdog. The programmable timer should expire first.
    xor a
    out ($03),a
    ld a,$0A
    out ($03),a
    ld a,$45
    out ($30),a
    ld a,$02
    out ($31),a
    ld a,1
    out ($32),a

    ei
    halt
    di

    ld a,(irq_count)
    ld (payload_irq_count),a
    ld a,(irq_status04)
    ld (payload_irq_status04),a
    ld a,(irq_mode31)
    ld (payload_irq_mode31),a
    ld a,(irq_counter32)
    ld (payload_irq_counter32),a
    in a,($04)
    ld (payload_after_port04),a
    in a,($31)
    ld (payload_after_port31),a
    in a,($32)
    ld (payload_after_port32),a
    ld a,(payload_irq_count)
    cp 1
    jr nz,unexpected_handler_count
    xor a
    ld (payload_outcome),a
    jr restore_state
unexpected_handler_count:
    ld a,6
    ld (payload_outcome),a
    jr restore_state

post_create_guard_failed:
    ld a,7
    ld (payload_outcome),a
    jr restore_state

abort_pending_source:
    ld a,1
    jr set_abort
abort_on_held:
    ld a,2
    jr set_abort
abort_timer_source:
    ld a,3
    jr set_abort
abort_timer_mode:
    ld a,4
    jr set_abort
abort_interrupts_disabled:
    ld a,5
    jr set_abort
abort_os_context:
    ld a,8
    jr set_abort
abort_vector_signature:
    ld a,9
    jr set_abort
abort_usb_source:
    ld a,10
set_abort:
    ld (payload_outcome),a

restore_state:
    di
    xor a
    out ($30),a
    out ($31),a
    ld a,(payload_pre_port32)
    out ($32),a
    ld a,(restore_mask)
    out ($03),a
    im 1
    ld a,(payload_pre_i)
    ld i,a

    in a,($03)
    ld (payload_post_port03),a
    in a,($04)
    ld (payload_post_port04),a
    in a,($30)
    ld (payload_post_port30),a
    in a,($31)
    ld (payload_post_port31),a
    in a,($32)
    ld (payload_post_port32),a
    ld a,i
    ld (payload_post_i),a

    ld a,(payload_post_port03)
    and $17
    ld b,a
    ld a,(restore_mask)
    and $17
    cp b
    jr nz,restoration_recorded
    ld a,(payload_post_port30)
    or a
    jr nz,restoration_recorded
    ld a,(payload_post_port31)
    or a
    jr nz,restoration_recorded
    ld a,(payload_post_port32)
    ld b,a
    ld a,(payload_pre_port32)
    cp b
    jr nz,restoration_recorded
    ld a,(payload_post_i)
    ld b,a
    ld a,(payload_pre_i)
    cp b
    jr nz,restoration_recorded
    ld a,1
    ld (payload_restore_ok),a
restoration_recorded:
    ld a,(result_created)
    or a
    jr z,create_final_result
    ld de,(result_frame_ptr)
    ld hl,frame
    ld bc,frame_end-frame
    ldir
    jr result_ready
create_final_result:
    ld ix,appvar_name
    ld hl,frame
    ld bc,frame_end-frame
    call create_probe_appvar
    ex de,hl
    ld de,-(frame_end-frame)
    add hl,de
    ld (result_frame_ptr),hl
result_ready:
    pop af
    jp po,interrupts_restored
    ei
interrupts_restored:
    ld ix,(result_frame_ptr)
    ld bc,frame_end-frame
    ld hl,display_label
    call display_probe_code
    ret

; The handler records the first wake source, then disables both the test timer
; and watchdog before returning from the interrupted HALT.
irq_handler:
    push af
    in a,($04)
    ld (irq_status04),a
    in a,($31)
    ld (irq_mode31),a
    in a,($32)
    ld (irq_counter32),a
    ld a,(irq_count)
    inc a
    ld (irq_count),a
    xor a
    out ($30),a
    out ($31),a
    out ($03),a
    pop af
    ei
    reti

irq_count: .db 0
irq_status04: .db 0
irq_mode31: .db 0
irq_counter32: .db 0
result_created: .db 0
result_frame_ptr: .dw 0
restore_mask: .db 0
im1_signature:
    .db $18,$33,$DB,$04,$CB,$7F

display_label:
    .db "HWPIRQ CODE ",0
#include "display.inc"

; Keep the vector table at 0xA200. Any interrupt-vector byte indexes two
; adjacent 0xA3 bytes, yielding handler address 0xA3A3.
.fill $A200-$,0
im2_table:
    .fill 257,$A3
.fill $A3A3-$,0
im2_handler_entry:
    jp irq_handler

appvar_name:
    .db AppVarObj,"HWPIRQ01"

frame:
    .db "HWP1",1,16
    .dw payload_end-payload
frame_asic: .db 0
frame_status: .db 0
payload:
payload_pre_port03: .db 0
payload_pre_port04: .db 0
payload_pre_port30: .db 0
payload_pre_port31: .db 0
payload_pre_port32: .db 0
payload_pre_i: .db 0
payload_outcome: .db $FF
payload_irq_count: .db 0
payload_irq_status04: .db 0
payload_irq_mode31: .db 0
payload_irq_counter32: .db 0
payload_after_port04: .db 0
payload_after_port31: .db 0
payload_after_port32: .db 0
payload_post_port03: .db 0
payload_post_port04: .db 0
payload_post_port30: .db 0
payload_post_port31: .db 0
payload_post_port32: .db 0
payload_post_i: .db 0
payload_restore_ok: .db 0
payload_end:
frame_end:
