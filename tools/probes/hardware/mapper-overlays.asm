; Restoring memory-mapper overlay probe.
; Result AppVar: HWPMAP01, probe ID 14, payload 47 bytes.
; Requires the normal TI-OS independent mapping on entry.

.org $9D95
    jp start
#include "common.inc"

start:
    ld a,i
    push af
    push ix
    push iy
    di

    in a,($15)
    ld (frame_asic),a
    in a,($02)
    ld (frame_status),a
    in a,($03)
    ld (payload_pre_port03),a
    in a,($04)
    ld (payload_pre_port04),a
    in a,($05)
    ld (payload_pre_port05),a
    in a,($06)
    ld (payload_pre_port06),a
    in a,($07)
    ld (payload_pre_port07),a
    in a,($0E)
    ld (payload_pre_port0e),a
    in a,($0F)
    ld (payload_pre_port0f),a
    in a,($27)
    ld (payload_pre_port27),a
    in a,($28)
    ld (payload_pre_port28),a

    ld a,(payload_pre_port05)
    or a
    jp nz,abort_port05
    ld a,(payload_pre_port06)
    cp $3F
    jp nz,abort_port06
    ld a,(payload_pre_port07)
    cp $81
    jp nz,abort_port07
    ld a,(payload_pre_port0e)
    or a
    jp nz,abort_port0e
    ld a,(payload_pre_port0f)
    or a
    jp nz,abort_port0f
    ld a,(payload_pre_port27)
    or a
    jp nz,abort_port27
    ld a,(payload_pre_port28)
    or a
    jp nz,abort_port28
    ld hl,$0CE6
    ld de,fixed_helper_signature
    ld b,5
check_fixed_helper:
    ld a,(de)
    cp (hl)
    jp nz,abort_helper_signature
    inc de
    inc hl
    djnz check_fixed_helper

    ; Create a pending result before changing RAM mappings or marker bytes.
    ld ix,appvar_name
    ld hl,frame
    ld bc,frame_end-frame
    call create_probe_appvar
    ex de,hl
    ld de,-(frame_end-frame)
    add hl,de
    ld (result_frame_ptr),hl
    ld a,1
    ld (result_created),a
    di

    ; AppVar creation runs OS code. Repeat the complete direct-Asm mapping
    ; contract before the first marker write.
    in a,($05)
    or a
    jp nz,abort_post_create
    in a,($06)
    cp $3F
    jp nz,abort_post_create
    in a,($07)
    cp $81
    jp nz,abort_post_create
    in a,($0E)
    or a
    jp nz,abort_post_create
    in a,($0F)
    or a
    jp nz,abort_post_create
    in a,($27)
    or a
    jp nz,abort_post_create
    in a,($28)
    or a
    jp nz,abort_post_create

    ; Back up and seed page 0 while it is still mapped through window C.
    ld a,($FB3F)
    ld (page0_backup+0),a
    ld a,$43
    ld ($FB3F),a
    ld a,($FB40)
    ld (page0_backup+1),a
    ld a,$44
    ld ($FB40),a
    ld a,($FB63)
    ld (page0_backup+2),a
    ld a,$45
    ld ($FB63),a
    ld a,($FB64)
    ld (page0_backup+3),a
    ld a,$46
    ld ($FB64),a
    ld a,($FFBF)
    ld (page0_backup+4),a
    ld a,$47
    ld ($FFBF),a
    ld a,($FFC0)
    ld (page0_backup+5),a
    ld a,$48
    ld ($FFC0),a

    ; Map physical RAM page 1 into C. The probe continues from B until the
    ; position-independent worker jumps to the page-1 alias of its own bytes.
    ld a,1
    out ($05),a
    ld ix,payload+$4000
    ld iy,marker_backup+$4000
    jp mapper_worker+$4000

abort_port05:
    ld a,1
    jr set_abort
abort_port06:
    ld a,2
    jr set_abort
abort_port07:
    ld a,3
    jr set_abort
