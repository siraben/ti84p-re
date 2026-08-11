; Guarded RAM execution-protection probe.
;
; The build passes TARGET_SELECTOR, TARGET_ADDRESS, and MARKER on the SPASM
; command line. The native fixture places the six-byte marker routine in the
; selected physical RAM page. This program verifies those bytes through data
; reads before attempting an instruction fetch.

.org $9D95

start:
    ld a,TARGET_SELECTOR
    out ($06),a
    ld hl,TARGET_ADDRESS
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
    call TARGET_ADDRESS
returned:
    ld a,($8478)
    ld (observed_marker),a
abort:
    ret

target_signature:
    .db $3E,MARKER,$32,$78,$84,$C9
observed_marker:
    .db $FF
