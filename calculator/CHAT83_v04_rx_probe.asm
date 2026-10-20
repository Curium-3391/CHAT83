.nolist
#include "ti83plus.inc"
.list

.org userMem - 2
.db t2ByteTok, tAsmCmp

; CHAT83 v0.4 LAB 1: cooperative RX/keyboard hardware probe
; TARGET: ORIGINAL TI-83 PLUS ONLY (not 83+ SE / 84+).
; On original 83+ PORT 00 bit 2 enables byte receive assist.
; PORT 00 bit 3 => byte ready; IN (05h) fetches + acknowledges it.
; Port 05h on the SE/84+ is RAM paging, NOT the same RX register.
; The upstream Uno is unchanged, and sends 128 bytes after 'S'.
;
; Observe:
;  RX:80  after 128 bytes
;  LAST:7F
;  XOR:00
;  KEY:xx increments when UP or DOWN is pressed during transfer.
; The first byte from Python must arrive AFTER port 00=04h.

start:
    xor a
    out (00h),a
    ld (received),a
    ld (last_rx),a
    ld (xor_sum),a
    ld (key_count),a
    ld (last_key),a
    call draw_static
    call draw_values

    ld a,'S'
    bcall(_SendAByte)
    ; Enable hardware receiver only AFTER the ROM send routine returns.
    ld a,04h
    out (00h),a

event_loop:
    ; Incoming byte has priority over screen drawing / keyboard scan.
    in a,(00h)
    bit 3,a
    jr z,poll_keys
    in a,(05h)
    ld (last_rx),a
    ld b,a
    ld a,(xor_sum)
    xor b
    ld (xor_sum),a
    ld a,(received)
    inc a
    ld (received),a

    ; Do not repaint every byte: only every 8 bytes.
    and 07h
    jr nz,poll_keys
    call draw_values

poll_keys:
    bcall(_GetCSC)                 ; scan code, no blocking wait
    ld b,a
    ld a,(last_key)
    cp b
    jr z,event_loop
    ld a,b
    ld (last_key),a
    cp skClear
    jr z,quit_cleanly
    cp skUp
    jr z,key_hit
    cp skDown
    jr nz,event_loop
key_hit:
    ld a,(key_count)
    inc a
    ld (key_count),a
    call draw_values
    jr event_loop

quit_cleanly:
    xor a
    out (00h),a                   ; release lines and disable RX assist
    ret

draw_static:
    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,title
    bcall(_PutS)
    ld a,6
    call set_row
    ld hl,help
    bcall(_PutS)
    ld a,7
    call set_row
    ld hl,footer
    bcall(_PutS)
    ret

set_row:
    ld (curRow),a
    xor a
    ld (curCol),a
    ret

draw_values:
    ld a,2
    call set_row
    ld hl,rx_label
    bcall(_PutS)
    ld a,(received)
    call print_hex
    ld a,3
    call set_row
    ld hl,last_label
    bcall(_PutS)
    ld a,(last_rx)
    call print_hex
    ld a,4
    call set_row
    ld hl,xor_label
    bcall(_PutS)
    ld a,(xor_sum)
    call print_hex
    ld a,5
    call set_row
    ld hl,key_label
    bcall(_PutS)
    ld a,(key_count)
    call print_hex
    ret

print_hex:
    ld (print_val),a
    and 0F0h
    rrca
    rrca
    rrca
    rrca
    call hex_nibble
    ld a,(print_val)
    and 0Fh
hex_nibble:
    cp 10
    jr c,hex_digit
    add a,7
hex_digit:
    add a,'0'
    bcall(_PutC)
    ret

title:      .db "CHAT83 RX LAB",0
rx_label:   .db "RX:   ",0
last_label: .db "LAST: ",0
xor_label:  .db "XOR:  ",0
key_label:  .db "KEY:  ",0
help:       .db "UP/DOWN: TEST",0
footer:     .db "CLEAR: EXIT",0

received:   .db 0
last_rx:    .db 0
xor_sum:    .db 0
key_count:  .db 0
last_key:   .db 0
print_val:  .db 0

.end