abort_port0e:
    ld a,4
    jr set_abort
abort_port0f:
    ld a,5
    jr set_abort
abort_port27:
    ld a,6
    jr set_abort
abort_port28:
    ld a,7
    jr set_abort
abort_post_create:
    ld a,8
    jr set_abort
abort_helper_signature:
    ld a,9
set_abort:
    ld (payload_outcome),a
    jp finish

worker_return:
    ; The worker has restored independent mode and the B selector before this
    ; jump, so the original logical program address is mapped again.
    xor a
    out ($05),a

    ; Restore and verify the six page-0 bytes through normal window C.
    ld a,(page0_backup+0)
    ld ($FB3F),a
    ld b,a
    ld a,($FB3F)
    cp b
    jr nz,page0_restore_failed
    ld a,(page0_backup+1)
    ld ($FB40),a
    ld b,a
    ld a,($FB40)
    cp b
    jr nz,page0_restore_failed
    ld a,(page0_backup+2)
    ld ($FB63),a
    ld b,a
    ld a,($FB63)
    cp b
    jr nz,page0_restore_failed
    ld a,(page0_backup+3)
    ld ($FB64),a
    ld b,a
    ld a,($FB64)
    cp b
    jr nz,page0_restore_failed
    ld a,(page0_backup+4)
    ld ($FFBF),a
    ld b,a
    ld a,($FFBF)
    cp b
    jr nz,page0_restore_failed
    ld a,(page0_backup+5)
    ld ($FFC0),a
    ld b,a
    ld a,($FFC0)
    cp b
    jr nz,page0_restore_failed
    ld a,(payload_restore_flags)
    or 1
    ld (payload_restore_flags),a
page0_restore_failed:

    ld a,(payload_pre_port05)
    out ($05),a
    in a,($03)
    ld (payload_post_port03),a
    in a,($04)
    ld (payload_post_port04),a
    in a,($05)
    ld (payload_post_port05),a
    in a,($06)
    ld (payload_post_port06),a
    in a,($07)
    ld (payload_post_port07),a
    in a,($0E)
    ld (payload_post_port0e),a
    in a,($0F)
    ld (payload_post_port0f),a
    in a,($27)
    ld (payload_post_port27),a
    in a,($28)
    ld (payload_post_port28),a

    ld a,(payload_outcome)
    cp $FF
    jr nz,finish
    xor a
    ld (payload_outcome),a

finish:
    ld a,(result_created)
    or a
    jr z,create_final_result
    ld de,(result_frame_ptr)
    ld hl,frame
    ld bc,frame_end-frame
    ldir
    jr result_ready
create_final_result:
    ld ix,appvar_name
    ld hl,frame
    ld bc,frame_end-frame
    call create_probe_appvar
    ex de,hl
    ld de,-(frame_end-frame)
    add hl,de
    ld (result_frame_ptr),hl
result_ready:
    pop iy
    pop ix
    pop af
    jp po,interrupts_restored
    ei
interrupts_restored:
    ld ix,(result_frame_ptr)
    ld bc,frame_end-frame
    ld hl,display_label
    call display_probe_code
    ret

; This worker uses only relative control flow until it restores the B mapping.
; IX addresses the frame through its physical-page-1 window-C alias. IY
; addresses private marker backups through the same alias.
mapper_worker:
    ; Seed and back up page 1 through C.
    ld hl,$C000
    ld de,$C03F
    ld bc,$C040
    ld a,(hl)
    ld (iy+0),a
    ld a,(de)
    ld (iy+1),a
    ld a,(bc)
    ld (iy+2),a
    ld a,$A1
    ld (hl),a
    ld a,$A2
    ld (de),a
    ld a,$A3
    ld (bc),a

    ; Seed and back up page 2 through B.
    ld a,$82
    out ($07),a
    ld hl,$8000
    ld de,$803F
    ld bc,$8040
    ld a,(hl)
    ld (iy+3),a
    ld a,(de)
    ld (iy+4),a
    ld a,(bc)
    ld (iy+5),a
    ld a,$B1
    ld (hl),a
    ld a,$B2
    ld (de),a
    ld a,$B3
    ld (bc),a

    ; Independent-mode port-0x28 read and write routing.
    ld a,1
    out ($28),a
    ld a,($8000)
    ld (ix+10),a
    ld a,($803F)
    ld (ix+11),a
    ld a,($8040)
    ld (ix+12),a
    ld a,$C1
    ld ($8000),a
    xor a
    out ($28),a
    ld a,($8000)
    ld (ix+19),a
    ld a,1
    out ($28),a
    ld a,($8000)
    ld (ix+20),a
    xor a
    out ($28),a

    ; Back up and seed the page-1 addresses used by port 0x27.
    ld a,($FB3F)
    ld (iy+6),a
    ld a,$46
    ld ($FB3F),a
    ld a,($FB40)
    ld (iy+7),a
    ld a,$47
    ld ($FB40),a
    ld a,($FB63)
    ld (iy+8),a
    ld a,$48
    ld ($FB63),a
    ld a,($FB64)
    ld (iy+9),a
    ld a,$49
    ld ($FB64),a
    ld a,($FFBF)
    ld (iy+10),a
    ld a,$4A
    ld ($FFBF),a
    ld a,($FFC0)
    ld (iy+11),a
    ld a,$4B
    ld ($FFC0),a

    ; Independent-mode port-0x27 boundaries and write routing.
    ld a,$13
    out ($27),a
    ld a,($FB3F)
    ld (ix+13),a
    ld a,($FB40)
    ld (ix+14),a
    ld a,($FB63)
    ld (ix+15),a
    ld a,($FB64)
    ld (ix+16),a
    ld a,$D1
    ld ($FB40),a
    xor a
    out ($27),a
    ld a,($FB40)
    ld (ix+21),a
    ld a,$13
    out ($27),a
    ld a,($FB40)
    ld (ix+22),a
    ld a,1
    out ($27),a
    ld a,($FFBF)
    ld (ix+17),a
    ld a,($FFC0)
    ld (ix+18),a
    xor a
    out ($27),a

    ; Restore test sentinels before the paired-mode pass.
    ld a,$A1
    ld ($C000),a
    ld a,$13
    out ($27),a
    ld a,$44
    ld ($FB40),a
    xor a
    out ($27),a
    ld a,$41
    ld ($FB40),a

    ; Paired C remains on page 1 through port 0x07 while A/B use RAM pages
    ; 2 and 3. This keeps both the worker and all test writes in RAM.
    ld a,$81
    out ($07),a
    ld a,$82
    out ($06),a
    xor a
    out ($0E),a
    out ($0F),a
    ld a,7
    out ($04),a

    ; Back up and seed page 3 through paired window B.
    ld hl,$8000
    ld de,$803F
    ld bc,$8040
    ld a,(hl)
    ld (iy+12),a
    ld a,(de)
    ld (iy+13),a
    ld a,(bc)
    ld (iy+14),a
    ld a,$E1
    ld (hl),a
    ld a,$E2
    ld (de),a
    ld a,$E3
    ld (bc),a

    ld a,1
    out ($28),a
    ld a,($8000)
    ld (ix+23),a
    ld a,($803F)
    ld (ix+24),a
    ld a,($8040)
    ld (ix+25),a
    ld a,$C2
    ld ($8000),a
    xor a
    out ($28),a
    ld a,($8000)
    ld (ix+32),a
    ld a,1
    out ($28),a
    ld a,($8000)
    ld (ix+33),a
    xor a
    out ($28),a

    ld a,$13
    out ($27),a
    ld a,($FB3F)
    ld (ix+26),a
    ld a,($FB40)
    ld (ix+27),a
    ld a,($FB63)
    ld (ix+28),a
    ld a,($FB64)
    ld (ix+29),a
    ld a,$D2
    ld ($FB40),a
    xor a
    out ($27),a
    ld a,($FB40)
    ld (ix+34),a
    ld a,$13
    out ($27),a
    ld a,($FB40)
    ld (ix+35),a
    ld a,1
    out ($27),a
    ld a,($FFBF)
    ld (ix+30),a
    ld a,($FFC0)
    ld (ix+31),a
    xor a
    out ($27),a

    ; Even Flash selector discriminator: Wabbitemu duplicates page 0 into B;
    ; TilEm and the public contract expose adjacent page 1.
    xor a
    out ($06),a
    ld a,($9000)
    ld (ix+36),a

    ; Restore page 3 while paired.
    ld a,$82
    out ($06),a
    ld a,(iy+12)
    ld ($8000),a
    ld a,(iy+13)
    ld ($803F),a
    ld a,(iy+14)
    ld ($8040),a

    ; Return to independent mode with page 1 in B and page 1 still in C.
    ld a,$81
    out ($07),a
    ld a,6
    out ($04),a

    ; Restore the page-1 lower markers.
    ld a,(iy+0)
    ld ($C000),a
    ld a,(iy+1)
    ld ($C03F),a
    ld a,(iy+2)
    ld ($C040),a

    ; Restore the page-1 upper markers.
    ld a,(iy+6)
    ld ($FB3F),a
    ld a,(iy+7)
    ld ($FB40),a
    ld a,(iy+8)
    ld ($FB63),a
    ld a,(iy+9)
    ld ($FB64),a
    ld a,(iy+10)
    ld ($FFBF),a
    ld a,(iy+11)
    ld ($FFC0),a

    ; Restore page 2 through B.
    ld a,$82
    out ($07),a
    ld a,(iy+3)
    ld ($8000),a
    ld a,(iy+4)
    ld ($803F),a
    ld a,(iy+5)
    ld ($8040),a
    ld a,$81
    out ($07),a

    ; Restore all saved selectors except port 0x05, which the B-side return
    ; path restores after this worker is no longer executing through C.
    ld a,(ix+3)
    out ($06),a
    ld a,(ix+4)
    out ($07),a
    ld a,(ix+5)
    out ($0E),a
    ld a,(ix+6)
    out ($0F),a
    ld a,(ix+7)
    out ($27),a
    ld a,(ix+8)
    out ($28),a
    ld a,$0E
    ld (ix+37),a
    jp worker_return

page0_backup:
    .fill 6,0
marker_backup:
    ; page 1 low (3), page 2 low (3), page 1 upper (6), page 3 low (3)
    .fill 15,0
result_created:
    .db 0
result_frame_ptr:
    .dw 0
fixed_helper_signature:
    .db $F5,$23,$2B,$F1,$C9

display_label:
    .db "HWPMAP CODE ",0
#include "display.inc"

appvar_name:
    .db AppVarObj,"HWPMAP01"

frame:
    .db "HWP1",1,14
    .dw payload_end-payload
frame_asic:
    .db 0
frame_status:
    .db 0
payload:
payload_pre_port03: .db 0
payload_pre_port04: .db 0
payload_pre_port05: .db 0
payload_pre_port06: .db 0
payload_pre_port07: .db 0
payload_pre_port0e: .db 0
payload_pre_port0f: .db 0
payload_pre_port27: .db 0
payload_pre_port28: .db 0
payload_outcome: .db $FF
payload_independent_reads: .fill 9,0
payload_independent_writes: .fill 4,0
payload_paired_reads: .fill 9,0
payload_paired_writes: .fill 4,0
payload_paired_even_flash_b: .db 0
payload_restore_flags: .db 0
payload_post_port03: .db 0
payload_post_port04: .db 0
payload_post_port05: .db 0
payload_post_port06: .db 0
payload_post_port07: .db 0
payload_post_port0e: .db 0
payload_post_port0f: .db 0
payload_post_port27: .db 0
payload_post_port28: .db 0
payload_end:
frame_end:
