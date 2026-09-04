; Recovery-gated hidden-column LCD experiment.
; Result AppVar: HWPLAB01, probe ID 17.
;
; This source is not part of the default hardware-probe build. The laboratory
; builder must define LCD_HIDDEN_LAB_ACK and EXPECTED_ASIC. The worker saves all
; 768 visible LCD bytes before the first hidden-column write, records direct and
; auto-increment observations, restores the visible image plus the four hidden
; bytes, verifies the visible image, restores the entry read latch, movement
; mode, and OS-tracked pointer, and only then displays the frame CRC.

#ifndef LCD_HIDDEN_LAB_ACK
#error "LCD_HIDDEN_LAB_ACK must be supplied by the laboratory builder"
#endif
#ifndef EXPECTED_ASIC
#error "EXPECTED_ASIC must be supplied by the laboratory builder"
#endif

.org $9D95
    jp start
#include "common.inc"

curY                    .equ $844F
curXRow                 .equ $8451

ACK_VALUE               .equ $4C43
OUTCOME_PENDING         .equ 0
OUTCOME_COMPLETE        .equ 1
OUTCOME_BAD_ACK         .equ 2
OUTCOME_BAD_ASIC        .equ 3
OUTCOME_BAD_OS          .equ 4
OUTCOME_CONTROLLER_RESET .equ 5
OUTCOME_NOT_EIGHT_BIT   .equ 6
OUTCOME_BAD_POINTER     .equ 7
OUTCOME_READY_TIMEOUT   .equ 8
OUTCOME_RESTORE_FAILED  .equ 9

start:
    ld a,i
    push af
    di

    in a,($15)
    ld (frame_asic),a
    in a,($02)
    ld (frame_status),a
    ld a,(curY)
    ld (payload_entry_cury),a
    ld a,(curXRow)
    ld (payload_entry_curxrow),a

    ld hl,LCD_HIDDEN_LAB_ACK
    ld de,ACK_VALUE
    or a
    sbc hl,de
    jr z,check_asic
    ld a,OUTCOME_BAD_ACK
    ld (payload_outcome),a
    jr create_result

check_asic:
    ld a,(frame_asic)
    cp EXPECTED_ASIC
    jr z,check_os
    ld a,OUTCOME_BAD_ASIC
    ld (payload_outcome),a
    jr create_result

check_os:
    ld hl,$0BD9
    ld de,os_signature
    ld b,8
check_os_loop:
    ld a,(de)
    cp (hl)
    jr nz,bad_os
    inc de
    inc hl
    djnz check_os_loop
    jr check_pointer
bad_os:
    ld a,OUTCOME_BAD_OS
    ld (payload_outcome),a
    jr create_result

check_pointer:
    ld a,(payload_entry_cury)
    cp $20
    jr c,bad_pointer
    cp $2C
    jr nc,bad_pointer
    ld a,(payload_entry_curxrow)
    cp $80
    jr c,bad_pointer
    cp $C0
    jr nc,bad_pointer

    in a,($10)
    ld (payload_entry_status),a
    and $03
    add a,$04
    ld (payload_entry_movement),a

check_controller:
    ld a,(payload_entry_status)
    bit 4,a
    jr z,check_word_length
    ld a,OUTCOME_CONTROLLER_RESET
    ld (payload_outcome),a
    jr create_result
check_word_length:
    bit 6,a
    jr nz,save_movement
    ld a,OUTCOME_NOT_EIGHT_BIT
    ld (payload_outcome),a
    jr create_result
save_movement:
    ld a,1
    ld (lcd_touched),a
    jr create_result
bad_pointer:
    ld a,OUTCOME_BAD_POINTER
    ld (payload_outcome),a

create_result:
    ld ix,appvar_name
    ld hl,frame
    ld bc,frame_end-frame
    call create_probe_appvar
    ex de,hl
    ld de,-(frame_end-frame)
    add hl,de
    ld (result_frame_ptr),hl

    ld a,(payload_outcome)
    or a
    jp nz,finish

    ; Command 4 decrements the row after each accepted data transfer. It lets
    ; each column stream cover all 64 rows from B8h through B9h with wrap.
    ld a,$04
    call safe_lcd_command
    jp c,measurement_timeout

    ; Preserve the controller's read latch. The addressed read that follows
    ; reloads it, so every screen capture readdresses independently.
    ld a,$B8
    call safe_lcd_command
    ld a,$20
    call safe_lcd_command
    call safe_lcd_data_read
    ld (payload_entry_latch),a
    call safe_lcd_data_read
    jp c,measurement_timeout
    ld (payload_entry_cell),a
    ld a,1
    ld (entry_cell_valid),a

    ld hl,payload_visible_before
    call capture_visible
    jp c,measurement_timeout
    ld hl,payload_hidden_before
    call capture_hidden
    jp c,measurement_timeout
    ld a,1
    call sync_stage

    ; Direct writes to the four columns outside the OS-visible 20h-2Bh range.
    ld hl,direct_patterns
    call write_hidden
    jp c,measurement_timeout
    ld hl,payload_hidden_direct
    call capture_hidden
    jp c,measurement_timeout
    ld hl,payload_visible_direct
    call capture_visible
    jp c,measurement_timeout
    ld hl,payload_visible_before
    ld de,payload_visible_direct
    call compare_visible_buffers
    ld (payload_direct_visible_changes),ix
    ld a,2
    call sync_stage

    ; Restore before the auto-increment case so its effects are independent.
    call restore_all_cells
    jp c,measurement_timeout
    ld a,3
    call sync_stage

    ; Command 7 increments the byte column. Starting at column 14 makes the
    ; second byte discriminate a 16-column cell, a wrap, or a row spill.
    ld a,$07
    call safe_lcd_command
    ld a,$B8
    call safe_lcd_command
    ld a,$2E
    call safe_lcd_command
    ld a,$A1
    call safe_lcd_data_write
    ld a,$A2
    call safe_lcd_data_write
    jp c,measurement_timeout

    ld a,$04
    call safe_lcd_command
    ld hl,payload_hidden_wrap
    call capture_hidden
    jp c,measurement_timeout
    ld hl,payload_visible_wrap
    call capture_visible
    jp c,measurement_timeout
    ld hl,payload_visible_before
    ld de,payload_visible_wrap
    call compare_visible_buffers
    ld (payload_wrap_visible_changes),ix
    ld a,4
    call sync_stage

    call restore_all_cells
    jp c,measurement_timeout
    call verify_all_cells
    jp c,measurement_timeout
    ld a,5
    call sync_stage

    ld a,(payload_visible_restore_mismatches)
    ld c,a
    ld a,(payload_visible_restore_mismatches+1)
    or c
    ld c,a
    ld a,(payload_hidden_restore_mismatches)
    or c
    jr nz,restore_failed
    ld a,OUTCOME_COMPLETE
    ld (payload_outcome),a
    jr restore_controller_state

restore_failed:
    ld a,OUTCOME_RESTORE_FAILED
    ld (payload_outcome),a
    jr restore_controller_state

measurement_timeout:
    ld a,OUTCOME_READY_TIMEOUT
    ld (payload_outcome),a
    ; A timed-out controller may still accept accesses after a conservative
    ; delay. Attempt the full restore without consulting ASIC-ready again.
    ld a,(payload_stage)
    or a
    call nz,force_restore_all_cells

restore_controller_state:
    ld a,(entry_cell_valid)
    or a
    call nz,restore_entry_latch

finish:
    ld a,(lcd_touched)
    or a
    jr z,finish_sync
    ld a,(payload_entry_movement)
    call force_lcd_command
    ld a,(payload_entry_curxrow)
    call force_lcd_command
    ld a,(payload_entry_cury)
    call force_lcd_command
finish_sync:
    call sync_frame
    pop af
    jp po,interrupts_restored
    ei
interrupts_restored:
    ld ix,(result_frame_ptr)
    ld bc,frame_end-frame
    ld hl,display_label
    call display_probe_code
    ret

; Store A as the pending stage and copy the complete local frame into the
; already-created AppVar. A reset therefore leaves both an outcome and the last
; completed stage, without relying on the display.
sync_stage:
    ld (payload_stage),a
sync_frame:
    push af
    push bc
    push de
    push hl
    ld hl,frame
    ld de,(result_frame_ptr)
    ld bc,frame_end-frame
    ldir
    pop hl
    pop de
    pop bc
    pop af
    ret

; HL receives 768 bytes ordered by column 20h-2Bh and row B8h downward.
capture_visible:
    ld d,$20
    ld b,12
capture_visible_column:
    ld a,$B8
    call safe_lcd_command
    ret c
    ld a,d
    call safe_lcd_command
    ret c
    call safe_lcd_data_read
    ret c
    ld c,64
capture_visible_row:
    call safe_lcd_data_read
    ret c
    ld (hl),a
    inc hl
    dec c
    jr nz,capture_visible_row
    inc d
    djnz capture_visible_column
    or a
    ret

; HL supplies 768 bytes in the capture_visible order.
restore_visible:
    ld d,$20
    ld b,12
restore_visible_column:
    ld a,$B8
    call safe_lcd_command
    ret c
    ld a,d
    call safe_lcd_command
    ret c
    ld c,64
restore_visible_row:
    ld a,(hl)
    call safe_lcd_data_write
    ret c
    inc hl
    dec c
    jr nz,restore_visible_row
    inc d
    djnz restore_visible_column
    or a
    ret

; HL receives or supplies columns 2Ch-2Fh at row B8h.
capture_hidden:
    ld d,$2C
    ld b,4
capture_hidden_loop:
    ld a,$B8
    call safe_lcd_command
    ret c
    ld a,d
    call safe_lcd_command
    ret c
    call safe_lcd_data_read
    ret c
    call safe_lcd_data_read
    ret c
    ld (hl),a
    inc hl
    inc d
    djnz capture_hidden_loop
    or a
    ret

write_hidden:
    ld d,$2C
    ld b,4
write_hidden_loop:
    ld a,$B8
    call safe_lcd_command
    ret c
    ld a,d
    call safe_lcd_command
    ret c
    ld a,(hl)
    call safe_lcd_data_write
    ret c
    inc hl
    inc d
    djnz write_hidden_loop
    or a
    ret

restore_all_cells:
    ld a,$04
    call safe_lcd_command
    ret c
    ld hl,payload_visible_before
    call restore_visible
    ret c
    ld hl,payload_hidden_before
    jp write_hidden

; Compare 768 bytes at HL and DE. Return the mismatch count in IX.
compare_visible_buffers:
    ld bc,768
    ld ix,0
compare_visible_loop:
    ld a,(de)
    cp (hl)
    jr z,compare_visible_same
    inc ix
compare_visible_same:
    inc de
    inc hl
    dec bc
    ld a,b
    or c
    jr nz,compare_visible_loop
    ret

verify_all_cells:
    ld hl,payload_visible_before
    call verify_visible
    ret c
    ld (payload_visible_restore_mismatches),ix
    ld hl,payload_hidden_after_restore
    call capture_hidden
    ret c
    ld hl,payload_hidden_before
    ld de,payload_hidden_after_restore
    ld b,4
    xor a
verify_hidden_loop:
    ld a,(de)
    cp (hl)
    jr z,verify_hidden_same
    ld a,(payload_hidden_restore_mismatches)
    inc a
    ld (payload_hidden_restore_mismatches),a
verify_hidden_same:
    inc hl
    inc de
    djnz verify_hidden_loop
    or a
    ret

; Compare one streamed visible capture against HL without retaining a fourth
; 768-byte array. Return the mismatch count in IX.
verify_visible:
    ld ix,0
    ld d,$20
    ld b,12
verify_visible_column:
    ld a,$B8
    call safe_lcd_command
    ret c
    ld a,d
    call safe_lcd_command
    ret c
    call safe_lcd_data_read
    ret c
    ld c,64
verify_visible_row:
    call safe_lcd_data_read
    ret c
    cp (hl)
    jr z,verify_visible_same
    inc ix
verify_visible_same:
    inc hl
    dec c
    jr nz,verify_visible_row
    inc d
    djnz verify_visible_column
    or a
    ret

