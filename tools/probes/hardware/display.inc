; Display one decimal verification code after the result AppVar is complete.
; Input: IX = HWP1 frame, BC = frame length, HL = zero-terminated label.

_ClrLCDFull        .equ $4540
_HomeUp            .equ $4558
_PutS              .equ $450A
_DispHL            .equ $4507
_GetKey            .equ $4972

display_probe_code:
    push hl
    call crc16_probe_frame
    push de
    rst $28
    .dw _ClrLCDFull
    rst $28
    .dw _HomeUp
    pop de
    pop hl
    push de
    rst $28
    .dw _PutS
    pop hl
    rst $28
    .dw _DispHL
    rst $28
    .dw _GetKey
    ret

; CRC-16/CCITT-FALSE over BC bytes at IX. Returns DE.
crc16_probe_frame:
    ld de,$FFFF
crc16_byte_loop:
    ld a,b
    or c
    ret z
    ld a,(ix+0)
    xor d
    ld d,a
    ld h,8
crc16_bit_loop:
    sla e
    rl d
    jr nc,crc16_no_polynomial
    ld a,e
    xor $21
    ld e,a
    ld a,d
    xor $10
    ld d,a
crc16_no_polynomial:
    dec h
    jr nz,crc16_bit_loop
    inc ix
    dec bc
    jr crc16_byte_loop
