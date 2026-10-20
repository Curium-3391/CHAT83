.nolist
#include "ti83plus.inc"
.list

.org userMem - 2
.db t2ByteTok, tAsmCmp

; CHAT83 v0.3.1 experimental remote history terminal
; 'S' sync; 'O' older; 'N' newer; 'Q'+LEN+ASCII question.
; Page = 'P'+COUNT+VIEW+FLAGS+COUNT*12 ASCII bytes.
; FLAGS bit 0: older records exist; bit 1: newer records exist.
; Cache: 24 rows * 13 bytes (12 chars and terminator).

start:
    xor a
    ld (input_len),a
    ld (input_buf),a
    ld (line_count),a
    ld (view_start),a
    ld (page_flags),a
    ld (cursor_row),a
    ld a,'S'
    ld (request_kind),a
    bcall(_SendAByte)
    jp recv_page

history_keys:
    bcall(_GetKey)
    cp kClear
    ret z
    cp kEnter
    jp z,input_screen
    cp kUp
    jp z,scroll_up
    cp kDown
    jp z,scroll_down
    jr history_keys

scroll_up:
    ld a,(line_count)
    or a
    jp z,history_keys
    ld a,(cursor_row)
    or a
    jr z,up_edge
    dec a
    ld (cursor_row),a
    call draw_history
    jp history_keys
up_edge:
    ld a,(view_start)
    or a
    jr z,up_remote
    dec a
    ld (view_start),a
    call draw_history
    jp history_keys
up_remote:
    ld a,(page_flags)
    and 1
    jp z,history_keys       ; no older history: DO NOT retransmit
    ld a,'O'
    ld (request_kind),a
    bcall(_SendAByte)
    jp recv_page

scroll_down:
    ld a,(line_count)
    or a
    jp z,history_keys
    ld a,(view_start)
    ld b,a
    ld a,(cursor_row)
    add a,b
    inc a                    ; next absolute cached line
    ld b,a
    ld a,(line_count)
    cp b
    jr z,down_remote
    ld a,(cursor_row)
    cp 5
    jr z,down_shift
    inc a
    ld (cursor_row),a
    call draw_history
    jp history_keys
down_shift:
    ld a,(view_start)
    inc a
    ld (view_start),a
    call draw_history
    jp history_keys
down_remote:
    ld a,(page_flags)
    and 2
    jp z,history_keys       ; latest line: no needless PC request
    ld a,'N'
    ld (request_kind),a
    bcall(_SendAByte)
    jp recv_page

input_screen:
    xor a
    ld (input_len),a
    ld (input_buf),a
    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,ask_title
    bcall(_PutS)
    ld a,2
    ld (curRow),a
    xor a
    ld (curCol),a
    ld hl,ask_label
    bcall(_PutS)
    call draw_input

input_keys:
    bcall(_GetKey)
    cp kClear
    jp z,leave_input
    cp kEnter
    jp z,send_question
    cp kDel
    jp z,delete_key
    cp kSpace
    jr z,space_key
    cp kCapA
    jr c,number_key
    cp kCapZ+1
    jr nc,input_keys
    sub kCapA-'A'
    jr append_key
number_key:
    cp k0
    jr c,input_keys
    cp k9+1
    jr nc,input_keys
    sub k0-'0'
    jr append_key
space_key:
    ld a,' '
append_key:
    ld c,a
    ld a,(input_len)
    cp 12
    jr nc,input_keys
    ld e,a
    ld d,0
    ld hl,input_buf
    add hl,de
    ld a,c
    ld (hl),a
    inc hl
    ld (hl),0
    ld a,(input_len)
    inc a
    ld (input_len),a
    call draw_input
    jp input_keys

delete_key:
    ld a,(input_len)
    or a
    jp z,input_keys
    dec a
    ld (input_len),a
    ld e,a
    ld d,0
    ld hl,input_buf
    add hl,de
    ld (hl),0
    call draw_input
    jp input_keys

leave_input:
    call draw_history
    jp history_keys

draw_input:
    ld a,3
    ld (curRow),a
    xor a
    ld (curCol),a
    ld hl,blank13
    bcall(_PutS)
    ld a,3
    ld (curRow),a
    xor a
    ld (curCol),a
    ld hl,input_buf
    bcall(_PutS)
    ld a,(input_len)
    ld (curCol),a
    ld a,'_'
    bcall(_PutC)             ; visible, steady input caret
    ret

send_question:
    ld a,(input_len)
    or a
    jp z,input_keys
    ld a,'Q'
    ld (request_kind),a
    bcall(_SendAByte)
    ld a,(input_len)
    bcall(_SendAByte)
    ld hl,input_buf
    ld (ptr),hl
    ld a,(input_len)
    ld (remaining),a
send_loop:
    ld a,(remaining)
    or a
    jr z,show_wait
    ld hl,(ptr)
    ld a,(hl)
    bcall(_SendAByte)
    ld hl,(ptr)
    inc hl
    ld (ptr),hl
    ld a,(remaining)
    dec a
    ld (remaining),a
    jr send_loop