restore_entry_latch:
    ; Load the saved latch through visible cell B8h/20h, then rewrite that
    ; cell's original byte. Writes do not replace the controller read latch.
    ld a,$04
    call force_lcd_command
    ld a,$B8
    call force_lcd_command
    ld a,$20
    call force_lcd_command
    ld a,(payload_entry_latch)
    call force_lcd_data_write
    ld a,$B8
    call force_lcd_command
    ld a,$20
    call force_lcd_command
    call force_lcd_data_read
    ld a,$B8
    call force_lcd_command
    ld a,$20
    call force_lcd_command
    ld a,(payload_entry_cell)
    jp force_lcd_data_write

safe_lcd_command:
    push af
    call wait_lcd_ready
    jr c,safe_lcd_command_timeout
    call long_lcd_delay
    pop af
    out ($10),a
    or a
    ret
safe_lcd_command_timeout:
    pop af
    scf
    ret

safe_lcd_data_read:
    call wait_lcd_ready
    ret c
    call long_lcd_delay
    in a,($11)
    or a
    ret

safe_lcd_data_write:
    push af
    call wait_lcd_ready
    jr c,safe_lcd_data_write_timeout
    call long_lcd_delay
    pop af
    out ($11),a
    or a
    ret
safe_lcd_data_write_timeout:
    pop af
    scf
    ret

wait_lcd_ready:
    push bc
    ld bc,$FFFF
wait_lcd_ready_loop:
    in a,($02)
    bit 1,a
    jr nz,lcd_ready
    dec bc
    ld a,b
    or c
    jr nz,wait_lcd_ready_loop
    pop bc
    scf
    ret
lcd_ready:
    pop bc
    or a
    ret

long_lcd_delay:
    push bc
    ld bc,$0800
long_lcd_delay_loop:
    dec bc
    ld a,b
    or c
    jr nz,long_lcd_delay_loop
    pop bc
    ret

force_lcd_command:
    push af
    call long_lcd_delay
    pop af
    out ($10),a
    ret

force_lcd_data_read:
    call long_lcd_delay
    in a,($11)
    ret

force_lcd_data_write:
    push af
    call long_lcd_delay
    pop af
    out ($11),a
    ret

; Timeout cleanup uses the same finite 768-byte visible sweep, with fixed
; delays instead of the failed ASIC-ready predicate.
force_restore_all_cells:
    ld a,$04
    call force_lcd_command
    ld hl,payload_visible_before
    ld d,$20
    ld b,12
force_restore_visible_column:
    ld a,$B8
    call force_lcd_command
    ld a,d
    call force_lcd_command
    ld c,64
force_restore_visible_row:
    ld a,(hl)
    call force_lcd_data_write
    inc hl
    dec c
    jr nz,force_restore_visible_row
    inc d
    djnz force_restore_visible_column
    ld hl,payload_hidden_before
    ld d,$2C
    ld b,4
force_restore_hidden_loop:
    ld a,$B8
    call force_lcd_command
    ld a,d
    call force_lcd_command
    ld a,(hl)
    call force_lcd_data_write
    inc hl
    inc d
    djnz force_restore_hidden_loop
    ret

os_signature:
    .db $3E,$C0,$D3,$00,$31,$F7,$FF,$CD
direct_patterns:
    .db $A5,$5A,$C3,$3C

result_frame_ptr:
    .dw 0
lcd_touched:
    .db 0
entry_cell_valid:
    .db 0
display_label:
    .db "HWPLAB CODE ",0
#include "display.inc"

appvar_name:
    .db AppVarObj,"HWPLAB01"

frame:
    .db "HWP1",1,17
    .dw payload_end-payload
frame_asic: .db 0
frame_status: .db 0
payload:
payload_outcome: .db OUTCOME_PENDING
payload_stage: .db 0
payload_entry_status: .db 0
payload_entry_movement: .db 0
payload_entry_cury: .db 0
payload_entry_curxrow: .db 0
payload_entry_latch: .db 0
payload_entry_cell: .db 0
payload_direct_visible_changes: .dw 0
payload_wrap_visible_changes: .dw 0
payload_visible_restore_mismatches: .dw 0
payload_hidden_restore_mismatches: .db 0
payload_hidden_before: .fill 4,0
payload_hidden_direct: .fill 4,0
payload_hidden_wrap: .fill 4,0
payload_hidden_after_restore: .fill 4,0
payload_visible_before: .fill 768,0
payload_visible_direct: .fill 768,0
payload_visible_wrap: .fill 768,0
payload_end:
frame_end:
