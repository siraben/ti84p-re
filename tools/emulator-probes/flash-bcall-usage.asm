; Guarded programmer-facing Flash bcall usage probe.
;
; The native Wabbitemu runner boots the exact retail ROM, injects this program
; into RAM page 1, opens only its in-memory Flash gate, seeds disposable Flash
; bytes, and validates every result below.  This probe does not implement the
; privileged port-14 unlock or a physical power-loss test.

.org $9D95

writeflash_af        .equ $9F00
writeflashunsafe_af  .equ $9F02
writeabytesafe_af    .equ $9F04
writeabyte_af        .equ $9F06
erasepage_af         .equ $9F08
eraseflash_af        .equ $9F0A
erasecertificate_af  .equ $9F0C
bound_iff_af         .equ $9F0E
writeflash_copy      .equ $9F20
writeflashunsafe_copy .equ $9F22
writeabytesafe_copy  .equ $9F24
writeabyte_copy      .equ $9F25
erasepage_copy       .equ $9F26
eraseflash_copy      .equ $9F27
erasecertificate_copy .equ $9F28

start:
    di
    ld iy,$89F0

    ; _WriteFlash: program two RAM-source bytes at 08:4100.
; executable-snippet-begin: write-flash
    ld a,$08
    ld de,$4100
    ld hl,writeflash_payload
    ld bc,writeflash_payload_end-writeflash_payload
    rst $28
    .dw $80C9
    or a
    jp nz,flash_failed
; executable-snippet-end: write-flash
    push af
    pop hl
    ld (writeflash_af),hl

    ; Read the complete programmed span back through _FlashToRam.
; executable-snippet-begin: flash-to-ram
    ld a,$08
    ld hl,$4100
    ld de,writeflash_copy
    ld bc,writeflash_payload_end-writeflash_payload
    rst $28
    .dw $5017
; executable-snippet-end: flash-to-ram

    ; _WriteFlashUnsafe: page 3E is accepted by the unsafe entry.
; executable-snippet-begin: write-flash-unsafe
    ld a,$3E
    ld de,$4100
    ld hl,writeflashunsafe_payload
    ld bc,writeflashunsafe_payload_end-writeflashunsafe_payload
    rst $28
    .dw $8087
    or a
    jp nz,flash_failed
; executable-snippet-end: write-flash-unsafe
    push af
    pop hl
    ld (writeflashunsafe_af),hl

    ld a,$3E
    ld hl,$4100
    ld de,writeflashunsafe_copy
    ld bc,writeflashunsafe_payload_end-writeflashunsafe_payload
    rst $28
    .dw $5017

    ; _WriteAByteSafe: perform the monotonic FE -> FC marker update.
; executable-snippet-begin: write-a-byte-safe
    ld a,$08
    ld de,$4102
    ld b,$FC
    rst $28
    .dw $80C6
    or a
    jp nz,flash_failed
; executable-snippet-end: write-a-byte-safe
    push af
    pop hl
    ld (writeabytesafe_af),hl

    ld a,$08
    ld hl,$4102
    ld de,writeabytesafe_copy
    ld bc,1
    rst $28
    .dw $5017

    ; _WriteAByte: page 3E is accepted and B is copied through OP1.
; executable-snippet-begin: write-a-byte
    ld a,$3E
    ld de,$4102
    ld b,$F8
    rst $28
    .dw $8021
    or a
    jp nz,flash_failed
; executable-snippet-end: write-a-byte
    push af
    pop hl
    ld (writeabyte_af),hl

    ld a,$3E
    ld hl,$4102
    ld de,writeabyte_copy
    ld bc,1
    rst $28
    .dw $5017

    ; _EraseFlashPage: page 0C selects physical sector 30000..3FFFF.
    ; DE is a defensive Flash reset pointer for the DQ5 failure tail.
; executable-snippet-begin: erase-flash-page
    ld a,$0C
    ld de,$4000
    rst $28
    .dw $8084
    or a
    jp nz,flash_failed
; executable-snippet-end: erase-flash-page
    push af
    pop hl
    ld (erasepage_af),hl

    ld a,$0C
    ld hl,$4000
    ld de,erasepage_copy
    ld bc,1
    rst $28
    .dw $5017

    ; _EraseFlash: an address inside page 10 selects its 64 KiB sector.
    ; DE mirrors HL so the DQ5 failure reset still targets Flash.
; executable-snippet-begin: erase-flash
    ld a,$10
    ld hl,$4567
    ld de,$4567
    rst $28
    .dw $8024
    or a
    jp nz,flash_failed
; executable-snippet-end: erase-flash
    push af
    pop hl
    ld (eraseflash_af),hl

    ld a,$10
    ld hl,$4567
    ld de,eraseflash_copy
    ld bc,1
    rst $28
    .dw $5017

    ; _EraseCertificateSector accepts H=60h without requiring L=0 and restores
    ; the caller's complete AF instead of returning the worker result.
; executable-snippet-begin: erase-certificate-sector
    ld hl,$A545
    push hl
    pop af
    ld hl,$6001
    ld de,$6001
    rst $28
    .dw $8060
; executable-snippet-end: erase-certificate-sector
    push af
    pop hl
    ld (erasecertificate_af),hl

    ld a,$3E
    ld hl,$6001
    ld de,erasecertificate_copy
    ld bc,1
    rst $28
    .dw $5017

    ; _SetFlashLowerBound actually writes the port-23 upper bound.  Enable
    ; interrupts first so the bcall's final DI is observable.
    ei
    nop
; executable-snippet-begin: set-flash-lower-bound
    ld a,$2A
    rst $28
    .dw $80CF
; executable-snippet-end: set-flash-lower-bound
    ld a,i
    push af
    pop hl
    ld (bound_iff_af),hl

    halt

flash_failed:
    jr flash_failed

writeflash_payload:
    .db $A5,$5A
writeflash_payload_end:
writeflashunsafe_payload:
    .db $3C,$C3
writeflashunsafe_payload_end:
