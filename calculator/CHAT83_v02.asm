.nolist
#include "ti83plus.inc"
.list

.org userMem - 2
.db t2ByteTok, tAsmCmp

start:
new_question:
    xor a
    ld (inlen),a
    ld (input),a
    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,title
    bcall(_PutS)
    ld a,2
    ld (curRow),a
    xor a
    ld (curCol),a
    ld hl,prompt
    bcall(_PutS)

key_loop:
    bcall(_GetKey)
    cp kClear
    ret z
    cp kEnter
    jp z,send_question
    cp kDel
    jr z,delete_key
    cp kSpace
    jr z,space_key
    cp kCapA
    jr c,number_key
    cp kCapZ+1
    jr nc,key_loop
    sub kCapA-'A'
    jr append_key

number_key:
    cp k0
    jr c,key_loop
    cp k9+1
    jr nc,key_loop
    sub k0-'0'
    jr append_key

space_key:
    ld a,' '
append_key:
    ld c,a
    ld a,(inlen)
    cp 12
    jr nc,key_loop
    ld e,a
    ld d,0
    ld hl,input
    add hl,de
    ld a,c
    ld (hl),a
    inc hl
    xor a
    ld (hl),a
    ld a,(inlen)
    inc a
    ld (inlen),a
    jr show_input

delete_key:
    ld a,(inlen)
    or a
    jr z,key_loop
    dec a
    ld (inlen),a
    ld e,a
    ld d,0
    ld hl,input
    add hl,de
    ld (hl),0
show_input:
    ld a,3
    ld (curRow),a
    xor a
    ld (curCol),a
    ld hl,blank
    bcall(_PutS)
    ld a,3
    ld (curRow),a
    xor a
    ld (curCol),a
    ld hl,input
    bcall(_PutS)
    jp key_loop

send_question:
    ld a,(inlen)
    or a
    jp z,key_loop
    ld a,(inlen)
    bcall(_SendAByte)
    ld hl,input
    ld (ptr),hl
send_loop:
    ld a,(inlen)
    or a
    jr z,receive_reply
    ld hl,(ptr)
    ld a,(hl)
    bcall(_SendAByte)
    ld hl,(ptr)
    inc hl
    ld (ptr),hl
    ld a,(inlen)
    dec a
    ld (inlen),a
    jr send_loop

receive_reply:
    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,waitmsg
    bcall(_PutS)
    bcall(_RecAByteIO)
    cp 49
    jr nc,bad_length
    ld (remaining),a
    ld hl,reply
    ld (ptr),hl
recv_loop:
    ld a,(remaining)
    or a
    jr z,show_reply
    bcall(_RecAByteIO)
    ld hl,(ptr)
    ld (hl),a
    inc hl
    ld (ptr),hl
    ld a,(remaining)
    dec a
    ld (remaining),a
    jr recv_loop

show_reply:
    ld hl,(ptr)
    ld (hl),0
    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,replytitle
    bcall(_PutS)
    ld a,2
    ld (curRow),a
    xor a
    ld (curCol),a
    ld (column),a
    ld hl,reply
    ld (ptr),hl
print_loop:
    ld hl,(ptr)
    ld a,(hl)
    or a
    jr z,await_next
    bcall(_PutC)
    ld hl,(ptr)
    inc hl
    ld (ptr),hl
    ld a,(column)
    inc a
    cp 12
    jr nz,save_col
    xor a
    ld (column),a
    ld a,(curRow)
    inc a
    ld (curRow),a
    xor a
    ld (curCol),a
    jr print_loop
save_col:
    ld (column),a
    jr print_loop

bad_length:
    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,badmsg
    bcall(_PutS)
await_next:
    bcall(_GetKey)
    cp kClear
    ret z
    cp kEnter
    jp z,new_question
    jr await_next

title:      .db "CHAT83 V0.2",0
prompt:     .db "YOU:",0
blank:      .db "            ",0
waitmsg:    .db "WAITING PC...",0
replytitle: .db "PC REPLY:",0
badmsg:     .db "BAD LENGTH",0
inlen:      .db 0
remaining:  .db 0
column:     .db 0
ptr:        .dw 0
input:      .db 0,0,0,0,0,0,0,0,0,0,0,0,0
reply:      .db 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.end
