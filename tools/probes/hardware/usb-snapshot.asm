; No-I/O-write low-USB snapshot. Register read side effects remain open.
; Result AppVar: HWPUSB01, probe ID 5, payload 15 bytes.

.org $9D95
    jp start
#include "common.inc"

start:
    ld a,i
    push af
    di

    in a,($15)
    ld (frame_asic),a
    in a,($02)
    ld (frame_status),a

    in a,($49)
    ld (payload_port49),a
    in a,($4A)
    ld (payload_port4a),a
    in a,($4B)
    ld (payload_port4b),a
    in a,($4C)
    ld (payload_port4c),a
    in a,($4D)
    ld (payload_port4d),a
    in a,($4F)
    ld (payload_port4f),a
    in a,($50)
    ld (payload_port50),a
    in a,($51)
    ld (payload_port51),a
    in a,($52)
    ld (payload_port52),a
    in a,($54)
    ld (payload_port54),a
    in a,($55)
    ld (payload_port55),a
    in a,($56)
    ld (payload_port56),a
    in a,($57)
    ld (payload_port57),a
    in a,($5A)
    ld (payload_port5a),a
    in a,($5B)
    ld (payload_port5b),a

    pop af
    jp po,interrupts_restored
    ei
interrupts_restored:
    ld ix,appvar_name
    ld hl,frame
    ld bc,frame_end-frame
    call create_probe_appvar
    ld bc,frame_end-frame
    ld hl,display_label
    call display_created_probe_code
    ret

display_label:
    .db "HWPUSB CODE ",0
#include "display.inc"

appvar_name:
    .db AppVarObj,"HWPUSB01"

frame:
    .db "HWP1",1,5
    .dw payload_end-payload
frame_asic:
    .db 0
frame_status:
    .db 0
payload:
payload_port49:
    .db 0
payload_port4a:
    .db 0
payload_port4b:
    .db 0
payload_port4c:
    .db 0
payload_port4d:
    .db 0
payload_port4f:
    .db 0
payload_port50:
    .db 0
payload_port51:
    .db 0
payload_port52:
    .db 0
payload_port54:
    .db 0
payload_port55:
    .db 0
payload_port56:
    .db 0
payload_port57:
    .db 0
payload_port5a:
    .db 0
payload_port5b:
    .db 0
payload_end:
frame_end:
