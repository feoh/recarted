; Captured RAM plus a read-only D1: for a disk that keeps reading sectors after
; its protected boot. Copy the XL/XE's own OS to the RAM underneath it, point
; DSKINV at a window of sectors stored in later banks, restore the program RAM
; captured at the hand-off and enter it. Neither the OS nor the original boot
; loader is stored in the .car.
.segment "CODE"
.org $a000
params = $bf00
; +0 first RAM page  +1 page count  +2/+3 entry  +4 first disk bank
; +5/+6 first sector  +7/+8 sector count
start:
    sei
    cld
    lda #0
    sta $d40e
    sta $d400
    lda $d301
    ora #3
    sta $d301
    ; Relocate the OS copy loop to RAM so its absolute operands are writable.
    ldx #r_end-reloc
move: lda source-1,x
    sta reloc-1,x
    dex
    bne move
    jsr reloc
    ; Now executing with RAM OS selected, cartridge bank 0 still visible.
    ldx #handler_end-driver
put: lda handler_src-1,x
    sta driver-1,x
    dex
    bne put
    ldx #4
window: lda params+4,x
    sta base,x
    dex
    bpl window
    lda #$4c
    sta $e453
    lda #<driver
    sta $e454
    lda #>driver
    sta $e455
    ; A disk boot leaves D1: in the DCB; some programs never set it again.
    lda #$31
    sta $0300
    lda #1
    sta $0301
    ldx #c_end-copy
put_copy: lda copy_src-1,x
    sta copy-1,x
    dex
    bne put_copy
    lda params
    sta dest+2
    lda params+1
    sta remaining
    lda params+2
    sta go+1
    lda params+3
    sta go+2
    jmp copy
source:
.org $0400                     ; overwritten later by the captured RAM
reloc:
    ldy #0
os_page:
    lda $d301
    ora #1
    sta $d301
os_read: ldx $c000,y
    and #$fe
    sta $d301
    txa
os_write: sta $c000,y
    iny
    bne os_page
    inc os_read+2
    inc os_write+2
    lda os_read+2
    cmp #$d0
    bne check
    lda #$d8
    sta os_read+2
    sta os_write+2
check: lda os_read+2
    bne os_page
    rts
r_end:
.assert r_end < $0500, error, "OS copy loop too big"
; Continue emitting bytes in bank 0, with run addresses in the stack page.
.org $a000+(source-start)+(r_end-reloc)
copy_src:
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
    ; The capture held only zeros above its last stored page; recreate them.
    lda dest+2
    sta fill+2
    lda #0
clear: ldx fill+2
    cpx #$c0
    beq done
fill: sta $ff00,y
    iny
    bne fill
    inc fill+2
    bne clear
done:
    lda $d013
    sta $03fa                  ; sync XL cartridge interlock with new state
    lda #$c0
    sta $6a
    lda #2
    sta $09
    lda #0
    sta $0244
    lda #$40
    sta $d40e
    cli
go: jmp $ffff
remaining: .byte 0
c_end:
.assert c_end < $01c0, error, "loader exceeds stack reservation"
; Continue emitting bytes in bank 0, with run addresses in shadow OS RAM.
.org $a000+(source-start)+(r_end-reloc)+(c_end-copy)
handler_src:
.org $cc00                     ; international font, unused by this recipe
driver:
    lda $0302
    cmp #$52
    bne fail
    lda $0301
    cmp #1
    bne fail
    ; Index into the stored window: sector - first, 64 sectors per bank.
    sec
    lda $030a
    sbc first
    sta low
    lda $030b
    sbc first+1
    sta high
    bcc fail                   ; below the window
    lda low
    cmp count
    lda high
    sbc count+1
    bcs fail                   ; past the window
    lda high
    asl
    asl
    sta high
    lda low
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr
    ora high
    clc
    adc base
    tax
    lda low
    lsr
    and #$1f
    ora #$a0
    sta fetch+2
    lda #0
    ror                        ; carry = sector offset bit 0
    sta fetch+1
    lda $0304
    sta store+1
    lda $0305
    sta store+2
    inc $42                    ; suppress deferred OS VBI during bank changes
    ldy #0
loop: sta $d500,x
fetch: lda $a000,y
    sta $d510
store: sta $ffff,y
    iny
    bpl loop
    dec $42
    ldy #1
    bne finish
fail: ldy #$8b                 ; unsupported (including writes)
finish: sty $0303
    tya
    rts
base: .byte 0
first: .word 0
count: .word 0
low: .byte 0
high: .byte 0
handler_end:
.assert handler_end-driver < 256, error, "handler too big"
