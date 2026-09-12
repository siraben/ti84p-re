; Read-only RTC rollover-coherence probe.
; Result AppVar: HWPRTC01, probe ID 13, payload 19 bytes.
; The wait for low byte $FF can take up to 256 observed RTC transitions.

.org $9D95
    jp start
#include "common.inc"

start:
    ld a,i
    jp po,entry_iff_disabled
    ld a,1
    jr entry_iff_recorded
entry_iff_disabled:
    xor a
entry_iff_recorded:
    ld (entry_iff),a
    in a,($15)
    ld (frame_asic),a
    in a,($02)
    ld (frame_status),a
    in a,($40)
    ld (payload_pre_control),a
    and 1
    jp z,rtc_disabled

    ; A disabled-interrupt caller cannot safely wait several minutes while
    ; preserving its entry state. Record the guard outcome without sampling.
    ld a,(entry_iff)
    or a
    jp z,interrupts_disabled

    in a,($45)
    ld e,a
    ld d,0                         ; 256 observed transitions maximum
    ld a,$40
    ld (progress_watchdog),a
wait_for_low_ff:
    ld a,e
    cp $FF
    jr z,low_ff_seen
    ld bc,$FFFF
wait_for_progress:
    in a,($45)
    cp e
    jr nz,low_byte_progressed
    dec bc
    ld a,b
    or c
    jr nz,wait_for_progress
    ld a,(progress_watchdog)
    dec a
    ld (progress_watchdog),a
    jr z,progress_timeout
    ld bc,$FFFF
    jr wait_for_progress
progress_timeout:
    ld a,4
    ld (payload_outcome),a
    jp snapshot_exit
low_byte_progressed:
    ld e,a
    ld a,$40
    ld (progress_watchdog),a
    dec d
    jr nz,wait_for_low_ff
    ld a,4
    ld (payload_outcome),a
    jp snapshot_exit

low_ff_seen:
    ; Mask interrupts only across the final one-second rollover window.
    di
    ld hl,sample_temp
    call sample_high_to_low
    ld a,(sample_temp+3)
    cp $FF
    jr nz,missed_rollover_window

    ld hl,sample_temp
    ld de,payload_last_ff
    ld bc,4
    ldir
    ld de,$FFFF
    ld a,$40
    ld (rollover_watchdog),a

wait_for_rollover:
    ld hl,sample_temp
    call sample_high_to_low
    ld a,(sample_temp+3)
    cp $FF
    jr nz,rollover_seen

    push de
    ld hl,sample_temp
    ld de,payload_last_ff
    ld bc,4
    ldir
    pop de
    dec de
    ld a,d
    or e
    jr nz,wait_for_rollover
    ld a,(rollover_watchdog)
    dec a
    ld (rollover_watchdog),a
    jr z,rollover_watchdog_expired
    ld de,$FFFF
    jr wait_for_rollover
rollover_watchdog_expired:
    ld a,5
    ld (payload_outcome),a
    jr sampling_done

rollover_seen:
    ld hl,sample_temp
    ld de,payload_first_after
    ld bc,4
    ldir

    ld hl,payload_reverse_after
    call sample_low_to_high
    ld hl,payload_followup
    call sample_high_to_low
    jr sampling_done

interrupts_disabled:
    ld a,1
    ld (payload_outcome),a
    jr snapshot_exit

rtc_disabled:
    ld a,3
    ld (payload_outcome),a
    jr snapshot_exit

missed_rollover_window:
    ld a,2
    ld (payload_outcome),a

sampling_done:
    ei

snapshot_exit:
    in a,($40)
    ld (payload_post_control),a
    ld ix,appvar_name
    ld hl,frame
    ld bc,frame_end-frame
    call create_probe_appvar
    ex de,hl
    ld de,-(frame_end-frame)
    add hl,de
    push hl
    pop ix
    ld a,(entry_iff)
    or a
    ret z
    ld bc,frame_end-frame
    ld hl,display_label
    call display_probe_code
    ret

; Store ports $48, $47, $46, $45 at HL.
sample_high_to_low:
    in a,($48)
    ld (hl),a
    inc hl
    in a,($47)
    ld (hl),a
    inc hl
    in a,($46)
    ld (hl),a
    inc hl
    in a,($45)
    ld (hl),a
    ret

; Store ports $45, $46, $47, $48 at HL.
sample_low_to_high:
    in a,($45)
    ld (hl),a
    inc hl
    in a,($46)
    ld (hl),a
    inc hl
    in a,($47)
    ld (hl),a
    inc hl
    in a,($48)
    ld (hl),a
    ret

sample_temp:
    .fill 4,0
entry_iff:
    .db 0
progress_watchdog:
    .db 0
rollover_watchdog:
    .db 0

display_label:
    .db "HWPRTC CODE ",0
#include "display.inc"

appvar_name:
    .db AppVarObj,"HWPRTC01"

frame:
    .db "HWP1",1,13
    .dw payload_end-payload
frame_asic:
    .db 0
frame_status:
    .db 0
payload:
payload_pre_control:
    .db 0
payload_outcome:
    .db 0
payload_last_ff:
    .fill 4,0
payload_first_after:
    .fill 4,0
payload_reverse_after:
    .fill 4,0
payload_followup:
    .fill 4,0
payload_post_control:
    .db 0
payload_end:
frame_end:
