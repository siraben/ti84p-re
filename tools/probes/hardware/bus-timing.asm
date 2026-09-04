; Six-class physical bus-wait timing probe using idle programmable timer 2.
; Result AppVar: HWBUS001, probe ID 10, payload 63 bytes.
; OS 2.55MP only; aborts before mutation unless timing gates and timer are idle.

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

    ; Status bit 2 changes when the protected Flash gate is open. The write
    ; case uses only 0xF0 reset commands, but an unlocked entry still aborts.
    ld a,(payload_pre_port02)
    bit 2,a
    jr nz,abort_flash_unlocked

    ; Every OS timing register must enable its corresponding Flash and RAM
    ; gate. This avoids changing ports 0x29 through 0x2C during measurement.
    ld hl,payload_pre_port29
    ld b,4
check_delay_gates:
    ld a,(hl)
    and 3
    cp 3
    jr nz,abort_delay_gate
    inc hl
    djnz check_delay_gates

    ; The Flash-M1 case calls this five-instruction fixed-page helper.
    ld hl,$0CE6
    ld de,helper_signature
    ld b,5
check_helper:
    ld a,(de)
    cp (hl)
    jr nz,abort_helper
    inc de
    inc hl
    djnz check_helper

    ld ix,payload_measurements

    xor a
    call measure_flash_opcode
    ld a,$01
    call measure_flash_opcode

    xor a
    call measure_flash_read
    ld a,$02
    call measure_flash_read

    xor a
    call measure_flash_write
    ld a,$04
    call measure_flash_write

    xor a
    call measure_ram_opcode
    ld a,$10
    call measure_ram_opcode

    xor a
    call measure_ram_read
    ld a,$20
    call measure_ram_read

    xor a
    call measure_ram_write
    ld a,$40
    call measure_ram_write

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
abort_flash_unlocked:
    ld a,3
    jr set_outcome
abort_delay_gate:
    ld a,4
    jr set_outcome
abort_helper:
    ld a,5
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

; A is the port-0x2E mask. The 4,096 calls execute five opcodes each from
; fixed Flash at 00:0CE6. The surrounding loop executes from RAM.
measure_flash_opcode:
    out ($2E),a
    ld bc,$1000
    ld hl,scratch_byte
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
flash_opcode_loop:
    call $0CE6
    dec bc
    ld a,b
    or c
    jr nz,flash_opcode_loop
    in a,($35)
    jp store_measurement

; One fixed-page Flash data read per iteration.
measure_flash_read:
    out ($2E),a
    ld bc,$4000
    ld hl,$0000
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
flash_read_loop:
    ld a,(hl)
    dec bc
    ld a,b
    or c
    jr nz,flash_read_loop
    in a,($35)
    jp store_measurement

; One locked 0xF0 Flash reset-command write per iteration. A forwarded write
; therefore resets read-array mode instead of forming a program sequence.
measure_flash_write:
    out ($2E),a
    ld bc,$4000
    ld hl,$0000
    ld d,$F0
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
flash_write_loop:
    ld a,d
    ld (hl),a
    dec bc
    ld a,b
    or c
    jr nz,flash_write_loop
    in a,($35)
    jp store_measurement

; Four RAM-resident loop opcodes per iteration. The counter-read opcode is
; the 65,537th wait-sensitive M1 fetch.
measure_ram_opcode:
    out ($2E),a
    ld bc,$4000
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
ram_opcode_loop:
    dec bc
    ld a,b
    or c
    jr nz,ram_opcode_loop
    in a,($35)
    jp store_measurement

; Each iteration performs one explicit RAM data read and fetches one JR
; operand. The counter IN contributes the final non-opcode operand read.
measure_ram_read:
    out ($2E),a
    ld bc,$4000
    ld hl,scratch_byte
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
ram_read_loop:
    ld a,(hl)
    dec bc
    ld a,b
    or c
    jr nz,ram_read_loop
    in a,($35)
    jp store_measurement

; Rewriting the scratch byte with its entry value makes every RAM write
; idempotent while preserving one wait-sensitive write per iteration.
measure_ram_write:
    out ($2E),a
    ld bc,$4000
    ld hl,scratch_byte
    ld d,(hl)
    ld a,$45
    out ($33),a
    xor a
    out ($34),a
    ld a,$FF
    out ($35),a
ram_write_loop:
    ld a,d
    ld (hl),a
    dec bc
    ld a,b
    or c
    jr nz,ram_write_loop
    in a,($35)

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

helper_signature:
    .db $F5,$23,$2B,$F1,$C9
scratch_byte:
    .db 0

display_label:
    .db "HWBUS CODE ",0
#include "display.inc"

appvar_name:
    .db AppVarObj,"HWBUS001"

frame:
    .db "HWP1",1,10
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
