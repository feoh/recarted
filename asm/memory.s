; ReCarted! type-41 RAM loader. Bank 0 holds this program; banks 1..15
; contain a page-aligned payload. The Atari OS calls start via CARTAD.
.segment "CODE"
.org $a000
params = $bf00
start:
    sei
    cld
    lda #0
    sta $d40e                 ; keep ANTIC NMIs out of the copy loop
    sta $d400
    lda $d301
    ora #2                     ; RAM, not BASIC, under the cartridge
    sta $d301
    ldx #ram_end-copy
move: lda source-1,x
    sta copy-1,x
    dex
    bne move
    lda params
    sta dest+2
    lda params+1
    sta remaining
    lda params+2
    sta go+1
    lda params+3
    sta go+2
    lda params+4
    sta $0c                    ; cassette init vector
    lda params+5
    sta $0d
    jmp copy
source:
.org $0100                     ; bottom of stack page (no JSRs while here)
copy:
    ldx #1
    ldy #0
byte:
    sta $d500,x                ; select 8 KiB bank X
src: lda $a000,y
    sta $d510                  ; release cartridge before writing to RAM
 dest: sta $1000,y
    iny
    bne byte
    inc dest+2
    inc src+2
    lda src+2
    cmp #$c0
    bne next
    lda #$a0
    sta src+2
    inx
next: dec remaining
    bne byte
    lda $d013
    sta $03fa                  ; sync XL cartridge interlock with new state
    lda #$c0
    sta $6a
    lda #2
    sta $09                    ; cassette boot flag (also used by Bruce Lee)
    lda #0
    sta $0244
    lda #$40
    sta $d40e
    cli
go: jmp $ffff
remaining: .byte 0
ram_end:
.assert ram_end < $01c0, error, "loader exceeds stack reservation"
