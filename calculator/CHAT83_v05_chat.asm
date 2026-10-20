.nolist
#include "ti83plus.inc"
.list

.org userMem - 2
.db t2ByteTok, tAsmCmp

; CHAT83 v0.5 EXPERIMENTAL -- original TI-83 Plus only
; Nonblocking port-0 RX assist, cooperative _GetCSC, predictive row prefetch.
; Protocol only for new Arduino Uno v0.5 + bridge_v05.py.
; Requires bridge/bridge_v04.py, six-row C frames.
;
; Frame: C SEQ START0 START1 START2 START3 COUNT FLAGS ROWS XOR
; FLAGS 1=older, 2=newer, 4=RESET, 8=LLM_BUSY, 16=LLM_ERR. MAX 6 rows per frame.
; Active ring 24*13 bytes, staging received frame 81 bytes.
; UI keeps selected/visible rows anchored when prefetch commits.
; Only one requested frame can be in flight.

CACHE_ROWS EQU 48
MAX_INPUT EQU 48

start:
    xor a
    out (00h),a
    ld (rx_pos),a
    ld (request_kind),a
    ld (cache_head),a
    ld (cache_count),a
    ld (cursor_off),a
    ld (view_off),a
    ld (page_flags),a
    ld (last_key),a
    ld (pending_enter),a
    ld (error_flag),a
    ld (exit_flag),a
    ld (sequence),a
    ld (cache_start),a
    ld (cache_start+1),a
    ld (cache_start+2),a
    ld (cache_start+3),a
    ld (evicted_flag),a
    ld (busy_flag),a
    ld (model_error),a
    ld (input_mode),a
    ld (input_cursor),a
    ld (poll_timer),a
    ld (poll_timer+1),a
    ld (retry_count),a
    ld a,0FFh                  ; initially prefetch older after SYNC
    ld (direction),a
    call draw_loading
    ld a,'S'
    ld (request_kind),a
    bcall(_SendAByte)
    call enable_rx

main_loop:
    call poll_rx
    call poll_keys
    ld a,(exit_flag)
    or a
    jr nz,exit_program
    ld a,(pending_enter)
    or a
    jr z,loop_plan
    ld a,(request_kind)
    or a
    jr nz,loop_plan
    xor a
    ld (pending_enter),a
    call input_screen
loop_plan:
    ld a,(input_mode)
    or a
    jr nz,no_background
    call maybe_prefetch
    call poll_live
no_background:
    jp main_loop

exit_program:
    xor a
    out (00h),a
    ret

enable_rx:
    ld a,04h
    out (00h),a
    ret

disable_rx:
    xor a
    out (00h),a
    ret

; RX assist returns immediately if no complete byte is available.
poll_rx:
    ld a,(request_kind)
    or a
    ret z
    in a,(00h)
    bit 3,a
    ret z
    in a,(05h)
    ld b,a
    ld a,(rx_pos)
    or a
    jr nz,rx_store
    ld a,b
    cp 'C'
    jp nz,packet_error
rx_store:
    ld a,b
    call crc8_update
    ld a,(rx_pos)
    ld e,a
    ld d,0
    ld hl,rx_frame
    add hl,de
    ld (hl),b
    ld a,(rx_pos)
    inc a
    ld (rx_pos),a
    cp 8
    jr nz,rx_check_done

    ; C header complete. Validate COUNT, FLAGS before body.
    ld a,(rx_frame+6)
    cp 7
    jp nc,packet_error
    ld b,a
    ld a,(rx_frame+7)
    cp 32
    jp nc,packet_error
    ; 9 + 12 * count, max 81 bytes
    ld a,(rx_frame+6)
    ld b,a
    ld a,9
    ld c,a
    ld a,b
    or a
    ld a,c
    jr z,expected_store
expected_loop:
    add a,12
    djnz expected_loop
expected_store:
    ld (rx_expected),a

rx_check_done:
    ld a,(rx_pos)
    ld b,a
    ld a,(rx_expected)
    cp b
    ret nz
    ld a,(crc_state)
    or a
    jp nz,retry_frame
    xor a
    ld (rx_pos),a
    ld (crc_state),a
    call commit_frame
    ret

packet_error:
    xor a
    ld (request_kind),a
    ld (rx_pos),a
    ld (crc_state),a
    inc a
    ld (error_flag),a
    call draw_error
    ret

; One completed frame with bad CRC can be retransmitted without repeating
; the original Q (which would otherwise duplicate SQLite messages).
retry_frame:
    ld a,(retry_count)
    cp 3
    jp nc,packet_error
    inc a
    ld (retry_count),a
    call disable_rx
    ld a,'R'
    ld (retry_wire),a
    ld a,(request_kind)
    cp 'F'
    jr nz,retry_seq_zero
    ld a,(expect_seq)
    jr retry_seq_ready
retry_seq_zero:
    xor a
retry_seq_ready:
    ld (retry_wire+1),a
    xor a
    ld (crc_state),a
    ld hl,retry_wire
    ld b,2
    call crc8_buffer
    ld a,(crc_state)
    ld (retry_wire+2),a
    ld hl,retry_wire
    ld a,3
    call send_bytes
    call reset_receiver_state
    call enable_rx
    ret

; A=byte, update cumulative CRC8 (poly 07, init 00), preserves BC/HL.
crc8_update:
    push bc
    ld c,a
    ld a,(crc_state)
    xor c
    ld b,8
crc8_bit:
    add a,a
    jr nc,crc8_no_poly
    xor 07h
crc8_no_poly:
    djnz crc8_bit
    ld (crc_state),a
    pop bc
    ret
; HL pointer, B length; updates crc_state, preserves HL and B at return.
crc8_buffer:
crc8_buffer_loop:
    ld a,(hl)
    call crc8_update
    inc hl
    djnz crc8_buffer_loop
    ret

; Fixed six-row frame commit. All header and checksum checks before modifying
; ring data; repeated row payload bytes remain only in RX staging buffer.
commit_frame:
    xor a
    ld (retry_count),a
    ld (evicted_flag),a
    ld a,(request_kind)
    cp 'F'
    jr nz,non_fetch_frame
    ld a,(rx_frame+1)
    ld b,a
    ld a,(expect_seq)
    cp b
    jp nz,packet_error
    ld hl,fetch_start
    ld de,rx_frame+2
    ld b,4
validate_start:
    ld a,(de)
    cp (hl)
    jp nz,packet_error
    inc de
    inc hl
    djnz validate_start
    ld a,(rx_frame+7)
    and 4
    jp nz,packet_error
    ld a,(pending_dir)
    or a
    jp z,commit_newer
    jp commit_older

non_fetch_frame:
    ld a,(rx_frame+1)
    or a
    jp nz,packet_error       ; S/Q replies must carry SEQ=0
    ld a,(request_kind)
    cp 'S'
    jr z,commit_reset
    cp 'Q'
    jr z,non_fetch_q
    cp 'U'
    jp z,commit_newer
    cp 'K'
    jp z,commit_newer
    jp packet_error
non_fetch_q:
    ld a,(rx_frame+7)
    and 4
    jr nz,commit_reset
    jp commit_newer          ; incremental reply must append at cache end

commit_reset:
    xor a
    ld (cache_head),a
    ld (cache_count),a
    ld (cursor_off),a
    ld (view_off),a
    ld hl,rx_frame+2
    ld de,cache_start
    ld bc,4
    ldir
    ld a,(rx_frame+6)
    ld (rows_to_copy),a
    xor a
    ld (stage_index),a
reset_loop:
    ld a,(stage_index)
    ld b,a
    ld a,(rows_to_copy)
    cp b
    jr z,reset_done
    ld a,(cache_count)
    call copy_stage_to_logical
    ld a,(cache_count)
    inc a
    ld (cache_count),a
    ld a,(stage_index)
    inc a
    ld (stage_index),a
    jp reset_loop
reset_done:
    ld a,(cache_count)
    or a
    jp z,apply_flags_draw
    dec a
    ld (cursor_off),a
    cp 6
    jr c,reset_small
    sub 5
    ld (view_off),a
    jp apply_flags_draw
reset_small:
    xor a
    ld (view_off),a
    jp apply_flags_draw

; Verify contiguous index and sufficient room to preserve 6 visible lines.
commit_older:
    ld a,(rx_frame+6)
    ld (rows_to_copy),a
    ; Each prepended row pushes current view/cursor indexes forward.
    ld a,(cache_count)
    ld b,a
    ld a,CACHE_ROWS
    sub b
    ld b,a
    ld a,(view_off)
    ld c,a
    ld a,(cache_count)
    sub c
    cp 6
    jr c,older_visible_len
    ld a,6
older_visible_len:
    add a,c
    ld c,a                    ; last protected index + 1
    ld a,(cache_count)
    sub c                     ; disposable tail count
    add a,b                   ; safe prepend budget
    ld b,a
    ld a,(rows_to_copy)
    cp b
    jr z,older_safe
    jr c,older_safe
    jp discard_prefetch
older_safe:
    ; Starting address must connect to current cache_start.
    ; request already bound by fetch_start; request count is <=6.
    ld a,(rows_to_copy)
    ld (stage_index),a
older_loop:
    ld a,(stage_index)
    or a
    jr z,older_done
    dec a
    ld (stage_index),a
    ld a,(cache_head)
    or a
    jr nz,older_head_dec
    ld a,CACHE_ROWS
older_head_dec:
    dec a
    ld (cache_head),a
    ld a,(cache_count)
    cp CACHE_ROWS
    jr nz,older_has_space
    ld a,2
    ld (evicted_flag),a
    jr older_not_evict
older_has_space:
    inc a
    ld (cache_count),a
older_not_evict:
    ld a,(cursor_off)
    inc a
    ld (cursor_off),a
    ld a,(view_off)
    inc a
    ld (view_off),a
    ld a,(stage_index)
    call copy_stage_to_logical_zero
    jp older_loop
older_done:
    ; Because rows form a contiguous older range, start = frame.START
    ld hl,rx_frame+2
    ld de,cache_start
    ld bc,4
    ldir
    jp apply_fetch_flags

; New lines append, evict oldest only when not on visible screen.
commit_newer:
    ; A previously selected tail must remain followed during incremental
    ; streaming updates, without forcibly jumping if the user scrolled away.
    xor a
    ld (follow_tail),a
    ld a,(cache_count)
    or a
    jr z,commit_newer_begin
    dec a
    ld b,a
    ld a,(cursor_off)
    cp b
    jr nz,commit_newer_begin
    ld a,1
    ld (follow_tail),a
commit_newer_begin:
    ld a,(rx_frame+6)
    ld (rows_to_copy),a
    ; Check that requested START equals cache_start + cache_count,
    ; except for Q + RESET handled earlier.
    ld hl,cache_start
    ld de,calc_addr
    ld bc,4
    ldir
    ld hl,calc_addr
    ld a,(cache_count)
    call add_u32
    ld hl,calc_addr
    ld de,rx_frame+2
    ld b,4
check_append_start:
    ld a,(de)
    cp (hl)
    jp nz,packet_error
    inc hl
    inc de
    djnz check_append_start

    ld a,(cache_count)
    ld b,a
    ld a,CACHE_ROWS
    sub b
    ld b,a
    ld a,(view_off)
    add a,b                  ; safe append budget
    ld b,a
    ld a,(rows_to_copy)
    cp b
    jr z,newer_safe
    jr c,newer_safe
    jp discard_prefetch
newer_safe:
    xor a
    ld (stage_index),a
newer_loop:
    ld a,(stage_index)
    ld b,a
    ld a,(rows_to_copy)
    cp b
    jr z,newer_done
    ld a,(cache_count)
    cp CACHE_ROWS
    jr nz,have_append_space
    ld a,1
    ld (evicted_flag),a
    ld a,(cache_head)
    inc a
    cp CACHE_ROWS
    jr c,store_new_head
    xor a
store_new_head:
    ld (cache_head),a
    ld hl,cache_start
    ld a,1
    call add_u32
    ld a,(cursor_off)
    dec a
    ld (cursor_off),a
    ld a,(view_off)
    dec a
    ld (view_off),a
    ld a,CACHE_ROWS-1
    ld (cache_count),a
have_append_space:
    ld a,(cache_count)
    call copy_stage_to_logical
    ld a,(cache_count)
    inc a
    ld (cache_count),a
    ld a,(stage_index)
    inc a
    ld (stage_index),a
    jr newer_loop
newer_done:
    ld a,(request_kind)
    cp 'Q'
    jr z,snap_to_tail
    cp 'U'
    jr z,update_tail
    cp 'K'
    jp z,apply_flags_draw
    jp apply_fetch_flags
update_tail:
    ld a,(follow_tail)
    or a
    jp z,apply_flags_draw
snap_to_tail:
    ld a,(cache_count)
    or a
    jp z,apply_flags_draw
    dec a
    ld (cursor_off),a
    cp 6
    jr c,newer_small
    sub 5
    ld (view_off),a
    jp apply_flags_draw
newer_small:
    xor a
    ld (view_off),a
    jp apply_flags_draw

discard_prefetch:
    ; Data was valid, but user moved during transmission. Keep selected and
    ; visible rows instead of evicting them. The next user movement replans.
    xor a
    ld (request_kind),a
    ld (direction),a
    ret

apply_fetch_flags:
    call read_model_flags
    ld a,(pending_dir)
    or a
    jr z,apply_newer_flags
    ; Fetching OLDER: trust response's older flag, retain existing newer
    ; boundary and set newer when old tail rows were evicted.
    ld a,(rx_frame+7)
    and 1
    ld b,a
    ld a,(page_flags)
    and 2
    or b
    ld b,a
    ld a,(evicted_flag)
    or b
    ld (page_flags),a
    xor a
    ld (request_kind),a
    ret
apply_newer_flags:
    ; Fetching NEWER: retain existing older boundary and set older if head
    ; rows were evicted. Newer boundary comes from fetched chunk end.
    ld a,(rx_frame+7)
    and 2
    ld b,a
    ld a,(page_flags)
    and 1
    or b
    ld b,a
    ld a,(evicted_flag)
    or b
    ld (page_flags),a
    xor a
    ld (request_kind),a
    ret

apply_flags_draw:
    call read_model_flags
    ld a,(rx_frame+7)
    and 3
    ld (page_flags),a
    xor a
    ld (request_kind),a
    call draw_history
    ret
apply_flags_nodraw:
    call read_model_flags
    ld a,(rx_frame+7)
    and 3
    ld (page_flags),a
    xor a
    ld (request_kind),a
    ret

read_model_flags:
    ld a,(rx_frame+7)
    and 8
    ld (busy_flag),a
    ld a,(rx_frame+7)
    and 16
    ld (model_error),a
    ret

; A=logical row index to write. Stage source = stage_index * 12.
copy_stage_to_logical:
    call ring_addr
    jp copy_row
copy_stage_to_logical_zero:
    xor a
    call ring_addr
copy_row:
    ex de,hl                 ; DE = active ring destination
    ld a,(stage_index)
    ld hl,rx_frame+8
    ld bc,12
    or a
    jr z,copy_row_ready
