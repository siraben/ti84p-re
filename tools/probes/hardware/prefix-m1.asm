; Physical RAM-M1 timing matrix for ordinary and prefixed instruction shapes.
; Result AppVar: HWPFX001, probe ID 11, payload 63 bytes.
; Aborts before mutation unless programmable timer 2 is idle and RAM waits gate.

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
    ld (payload_pre_port02),a
    in a,($03)
    ld (payload_pre_port03),a
    in a,($04)
    ld (payload_pre_port04),a
    in a,($20)
    ld (payload_pre_port20),a
    in a,($29)
    ld (payload_pre_port29),a
    in a,($2A)
    ld (payload_pre_port2a),a
    in a,($2B)
    ld (payload_pre_port2b),a
    in a,($2C)
    ld (payload_pre_port2c),a
    in a,($2E)
    ld (payload_pre_port2e),a
    in a,($2F)
    ld (payload_pre_port2f),a
    in a,($33)
    ld (payload_pre_port33),a
    in a,($34)
    ld (payload_pre_port34),a
    in a,($35)
    ld (payload_pre_port35),a

    xor a
    ld (payload_outcome),a

    ; Timer 2 must be idle so the probe can restore its exact initial state.
    ld a,(payload_pre_port33)
    or a
    jr nz,abort_timer_source
    ld a,(payload_pre_port34)
    or a
    jr nz,abort_timer_mode

    ; Every speed-selectable delay register must leave the RAM group enabled.
    ; This avoids changing ports 0x29 through 0x2C during measurement.
    ld hl,payload_pre_port29
    ld b,4
check_ram_gates:
    ld a,(hl)
    bit 1,a
    jr z,abort_ram_gate
    inc hl
    djnz check_ram_gates

    ld ix,payload_measurements

    xor a
    call measure_unprefixed
    ld a,$10
    call measure_unprefixed

    xor a
    call measure_cb
    ld a,$10
    call measure_cb

    xor a
    call measure_ed
    ld a,$10
    call measure_ed

    xor a
    call measure_dd
    ld a,$10
    call measure_dd

    xor a
    call measure_dd_dd
    ld a,$10
    call measure_dd_dd

    xor a
    call measure_dd_cb
    ld a,$10
    call measure_dd_cb

    ; Each measurement stopped and acknowledged timer 2. Restore its idle
    ; counter byte and the complete entry port-0x2E value.
    ld a,(payload_pre_port35)
    out ($35),a
    ld a,(payload_pre_port2e)
    out ($2E),a
    jr capture_post

abort_timer_source:
    ld a,1
    jr set_outcome
abort_timer_mode:
    ld a,2
    jr set_outcome
abort_ram_gate:
    ld a,3
set_outcome:
    ld (payload_outcome),a

capture_post:
    in a,($02)
    ld (payload_post_port02),a
    in a,($03)
    ld (payload_post_port03),a
    in a,($04)
    ld (payload_post_port04),a
    in a,($20)
    ld (payload_post_port20),a
    in a,($29)
    ld (payload_post_port29),a
    in a,($2A)
    ld (payload_post_port2a),a
    in a,($2B)
    ld (payload_post_port2b),a
    in a,($2C)
    ld (payload_post_port2c),a
    in a,($2E)
    ld (payload_post_port2e),a
    in a,($2F)
    ld (payload_post_port2f),a
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
    ld bc,frame_end-frame
    ld hl,display_label
    call display_created_probe_code
    ret

; Every timed loop has 12,288 iterations. DEC BC, LD A,B, OR C, and JR NZ
; contribute four common M1 fetches per iteration. The final IN opcode adds one.

measure_unprefixed:
    out ($2E),a
    ld bc,$3000
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
unprefixed_loop:
    .db $00                   ; NOP: one M1 fetch
    dec bc
    ld a,b
    or c
    jr nz,unprefixed_loop
    in a,($35)
    jp store_measurement

measure_cb:
    out ($2E),a
    ld bc,$3000
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
cb_loop:
    .db $CB,$42               ; BIT 0,D: two M1 fetches
    dec bc
    ld a,b
    or c
    jr nz,cb_loop
    in a,($35)
    jp store_measurement

measure_ed:
    out ($2E),a
    ld bc,$3000
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
ed_loop:
    .db $ED,$44               ; NEG: two M1 fetches
    dec bc
    ld a,b
    or c
    jr nz,ed_loop
    in a,($35)
    jp store_measurement

measure_dd:
    out ($2E),a
    ld bc,$3000
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
dd_loop:
    .db $DD,$7C               ; LD A,IXH: two M1 fetches
    dec bc
    ld a,b
    or c
    jr nz,dd_loop
    in a,($35)
    jp store_measurement

measure_dd_dd:
    out ($2E),a
    ld bc,$3000
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
dd_dd_loop:
    .db $DD,$DD,$7C           ; repeated DD plus LD A,IXH: three M1 fetches
    dec bc
    ld a,b
    or c
    jr nz,dd_dd_loop
    in a,($35)
    jp store_measurement

measure_dd_cb:
    out ($2E),a
    ld bc,$3000
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
dd_cb_loop:
    ; Real Z80 M1 signaling covers DD and CB. The displacement and final
    ; opcode are ordinary reads. TilEm follows that split; Wabbitemu applies
    ; its opcode wait to the final byte as well, despite compensating R.
    .db $DD,$CB,$00,$46       ; BIT 0,(IX+0)
    dec bc
    ld a,b
    or c
    jr nz,dd_cb_loop
    in a,($35)
    jp store_measurement

store_measurement:
    ld (ix+0),a
    in a,($34)
    ld (ix+1),a
    in a,($04)
    ld (ix+2),a
    inc ix
    inc ix
    inc ix
    xor a
    out ($33),a
    out ($34),a
    ld a,(payload_pre_port2e)
    out ($2E),a
    ret

display_label:
    .db "HWPFX CODE ",0
#include "display.inc"

appvar_name:
    .db AppVarObj,"HWPFX001"

frame:
    .db "HWP1",1,11
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
payload_pre_port20:
    .db 0
payload_pre_port29:
    .db 0
payload_pre_port2a:
    .db 0
payload_pre_port2b:
    .db 0
payload_pre_port2c:
    .db 0
payload_pre_port2e:
    .db 0
payload_pre_port2f:
    .db 0
payload_pre_port33:
    .db 0
payload_pre_port34:
    .db 0
payload_pre_port35:
    .db 0
payload_outcome:
    .db 0
payload_measurements:
    .fill 36,0
payload_post_port02:
    .db 0
payload_post_port03:
    .db 0
payload_post_port04:
    .db 0
payload_post_port20:
    .db 0
payload_post_port29:
    .db 0
payload_post_port2a:
    .db 0
payload_post_port2b:
    .db 0
payload_post_port2c:
    .db 0
payload_post_port2e:
    .db 0
payload_post_port2f:
    .db 0
payload_post_port33:
    .db 0
payload_post_port34:
    .db 0
payload_post_port35:
    .db 0
payload_end:
frame_end:
