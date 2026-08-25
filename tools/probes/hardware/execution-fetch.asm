; Read-only execution-protection fetch probe.
; The builder supplies the target kind, selector, scan range, and AppVar name.
; Probe ID 4, payload 16 bytes.

.org $9D95
    jp start
#include "common.inc"

OUTCOME_PENDING         .equ 0
OUTCOME_RETURNED        .equ 1
OUTCOME_NO_RET          .equ 2
OUTCOME_TARGET_CHANGED  .equ 3
OUTCOME_PAIRED_MAPPING  .equ 4

start:
    ld a,i
    push af
    di

    in a,($15)
    ld (frame_asic),a
    in a,($02)
    ld (frame_status),a
    in a,($04)
    ld (payload_port04),a
    in a,($06)
    ld (saved_port6),a
    ld (payload_port06),a
    in a,($21)
    ld (payload_port21),a
    in a,($22)
    ld (payload_port22),a
    in a,($23)
    ld (payload_port23),a
    in a,($25)
    ld (payload_port25),a
    in a,($26)
    ld (payload_port26),a

    ; In paired mapper mode port 06h remaps both bank A and the bank-B program.
    ; Refuse the case before a mapping write can unmap this probe.
    ld a,(payload_port04)
    and 1
    jr z,mapping_supported
    ld a,OUTCOME_PAIRED_MAPPING
    ld (payload_outcome),a
    jr create_result

mapping_supported:
    ld a,TARGET_SELECTOR
    out ($06),a
    ld hl,SCAN_START
    ld bc,SCAN_LENGTH
find_ret:
    ld a,(hl)
    cp $C9
    jr z,ret_found
    inc hl
    dec bc
    ld a,b
    or c
    jr nz,find_ret
    ld a,$FF
    ld (payload_target),a
    ld (payload_target+1),a
    ld a,OUTCOME_NO_RET
    ld (payload_outcome),a
    jr create_result

ret_found:
    ld (payload_target),hl

create_result:
    ld a,(saved_port6)
    out ($06),a
    ld ix,appvar_name
    ld hl,frame
    ld bc,frame_end-frame
    call create_probe_appvar

    ; create_probe_appvar leaves DE one byte past the copied frame. Preserve
    ; both the resident frame start and its outcome-field address.
    ex de,hl
    ld de,-(frame_end-frame)
    add hl,de
    ld (result_frame_ptr),hl
    ld de,payload_outcome-frame
    add hl,de
    ld (result_outcome_ptr),hl

    ; Record the mapper and protection state after AppVar allocation, directly
    ; before any guarded mapping write.
    ld hl,(result_outcome_ptr)
    inc hl
    in a,($04)
    ld (hl),a
    ld d,a
    inc hl
    in a,($06)
    ld (hl),a
    inc hl
    in a,($21)
    ld (hl),a
    inc hl
    in a,($22)
    ld (hl),a
    inc hl
    in a,($23)
    ld (hl),a
    inc hl
    in a,($25)
    ld (hl),a
    inc hl
    in a,($26)
    ld (hl),a

    ld a,d
    and 1
    jr z,post_create_mapping_supported
    ld hl,(result_outcome_ptr)
    ld (hl),OUTCOME_PAIRED_MAPPING
    jr finish_without_port_restore

post_create_mapping_supported:
    ld a,(payload_outcome)
    cp OUTCOME_PAIRED_MAPPING
    jr z,finish_without_port_restore
    or a
    jr nz,finish

    ; AppVar allocation can change RAM. Verify the selected byte again before
    ; attempting the only opcode fetch outside this program.
    ld a,TARGET_SELECTOR
    out ($06),a
    ld hl,(payload_target)
    ld a,(hl)
    cp $C9
    jr z,guarded_fetch
    ld hl,(result_outcome_ptr)
    ld (hl),OUTCOME_TARGET_CHANGED
    jr finish

guarded_fetch:
    ld de,returned
    push de
    jp (hl)

returned:
    ld hl,(result_outcome_ptr)
    ld (hl),OUTCOME_RETURNED

finish:
    ld a,(saved_port6)
    out ($06),a
finish_without_port_restore:
    pop af
    jp po,interrupts_restored
    ei
interrupts_restored:
    ld ix,(result_frame_ptr)
    ld bc,frame_end-frame
    ld hl,display_label
    call display_probe_code
    ret

saved_port6:
    .db 0
result_outcome_ptr:
    .dw 0
result_frame_ptr:
    .dw 0

display_label:
    .db APPVAR_0,APPVAR_1,APPVAR_2,APPVAR_3
    .db APPVAR_4,APPVAR_5,APPVAR_6,APPVAR_7," CODE ",0
#include "display.inc"

appvar_name:
    .db AppVarObj,APPVAR_0,APPVAR_1,APPVAR_2,APPVAR_3
    .db APPVAR_4,APPVAR_5,APPVAR_6,APPVAR_7

frame:
    .db "HWP1",1,4
    .dw payload_end-payload
frame_asic:
    .db 0
frame_status:
    .db 0
payload:
    .db TARGET_KIND,TARGET_SELECTOR
    .dw SCAN_START,SCAN_LENGTH
payload_target:
    .dw $FFFF
payload_outcome:
    .db OUTCOME_PENDING
payload_port04:
    .db 0
payload_port06:
    .db 0
payload_port21:
    .db 0
payload_port22:
    .db 0
payload_port23:
    .db 0
payload_port25:
    .db 0
payload_port26:
    .db 0
payload_end:
frame_end:
