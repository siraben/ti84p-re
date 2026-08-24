; Safe return-path probe for valid main-table IDs found through local equates.
.org $9D95

    ld iy,$89F0
    ld hl,$BCA3
    ld ($9872),hl

    rst $28
    .dw $4051          ; _lcd_busy
    ld a,$51
    ld ($9874),a

    rst $28
    .dw $4936          ; _BufClear
    ld a,$36
    ld ($9875),a

    ld de,$BB6A        ; Asm token, matching Plasma's _bufInsert caller
    rst $28
    .dw $4909          ; _bufInsert
    ld a,$09
    ld ($9876),a

    rst $28
    .dw $4936          ; leave the edit buffer clear
    ld a,$37
    ld ($9877),a

    ld a,$A5
    rst $28
    .dw $50E0          ; _NZIf83Plus
    push af
    pop hl
    ld ($9878),hl

    ld hl,$600D
    ld ($987A),hl
    ret
