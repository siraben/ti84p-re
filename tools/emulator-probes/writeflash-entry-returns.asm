; Read-only _WriteFlash entry-return fixture.
;
; This program verifies the exact _WriteFlashUnsafe entry bytes before calling
; any Flash bcall.  It never unlocks Flash and every tested path returns before
; the RAM worker can execute.

.org $9D95

start:
    ld a,i
    push af
    di

    in a,($06)
    ld (saved_page),a
    ld a,$3F
    out ($06),a
    ld hl,$4CA6
    ld de,entry_signature
    ld b,8
check_entry:
    ld a,(de)
    cp (hl)
    jr nz,abort
    inc de
    inc hl
    djnz check_entry
    ld a,(saved_page)
    out ($06),a

    ; The safe entry masks 7Eh to 3Eh and returns at its page-3E guard.
    ld a,$7E
    ld de,$4000
    ld bc,1
    ld hl,dummy_source
    rst $28
    .dw $80C9
    push af
    pop hl
    ld (safe_page_3e_af),hl

    ; The unsafe entry masks 7Fh to 3Fh and returns at its page-3F guard.
    ld a,$7F
    ld de,$4000
    ld bc,1
    ld hl,dummy_source
    rst $28
    .dw $8087
    push af
    pop hl
    ld (unsafe_page_3f_af),hl

    ; Page 3Dh passes both page guards.  BC=0 returns before worker launch.
    ld a,$7D
    ld de,$4000
    ld bc,0
    ld hl,dummy_source
    rst $28
    .dw $8087
    push af
    pop hl
    ld (zero_length_af),hl

    ; A direct RAM call leaves a return address >= 8000h on the stack.  The
    ; entry rejects it before masking A or examining the remaining inputs.
    in a,($06)
    ld (saved_page),a
    ld a,$3F
    out ($06),a
    scf
    ld a,$A5
    call $4CA6
    push af
    pop hl
    ld (direct_call_af),hl

abort:
    ld a,(saved_page)
    out ($06),a
    pop af
    jp po,done
    ei
done:
    ret

entry_signature:
    .db $E3,$CB,$7C,$E3,$C0,$E6,$3F,$FE
dummy_source:
    .db $FF
saved_page:
    .db $00
safe_page_3e_af:
    .dw $FFFF
unsafe_page_3f_af:
    .dw $FFFF
zero_length_af:
    .dw $FFFF
direct_call_af:
    .dw $FFFF
