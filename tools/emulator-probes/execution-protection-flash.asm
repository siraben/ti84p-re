; Guarded Flash execution-protection boundary probe.
;
; The build passes TARGET_PAGE on the SPASM command line. The fixture ROM puts
; a six-byte marker routine at TARGET_PAGE:7FF0. This program verifies those
; bytes through ordinary data reads before attempting an instruction fetch.

.org $9D95

start:
    ld a,i
    push af
    di

    in a,($06)
    ld (saved_page),a
    ld a,($8478)
    ld (saved_op1),a

    ld a,TARGET_PAGE
    out ($06),a
    ld hl,$7FF0
    ld de,target_signature
    ld b,6
check_target:
    ld a,(de)
    cp (hl)
    jr nz,abort
    inc de
    inc hl
    djnz check_target

    ld a,$A0
    ld ($8478),a
call_target:
    call $7FF0
returned:
    ld a,($8478)
    ld (observed_marker),a

abort:
    ld a,(saved_op1)
    ld ($8478),a
    ld a,(saved_page)
    out ($06),a
    pop af
    jp po,done
    ei
done:
    ret

target_signature:
    .db $3E,TARGET_PAGE,$32,$78,$84,$C9
saved_page:
    .db $00
saved_op1:
    .db $00
observed_marker:
    .db $FF
