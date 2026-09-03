; Controlled return-path and state probe for nonblocking community-used bcalls.
.org $9D95

    ld iy,$89F0
    ld hl,$C24B
    ld ($9872),hl

    ; _newContext: preserve the bank-A selector and observe kbdKey clearing.
    in a,($06)
    ld ($9874),a
    ld a,$40
    rst $28
    .dw $4030
    ld a,$30
    ld ($9875),a
    ld a,($8444)
    ld ($9876),a
    in a,($06)
    ld ($9877),a

    ; _ShRAcc: the result block stores F followed by A.
    ld a,$AB
    rst $28
    .dw $41D4
    push af
    pop hl
    ld ($9878),hl

    ; _ConvKeyToTok: cooked key 0x05 has the dedicated DE=0x003F path.
    ld a,$05
    rst $28
    .dw $4A02
    ld ($987A),de

    ; _GetK: seed one pending kbdGetKy value, then restore the mailbox.
    ld a,($8445)
    ld ($987C),a
    ld a,($843F)
    ld ($9895),a
    xor a
    ld ($843F),a
    ld a,$01
    ld ($8445),a
    rst $28
    .dw $4744
    ld ($987D),a
    ld ($987E),hl
    ld a,($987C)
    ld ($8445),a
    ld a,($9895)
    ld ($843F),a

    ; Save hook flags and target records before exercising setters/clearer.
    ld a,($8A24)
    ld ($9880),a
    ld a,($8A25)
    ld ($9893),a
    ld a,($8A26)
    ld ($9894),a
    ld hl,($9BC8)
    ld ($9881),hl
    ld a,($9BCA)
    ld ($9883),a
    ld hl,($9BD0)
    ld ($9884),hl
    ld a,($9BD2)
    ld ($9886),a

    ld hl,$9872
    xor a
    rst $28
    .dw $4F99
    ld hl,($9BC8)
    ld ($9887),hl
    ld a,($9BCA)
    ld ($9889),a
    ld a,($8A25)
    ld ($988A),a
    ld hl,($9881)
    ld ($9BC8),hl
    ld a,($9883)
    ld ($9BCA),a
    ld a,($9893)
    ld ($8A25),a

    ld hl,$9875
    xor a
    rst $28
    .dw $50CE
    ld hl,($9BD0)
    ld ($988B),hl
    ld a,($9BD2)
    ld ($988D),a
    ld a,($8A26)
    ld ($988E),a
    ld hl,($9884)
    ld ($9BD0),hl
    ld a,($9886)
    ld ($9BD2),a
    ld a,($9894)
    ld ($8A26),a

    ld a,($9880)
    or $80
    ld ($8A24),a
    rst $28
    .dw $4F69
    ld a,($8A24)
    ld ($988F),a

    ; Restore all three hook flag bytes exactly.
    ld a,($9880)
    ld ($8A24),a

    ; _FlashWriteDisable is last: prove return, then re-enable interrupts.
    rst $28
    .dw $4F3C
    ld a,$3C
    ld ($9890),a
    ei

    ld hl,$600D
    ld ($9891),hl
halt_loop:
    di
    halt
    jr halt_loop
