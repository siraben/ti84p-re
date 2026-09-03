; Physical programmable-timer edge matrix.
; Result AppVar: HWTMR001, probe ID 12, payload 91 bytes.
; Requires idle timers 1 and 2 and restores their registers and timing controls.

.org $9D95
    jp start
#include "common.inc"

start:
    ld a,i
    push af
    di

    in a,($15)
    ld (frame_asic),a
    ld (payload_pre_port15),a
    in a,($02)
    ld (frame_status),a
    ld (payload_pre_port02),a
    in a,($03)
    ld (payload_pre_port03),a
    in a,($04)
    ld (payload_pre_port04),a
    in a,($20)
    ld (payload_pre_port20),a
    in a,($2D)
    ld (payload_pre_port2d),a
    in a,($2F)
    ld (payload_pre_port2f),a
    in a,($30)
    ld (payload_pre_port30),a
    in a,($31)
    ld (payload_pre_port31),a
    in a,($32)
    ld (payload_pre_port32),a
    in a,($33)
    ld (payload_pre_port33),a
    in a,($34)
    ld (payload_pre_port34),a
    in a,($35)
    ld (payload_pre_port35),a

    xor a
    ld (payload_outcome),a

    ld a,(payload_pre_port30)
    or a
    jr nz,abort_timer1_source
    ld a,(payload_pre_port31)
    or a
    jr nz,abort_timer1_mode
    ld a,(payload_pre_port33)
    or a
    jr nz,abort_timer2_source
    ld a,(payload_pre_port34)
    or a
    jr nz,abort_timer2_mode
    ld a,(payload_pre_port04)
    and $60
    jr nz,abort_timer_pending

    ld a,$4B
    out ($2F),a

    ld ix,payload_crystal
    call measure_crystal_divisor
    jr c,measurement_timeout
    call measure_crystal_divisor
    jr c,measurement_timeout
    call measure_crystal_divisor
    jr c,measurement_timeout
    call measure_crystal_divisor
    jr c,measurement_timeout

    ld ix,payload_mode3
    xor a
    call measure_mode3
    jr c,measurement_timeout
    ld a,1
    call measure_mode3
    jr c,measurement_timeout
    ld a,2
    call measure_mode3
    jr c,measurement_timeout
    ld a,3
    call measure_mode3
    jr c,measurement_timeout

    ld ix,payload_zero
    call measure_counter_zero
    jr c,measurement_timeout

    ld ix,payload_expiry
    call measure_expiry_status
    jr c,measurement_timeout

    call restore_state
    jr capture_post

abort_timer1_source:
    ld a,1
    jr set_outcome
abort_timer1_mode:
    ld a,2
    jr set_outcome
abort_timer2_source:
    ld a,3
    jr set_outcome
abort_timer2_mode:
    ld a,4
    jr set_outcome
abort_timer_pending:
    ld a,5
set_outcome:
    ld (payload_outcome),a
    jr capture_post

measurement_timeout:
    ld a,6
    ld (payload_outcome),a
    call restore_state

capture_post:
    in a,($02)
    ld (payload_post_port02),a
    in a,($03)
    ld (payload_post_port03),a
    in a,($04)
    ld (payload_post_port04),a
    in a,($15)
    ld (payload_post_port15),a
    in a,($20)
    ld (payload_post_port20),a
    in a,($2D)
    ld (payload_post_port2d),a
    in a,($2F)
    ld (payload_post_port2f),a
    in a,($30)
    ld (payload_post_port30),a
    in a,($31)
    ld (payload_post_port31),a
    in a,($32)
    ld (payload_post_port32),a
    in a,($33)
    ld (payload_post_port33),a
    in a,($34)
    ld (payload_post_port34),a
    in a,($35)
    ld (payload_post_port35),a

    pop af
    jp po,interrupts_restored
    ei
interrupts_restored:
    ld ix,appvar_name
    ld hl,frame
    ld bc,frame_end-frame
    call create_probe_appvar
    ret

; Compare source 0x41 against the agreed 2,048 Hz source 0x45. Four trials
; retain both start and end counters so the decoder can aggregate ratios.
measure_crystal_divisor:
    call stop_timers
    ld a,$41
    out ($30),a
    xor a
    out ($31),a
    ld a,$FF
    out ($32),a
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
    in a,($32)
    ld (ix+0),a
    in a,($35)
    ld (ix+1),a
    ld bc,$FFFF
crystal_wait:
    in a,($35)
    cp $21
    jr c,crystal_done
    dec bc
    ld a,b
    or c
    jr nz,crystal_wait
    scf
    ret
crystal_done:
    ld (ix+3),a
    in a,($32)
    ld (ix+2),a
    call stop_timers
    inc ix
    inc ix
    inc ix
    inc ix
    or a
    ret

