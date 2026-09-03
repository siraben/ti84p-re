; Read-only locked-Flash _WriteAByte fixture.
;
; This program verifies the byte wrapper and protected lock wrapper, forces
; Flash locked, and aborts unless port 02h confirms the lock. It requests a
; legal 50h -> 40h program at 3D:7FFF and verifies that the byte is unchanged.

.org $9D95

start:
    ld a,i
    push af
    di

    in a,($06)
    ld (saved_page),a
    ld a,($8478)
    ld (saved_op1),a

    ; Verify _WriteAByteSafe through the unsafe core's direct-call check.
    ld a,$3F
    out ($06),a
    ld hl,$4C9A
    ld de,write_entry_signature
    call check_signature
    jp nz,abort

    ; Verify the protected page-3C lock wrapper through its port-14 output.
    ld a,$3C
    out ($06),a
    ld hl,$66D5
    ld de,lock_signature
    call check_signature
    jp nz,abort

    ; Require the audited source byte before the worker can run.
    ld a,$3D
    out ($06),a
    ld a,($7FFF)
    cp $50
    jp nz,abort
    ld (before_value),a

    ; Lock through the protected wrapper, then require port 02h bit 2 clear.
    ld a,$3C
    out ($06),a
    call $66D5
    in a,($02)
    ld (before_port02),a
    and $04
    jp nz,abort

    ; Request legal NOR programming with the same DQ7 as the stored byte.
    ld a,$3D
    ld de,$7FFF
    ld b,$40
    ld c,$99
    rst $28
    .dw $8021
locked_call_return:
    ld (return_hl),hl
    ld (return_de),de
    ld (return_bc),bc
    push af
    pop hl
    ld (return_af),hl
    ld a,($8478)
    ld (return_op1),a

    ; The ASIC gate must leave the array byte unchanged and remain locked.
    ld a,$3D
    out ($06),a
    ld a,($7FFF)
    ld (after_value),a
    in a,($02)
    ld (after_port02),a

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

check_signature:
    ld b,16
check_signature_byte:
    ld a,(de)
    cp (hl)
    ret nz
    inc de
    inc hl
    djnz check_signature_byte
    ret

write_entry_signature:
    .db $E6,$3F,$FE,$3E,$C8,$21,$78,$84
    .db $70,$01,$01,$00,$E3,$CB,$7C,$E3
lock_signature:
    .db $00,$00,$00,$00,$F5,$AF,$00,$F3
    .db $00,$00,$ED,$56,$F3,$D3,$14,$F3
saved_page:
    .db $00
saved_op1:
    .db $00
before_value:
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
return_op1:
    .db $FF
after_value:
    .db $FF
after_port02:
    .db $FF
