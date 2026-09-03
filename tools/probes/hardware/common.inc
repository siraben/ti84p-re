; Shared definitions for TI-83+/84+ physical hardware probes.

userMem             .equ $9D95
OP1                 .equ $8478
AppVarObj           .equ $15
_CreateAppVar       .equ $4E6A

; Copy the frame named by HL/BC into a newly created AppVar.
; The caller supplies IX = 9-byte OP1 name and must ensure it does not exist.
create_probe_appvar:
    push hl
    push bc
    push ix
    pop hl
    ld de,OP1
    ld bc,9
    ldir
    pop bc
    pop hl
    push bc
    push hl
    ld h,b
    ld l,c
    rst $28
    .dw _CreateAppVar
    pop hl
    pop bc
    ; _CreateAppVar returns DE at the AppVar's internal size word.
    inc de
    inc de
    ldir
    ret