show_wait:
    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,waiting
    bcall(_PutS)
    jp recv_page

recv_page:
    bcall(_RecAByteIO)
    cp 'P'
    jp nz,bad_page
    bcall(_RecAByteIO)
    cp 25
    jp nc,bad_page
    ld (line_count),a
    bcall(_RecAByteIO)
    ld (view_start),a
    bcall(_RecAByteIO)       ; paging flags in v0.3.1 header
    cp 4
    jp nc,bad_page
    ld (page_flags),a
    ld a,(line_count)
    or a
    jr z,empty_page
    ld b,a
    ld a,(view_start)
    cp b
    jp nc,bad_page
empty_page:
    xor a
    ld (row_index),a
row_loop:
    ld a,(row_index)
    ld b,a
    ld a,(line_count)
    cp b
    jr z,page_done
    ld a,(row_index)
    call row_addr
    ld (ptr),hl
    ld a,12
    ld (remaining),a
byte_loop:
    bcall(_RecAByteIO)
    cp 32
    jr nc,check_ascii_high
    ld a,'?'
check_ascii_high:
    cp 127
    jr c,write_byte
    ld a,'?'
write_byte:
    ld hl,(ptr)
    ld (hl),a
    inc hl
    ld (ptr),hl
    ld a,(remaining)
    dec a
    ld (remaining),a
    jr nz,byte_loop
    ld hl,(ptr)
    ld (hl),0
    ld a,(row_index)
    inc a
    ld (row_index),a
    jr row_loop
page_done:
    ld a,(request_kind)
    cp 'O'
    jr z,select_top
    cp 'N'
    jr z,select_top
    ; SYNC and ASK: select the newest visible row
    ld a,(line_count)
    or a
    jr z,select_top
    dec a
    ld b,a
    ld a,(view_start)
    ld c,a
    ld a,b
    sub c
    cp 6
    jr c,select_end
    ld a,5
select_end:
    ld (cursor_row),a
    jr show_new_page
select_top:
    xor a
    ld (cursor_row),a
show_new_page:
    call draw_history
    jp history_keys

bad_page:
    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,error_msg
    bcall(_PutS)
error_wait:
    bcall(_GetKey)
    cp kClear
    jr nz,error_wait
    ret

row_addr:
    ld hl,history_cache
    or a
    ret z
    ld bc,13
row_addr_loop:
    add hl,bc
    dec a
    jr nz,row_addr_loop
    ret

draw_history:
    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,history_title
    bcall(_PutS)
    ld a,7
    ld (curRow),a
    xor a
    ld (curCol),a
    ld hl,history_help
    bcall(_PutS)
    ld a,(line_count)
    or a
    jr nz,draw_rows
    ld a,2
    ld (curRow),a
    xor a
    ld (curCol),a
    ld hl,none_msg
    bcall(_PutS)
    ret

draw_rows:
    ld a,(view_start)
    ld (draw_index),a
    ld a,1
    ld (draw_row),a
draw_loop:
    ld a,(draw_row)
    cp 7
    ret nc
    ld a,(draw_index)
    ld b,a
    ld a,(line_count)
    cp b
    ret z
    ld a,(draw_index)
    call row_addr
    ld a,(draw_row)
    ld (curRow),a
    xor a
    ld (curCol),a
    bcall(_PutS)
    ld a,(draw_row)
    dec a
    ld b,a
    ld a,(cursor_row)
    cp b
    jr nz,no_history_cursor
    ld a,(draw_row)
    ld (curRow),a
    ld a,14
    ld (curCol),a
    ld a,'>'
    bcall(_PutC)
no_history_cursor:
    ld a,(draw_index)
    inc a
    ld (draw_index),a
    ld a,(draw_row)
    inc a
    ld (draw_row),a
    jr draw_loop

history_title: .db "CHAT83 V0.3.1",0
history_help:  .db "ENTER:ASK",0
ask_title:     .db "CHAT83 INPUT",0
ask_label:     .db "YOU:",0
waiting:       .db "WAIT FOR PC",0
error_msg:     .db "PAGE ERROR",0
none_msg:      .db "NO HISTORY",0
blank13:       .db "             ",0
input_len:     .db 0
input_buf:     .db 0,0,0,0,0,0,0,0,0,0,0,0,0
line_count:    .db 0
view_start:    .db 0
cursor_row:    .db 0
page_flags:    .db 0
request_kind:  .db 0
row_index:     .db 0
remaining:     .db 0
draw_index:    .db 0
draw_row:      .db 0
ptr:           .dw 0
history_cache:
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 0
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 1
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 2
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 3
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 4
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 5
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 6
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 7
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 8
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 9
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 10
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 11
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 12
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 13
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 14
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 15
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 16
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 17
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 18
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 19
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 20
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 21
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 22
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; row 23
history_end:
.end
