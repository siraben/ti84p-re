; Self-contained guarded RAM execution-protection probe for TilEm.
;
; The build passes TARGET_SELECTOR, TARGET_ADDRESS, and MARKER on the SPASM
; command line. The program installs a six-byte marker in the selected physical
; RAM page, verifies it through data reads, and then attempts an instruction
; fetch from the same logical address.

.org $9D95

start:
    ld a,i
    push af
    di

    in a,($06)
    ld (saved_page),a
    ld a,($8478)
    ld (saved_op1),a

    ld a,TARGET_SELECTOR
    out ($06),a
    ld hl,target_signature
    ld de,TARGET_ADDRESS
    ld bc,6
    ldir

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
    .db $3E,MARKER,$32,$78,$84,$C9
saved_page:
    .db $00
saved_op1:
    .db $00
observed_marker:
    .db $FF
