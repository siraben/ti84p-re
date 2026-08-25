.NOLIST
#include "tools/ti83plus.inc"
.LIST

; Valid _GetStringInput2 caller reconstructed from the archived Elite source.
.org $9D95

    ld iy,flags
    ld hl,$3253
    ld ($9872),hl

    ; Consume an explicitly injected ENTER before opening the editor context.
    bcall(_GetKey)
    ld a,$01
    ld ($9874),a

    bcall(_NewLine)
    ld hl,prompt
    ld de,ioPrompt
    ld bc,4
    ldir
    ld hl,(cleanTmp)
    push hl
    ld hl,(pTempCnt)
    ld (cleanTmp),hl

    rst $28
    .dw $4E61

    pop hl
    ld (cleanTmp),hl
    ld hl,OP1
    ld de,$9875
    ld bc,11
    ldir
    ld a,$02
    ld ($9880),a
    ld hl,$600D
    ld ($9881),hl

halt_loop:
    di
    halt
    jr halt_loop

prompt:
    .db "A=?",0
