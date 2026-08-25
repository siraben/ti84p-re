; Restoring visible-cell LCD status and ASIC-ready probe.
; Result AppVar: HWPLCD02, probe ID 15, payload 42 bytes.
; The default artifact never addresses a hidden byte column. It rewrites one
; visible cell with its original value, verifies it, and restores the movement
; mode plus the OS-tracked row and column before any display bcall.

.org $9D95
    jp start
#include "common.inc"

curY                .equ $844F
curXRow             .equ $8451

start:
    ld a,i
    push af
    di

    in a,($15)
    ld (frame_asic),a
    in a,($02)
    ld (frame_status),a
    ld (payload_pre_port02),a
    in a,($04)
    ld (payload_pre_port04),a
    in a,($10)
    ld (payload_pre_status10),a
    in a,($20)
    ld (payload_pre_port20),a
    in a,($29)
    ld (payload_pre_waits+0),a
    in a,($2A)
    ld (payload_pre_waits+1),a
    in a,($2B)
    ld (payload_pre_waits+2),a
    in a,($2C)
    ld (payload_pre_waits+3),a
    in a,($2D)
    ld (payload_pre_waits+4),a
    in a,($2E)
    ld (payload_pre_waits+5),a
    in a,($2F)
    ld (payload_pre_waits+6),a
    ld a,(curY)
    ld (payload_pre_cury),a
    ld a,(curXRow)
    ld (payload_pre_curxrow),a

    xor a
    ld (payload_outcome),a
    ld a,(payload_pre_status10)
    bit 4,a
    jp nz,abort_controller_reset
    bit 6,a
    jp z,abort_not_eight_bit
    and $03
    add a,$04
    ld (payload_pre_movement),a

    ; Only the twelve visible 8-bit byte columns are permitted.
    ld a,(payload_pre_cury)
    cp $20
    jp c,abort_bad_os_pointer
    cp $2C
    jp nc,abort_hidden_column
    ld a,(payload_pre_curxrow)
    cp $80
    jp c,abort_bad_os_pointer
    cp $C0
    jp nc,abort_bad_os_pointer
    ld a,1
    ld (pointer_safe),a

    call read_tracked_cell
    ld (payload_cell_before),a
    ld a,(lcd_timeout)
    or a
    jp nz,abort_ready_timeout

    ; A harmless row-address command is repeated so the ready counter and the
    ; controller-status sample do not time each other's port access.
    ld a,(payload_pre_curxrow)
    out ($10),a
    in a,($02)
    ld (payload_immediate_command_port02),a
    call measure_ready_count
    ld (payload_ready_command),hl
    call long_lcd_delay

    ld a,(payload_pre_curxrow)
    call safe_lcd_command
    in a,($10)
    ld (payload_immediate_command_status10),a
    call long_lcd_delay

    ; Readdress before each read. The first data read fills the controller's
    ; output latch; the second returns the selected visible cell.
    call address_tracked_cell
    call safe_lcd_data_read
    call safe_lcd_data_read
    in a,($02)
    ld (payload_immediate_read_port02),a
    call measure_ready_count
    ld (payload_ready_read),hl
    call long_lcd_delay

    call address_tracked_cell
    call safe_lcd_data_read
    call safe_lcd_data_read
    in a,($10)
    ld (payload_immediate_read_status10),a
    call long_lcd_delay

    ; Rewrite the selected visible cell with the byte that was read from it.
    call address_tracked_cell
    ld a,(payload_cell_before)
    call safe_lcd_data_write
    in a,($02)
    ld (payload_immediate_write_port02),a
    call measure_ready_count
    ld (payload_ready_write),hl
    call long_lcd_delay

    call address_tracked_cell
    ld a,(payload_cell_before)
    call safe_lcd_data_write
    in a,($10)
    ld (payload_immediate_write_status10),a
    call long_lcd_delay

    call read_tracked_cell
    ld (payload_cell_after_write),a
    ld a,(payload_cell_before)
    call write_tracked_cell
    call read_tracked_cell
    ld (payload_cell_after_restore),a
    ld c,a
    ld a,(payload_cell_before)
    cp c
    jr nz,restore_failed
    ld a,1
    ld (payload_restore_ok),a
    jr restore_controller_state

restore_failed:
    ld a,6
    ld (payload_outcome),a
    jr restore_controller_state

abort_controller_reset:
    ld a,1
    jr set_abort
abort_not_eight_bit:
    ld a,2
    jr set_abort
abort_bad_os_pointer:
    ld a,3
    jr set_abort
abort_ready_timeout:
    ld a,4
    jr set_abort
abort_hidden_column:
    ld a,5