copy_stage_advance:
    add hl,bc
    dec a
    jr nz,copy_stage_advance
copy_row_ready:
    ld bc,12
    ldir
    xor a
    ld (de),a
    ret

; A=logical row index, returns HL -> 13-byte NUL terminated row.
ring_addr:
    ld b,a
    ld a,(cache_head)
    add a,b
    cp CACHE_ROWS
    jr c,ring_phys
    sub CACHE_ROWS
ring_phys:
    ld hl,history_cache
    ld bc,13
    or a
    ret z
ring_advance:
    add hl,bc
    dec a
    jr nz,ring_advance
    ret

; Add A(0..48) to four-byte little endian [HL].
add_u32:
    add a,(hl)
    ld (hl),a
    inc hl
    ld a,0
    adc a,(hl)
    ld (hl),a
    inc hl
    ld a,0
    adc a,(hl)
    ld (hl),a
    inc hl
    ld a,0
    adc a,(hl)
    ld (hl),a
    ret

; Subtract A(0..6) from 4-byte [HL], preserves borrow across LD/INC.
sub_u32:
    ld b,a
    ld a,(hl)
    sub b
    ld (hl),a
    inc hl
    ld a,(hl)
    sbc a,0
    ld (hl),a
    inc hl
    ld a,(hl)
    sbc a,0
    ld (hl),a
    inc hl
    ld a,(hl)
    sbc a,0
    ld (hl),a
    ret

; ---- Keypad and prefetch planner -------------------------------------
poll_keys:
    bcall(_GetCSC)
    ld b,a
    ld a,(last_key)
    cp b
    ret z
    ld a,b
    ld (last_key),a
    ld a,(input_mode)
    or a
    jr z,history_key
    ld a,b
    jp input_key
history_key:
    ld a,b
    cp skClear
    jr z,request_exit
    ld a,(error_flag)
    or a
    ret nz
    ld a,b
    cp skEnter
    jr z,request_input
    cp skUp
    jr z,key_up
    cp skDown
    jr z,key_down
    ret
request_exit:
    ld a,1
    ld (exit_flag),a
    ret
request_input:
    ld a,(busy_flag)
    or a
    ret nz                 ; Only one model response may be active.
    ld a,1
    ld (pending_enter),a
    ret
key_up:
    ld a,0FFh
    ld (direction),a
    ld a,(cache_count)
    or a
    ret z
    ld a,(cursor_off)
    or a
    ret z
    dec a
    ld (cursor_off),a
    ld b,a
    ld a,(view_off)
    cp b
    jr c,up_redraw
    jr z,up_redraw
    dec a
    ld (view_off),a
up_redraw:
    call draw_history
    ret
key_down:
    ld a,1
    ld (direction),a
    ld a,(cache_count)
    or a
    ret z
    ld b,a
    ld a,(cursor_off)
    inc a
    cp b
    ret nc
    ld (cursor_off),a
    ld b,a
    ld a,(view_off)
    add a,6
    cp b
    jr z,down_view
    jr c,down_view
    call draw_history
    ret
down_view:
    ld a,(view_off)
    inc a
    ld (view_off),a
    call draw_history
    ret

maybe_prefetch:
    ld a,(request_kind)
    or a
    ret nz
    ld a,(pending_enter)
    or a
    ret nz
    ld a,(error_flag)
    or a
    ret nz
    ld a,(cache_count)
    or a
    ret z
    ld a,(direction)
    or a
    ret z
    cp 0FFh
    jp z,try_older

try_newer:
    ld a,(page_flags)
    and 2
    ret z
    ld a,(cache_count)
    dec a
    ld b,a
    ld a,(cursor_off)
    ld c,a
    ld a,b
    sub c
    cp 17
    ret nc                  ; fetch ahead at the last one-third of 48 rows
    ld a,(cache_count)
    ld b,a
    ld a,CACHE_ROWS
    sub b
    ld b,a
    ld a,(view_off)
    add a,b
    jp nc,clamp_newer_count
    ret
clamp_newer_count:
    call clamp_six
    or a
    ret z
    ld (fetch_count),a
    xor a
    ld (pending_dir),a      ; zero = newer
    ld hl,cache_start
    ld de,fetch_start
    ld bc,4
    ldir
    ld hl,fetch_start
    ld a,(cache_count)
    call add_u32
    jp send_fetch

try_older:
    ld a,(page_flags)
    and 1
    ret z
    ld a,(cursor_off)
    cp 17
    ret nc                  ; fetch ahead at first one-third of 48 rows
    ld a,(cache_count)
    ld b,a
    ld a,CACHE_ROWS
    sub b
    ld (safe_space),a
    ld a,(view_off)
    ld c,a
    ld a,(cache_count)
    sub c
    cp 6
    jr c,older_len_ok
    ld a,6
older_len_ok:
    add a,c
    ld b,a
    ld a,(cache_count)
    sub b
    ld b,a
    ld a,(safe_space)
    add a,b
    call clamp_six
    or a
    ret z
    ld b,a
    ; Clamp requested older range to absolute zero.
    ld a,(cache_start+1)
    ld c,a
    ld a,(cache_start+2)
    or c
    ld c,a
    ld a,(cache_start+3)
    or c
    jr nz,older_count_set
    ld a,(cache_start)
    cp b
    jr nc,older_count_set
    ld b,a
older_count_set:
    ld a,b
    or a
    ret z
    ld (fetch_count),a
    ld a,1
    ld (pending_dir),a      ; one = older
    ld hl,cache_start
    ld de,fetch_start
    ld bc,4
    ldir
    ld hl,fetch_start
    ld a,(fetch_count)
    call sub_u32
    jp send_fetch

clamp_six:
    cp 7
    ret c
    ld a,6
    ret

send_fetch:
    ld a,(sequence)
    inc a
    jr nz,seq_ready
    inc a
seq_ready:
    ld (sequence),a
    ld (expect_seq),a
    ld a,'F'
    ld (fetch_wire),a
    ld a,(sequence)
    ld (fetch_wire+1),a
    ld a,(pending_dir)
    xor 1                  ; newer=1, older=0
    ld (fetch_wire+2),a
    ld hl,fetch_start
    ld de,fetch_wire+3
    ld bc,4
    ldir
    ld a,(fetch_count)
    ld (fetch_wire+7),a
    ld hl,fetch_wire
    ld b,8
    xor a
    ld (crc_state),a
wire_checksum:
    ; Placeholder replaced by CRC8 buffer below.
    ld a,(hl)
    call crc8_update
    inc hl
    djnz wire_checksum
    ld a,(crc_state)
    ld (fetch_wire+8),a
    call disable_rx
    ld hl,fetch_wire
    ld a,9
    call send_bytes
    ld a,'F'
    ld (request_kind),a
    call reset_receiver_state
    call enable_rx
    ret

send_bytes:
    ld (send_left),a
    ld (send_ptr),hl
send_byte_loop:
    ld a,(send_left)
    or a
    ret z
    ld hl,(send_ptr)
    ld a,(hl)
    bcall(_SendAByte)
    ld hl,(send_ptr)
    inc hl
    ld (send_ptr),hl
    ld a,(send_left)
    dec a
    ld (send_left),a
    jr send_byte_loop

reset_receiver_state:
    xor a
    ld (rx_pos),a
    ld (crc_state),a
    ld (rx_expected),a
    ret

; Cooperative live-update polling. F is only sent for history navigation;
; U appends generated assistant rows from SQLite without resetting UI.
; A Z80 keyboard scan is made every loop, even while U is in flight.
poll_live:
    ld a,(request_kind)
    or a
    ret nz
    ld a,(busy_flag)
    or a
    jr nz,live_status_ok
    ld a,(page_flags)
    and 2
    ret z
