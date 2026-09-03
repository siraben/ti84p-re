; Read-only Flash erase-entry return fixture.
;
; This program verifies all entry bytes before calling the erase APIs.  It
; never unlocks Flash, and every tested path returns before an erase worker can
; execute.

.org $9D95

start:
    ld a,i
    push af
    di

    in a,($06)
    ld (saved_page),a
    ld a,$3F
    out ($06),a

    ld hl,$4C1E
    ld de,erase_page_signature
    call check_signature
    jr nz,abort
    ld hl,$4C2A
    ld de,erase_signature
    call check_signature
    jr nz,abort
    ld hl,$4E3F
    ld de,certificate_signature
    call check_signature
    jr nz,abort

    ld a,(saved_page)
    out ($06),a

    ; The page wrapper masks 7Eh to 3Eh and returns at its page guard.
    ld a,$7E
    rst $28
    .dw $8084
    push af
    pop hl
    ld (erase_page_3e_af),hl

    ; A direct RAM call leaves a return address >= 8000h on the stack.
    in a,($06)
    ld (saved_page),a
    ld a,$3F
    out ($06),a
    xor a
    scf
    ld a,$A5
    call $4C2A
    push af
    pop hl
    ld (direct_erase_af),hl
    ld a,(saved_page)
    out ($06),a

    ; H=50h is outside the accepted certificate-half values 40h and 60h.
    ; The wrapper restores the incoming AF on this no-op path.
    xor a
    scf
    ld a,$A5
    ld hl,$5000
    rst $28
    .dw $8060
    push af
    pop hl
    ld (invalid_certificate_af),hl
    jr restore_interrupts

check_signature:
    ld b,8
check_signature_byte:
    ld a,(de)
    cp (hl)
    ret nz
    inc de
    inc hl
    djnz check_signature_byte
    ret

abort:
    ld a,(saved_page)
    out ($06),a

restore_interrupts:
    pop af
    jp po,done
    ei
done:
    ret

erase_page_signature:
    .db $21,$00,$40,$E6,$3F,$FE,$3E,$C8
erase_signature:
    .db $E3,$CB,$7C,$E3,$C0,$DD,$E5,$DD
certificate_signature:
    .db $F5,$7C,$EE,$40,$FE,$00,$28,$09
saved_page:
    .db $00
erase_page_3e_af:
    .dw $FFFF
direct_erase_af:
    .dw $FFFF
invalid_certificate_af:
    .dw $FFFF