set_abort:
    ld (payload_outcome),a

restore_controller_state:
    ld a,(lcd_timeout)
    or a
    jr z,restore_movement
    ld a,(payload_outcome)
    or a
    jr nz,restore_movement
    ld a,4
    ld (payload_outcome),a
restore_movement:
    ld a,(payload_pre_movement)
    cp $04
    jr c,restore_pointer
    cp $08
    jr nc,restore_pointer
    call safe_lcd_command
restore_pointer:
    ld a,(pointer_safe)
    or a
    jr z,capture_post
    ld a,(payload_pre_curxrow)
    call safe_lcd_command
    ld a,(payload_pre_cury)
    call safe_lcd_command
    call long_lcd_delay

capture_post:
    in a,($02)
    ld (payload_post_port02),a
    in a,($04)
    ld (payload_post_port04),a
    in a,($10)
    ld (payload_post_status10),a
    in a,($20)
    ld (payload_post_port20),a
    in a,($29)
    ld (payload_post_waits+0),a
    in a,($2A)
    ld (payload_post_waits+1),a
    in a,($2B)
    ld (payload_post_waits+2),a
    in a,($2C)
    ld (payload_post_waits+3),a
    in a,($2D)
    ld (payload_post_waits+4),a
    in a,($2E)
    ld (payload_post_waits+5),a
    in a,($2F)
    ld (payload_post_waits+6),a

    ; A status read can move the pointer on replacement controllers. Restore
    ; the tracked address once more after the post-status sample.
    ld a,(pointer_safe)
    or a
    jr z,finish_restore
    ld a,(payload_pre_curxrow)
    call safe_lcd_command
    ld a,(payload_pre_cury)
    call safe_lcd_command
    call long_lcd_delay

finish_restore:
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
    push hl
    pop ix
    ld bc,frame_end-frame
    ld hl,display_label
    call display_probe_code
    ret

address_tracked_cell:
    ld a,(payload_pre_curxrow)
    call safe_lcd_command
    ld a,(payload_pre_cury)
    jp safe_lcd_command

read_tracked_cell:
    call address_tracked_cell
    call safe_lcd_data_read
    jp safe_lcd_data_read

write_tracked_cell:
    push af
    call address_tracked_cell
    pop af
    jp safe_lcd_data_write

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
    ld a,(lcd_timeout)
    or a
    jr nz,lcd_ready_prior_timeout
    ld bc,$FFFF
wait_lcd_ready_loop:
    in a,($02)
    bit 1,a
    jr nz,lcd_ready
    dec bc
    ld a,b
    or c
    jr nz,wait_lcd_ready_loop
    ld a,1
    ld (lcd_timeout),a
    pop bc
    scf
    ret
lcd_ready_prior_timeout:
    pop bc
    scf
    ret
lcd_ready:
    pop bc
    or a
    ret

; This delay exceeds the documented T6K04 busy maximum at the fastest CPU
; speed. Restoration does not depend on controller-status polling.
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

; Return in HL the number of not-ready samples after one LCD access.
measure_ready_count:
    ld hl,0
measure_ready_loop:
    in a,($02)
    bit 1,a
    ret nz
    inc hl
    ld a,h
    and l
    cp $FF
    jr nz,measure_ready_loop
    ret

lcd_timeout:
    .db 0
pointer_safe:
    .db 0

display_label:
    .db "HWPLCD CODE ",0
#include "display.inc"

appvar_name:
    .db AppVarObj,"HWPLCD02"

frame:
    .db "HWP1",1,15
    .dw payload_end-payload
frame_asic: .db 0
frame_status: .db 0
payload:
payload_pre_port02: .db 0
payload_pre_port04: .db 0
payload_pre_status10: .db 0
payload_pre_port20: .db 0
payload_pre_waits: .fill 7,0
payload_pre_cury: .db 0
payload_pre_curxrow: .db 0
payload_outcome: .db 0
payload_ready_command: .dw 0
payload_ready_read: .dw 0
payload_ready_write: .dw 0
payload_immediate_command_port02: .db 0
payload_immediate_command_status10: .db 0
payload_immediate_read_port02: .db 0
payload_immediate_read_status10: .db 0
payload_immediate_write_port02: .db 0
payload_immediate_write_status10: .db 0
payload_cell_before: .db 0
payload_cell_after_write: .db 0
payload_cell_after_restore: .db 0
payload_pre_movement: .db 0
payload_restore_ok: .db 0
payload_post_port02: .db 0
payload_post_port04: .db 0
payload_post_status10: .db 0
payload_post_port20: .db 0
payload_post_waits: .fill 7,0
payload_end:
frame_end:
