.NOLIST
#include "tools/ti83plus.inc"
.LIST

; TI-83+ behavioral witness for the initial one-sided wait in the archived
; linktutorial83plus example.  The original release's calculator files are
; TI-83 containers, so this transcribes only the relevant source instructions.
.org userMem

    ld a,$FF
    out (1),a

waitkey:
    in a,(0)
    and 3
    cp 2
    jr z,peer_two

    ld a,$D1
    out (0),a

waitplayer:
    in a,(0)
    and 3
    cp 0
    jr z,peer_one

    ld a,$BF
    out (1),a
    in a,(1)
    cp $BF
    ret z
    jr waitplayer

peer_two:
    ld a,$D2
    out (0),a
peer_one:
    ret
