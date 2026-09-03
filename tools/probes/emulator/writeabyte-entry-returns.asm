; Read-only _WriteAByte entry-return fixture.
;
; This program verifies the exact _WriteAByteSafe and _WriteAByte wrapper bytes
; before calling either bcall. It never unlocks Flash, and every tested path
; returns before the RAM worker can execute.

.org $9D95

start:
    ld a,i
    push af
    di

    in a,($06)
    ld (saved_page),a
    ld a,($8478)
    ld (saved_op1),a

    ld a,$3F
    out ($06),a
    ld hl,$4C9A
    ld de,entry_signature
    ld b,16
check_entry:
    ld a,(de)
    cp (hl)
    jp nz,abort
    inc de
    inc hl
    djnz check_entry
    ld a,(saved_page)
    out ($06),a

    ; Page 7Eh masks to 3Eh and returns before _WriteAByte stores B in OP1.
    ld a,$11
    ld ($8478),a
    ld a,$7E
    ld bc,$2233
    ld de,$4455
    ld hl,$6677
    rst $28
    .dw $80C6
safe_page_3e_return:
    ld (safe_page_3e_hl),hl
    ld (safe_page_3e_de),de
    ld (safe_page_3e_bc),bc
    push af
    pop hl
    ld (safe_page_3e_af),hl
    ld a,($8478)
    ld (safe_page_3e_op1),a

    ; Page 7Fh passes the safe 3Eh guard. _WriteAByte stores B in OP1 and
    ; sets HL=OP1, BC=1 before the unsafe core rejects masked page 3Fh.
    ld a,$7F
    ld bc,$4455
    ld de,$6677
    ld hl,$8899
    rst $28
    .dw $80C6
safe_page_3f_return:
    ld (safe_page_3f_hl),hl
    ld (safe_page_3f_de),de
    ld (safe_page_3f_bc),bc
    push af
    pop hl
    ld (safe_page_3f_af),hl
    ld a,($8478)
    ld (safe_page_3f_op1),a

    ; The unsafe byte entry performs the same setup before its page-3F guard.
    ld a,$7F
    ld bc,$5566
    ld de,$7788
    ld hl,$99AA
    rst $28
    .dw $8021
unsafe_page_3f_return:
    ld (unsafe_page_3f_hl),hl
    ld (unsafe_page_3f_de),de
    ld (unsafe_page_3f_bc),bc
    push af
    pop hl
    ld (unsafe_page_3f_af),hl
    ld a,($8478)
    ld (unsafe_page_3f_op1),a

    ; A direct RAM call still performs the byte-wrapper setup. The unsafe
    ; core then rejects the RAM return address before masking A.
    ld a,$3F
    out ($06),a
    scf
    ld a,$A5
    ld bc,$6677
    ld de,$8899
    ld hl,$AABB
    call $4C9F
direct_call_return:
    ld (direct_call_hl),hl
    ld (direct_call_de),de
    ld (direct_call_bc),bc
    push af
    pop hl
    ld (direct_call_af),hl
    ld a,($8478)
    ld (direct_call_op1),a

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

entry_signature:
    .db $E6,$3F,$FE,$3E,$C8,$21,$78,$84
    .db $70,$01,$01,$00,$E3,$CB,$7C,$E3
saved_page:
    .db $00
saved_op1:
    .db $00
safe_page_3e_af:
    .dw $FFFF
safe_page_3e_bc:
    .dw $FFFF
safe_page_3e_de:
    .dw $FFFF
safe_page_3e_hl:
    .dw $FFFF
safe_page_3e_op1:
    .db $FF
safe_page_3f_af:
    .dw $FFFF
safe_page_3f_bc:
    .dw $FFFF
safe_page_3f_de:
    .dw $FFFF
safe_page_3f_hl:
    .dw $FFFF
safe_page_3f_op1:
    .db $FF
unsafe_page_3f_af:
    .dw $FFFF
unsafe_page_3f_bc:
    .dw $FFFF
unsafe_page_3f_de:
    .dw $FFFF
unsafe_page_3f_hl:
    .dw $FFFF
unsafe_page_3f_op1:
    .db $FF
direct_call_af:
    .dw $FFFF
direct_call_bc:
    .dw $FFFF
direct_call_de:
    .dw $FFFF
direct_call_hl:
    .dw $FFFF
direct_call_op1:
    .db $FF
