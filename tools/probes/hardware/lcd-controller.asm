; Restoring LCD hidden-column and ready-trigger probe.
; Result AppVar: HWPLCD01, probe ID 15, payload 43 bytes.
; No display, power, test, contrast, or Z-address command is issued by the
; measurement. The final OS result display occurs only after restoration.

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
    ld a,(payload_pre_cury)
    cp $20
    jp c,abort_bad_os_pointer
    cp $40
    jp nc,abort_bad_os_pointer
    ld a,(payload_pre_curxrow)
    cp $80
    jp c,abort_bad_os_pointer
    cp $C0
    jp nc,abort_bad_os_pointer

    call backup_cells
    ld a,(lcd_timeout)
    or a
    jp nz,abort_ready_timeout

    ; Measure whether command, data-read, and data-write accesses restart the
    ; ASIC port-0x02 ready interval. All loops saturate at 0xFFFF.
    ld a,$80
    out ($10),a
    call measure_ready_count
    ld (payload_ready_command),hl
    call long_lcd_delay

    ld a,$80
    call safe_lcd_command
    ld a,$20
    call safe_lcd_command
    in a,($11)
    call measure_ready_count
    ld (payload_ready_read),hl
    call long_lcd_delay

    ld a,$80
    call safe_lcd_command
    ld a,$20
    call safe_lcd_command
    ld a,(cell_backup+0)
    out ($11),a
    in a,($02)
    ld (payload_immediate_port02),a
    in a,($10)
    ld (payload_immediate_status10),a
    call measure_ready_count
    ld (payload_ready_write),hl
    call long_lcd_delay

    ; Three column-increment writes starting at row 0, column 14 distinguish
    ; a 16-column row, 15-column wrap, and MAME's 15-byte linear spill.
    ld a,$01
    call safe_lcd_command
    ld a,$07
    call safe_lcd_command
    ld a,$80
    call safe_lcd_command
    ld a,$2E
    call safe_lcd_command
    ld a,$A4
    call safe_lcd_data_write
    ld a,$A5
    call safe_lcd_data_write
    ld a,$A6
    call safe_lcd_data_write

    ld hl,probe_cells
    ld de,payload_observed_cells
    ld b,7
observe_cells_loop:
    push bc
    ld b,(hl)
    inc hl
    ld c,(hl)
    inc hl
    push hl
    call read_lcd_cell
    ld (de),a
    inc de
    pop hl
    pop bc
    djnz observe_cells_loop

    ; Read-only out-of-range commands remain at row 0, avoiding MAME's known
    ; row-63 out-of-bounds case.
    ld b,$80
    ld c,$30
    call read_lcd_cell
    ld (payload_direct_column16),a
    ld b,$80
    ld c,$3F
    call read_lcd_cell
    ld (payload_direct_column31),a

    call restore_cells
    jr c,restore_failed
    ld a,1
    ld (payload_restore_ok),a
    jr normalize_controller

restore_failed:
    ld a,6
    ld (payload_outcome),a

normalize_controller:
    ld a,$01
    call safe_lcd_command
    ld a,$05
    call safe_lcd_command
    ld a,(payload_pre_curxrow)
    call safe_lcd_command
    ld a,(payload_pre_cury)
    call safe_lcd_command
    jr capture_post

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
set_abort:
    ld (payload_outcome),a

capture_post:
    ld a,(lcd_timeout)
    or a
    jr z,capture_post_ports
    ld a,(payload_outcome)
    or a
    jr nz,capture_post_ports
    ld a,4
    ld (payload_outcome),a
capture_post_ports:
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

; Read and save the seven cells that can be affected by the increment case or
; by MAME's known row-stride aliases.
backup_cells:
    ld hl,probe_cells
    ld de,cell_backup
    ld b,7
backup_cells_loop:
    push bc
    ld b,(hl)
    inc hl
    ld c,(hl)
    inc hl
    push hl
    call read_lcd_cell
    ld (de),a
    inc de
    pop hl
    pop bc
    djnz backup_cells_loop
    or a
    ret

restore_cells:
    ld hl,probe_cells
    ld de,cell_backup
    ld b,7
restore_cells_loop:
    push bc
    ld b,(hl)
    inc hl
    ld c,(hl)
    inc hl
    ld a,(de)
    inc de
    push hl
    push de
    call write_lcd_cell
    pop de
    pop hl
    pop bc
    djnz restore_cells_loop

    ld hl,probe_cells
    ld de,cell_backup
    ld b,7
verify_cells_loop:
    push bc
    ld b,(hl)
    inc hl
    ld c,(hl)
    inc hl
    push hl
    call read_lcd_cell
    ld c,a
    ld a,(de)
    inc de
    cp c
    pop hl
    pop bc
    scf
    ret nz
    djnz verify_cells_loop
    or a
    ret

; B = row command, C = column command. Returns the addressed byte in A after
; the controller's required dummy read.
read_lcd_cell:
    ld a,$01
    call safe_lcd_command
    ld a,b
    call safe_lcd_command
    ld a,c
    call safe_lcd_command
    call safe_lcd_data_read
    call safe_lcd_data_read
    ret

; B = row command, C = column command, A = value.
write_lcd_cell:
    push af
    ld a,$01
    call safe_lcd_command
    ld a,b
    call safe_lcd_command
    ld a,c
    call safe_lcd_command
    pop af
    jp safe_lcd_data_write

safe_lcd_command:
    push af
    call wait_lcd_ready
    call long_lcd_delay
    pop af
    out ($10),a
    ret

safe_lcd_data_read:
    call wait_lcd_ready
    call long_lcd_delay
    in a,($11)
    ret

safe_lcd_data_write:
    push af
    call wait_lcd_ready
    call long_lcd_delay
    pop af
    out ($11),a
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
    ld a,1
    ld (lcd_timeout),a
    pop bc
    scf
    ret
lcd_ready:
    pop bc
    or a
    ret

; This fixed delay exceeds the documented T6K04 busy maximum at the fastest
; calculator clock. It keeps restoration independent of status-bit polling.
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

probe_cells:
    .db $80,$20,$80,$21,$80,$2E,$80,$2F
    .db $81,$20,$81,$21,$82,$21
cell_backup:
    .fill 7,0
lcd_timeout:
    .db 0

display_label:
    .db "HWPLCD CODE ",0
#include "display.inc"

appvar_name:
    .db AppVarObj,"HWPLCD01"

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
payload_immediate_port02: .db 0
payload_immediate_status10: .db 0
payload_observed_cells: .fill 7,0
payload_direct_column16: .db 0
payload_direct_column31: .db 0
payload_restore_ok: .db 0
payload_post_port02: .db 0
payload_post_port04: .db 0
payload_post_status10: .db 0
payload_post_port20: .db 0
payload_post_waits: .fill 7,0
payload_end:
frame_end:
