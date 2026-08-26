; Display a decimal verification code, then a reversible compact frame code.
; OS display and key bcalls run only when the caller entered with interrupts
; enabled. Input: IX = HWP1 frame, BC = frame length, HL = zero-terminated label.

_ClrLCDFull        .equ $4540
_ClrLCD            .equ $4543
_HomeUp            .equ $4558
_PutS              .equ $450A
_DispHL            .equ $4507
_VPutMap           .equ $455E
_GetKey            .equ $4972
penCol             .equ $86D7
penRow             .equ $86D8

display_probe_code:
    ld a,i
    ret po
    push ix
    push bc
    push hl
    call crc16_probe_frame
    ld (compact_expected_crc),de
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
    pop bc
    pop ix
    call display_compact_frame
    ret

; Input: DE = first byte after the AppVar-resident HWP1 frame,
; BC = frame length, HL = zero-terminated label.
display_created_probe_code:
    push hl
    ex de,hl
    or a
    sbc hl,bc
    push hl
    pop ix
    pop hl
    jp display_probe_code

; Display HWPZ1- followed by Crockford Base32 over:
;   frame length LE, frame CRC LE, escape-run compressed frame.
; Escape-run records are FF,count,value for runs >= 3 and every literal FF.
display_compact_frame:
    xor a
    ld (compact_bit_count),a
    ld (compact_bit_buffer),a
    ld (compact_bit_buffer+1),a
    ld (compact_column),a
    ld (compact_row),a
    push bc
    push ix
    rst $28
    .dw _ClrLCD
    pop ix
    pop bc

    ld hl,compact_prefix
compact_prefix_loop:
    ld a,(hl)
    or a
    jr z,compact_prefix_done
    call compact_emit_small_char
    inc hl
    jr compact_prefix_loop
compact_prefix_done:
    ld a,c
    call compact_emit_encoded_byte
    ld a,b
    call compact_emit_encoded_byte
    ld a,(compact_expected_crc)
    call compact_emit_encoded_byte
    ld a,(compact_expected_crc+1)
    call compact_emit_encoded_byte

compact_start_run:
    ld a,b
    or c
    jr z,compact_finish_stream
    ld a,(ix+0)
    ld (compact_run_value),a
    ld a,1
    ld (compact_run_count),a
    inc ix
    dec bc

compact_gather_run:
    ld a,b
    or c
    jr z,compact_flush_last_run
    ld a,(ix+0)
    ld d,a
    ld a,(compact_run_value)
    cp d
    jr nz,compact_flush_then_restart
    ld a,(compact_run_count)
    cp $FF
    jr z,compact_flush_then_restart
    inc a
    ld (compact_run_count),a
    inc ix
    dec bc
    jr compact_gather_run

compact_flush_then_restart:
    call compact_flush_run
    jr compact_start_run

compact_flush_last_run:
    call compact_flush_run

compact_finish_stream:
    ld a,(compact_bit_count)
    or a
    jr z,compact_finish_page
    ld b,a
    ld a,5
    sub b
    ld b,a
    ld a,(compact_bit_buffer)
compact_final_shift:
    sla a
    djnz compact_final_shift
    and $1F
    call compact_emit_base32_index
    xor a
    ld (compact_bit_count),a

compact_finish_page:
    ld a,(compact_column)
    ld d,a
    ld a,(compact_row)
    or d
    jr z,compact_display_done
    rst $28
    .dw _GetKey
compact_display_done:
    ld a,$C7
    cp $C7
    ret

; Flush the saved run without changing the input IX/BC pair.
compact_flush_run:
    push bc
    ld a,(compact_run_count)
    cp 3
    jr nc,compact_flush_escape
    ld a,(compact_run_value)
    cp $FF
    jr z,compact_flush_escape
    ld a,(compact_run_count)
    ld b,a
compact_flush_literal_loop:
    ld a,(compact_run_value)
    call compact_emit_encoded_byte
    djnz compact_flush_literal_loop
    pop bc
    ret
compact_flush_escape:
    ld a,$FF
    call compact_emit_encoded_byte
    ld a,(compact_run_count)
    call compact_emit_encoded_byte
    ld a,(compact_run_value)
    call compact_emit_encoded_byte
    pop bc
    ret

; Append A to the Base32 bit stream. Preserve the frame input IX/BC pair.
compact_emit_encoded_byte:
    push bc
    push ix
    ld hl,(compact_bit_buffer)
    ld h,l
    ld l,a
    ld (compact_bit_buffer),hl
    ld a,(compact_bit_count)
    add a,8
    ld (compact_bit_count),a
compact_emit_group_loop:
    ld a,(compact_bit_count)
    cp 5
    jr c,compact_emit_group_done
    sub 5
    ld (compact_bit_count),a
    ld hl,(compact_bit_buffer)
    ld d,h
    ld e,l
    ld b,a
    ld a,b
    or a
    jr z,compact_group_shift_done
compact_group_shift_loop:
    srl d
    rr e
    djnz compact_group_shift_loop
compact_group_shift_done:
    ld a,e
    and $1F
    push af
    ld a,(compact_bit_count)
    ld c,a
    ld b,0
    ld de,compact_low_masks
    push hl
    ex de,hl
    add hl,bc
    ld a,(hl)
    pop hl
    and l
    ld l,a
    ld h,0
    ld (compact_bit_buffer),hl
    pop af
    call compact_emit_base32_index
    jr compact_emit_group_loop
compact_emit_group_done:
    pop ix
    pop bc
    ret

compact_emit_base32_index:
    ld e,a
    ld d,0
    ld hl,compact_alphabet
    add hl,de
    ld a,(hl)
    jp compact_emit_small_char

; Place one character in a fixed 6-by-7 cell through the OS small-font bcall.
; Sixteen cells fit each row and nine rows fit each LCD page.
compact_emit_small_char:
    push bc
    push de
    push hl
    push ix
    push af
    ld a,(compact_column)
    ld b,a
    add a,a
    add a,b
    add a,a
    ld (penCol),a
    ld a,(compact_row)
    ld b,a
    add a,a
    add a,a
    add a,a
    sub b
    ld (penRow),a
    pop af
    rst $28
    .dw _VPutMap
    pop ix
    pop hl
    pop de
    pop bc
    ld a,(compact_column)
    inc a
    cp 16
    jr c,compact_store_column
    xor a
    ld (compact_column),a
    ld a,(compact_row)
    inc a
    cp 9
    jr c,compact_store_row
    push bc
    push de
    push hl
    push ix
    rst $28
    .dw _GetKey
    rst $28
    .dw _ClrLCD
    pop ix
    pop hl
    pop de
    pop bc
    xor a
    ld (compact_row),a
    ret
compact_store_row:
    ld (compact_row),a
    ret
compact_store_column:
    ld (compact_column),a
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

compact_prefix:
    .db "HWPZ1-",0
compact_alphabet:
    .db "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
compact_low_masks:
    .db $00,$01,$03,$07,$0F,$1F,$3F,$7F
compact_expected_crc:
    .dw 0
compact_bit_buffer:
    .dw 0
compact_bit_count:
    .db 0
compact_run_value:
    .db 0
compact_run_count:
    .db 0
compact_column:
    .db 0
compact_row:
    .db 0
