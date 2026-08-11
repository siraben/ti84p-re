; Emulator-only internal certificate-program DQ5-failure fixture.
;
; This program exits unless page 3C contains the return shim produced by
; build_flash_emulator_fixture.py and both copied-worker signatures match.
; Do not remove the signature checks.

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
    jp nz,abort
    inc de
    inc hl
    djnz check_patch

    ld a,$3D
    out ($06),a
    ld hl,$730A
    ld de,worker_head_signature
    ld b,12
check_worker_head:
    ld a,(de)
    cp (hl)
    jp nz,abort
    inc de
    inc hl
    djnz check_worker_head

    ld hl,$7379
    ld de,worker_tail_signature
    ld b,18
check_worker_tail:
    ld a,(de)
    cp (hl)
    jp nz,abort
    inc de
    inc hl
    djnz check_worker_tail

    ; The patched wrapper performs the protected port-14 unlock and returns
    ; before its original operation and lock tail.
    ld a,$3C
    out ($06),a
    call $7058

    ; Certificate reads are censored while locked.  Check the audited 00h
    ; target after the protected unlock but before any program command.
    ld a,$3E
    out ($06),a
    ld a,($4000)
    or a
    jp nz,relock_abort

    ; Copy the internal 129-byte worker to ramCode.
    ld a,$3D
    out ($06),a
    ld hl,$730A
    ld de,$8100
    ld bc,129
    ldir

    ; Save page zero in the worker prologue.  Programming 80h over stored 00h
    ; requests an illegal zero-to-one transition and reaches the DQ5 tail.
    xor a
    out ($06),a
    ld a,$3E
    ld de,$4000
    ld bc,1
    ld hl,source_byte
    call $8100

after_worker:
    ld (worker_bc),bc
    ld (worker_de),de
    ld (worker_hl),hl
    push af
    pop hl
    ld (worker_af),hl
    in a,($06)
    ld (restored_page),a

    ld a,$3E
    out ($06),a
    ld a,($4000)
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

relock_abort:
    ld a,$3C
    out ($06),a
    call $66D5
    jr restore_interrupts

patch_signature:
    .db $F1,$C9,$00,$00,$00,$00,$00,$00
worker_head_signature:
    .db $32,$68,$98,$DB,$06,$F5,$3A,$68,$98,$D3,$06,$CB
worker_tail_signature:
    .db $1B,$3E,$F0,$12,$13,$F1,$D3,$06,$AF,$C9
    .db $3E,$F0,$12,$F1,$D3,$06,$B7,$C9
source_byte:
    .db $80
worker_af:
    .dw $FFFF
worker_bc:
    .dw $FFFF
worker_de:
    .dw $FFFF
worker_hl:
    .dw $FFFF
restored_page:
    .db $FF
stored_byte:
    .db $FF