live_status_ok:
    ld a,(cache_count)
    or a
    ret z
    dec a
    ld b,a
    ld a,(cursor_off)
    cp b
    ret nz
    ld hl,(poll_timer)
    inc hl
    ld (poll_timer),hl
    ld a,h
    cp 8                   ; bounded quiet period between U probes
    ret c
    xor a
    ld (poll_timer),a
    ld (poll_timer+1),a
    call send_update
    ret

send_update:
    ld a,'U'
    ld (update_wire),a
    ld hl,cache_start
    ld de,calc_addr
    ld bc,4
    ldir
    ld hl,calc_addr
    ld a,(cache_count)
    call add_u32
    ld hl,calc_addr
    ld de,update_wire+1
    ld bc,4
    ldir
    xor a
    ld (crc_state),a
    ld hl,update_wire
    ld b,5
    call crc8_buffer
    ld a,(crc_state)
    ld (update_wire+5),a
    call disable_rx
    ld hl,update_wire
    ld a,6
    call send_bytes
    ld a,'U'
    ld (request_kind),a
    call reset_receiver_state
    call enable_rx
    ret

; ---- Input (only entered when no frame is inflight) -------------------
input_screen:
    xor a
    ld (input_len),a
    ld (input_buf),a
    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,ask_title
    bcall(_PutS)
    ld a,2
    call set_row
    ld hl,ask_label
    bcall(_PutS)
    call draw_input
input_keys:
    bcall(_GetKey)
    cp kClear
    jr z,input_cancel
    cp kEnter
    jp z,input_send
    cp kDel
    jp z,input_delete
    cp kSpace
    jr z,input_space
    cp kCapA
    jr c,input_number
    cp kCapZ+1
    jr nc,input_keys
    sub kCapA-'A'
    jp input_append
input_number:
    cp k0
    jr c,input_keys
    cp k9+1
    jr nc,input_keys
    sub k0-'0'
    jp input_append
input_space:
    ld a,' '
input_append:
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

input_delete:
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

input_cancel:
    call draw_history
    ret

input_send:
    ld a,(input_len)
    or a
    jp z,input_keys
    call disable_rx
    ld a,'Q'
    bcall(_SendAByte)
    ld a,(input_len)
    bcall(_SendAByte)
    ld hl,input_buf
    ld a,(input_len)
    call send_bytes
    ld a,(page_flags)
    and 2
    jr nz,input_not_latest
    ld a,1
    jr input_latest_ready
input_not_latest:
    xor a
input_latest_ready:
    bcall(_SendAByte)     ; at latest page? prevents bad delta concatenation
    ld a,'Q'
    ld (request_kind),a
    call reset_receiver_state
    call enable_rx
    call draw_loading
    ret

draw_input:
    ld a,3
    call set_row
    ld hl,blank13
    bcall(_PutS)
    ld a,3
    call set_row
    ld hl,input_buf
    bcall(_PutS)
    ld a,(input_len)
    ld (curCol),a
    ld a,'_'
    bcall(_PutC)
    ret

; ---- text UI ----------------------------------------------------------
set_row:
    ld (curRow),a
    xor a
    ld (curCol),a
    ret

draw_loading:
    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,title
    bcall(_PutS)
    ld a,3
    call set_row
    ld hl,loading
    bcall(_PutS)
    ret
draw_error:
    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,error_text
    bcall(_PutS)
    ld a,2
    call set_row
    ld hl,exit_help
    bcall(_PutS)
    ret

draw_history:
    bcall(_ClrLCDFull)
    bcall(_HomeUp)
    ld hl,title
    bcall(_PutS)
    ld a,7
    call set_row
    ld hl,history_help
    bcall(_PutS)
    ld a,(model_error)
    or a
    jr nz,show_model_error
    ld a,(busy_flag)
    or a
    jr z,history_no_state
    ld a,11
    ld (curCol),a
    ld hl,live_label
    bcall(_PutS)
    jr history_no_state
show_model_error:
    ld a,11
    ld (curCol),a
    ld hl,err_label
    bcall(_PutS)
history_no_state:
    ld a,(cache_count)
    or a
    jr nz,draw_rows
    ld a,2
    call set_row
    ld hl,empty_text
    bcall(_PutS)
    ret
draw_rows:
    ld a,(view_off)
    ld (draw_index),a
    ld a,1
    ld (draw_row),a
draw_row_loop:
    ld a,(draw_row)
    cp 7
    ret nc
    ld a,(draw_index)
    ld b,a
    ld a,(cache_count)
    cp b
    ret z
    ld a,(draw_index)
    call ring_addr
    ld a,(draw_row)
    call set_row
    bcall(_PutS)
    ld a,(draw_index)
    ld b,a
    ld a,(cursor_off)
    cp b
    jr nz,no_cursor
    ld a,(draw_row)
    ld (curRow),a
    ld a,14
    ld (curCol),a
    ld a,'>'
    bcall(_PutC)
no_cursor:
    ld a,(draw_index)
    inc a
    ld (draw_index),a
    ld a,(draw_row)
    inc a
    ld (draw_row),a
    jp draw_row_loop

title:          .db "CHAT83 V0.5",0
loading:        .db "RX IN BG...",0
error_text:     .db "LINK ERROR",0
exit_help:      .db "CLEAR: EXIT",0
empty_text:     .db "NO HISTORY",0
history_help:   .db "ENTER:ASK",0
live_label:     .db "AI",0
err_label:      .db "ERR",0
ask_title:      .db "CHAT83 INPUT",0
ask_label:      .db "YOU:",0
blank13:        .db "             ",0

; ---- RAM state; explicit storage for old calculators / SPASM-ng ------
rx_pos:         .db 0
crc_state:      .db 0
rx_expected:    .db 0
request_kind:   .db 0
error_flag:     .db 0
exit_flag:      .db 0
last_key:       .db 0
pending_enter:  .db 0
cache_head:     .db 0
cache_count:    .db 0
cache_start:    .db 0,0,0,0
cursor_off:     .db 0
view_off:       .db 0
page_flags:     .db 0
direction:      .db 0
pending_dir:    .db 0
fetch_count:    .db 0
safe_space:     .db 0
evicted_flag:   .db 0
busy_flag:      .db 0
model_error:    .db 0
follow_tail:    .db 0
poll_timer:     .dw 0
retry_count:    .db 0
input_mode:     .db 0
input_cursor:   .db 0
alpha_mode:     .db 0
retry_wire:     .db 0,0,0
update_wire:    .db 0,0,0,0,0,0
sequence:       .db 0
expect_seq:     .db 0
stage_index:    .db 0
rows_to_copy:   .db 0
draw_index:     .db 0
draw_row:       .db 0
input_len:      .db 0
input_buf:      .db 0,0,0,0,0,0,0,0,0,0,0,0,0
send_ptr:       .dw 0
send_left:      .db 0
fetch_start:    .db 0,0,0,0
calc_addr:      .db 0,0,0,0
fetch_wire:     .db 0,0,0,0,0,0,0,0,0
rx_frame:
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0
    .db 0,0,0
history_cache:
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 0
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 1
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 2
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 3
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 4
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 5
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 6
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 7
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 8
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 9
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 10
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 11
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 12
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 13
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 14
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 15
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 16
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 17
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 18
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 19
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 20
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 21
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 22
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 23
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 24
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 25
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 26
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 27
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 28
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 29
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 30
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 31
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 32
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 33
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 34
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 35
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 36
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 37
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 38
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 39
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 40
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 41
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 42
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 43
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 44
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 45
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 46
    .db 0,0,0,0,0,0,0,0,0,0,0,0,0 ; 47
.end
