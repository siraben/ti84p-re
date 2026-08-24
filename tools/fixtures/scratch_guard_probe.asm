.NOLIST
#include "tools/ti83plus.inc"
.LIST

; Compiled-Asm fixture for the saveSScreen/statVars lifetime claims. Load this
; together with a TI-BASIC wrapper whose body is Asm(prgmSCRPROBE), then drive
; that wrapper with scratch-guard-probe.macro. Direct PRGM > EXEC treats the
; BB 6D program as TI-BASIC and reports an error.
; The fixture intentionally tests only the two WikiTI conditional SafeRAM
; claims. It does not claim that the other advertised scratch ranges are safe.
; The ASCRATCH wrapper built by build_scratch_probe_wrapper.py supplies the
; required Asm(prgmSCRPROBE) launch path.

.org 9D93h
.db 0BBh,06Dh

    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,waiting_text
    bcall(_PutS)

    ; Consume the ENTER that starts Asm(prgmSCRPROBE) before installing the
    ; guards. The following _GetKey is then the measured wait.
    bcall(_GetKey)

    bcall(_DisableApd)
    bcall(_DelRes)

    ld hl,saveSScreen
    ld de,saveSScreen+1
    ld bc,767
    ld (hl),0A5h
    ldir

    ld hl,statVars
    ld de,statVars+1
    ld bc,530
    ld (hl),05Ah
    ldir

    ; Exercise raw polling before entering the cooked, blocking input path.
    ld b,100
poll_loop:
    push bc
    bcall(_GetCSC)
    pop bc
    djnz poll_loop

    bcall(_GetKey)

    ld hl,saveSScreen
    ld bc,768
    ld a,0A5h
    call check_fill
    ld a,0
    jr nz,save_done
    inc a
save_done:
    ld (save_result),a

    ld hl,statVars
    ld bc,531
    ld a,05Ah
    call check_fill
    ld a,0
    jr nz,stat_done
    inc a
stat_done:
    ld (stat_result),a

    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,result_text
    bcall(_PutS)
    ld a,(save_result)
    add a,'0'
    bcall(_PutC)
    ld a,' '
    bcall(_PutC)
    ld a,(stat_result)
    add a,'0'
    bcall(_PutC)
    bcall(_GetKey)
    ret

; A = fill byte, HL = start, BC = size. Returns Z if every byte matches.
check_fill:
    cp (hl)
    ret nz
    inc hl
    dec bc
    push af
    ld a,b
    or c
    jr z,check_done
    pop af
    jr check_fill
check_done:
    pop af
    cp a
    ret

waiting_text:
    .db "SCRATCH GUARD",0
result_text:
    .db "SAVE STAT ",0
save_result:
    .db 0
stat_result:
    .db 0
