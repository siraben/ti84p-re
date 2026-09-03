.NOLIST
#include "tools/symbols/ti83plus.inc"
.LIST

; One-sided _SendPacket probe with a calculator-side error handler.
.org $9D95

    ld iy,flags
    ld hl,$4B50
    ld (appBackUpScreen),hl

    ld hl,error_handler
    call APP_PUSH_ERRORH
    ld hl,$1523
    ld (header),hl
    ld hl,1
    ld (header+2),hl
    ld hl,payload
    ld (iMathPtr5),hl

    rst $28
    .dw $4ED6

    ld a,$01
    call APP_POP_ERRORH
    jr finish

error_handler:
    call APP_POP_ERRORH
    ld a,$EE

finish:
    ld (appBackUpScreen+2),a
    ld hl,$600D
    ld (appBackUpScreen+3),hl
halt_loop:
    di
    halt
    jr halt_loop

payload:
    .db $A5
