; Emulator-only _WriteFlashUnsafe page-3E crossing fixture.
;
; This program exits unless page 3C contains the return shim produced by
; build_flash_emulator_fixture.py.  Do not remove the signature check.

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

    ; 3D:7FFF contains 50h and 3D:4000 contains F5h in the source ROM.  These
    ; values only clear bits, so both byte programs are legal NOR transitions.
    ld a,$3D
    ld de,$7FFF
    ld bc,2
    ld hl,source_bytes
    rst $28
    .dw $8087
    ld (worker_result),a

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
source_bytes:
    .db $40,$E0
worker_result:
    .db $FF
