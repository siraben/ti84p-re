; Guarded low-source _WriteFlashUnsafe crossing fixture.
;
; This emulator-only program locks Flash, clears the worker's source-mode flag,
; and calls the unmodified block worker with source 0068h, destination 7FFFh,
; and length two.  The second LDI and terminal F0h reset target RAM 8000h.  The
; program captures the result, then restores RAM 8000h, (IY+25h), port 06h, and
; the incoming interrupt state.

.org $9D95

start:
    ld a,i
    push af
    di

    in a,($06)
    ld (saved_page),a
    ld a,($8000)
    ld (saved_ram_8000),a

    push iy
    pop hl
    ld de,$0025
    add hl,de
    ld a,(hl)
    ld (saved_iy25),a
    res 1,(hl)
    ld a,(hl)
    ld (cleared_iy25),a

    ; Require two audited fixed-page source bytes with DQ7 clear.
    ld hl,$0068
    ld de,source_signature
    ld b,2
    call check_signature
    jp nz,abort

    ; Require the first destination byte used by the locked no-op.
    ld a,$3D
    out ($06),a
    ld a,($7FFF)
    cp $50
    jp nz,abort
    ld (before_flash),a

    ; Verify the copied worker's source-mode and boundary-selection head.
    ld a,$3F
    out ($06),a
    ld hl,$4CCA
    ld de,worker_signature
    ld b,16
    call check_signature
    jp nz,abort

    ; Verify and call the protected page-3C lock wrapper.
    ld a,$3C
    out ($06),a
    ld hl,$66D5
    ld de,lock_signature
    ld b,16
    call check_signature
    jp nz,abort
    call $66D5
    in a,($02)
    ld (before_port02),a
    and $04
    jp nz,abort

    ; H < 80h selects source mode.  The first target is Flash at 3D:7FFF;
    ; the skipped boundary logic leaves the second target at RAM 8000h.
    ld a,$3D
    ld de,$7FFF
    ld bc,2
    ld hl,$0068
    rst $28
    .dw $8087
call_return:
    ld (return_hl),hl
    ld (return_de),de
    ld (return_bc),bc
    push af
    pop hl
    ld (return_af),hl

    ld a,($8000)
    ld (after_ram_8000),a
    push iy
    pop hl
    ld de,$0025
    add hl,de
    ld a,(hl)
    ld (after_iy25),a

    ld a,$3D
    out ($06),a
    ld a,($7FFF)
    ld (after_flash),a
    in a,($02)
    ld (after_port02),a

abort:
    ld a,(saved_ram_8000)
    ld ($8000),a
    push iy
    pop hl
    ld de,$0025
    add hl,de
    ld a,(saved_iy25)
    ld (hl),a
    ld a,(saved_page)
    out ($06),a
    pop af
    jp po,done
    ei
done:
    ret

check_signature:
    ld a,(de)
    cp (hl)
    ret nz
    inc de
    inc hl
    djnz check_signature
    ret

source_signature:
    .db $4D,$50
worker_signature:
    .db $E6,$3F,$D3,$06,$CB,$7C,$20,$04
    .db $FD,$CB,$25,$CE,$FD,$CB,$25,$4E
lock_signature:
    .db $00,$00,$00,$00,$F5,$AF,$00,$F3
    .db $00,$00,$ED,$56,$F3,$D3,$14,$F3
saved_page:
    .db $00
saved_ram_8000:
    .db $00
saved_iy25:
    .db $00
cleared_iy25:
    .db $FF
before_flash:
    .db $FF
before_port02:
    .db $FF
return_af:
    .dw $FFFF
return_bc:
    .dw $FFFF
return_de:
    .dw $FFFF
return_hl:
    .dw $FFFF
after_ram_8000:
    .db $FF
after_iy25:
    .db $FF
after_flash:
    .db $FF
after_port02:
    .db $FF
