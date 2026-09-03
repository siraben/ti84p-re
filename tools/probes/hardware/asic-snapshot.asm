; Read-only ASIC control, timing, and GPIO snapshot.
; Result AppVar: HWPASIC1, probe ID 3, payload 11 bytes.

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

    in a,($04)
    ld (payload_port04),a
    in a,($20)
    ld (payload_port20),a
    in a,($21)
    ld (payload_port21),a
    in a,($29)
    ld (payload_port29),a
    in a,($2A)
    ld (payload_port2a),a
    in a,($2B)
    ld (payload_port2b),a
    in a,($2C)
    ld (payload_port2c),a
    in a,($2E)
    ld (payload_port2e),a
    in a,($2F)
    ld (payload_port2f),a
    in a,($39)
    ld (payload_port39),a
    in a,($3A)
    ld (payload_port3a),a

    pop af
    jp po,interrupts_restored
    ei
interrupts_restored:
    ld ix,appvar_name
    ld hl,frame
    ld bc,frame_end-frame
    call create_probe_appvar
    ret

appvar_name:
    .db AppVarObj,"HWPASIC1"

frame:
    .db "HWP1",1,3
    .dw payload_end-payload
frame_asic:
    .db 0
frame_status:
    .db 0
payload:
payload_port04:
    .db 0
payload_port20:
    .db 0
payload_port21:
    .db 0
payload_port29:
    .db 0
payload_port2a:
    .db 0
payload_port2b:
    .db 0
payload_port2c:
    .db 0
payload_port2e:
    .db 0
payload_port2f:
    .db 0
payload_port39:
    .db 0
payload_port3a:
    .db 0
payload_end:
frame_end:
