; Emulator-only _WriteFlashUnsafe illegal-program fixture.
;
; This program exits unless page 3C contains the return shim produced by
; ti84re.flash.build_emulator_fixture.  Do not remove the signature check.

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

    ; The patched page-3C wrapper performs the protected port-14 unlock and
    ; returns before its original operation and lock tail.
    call $7058

    ; 3D:7FFF contains 50h.  D0h requests its stored bit 7 to change from
    ; zero to one, which TilEm models as a persistent Flash program error.
    ld a,$3D
    ld de,$7FFF
    ld bc,1
    ld hl,source_byte
    rst $28
    .dw $8087

after_writeflash:
    push af
    pop hl
    ld (worker_af),hl
    ld a,$3D
    out ($06),a
    ld a,($7FFF)
    ld (stored_byte),a

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
source_byte:
    .db $D0
worker_af:
    .dw $FFFF
stored_byte:
    .db $FF
