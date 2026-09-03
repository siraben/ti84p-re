; Safe execution probe for two numeric bcalls found in community source.
.org $9D95

    ld iy,$89F0
    ld hl,$BCA1
    ld ($9872),hl

    rst $28
    .dw $5011          ; _FillBasePageTable
    rst $28
    .dw $5014          ; _ArcChk

    ld hl,($839F)
    ld ($9874),hl
    ld hl,($83A1)
    ld ($9876),hl
    ld hl,$600D
    ld ($9878),hl
    ret
