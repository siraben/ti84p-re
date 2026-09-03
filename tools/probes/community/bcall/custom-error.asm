.NOLIST
#include "tools/symbols/ti83plus.inc"
.LIST

; Dynamic witness for the community use of _ErrCustom1 = 4D41h.  The payload
; bounds the custom message to appErr1's 13-byte slot, unlike generateerror.
.org userMem

    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,message
    ld de,appErr1
    ld bc,message_end-message
    ldir
    bcall(_ErrCustom1)

    ; _ErrCustom1 exits through the OS error frame and must not return here.
unexpected_return:
    di
    halt
    jr unexpected_return

message:
    .db "COMMTRACE",0
message_end:
