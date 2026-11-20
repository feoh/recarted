; Read-only D1: driver for two specifically recognized 90 KiB boot disks.
; Copy the XL/XE's own OS to the RAM underneath it, then redirect DSKINV.
; The OS itself is neither part of ReCarted nor stored in the .car.
.segment "CODE"
.org $a000
params = $bf00
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
    lda #$4c
    sta $e453
    lda #<driver
    sta $e454
    lda #>driver
    sta $e455
    lda params
    sta $0304
    clc
    adc #6
    sta enter+1
    lda params+1
    sta $0305
    adc #0
    sta enter+2
    lda params+2
    sta nboot
    lda #$31
    sta $0300
    lda #1
    sta $0301
    sta $030a
    sta $09
    lda #0
    sta $030b
    sta $0244
    lda #$52
    sta $0302
    jmp load_boot
source:
.org $0400
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
load_boot:
    sta $d510
    lda $d013
    sta $03fa
    lda #$c0
    sta $6a
    lda #$40
    sta $d40e
    cli
read_boot:
    jsr driver
    clc
    lda $0304
    adc #128
    sta $0304
    bcc skip
    inc $0305
skip: inc $030a
    dec nboot
    bne read_boot
enter: jmp $ffff
nboot: .byte 0
r_end:
.assert r_end < $0600, error, "boot code overlaps boot sectors"
; Continue emitting bytes in bank 0, with run addresses in shadow OS RAM.
.org $a000+(source-start)+(r_end-reloc)
handler_src:
.org $cc00                     ; international font, unused by these recipes
driver:
    lda $0302
    cmp #$52
    bne fail
    lda $0301
    cmp #1
    bne fail
    ; One-based sector, 64 sectors per 8 KiB bank; max 720 sectors ($2d0).
    sec
    lda $030a
    sbc #1
    sta low
    lda $030b
    sbc #0
    cmp #3
    bcs fail
    cmp #2
    bne in_range
    ldy low
    cpy #$d0
    bcs fail
in_range:
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
    tax
    inx
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
low: .byte 0
high: .byte 0
handler_end:
.assert handler_end-driver < 256, error, "handler too big"
