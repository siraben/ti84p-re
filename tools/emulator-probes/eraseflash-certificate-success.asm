; Emulator-only _EraseCertificateSector success fixture.
;
; This program exits unless page 3C contains the return shim produced by
; build_flash_emulator_fixture.py.  It erases only the first certificate half
; in the copied ROM image.  Do not remove the signature check.

.org $9D95

start:
    ld a,i
    push af
    di

    ld a,$3C
    out ($06),a
    ld hl,$7068
    ld de,patch_signature
    ld b,8
check_patch:
    ld a,(de)
    cp (hl)
    jr nz,abort
    inc de
    inc hl
    djnz check_patch

    ; The patched wrapper performs the protected port-14 unlock and returns
    ; before its original operation and lock tail.
    call $7058

    ; Seed caller AF, then erase the 3E:4000-5FFF certificate sector.
    xor a
    scf
    ld a,$A5
    ld hl,$4000
    rst $28
    .dw $8060

after_erase:
    push af
    pop hl
    ld (wrapper_af),hl

    ; Read the first byte while the certificate page remains readable.
    ld a,$3E
    out ($06),a
    ld a,($4000)
    ld (erased_byte),a

    ; Relock through the original protected page-3C sequence.
    ld a,$3C
    out ($06),a
    call $66D5

restore_interrupts:
    pop af
    jp po,done
    ei
done:
    ret

abort:
    jr restore_interrupts

patch_signature:
    .db $F1,$C9,$00,$00,$00,$00,$00,$00
wrapper_af:
    .dw $FFFF
erased_byte:
    .db $00
