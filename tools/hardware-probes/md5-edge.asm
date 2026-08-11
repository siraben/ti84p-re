; Non-destructive MD5-assist edge probe.
; Result AppVar: HWPMD511, probe ID 1, payload 20 bytes.

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

    ; Valid first MD5 step for "abc" -> D6D117B4.
    xor a
    out ($1F),a
    ld hl,abc_operands
    ld c,$18
    ld d,6
load_abc_operand:
    ld b,4
load_abc_byte:
    ld a,(hl)
    out (c),a
    inc hl
    djnz load_abc_byte
    inc c
    dec d
    jr nz,load_abc_operand
    ld a,7
    out ($1E),a
    ld hl,payload_valid
    call read_result

    ; Physical reads are undefined; TilEm and Wabbitemu return four zeroes.
    ld hl,payload_undefined
    ld c,$18
    ld b,4
read_undefined:
    in a,(c)
    ld (hl),a
    inc hl
    inc c
    djnz read_undefined

    ; Four zero writes followed by 12h expose fifth-write sliding behavior.
    call clear_operands
    ld a,2
    out ($1F),a
    xor a
    out ($1E),a
    ld a,$12
    out ($18),a
    ld hl,payload_fifth
    call read_result

    ; High control bits distinguish masking from wider physical fields.
    call clear_operands
    ld a,1
    out ($18),a
    xor a
    out ($18),a
    out ($18),a
    out ($18),a
    ld a,$FF
    out ($1F),a
    out ($1E),a
    ld hl,payload_masked
    call read_result

    ; Read one byte, mutate A, then read the remaining bytes.
    call clear_operands
    ld a,2
    out ($1F),a
    xor a
    out ($1E),a
    ld a,1
    out ($18),a
    xor a
    out ($18),a
    out ($18),a
    out ($18),a
    in a,($1C)
    ld (payload_mixed),a
    ld a,$FF
    out ($18),a
    out ($18),a
    out ($18),a
    out ($18),a
    ld hl,payload_mixed+1
    ld c,$1D
    ld b,3
read_mixed_tail:
    in a,(c)
    ld (hl),a
    inc hl
    inc c
    djnz read_mixed_tail

    call clear_operands
    xor a
    out ($1E),a
    out ($1F),a

    pop af
    jp po,interrupts_restored
    ei
interrupts_restored:
    ld ix,appvar_name
    ld hl,frame
    ld bc,frame_end-frame
    call create_probe_appvar
    ret

clear_operands:
    ld c,$18
    ld d,6
clear_one_operand:
    ld b,4
    xor a
clear_one_byte:
    out (c),a
    djnz clear_one_byte
    inc c
    dec d
    jr nz,clear_one_operand
    ret

read_result:
    ld c,$1C
    ld b,4
read_result_byte:
    in a,(c)
    ld (hl),a
    inc hl
    inc c
    djnz read_result_byte
    ret

appvar_name:
    .db AppVarObj,"HWPMD511"

abc_operands:
    .db $01,$23,$45,$67
    .db $89,$AB,$CD,$EF
    .db $FE,$DC,$BA,$98
    .db $76,$54,$32,$10
    .db $61,$62,$63,$80
    .db $78,$A4,$6A,$D7

frame:
    .db "HWP1",1,1
    .dw payload_end-payload
frame_asic:
    .db 0
frame_status:
    .db 0
payload:
payload_valid:
    .fill 4,0
payload_undefined:
    .fill 4,0
payload_fifth:
    .fill 4,0
payload_masked:
    .fill 4,0
payload_mixed:
    .fill 4,0
payload_end:
frame_end:
