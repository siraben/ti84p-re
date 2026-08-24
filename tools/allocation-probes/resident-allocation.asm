.nolist
#include "ti83plus.inc"
.list

.org userMem

program_start:
    ld hl, 16
    bcall(_EnoughMem)
after_enough_mem:

    ld hl, appvar_name
    bcall(_Mov9ToOP1)
    ld hl, 32
    bcall(_CreateAppVar)
after_create_appvar:
    ld hl, appvar_name
    bcall(_Mov9ToOP1)
    bcall(_ChkFindSym)
    bcall(_DelVar)
after_delete_appvar:

    ld hl, program_name
    bcall(_Mov9ToOP1)
    ld hl, 32
    bcall(_CreateProg)
after_create_program:
    ld hl, program_name
    bcall(_Mov9ToOP1)
    bcall(_ChkFindSym)
    bcall(_DelVar)
after_delete_program:

    call find_self
    ld (source_before), de
    ex de, hl
    ld de, 16
    add hl, de
    ld (source_expected_up), hl

    ld de, (source_before)
    ld hl, 16
    bcall(_InsertMem)
    call find_self
    ld (source_after_insert), de
after_insert_mem:

    ld hl, (source_before)
    ld de, 16
    bcall(_DelMem)
    call find_self
    ld (source_after_delete), de
after_delete_mem:

    bcall(_MemChk)
    ld (max_free_before), hl
    ld de, 14
    or a
    sbc hl, de
    ld (max_request), hl
    inc hl
    bcall(_EnoughMem)
    ld a, 0
    adc a, 0
    ld (max_plus_one_carry), a

    ld hl, max_name
    bcall(_Mov9ToOP1)
    ld hl, (max_request)
    bcall(_CreateAppVar)
after_max_create:
    ld hl, max_name
    bcall(_Mov9ToOP1)
    bcall(_ChkFindSym)
    bcall(_DelVar)
after_max_delete:

    ret

find_self:
    ld hl, self_name
    bcall(_Mov9ToOP1)
    bcall(_ChkFindSym)
    ret

appvar_name:
    .db AppVarObj, "ALAPP", 0, 0, 0
program_name:
    .db ProgObj, "ALPRG", 0, 0, 0
self_name:
    .db ProgObj, "ALPROBE", 0
max_name:
    .db AppVarObj, "ALMAX", 0, 0, 0

source_before:
    .dw 0
source_expected_up:
    .dw 0
source_after_insert:
    .dw 0
source_after_delete:
    .dw 0
max_free_before:
    .dw 0
max_request:
    .dw 0
max_plus_one_carry:
    .db 0

execution_guard:
    .db $51, $A7, $32, $EC, $09, $D4, $6B, $F0
execution_guard_end:

program_end:
