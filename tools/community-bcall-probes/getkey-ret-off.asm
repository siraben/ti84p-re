.NOLIST
#include "tools/ti83plus.inc"
.LIST

; Interactive _GetKeyRetOff probe. The first _GetKey drains launch ENTER.
.org $9D95

    ld iy,$89F0
    ld hl,$4F4E
    ld ($9872),hl

    bcall(_GetKey)
    ld a,$01
    ld ($9874),a

wait_off:
    rst $28
    .dw $500B
    cp $3F
    jr nz,wait_off
    ld ($9875),a
    ld a,$02
    ld ($9876),a
    ld hl,$600D
    ld ($9877),hl

halt_loop:
    di
    halt
    jr halt_loop