; Count source 0xE0 expiries during a crystal-timer window. The source uses
; CPU/64 before the documented speed-selected port-0x2F prescaler.
measure_mode3:
    ld (ix+0),a
    out ($20),a
    nop
    nop
    nop
    nop
    in a,($20)
    ld (ix+1),a
    call stop_timers
    ld a,$E0
    out ($30),a
    ld a,1
    out ($31),a
    ld a,250
    out ($32),a
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
    in a,($35)
    ld (ix+2),a
    in a,($32)
    ld (ix+4),a
    xor a
    ld (ix+6),a
    ld bc,$FFFF
mode3_wait:
    in a,($35)
    cp $41
    jr c,mode3_done
    in a,($04)
    bit 5,a
    jr z,mode3_no_event
    inc (ix+6)
    ld a,1
    out ($31),a
mode3_no_event:
    dec bc
    ld a,b
    or c
    jr nz,mode3_wait
    scf
    ret
mode3_done:
    ld (ix+3),a
    in a,($31)
    ld (ix+7),a
    in a,($04)
    ld (ix+8),a
    bit 5,a
    jr z,mode3_boundary_clear
    inc (ix+6)
    ld a,1
    out ($31),a
mode3_boundary_clear:
    in a,($32)
    ld (ix+5),a
    call stop_timers
    ld de,9
    add ix,de
    or a
    ret

; Counter zero runs against 31 ticks of source 0x46. Source 0x45 advances 16
; times faster, producing about 496 target ticks before the reference expires.
measure_counter_zero:
    call stop_timers
    ld a,$45
    out ($30),a
    xor a
    out ($31),a
    out ($32),a
    ld a,$46
    out ($33),a
    xor a
    out ($34),a
    ld a,31
    out ($35),a
    in a,($32)
    ld (ix+0),a
    in a,($35)
    ld (ix+1),a
    call wait_timer2_completion
    ret c
    in a,($35)
    ld (ix+2),a
    in a,($32)
    ld (ix+3),a
    in a,($31)
    ld (ix+4),a
    in a,($04)
    ld (ix+5),a
    call stop_timers
    or a
    ret

; Capture status after one ordinary loop expiry, then after the following
; unacknowledged 256-count overflow period.
measure_expiry_status:
    call stop_timers
    ld a,$45
    out ($30),a
    ld a,1
    out ($31),a
    ld a,4
    out ($32),a
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,8
    out ($35),a
    call wait_timer2_completion
    ret c
    in a,($32)
    ld (ix+0),a
    in a,($31)
    ld (ix+1),a
    in a,($04)
    ld (ix+2),a

    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
    call wait_timer2_completion
    ret c
    in a,($32)
    ld (ix+3),a
    in a,($31)
    ld (ix+4),a
    in a,($04)
    ld (ix+5),a
    call stop_timers
    or a
    ret

wait_timer2_completion:
    ld bc,$FFFF
timer2_completion_wait:
    in a,($35)
    in a,($04)
    bit 6,a
    jr nz,timer2_completion_done
    dec bc
    ld a,b
    or c
    jr nz,timer2_completion_wait
    scf
    ret
timer2_completion_done:
    or a
    ret

stop_timers:
    xor a
    out ($30),a
    out ($31),a
    out ($33),a
    out ($34),a
    ret

restore_state:
    call stop_timers
    ld a,(payload_pre_port32)
    out ($32),a
    ld a,(payload_pre_port35)
    out ($35),a
    ld a,(payload_pre_port2f)
    out ($2F),a
    ld a,(payload_pre_port20)
    out ($20),a
    ret

appvar_name:
    .db AppVarObj,"HWTMR001"

frame:
    .db "HWP1",1,12
    .dw payload_end-payload
frame_asic:
    .db 0
frame_status:
    .db 0
payload:
payload_pre_port02:
    .db 0
payload_pre_port03:
    .db 0
payload_pre_port04:
    .db 0
payload_pre_port15:
    .db 0
payload_pre_port20:
    .db 0
payload_pre_port2d:
    .db 0
payload_pre_port2f:
    .db 0
payload_pre_port30:
    .db 0
payload_pre_port31:
    .db 0
payload_pre_port32:
    .db 0
payload_pre_port33:
    .db 0
payload_pre_port34:
    .db 0
payload_pre_port35:
    .db 0
payload_outcome:
    .db 0
payload_crystal:
    .fill 16,0
payload_mode3:
    .fill 36,0
payload_zero:
    .fill 6,0
payload_expiry:
    .fill 6,0
payload_post_port02:
    .db 0
payload_post_port03:
    .db 0
payload_post_port04:
    .db 0
payload_post_port15:
    .db 0
payload_post_port20:
    .db 0
payload_post_port2d:
    .db 0
payload_post_port2f:
    .db 0
payload_post_port30:
    .db 0
payload_post_port31:
    .db 0
payload_post_port32:
    .db 0
payload_post_port33:
    .db 0
payload_post_port34:
    .db 0
payload_post_port35:
    .db 0
payload_end:
frame_end:
