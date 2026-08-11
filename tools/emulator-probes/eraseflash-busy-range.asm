; Emulator-only erase-busy read-range fixture.
;
; This program exits unless page 3C contains the return shim produced by
; build_flash_emulator_fixture.py.  It erases only the first certificate half
; in the copied ROM image.  Do not remove the signature check.

.org $9D95

start:
    ld a,i
    push af
    di

    ld a,$3C
    out ($06),a
    ld hl,$7068
    ld de,patch_signature
    ld b,8
check_patch:
    ld a,(de)
    cp (hl)
    jr nz,guard_abort
    inc de
    inc hl
    djnz check_patch
    jr patch_ok
guard_abort:
    jp abort

    ; Unlock Flash through the protected page-3C wrapper.
patch_ok:
    call $7058

    ; Issue AA 55 80 AA 55 30 directly, targeting 3E:4000.
    ld a,$02
    out ($06),a
    ld a,$AA
    ld ($6AAA),a
    ld a,$01
    out ($06),a
    ld a,$55
    ld ($5555),a
    ld a,$02
    out ($06),a
    ld a,$80
    ld ($6AAA),a
    ld a,$02
    out ($06),a
    ld a,$AA
    ld ($6AAA),a
    ld a,$01
    out ($06),a
    ld a,$55
    ld ($5555),a
    ld a,$3E
    out ($06),a
    ld a,$30
    ld ($4000),a

    ; DQ3 distinguishes TilEm's active erase from its short command window.
wait_active:
    ld a,($4000)
    bit 3,a
    jr z,wait_active

    ; Sample both selected-sector ends, the adjacent top-boot sector, the
    ; preceding 32 KiB sector, the boot sector, and a distant archive sector.
    ld a,($4000)
    ld (busy_selected_start),a
    ld a,($5FFF)
    ld (busy_selected_end),a
    ld a,($6000)
    ld (busy_adjacent_start),a

    ld a,$3D
    out ($06),a
    ld a,($7FFF)
    ld (busy_preceding_end),a

    ld a,$3F
    out ($06),a
    ld a,($4000)
    ld (busy_boot_start),a

    ld a,$08
    out ($06),a
    ld a,($4000)
    ld (busy_distant_start),a

    ; Wait for array data, then capture the same boundaries after completion.
    ld a,$3E
    out ($06),a
wait_complete:
    ld a,($4000)
    bit 7,a
    jr z,wait_complete
    ld (final_selected_start),a
    ld a,($5FFF)
    ld (final_selected_end),a
    ld a,($6000)
    ld (final_adjacent_start),a

    ld a,$3D
    out ($06),a
    ld a,($7FFF)
    ld (final_preceding_end),a

    ld a,$3F
    out ($06),a
    ld a,($4000)
    ld (final_boot_start),a

    ld a,$08
    out ($06),a
    ld a,($4000)
    ld (final_distant_start),a

    ; Relock through the original protected page-3C sequence.
    ld a,$3C
    out ($06),a
    call $66D5

restore_interrupts:
    pop af
    jp po,done
    ei
done:
    ret

abort:
    jr restore_interrupts

patch_signature:
    .db $F1,$C9,$00,$00,$00,$00,$00,$00
busy_selected_start:
    .db $FF
busy_selected_end:
    .db $FF
busy_adjacent_start:
    .db $FF
busy_preceding_end:
    .db $FF
busy_boot_start:
    .db $FF
busy_distant_start:
    .db $FF
final_selected_start:
    .db $00
final_selected_end:
    .db $00
final_adjacent_start:
    .db $00
final_preceding_end:
    .db $00
final_boot_start:
    .db $00
final_distant_start:
    .db $00
