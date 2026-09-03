.nolist
#include "ti83plus.inc"
.list

.org userMem

program_start:
    ld hl, 0
    add hl, sp
    ld (saved_sp), hl

    ld hl, program_name
    ld de, OP1
    ld bc, 9
    ldir
    bcall(_ChkFindSym)
    jr c, lookup_failed

    ex de, hl
    ld de, result_area - program_start + 4
    add hl, de
    ld (result_ptr), hl

    ex de, hl
    ld hl, result_header
    ld bc, result_header_end - result_header
    ldir
    ld (result_ptr), de

    ld a, 1
    call capture_snapshot

    ld hl, 0
    add hl, sp
    ld (saved_sp), hl
    ld a, 2
    call capture_snapshot

    bcall(_MemChk)
    ld (nested_memchk), hl

    ld hl, 0
    add hl, sp
    ld (saved_sp), hl
    ld a, 3
    call capture_snapshot

    ld hl, 0
    add hl, sp
    ld (saved_sp), hl
    ld a, 4
    call capture_snapshot

lookup_failed:
    ret

capture_snapshot:
    push af
    push bc
    push de
    push hl
    push ix

    ld ix, (result_ptr)
    ld (ix + 0), a

    ld hl, (fpBase)
    ld (ix + 1), l
    ld (ix + 2), h
    ld hl, (FPS)
    ld (ix + 3), l
    ld (ix + 4), h
    ld hl, (OPBase)
    ld (ix + 5), l
    ld (ix + 6), h
    ld hl, (OPS)
    ld (ix + 7), l
    ld (ix + 8), h
    ld hl, (pTemp)
    ld (ix + 9), l
    ld (ix + 10), h
    ld hl, (progPtr)
    ld (ix + 11), l
    ld (ix + 12), h
    ld hl, symTable
    ld (ix + 13), l
    ld (ix + 14), h
    ld hl, (saved_sp)
    ld (ix + 15), l
    ld (ix + 16), h

    ld hl, (OPS)
    ld de, (FPS)
    or a
    sbc hl, de
    jr c, memchk_zero
    inc hl
    jr store_memchk
memchk_zero:
    ld hl, 0
store_memchk:
    ld (ix + 17), l
    ld (ix + 18), h

    ld de, 19
    add ix, de
    ld (result_ptr), ix

    pop ix
    pop hl
    pop de
    pop bc
    pop af
    ret

program_name:
    .db 5, "RTSNAP", 0, 0

result_header:
    .db "RTSNAP01"
    .db 19
    .db 4
result_header_end:

saved_sp:
    .dw 0
result_ptr:
    .dw 0
nested_memchk:
    .dw 0

result_area:
    .fill 96, 0

program_end:
