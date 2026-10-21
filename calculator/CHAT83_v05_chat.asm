.nolist
#include "ti83plus.inc"
.list

; Build targets (see .github/workflows/verify-v05.yml):
;   default            C83V5.8xp program, run with Asm(prgmC83V5)
;   -DCHAT83_APP       CHAT83.8xk signed Flash App, run from the APPS menu
;   -DCHAT83_UI_DEMO   offline UI preview (C83DEMO): no link traffic, seeded
;                      history, local answers; for emulators without a PC
#ifdef CHAT83_APP
#include "app.inc"
#ifdef CHAT83_UI_DEMO
    defpage(0, "C83DEMO")
#else
    defpage(0, "CHAT83")
#endif
#else
.org userMem - 2
.db t2ByteTok, tAsmCmp
#endif

; CHAT83 v0.5 EXPERIMENTAL -- original TI-83 Plus only
; Nonblocking port-0 RX assist, cooperative _GetCSC, predictive row prefetch.
; Protocol only for new Arduino Uno v0.5 + bridge_v05.py (docs/v05-wire-protocol.md).
; Not compatible with serial2ti83, bridge_v03.py or bridge_v04.py.
;
; Frame: C SEQ START0 START1 START2 START3 COUNT FLAGS ROWS CRC8
; CRC8 poly 07h, init 00h, over every preceding byte from 'C'.
; FLAGS 1=older, 2=newer, 4=RESET, 8=LLM_BUSY, 16=LLM_ERR. MAX 6 rows per frame.
; Active ring 48*13 bytes, staging received frame 81 bytes.
; UI keeps selected/visible rows anchored when prefetch commits.
; Only one requested frame can be in flight.

CACHE_ROWS EQU 48
MAX_INPUT EQU 48
ERROR_RECEIVE EQU 1      ; error_flag: bad or missing C frame after retries
ERROR_SEND    EQU 2      ; error_flag: _SendAByte raised ERR:LINK

start:
    xor a
    out (00h),a
    res textInverse,(iy+textFlags)
    ; RAM state lives outside the program image (an App runs from read-only
    ; Flash), so every variable and the row cache start from zero here.
    ld hl,ram_vars
    ld bc,RAM_VARS_SIZE
    call zero_fill
    ld hl,history_cache
    ld bc,CACHE_ROWS*13
    call zero_fill
    ; Catch OS errors raised inside bcalls. _SendAByte raises ERR:LINK when
    ; the PC/Uno side does not complete the handshake; without a handler
    ; the OS would show ERR:LINK and end the program. Must be installed at
    ; this stack depth: the OS unwinds SP to here before jumping to the trap.
    ; Every build installs it, because exit_program always removes it.
    ld hl,os_error_trap
    call APP_PUSH_ERRORH
#ifdef CHAT83_UI_DEMO
    call demo_seed
    call draw_history
    jp main_loop
#endif
    call draw_loading
    call send_sync

main_loop:
    call poll_rx
    call timeout_tick
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
    ld a,(pending_cancel)
    or a
    jr z,loop_check_prefetch
    ld a,(request_kind)
    or a
    jr nz,loop_check_prefetch
    xor a
    ld (pending_cancel),a
    ld a,(busy_flag)
    or a
    jr z,loop_check_prefetch
    call send_cancel
loop_check_prefetch:
    ld a,(input_mode)
    or a
    jr nz,loop_live
    call maybe_prefetch
loop_live:
    call poll_live
    jp main_loop

exit_program:
    call APP_POP_ERRORH
exit_after_trap:                     ; the OS already removed the handler
    xor a
    out (00h),a
    set graphDraw,(iy+graphFlags)  ; history_cache overwrote plotSScreen
    res textInverse,(iy+textFlags)
#ifdef CHAT83_APP
    bjump(_JForceCmdNoChar)
#else
    ret
#endif

; OS error raised in a bcall. The OS has restored SP to its value when
; os_error_trap was installed and removed the handler; A = error code.
; ERR:BREAK (ON key) exits. Anything else, in practice ERR:LINK from
; _SendAByte, abandons the request and shows CHAT83's own error screen,
; from which MODE resynchronizes.
os_error_trap:
    and E_Mask
    cp E_Break & E_Mask
    jr z,exit_after_trap
    xor a
    out (00h),a              ; release the link and receive assist
    ld (request_kind),a
    ld (pending_enter),a
    ld (pending_cancel),a
    ld (pending_scroll),a
    ld (input_mode),a
    call reset_receiver_state
    ld a,ERROR_SEND
    ld (error_flag),a
    ld hl,os_error_trap
    call APP_PUSH_ERRORH
    call draw_error
    jp main_loop

; HL = start, BC = length (>= 2). Clears BC bytes.
zero_fill:
    ld (hl),0
    ld d,h
    ld e,l
    inc de
    dec bc
    ldir
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
    xor a
    ld (idle_ticks),a
    ld (idle_ticks+1),a
    ld a,b
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
    ld a,ERROR_RECEIVE
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
timeout_tick:
    ld a,(request_kind)
    or a
    jr z,timeout_clear
    ld hl,(idle_ticks)
    inc hl
    ld (idle_ticks),hl
    ld a,h
    cp 0F0h
    ret c
    xor a
    ld (idle_ticks),a
    ld (idle_ticks+1),a
    jp retry_frame
timeout_clear:
    xor a
    ld (idle_ticks),a
    ld (idle_ticks+1),a
    ret

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
; HL pointer, B length; updates crc_state. Returns HL past the buffer and
; B=0; DE and C are preserved.
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
    jr z,non_fetch_cancel
    jp packet_error
non_fetch_cancel:
    ld a,(rx_frame+7)
    and 4
    jp nz,commit_reset
    jp commit_newer
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
    ld a,(rows_to_copy)
    or a
    jr nz,update_maybe_follow
    ; Empty live poll: no rows changed, so only the status bars (AI/ERR,
    ; ENTER/MODE hint) are repainted, and only on the history screen.
    call read_model_flags
    ld a,(rx_frame+7)
    and 3
    ld (page_flags),a
    xor a
    ld (request_kind),a
    ld a,(screen_kind)
    cp SCREEN_HISTORY
    ret nz
    jp draw_status_bars
update_maybe_follow:
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
    call replay_scroll
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
    call replay_scroll
    ret

apply_flags_draw:
    call read_model_flags
    ld a,(rx_frame+7)
    and 3
    ld (page_flags),a
    xor a
    ld (request_kind),a
    ld a,(input_mode)
    or a
    ret nz                 ; do not overwrite editor while streaming
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
    jr nz,key_new_press
    ld a,b
    cp skUp
    jr z,key_repeat
    cp skDown
    jr z,key_repeat
    ld a,(input_mode)
    or a
    ret z
    ld a,b
    cp skLeft
    jr z,key_repeat
    cp skRight
    jr z,key_repeat
    cp skDel
    ret nz
key_repeat:
    ld hl,(repeat_ticks)
    inc hl
    ld (repeat_ticks),hl
    ld a,h
    cp 4                  ; repeat only after sustained hold
    ret c
key_new_press:
    xor a
    ld (repeat_ticks),a
    ld (repeat_ticks+1),a
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
    jr z,history_not_error
    ld a,b
    cp skMode
    jp z,restart_sync
    ret
history_not_error:
    ld a,b
    cp skEnter
    jp z,request_input
    cp skMode
    jp z,maybe_cancel_model
    cp skUp
    jp z,key_up
    cp skDown
    jp z,key_down
    cp skGraph
    jp z,key_newest
    ret

; GRAPH: select the newest row. Local when the newest rows are cached;
; otherwise SYNC replaces the cache with them, keeping history on screen
; (LOADING in the hint bar) until the reply arrives.
key_newest:
    xor a
    ld (direction),a
    ld (pending_scroll),a
    ld a,(page_flags)
    and 2
    jr nz,newest_remote
    ld a,(cache_count)
    or a
    ret z
    dec a
    ld (cursor_off),a
    sub 5
    jr nc,newest_view
    xor a
newest_view:
    ld (view_off),a
    jp draw_history
newest_remote:
    ld a,(request_kind)
    or a
    ret nz                   ; a frame is in flight; press GRAPH again after
    call send_sync
    jp draw_load_status
request_exit:
    ld a,1
    ld (exit_flag),a
    ret
maybe_cancel_model:
    ld a,(error_flag)
    or a
    jp nz,restart_sync
    ld a,(busy_flag)
    or a
    ret z
    ld a,(request_kind)
    or a
    jp z,send_cancel
    ; Never send K during a six-row PC reply: request/response streams
    ; would collide. Defer until the in-flight C frame is committed.
    ld a,1
    ld (pending_cancel),a
    ret

restart_sync:
    xor a
    ld (error_flag),a
    ld (retry_count),a
    call draw_loading
    jp send_sync

; Request the newest rows (the reply RESETs the cache).
send_sync:
    call disable_rx
    ld a,'S'
    ld (request_kind),a
    bcall(_SendAByte)
    call reset_receiver_state
    jp enable_rx

send_cancel:
    call disable_rx
    ld a,'K'
    ld (cancel_wire),a
    xor a
    ld (crc_state),a
    ld a,'K'
    call crc8_update
    ld a,(crc_state)
    ld (cancel_wire+1),a
    ld hl,cancel_wire
    ld a,2
    call send_bytes
    ld a,'K'
    ld (request_kind),a
    call reset_receiver_state
    call enable_rx
    ret

request_input:
    ; May edit during an existing LLM stream, but cannot send yet.
    ld a,1
    ld (pending_enter),a
    ret
key_up:
    ld a,(direction)
    cp 0FFh
    jr z,up_dir_ready
    xor a
    ld (pending_scroll),a
up_dir_ready:
    ld a,0FFh
    ld (direction),a
    ld a,(cache_count)
    or a
    ret z
    ld a,(cursor_off)
    or a
    jp z,queue_older_key
    ld (prior_cursor),a
    ld a,(view_off)
    ld (prior_view),a
    ld a,(cursor_off)
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
    call cursor_refresh
    ret
queue_older_key:
    ld a,(page_flags)
    and 1
    ret z
    jp queue_scroll

key_down:
    ld a,(direction)
    cp 1
    jr z,down_dir_ready
    xor a
    ld (pending_scroll),a
down_dir_ready:
    ld a,1
    ld (direction),a
    ld a,(cache_count)
    or a
    ret z
    ld b,a
    ld a,(cursor_off)
    inc a
    cp b
    jp nc,queue_newer_key
    ld a,(cursor_off)
    ld (prior_cursor),a
    ld a,(view_off)
    ld (prior_view),a
    ld a,(cursor_off)
    inc a
    ld (cursor_off),a
    ld b,a
    ld a,(view_off)
    add a,6
    cp b
    jr z,down_view
    jr c,down_view
    call cursor_refresh
    ret
down_view:
    ld a,(view_off)
    inc a
    ld (view_off),a
    call cursor_refresh
    ret
queue_newer_key:
    ld a,(page_flags)
    and 2
    ret z
    jp queue_scroll

queue_scroll:
    ld a,(pending_scroll)
    cp 12
    ret nc
    inc a
    ld (pending_scroll),a
    cp 1
    ret nz
    call draw_load_status
    ret

; Call only once after one six-row prefetch has committed. Extra key presses
; at an unloaded boundary are preserved and replayed against newly added rows.
replay_scroll:
    ld a,(pending_scroll)
    or a
    ret z
    ld b,a
    xor a
    ld (pending_scroll),a
scroll_replay_loop:
    push bc
    ld a,(direction)
    cp 0FFh
    jr nz,replay_newer
    call key_up
    jr replay_next
replay_newer:
    call key_down
replay_next:
    pop bc
    djnz scroll_replay_loop
    call draw_history
    ld a,(pending_scroll)
    or a
    ret z
    call draw_load_status
    ret

draw_load_status:
    ld a,7
    ld hl,loading_hint
    jp draw_bar

; Cursor moved inside an unchanged viewport: repaint only the previously
; selected row and the newly selected one. Any viewport change repaints all.
cursor_refresh:
    ld a,(view_off)
    ld b,a
    ld a,(prior_view)
    cp b
    jp nz,draw_history
    ld a,(screen_kind)
    cp SCREEN_HISTORY
    jp nz,draw_history
    ld a,(prior_cursor)
    call draw_history_row
    ld a,(cursor_off)
    call draw_history_row
    ld a,(pending_scroll)
    or a
    ret nz                   ; keep LOADING... while a boundary fetch waits
    jp draw_hint_bar

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
    ; CRC8 over F SEQ DIR START0..3 COUNT (8 bytes).
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
    ld (idle_ticks),a
    ld (idle_ticks+1),a
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
    ld (input_cursor),a
    ld (input_buf),a
    ld a,1
    ld (input_mode),a
    ld (alpha_mode),a
    ld a,SCREEN_EDITOR
    call enter_screen
    xor a
    ld hl,ask_title
    call draw_bar
    ld a,2
    call set_row
    ld hl,ask_label
    call put_str
    call draw_input
    ret

; Nonblocking GetCSC editor: ALPHA toggles letters/numbers, 2nd inserts a
; space, LEFT/RIGHT move insertion point, DEL backspaces, ENTER submits.
; Four 12-character editor lines: up to 48 ASCII characters.
input_key:
    cp skClear
    jp z,input_cancel
    cp skEnter
    jp z,input_send
    cp skDel
    jp z,input_delete
    cp skLeft
    jp z,input_left
    cp skRight
    jp z,input_right
    cp skAlpha
    jp z,input_toggle
    cp sk2nd
    jp z,input_space
    ld (scan_key),a
    ld b,a
    ld a,(alpha_mode)
    or a
    jr z,input_numeric
    ld a,b
    cp sk0
    jr z,input_space
    ld hl,alpha_pairs
    ld b,ALPHA_PAIR_COUNT
    jr input_lookup
input_numeric:
    ld a,b
    ld hl,numeric_pairs
    ld b,19
input_lookup:
    cp (hl)
    jr z,input_pair_found
    inc hl
    inc hl
    djnz input_lookup
    ret
input_pair_found:
    inc hl
    ld a,(hl)
    jp input_append

input_toggle:
    ld a,(alpha_mode)
    xor 1
    ld (alpha_mode),a
    call draw_input
    ret
input_space:
    ld a,' '
    jp input_append
input_left:
    ld a,(input_cursor)
    or a
    ret z
    dec a
    ld (input_cursor),a
    call draw_input
    ret
input_right:
    ld a,(input_cursor)
    ld b,a
    ld a,(input_len)
    cp b
    ret z
    ld a,b
    inc a
    ld (input_cursor),a
    call draw_input
    ret

input_append:
    ld (temp_char),a
    ld a,(input_len)
    cp MAX_INPUT
    ret nc
    ld b,a
    ld a,(input_cursor)
    ld c,a
    ld a,b
    sub c
    inc a                  ; shift terminator as well
    ld c,a
    ld b,0
    ld hl,input_buf
    ld a,(input_len)
    ld e,a
    ld d,0
    add hl,de               ; HL = terminator
    ld d,h
    ld e,l
    inc de                  ; DE = one byte later
    lddr
    ld hl,input_buf
    ld a,(input_cursor)
    ld e,a
    ld d,0
    add hl,de
    ld a,(temp_char)
    ld (hl),a
    ld a,(input_cursor)
    inc a
    ld (input_cursor),a
    ld a,(input_len)
    inc a
    ld (input_len),a
    call draw_input
    ret

input_delete:
    ld a,(input_cursor)
    or a
    ret z
    dec a
    ld (input_cursor),a
    ld e,a
    ld d,0
    ld hl,input_buf
    add hl,de               ; HL points to destination
    ld d,h
    ld e,l
    inc hl                  ; source is one byte after cursor-1
    ld a,(input_len)
    ld b,a
    ld a,(input_cursor)
    ld c,a
    ld a,b
    sub c                   ; copy (len - newcursor) including terminator
    ld c,a
    ld b,0
    ldir
    ld a,(input_len)
    dec a
    ld (input_len),a
    call draw_input
    ret

input_cancel:
    xor a
    ld (input_mode),a
    call draw_history
    ret

input_send:
    ld a,(input_len)
    or a
    ret z
    ld a,(busy_flag)
    or a
    ret nz                 ; preserve composed text until model is idle
#ifdef CHAT83_UI_DEMO
    jp demo_answer
#endif

    ; Build a complete checksum-protected question BEFORE touching Link port.
    ; Q + LEN + ASCII(1..48) + LATEST + CRC8(poly 07)
    ld a,'Q'
    ld (question_wire),a
    ld a,(input_len)
    ld (question_wire+1),a
    ld c,a
    ld b,0
    ld hl,input_buf
    ld de,question_wire+2
    ldir
    ld a,(page_flags)
    and 2
    jr nz,question_not_latest
    ld a,1
    jr question_latest_set
question_not_latest:
    xor a
question_latest_set:
    ld (de),a
    inc de                  ; DE = CRC destination
    xor a
    ld (crc_state),a
    ld hl,question_wire
    ld a,(input_len)
    add a,3                 ; header 2 + latest 1
    ld b,a
    call crc8_buffer
    ld a,(crc_state)
    ld (de),a

    xor a
    ld (input_mode),a
    call disable_rx
    ld hl,question_wire
    ld a,(input_len)
    add a,4                 ; Q LEN TEXT LATEST CRC8
    call send_bytes
    ld a,'Q'
    ld (request_kind),a
    call reset_receiver_state
    call enable_rx
    call draw_history
    ret

; Editor: rows 3-6 hold 4 x 12 characters, row 2 shows "YOU:" and a
; length counter, the insertion point is an inverse block over the character
; it precedes, and row 7 shows the keyboard mode and what ENTER will do.
draw_input:
    ld a,3
    ld (editor_row),a
    xor a
    ld (editor_offset),a
input_draw_loop:
    ld hl,input_buf
    ld a,(editor_offset)
    ld e,a
    ld d,0
    add hl,de
    ld de,input_line
    ld b,12
input_line_copy:
    ld a,(hl)
    or a
    jr nz,input_copy_printable
    ld a,' '
input_copy_printable:
    ld (de),a
    inc hl
    inc de
    djnz input_line_copy
    xor a
    ld (de),a
    ld a,(editor_row)
    call set_row
    ld hl,input_line
    call put_str
    ld a,13
    call pad_to              ; clears a block cursor left in column 12
    ld a,(editor_offset)
    add a,12
    ld (editor_offset),a
    ld a,(editor_row)
    inc a
    ld (editor_row),a
    cp 7
    jr c,input_draw_loop

    ; Length counter "nn/48" in columns 11-15 of row 2.
    ld a,2
    call set_row
    ld a,11
    ld (curCol),a
    ld a,(input_len)
    ld b,'0'-1
input_count_tens:
    inc b
    sub 10
    jr nc,input_count_tens
    add a,'0'+10
    ld c,a
    ld a,b
    cp '0'
    jr nz,input_count_draw
    ld a,' '
input_count_draw:
    call put_char
    ld a,c
    call put_char
    ld hl,count_suffix
    call put_str

    ; Cursor index 48 is drawn in the spare 13th column of row 6.
    ld a,(input_cursor)
    ld b,3
input_cursor_div:
    cp 12
    jr c,input_cursor_position
    sub 12
    inc b
    ld c,a
    ld a,b
    cp 7
    ld a,c
    jr c,input_cursor_div
    ld a,12
    ld b,6
input_cursor_position:
    ld (curCol),a
    ld a,b
    ld (curRow),a
    ld hl,input_buf
    ld a,(input_cursor)
    ld e,a
    ld d,0
    add hl,de
    ld a,(hl)
    or a
    jr nz,input_cursor_char
    ld a,' '
input_cursor_char:
    call inverse_on
    call put_char
    call inverse_off

    ld hl,alpha_hint
    ld a,(alpha_mode)
    or a
    jr nz,input_hint_mode
    ld hl,number_hint
input_hint_mode:
    ld a,7
    call draw_bar
    ld hl,send_hint
    ld a,(busy_flag)
    or a
    jr z,input_hint_send
    ld hl,wait_hint          ; ENTER keeps the text until the model is idle
input_hint_send:
    ld a,6
    jp draw_bar_tag

; Physical TI-83+ ALPHA legend positions via GetCSC scan codes.
alpha_pairs:
    .db skMath,'A',skMatrix,'B',skPrgm,'C'            ; skMatrix = APPS key
    .db skRecip,'D',skSin,'E',skCos,'F',skTan,'G',skPower,'H'
    .db skSquare,'I',skComma,'J',skLParen,'K',skRParen,'L',skDiv,'M'
    .db skLog,'N',sk7,'O',sk8,'P',sk9,'Q',skMul,'R'
    .db skLn,'S',sk4,'T',sk5,'U',sk6,'V',skSub,'W'
    .db skStore,'X',sk1,'Y',sk2,'Z'
    .db skDecPnt,':',skChs,'?'
ALPHA_PAIR_COUNT EQU 28
numeric_pairs:
    .db sk0,'0',sk1,'1',sk2,'2',sk3,'3',sk4,'4'
    .db sk5,'5',sk6,'6',sk7,'7',sk8,'8',sk9,'9'
    .db skDecPnt,'.',skChs,'-',skAdd,'+',skSub,'-'
    .db skMul,'*',skDiv,'/',skLParen,'(',skRParen,')'
    .db skComma,','

#ifdef CHAT83_UI_DEMO
; ---- UI demo build ----------------------------------------------------
; No link traffic: history is seeded from demo_rows and each question is
; answered locally, so the whole UI can be explored in an emulator. The
; demo never sets the older/newer flags, so no F/U requests are planned.
demo_seed:
    ld hl,demo_rows
    ld b,DEMO_ROW_COUNT
demo_seed_loop:
    push bc
    call demo_append_row
    pop bc
    djnz demo_seed_loop
    jp demo_snap_tail

; HL = 12 bytes. Appends one row, overwriting the oldest when the cache is
; full. Returns HL past the source row.
demo_append_row:
    push hl
    ld a,(cache_count)
    cp CACHE_ROWS
    jr c,demo_row_space
    ld a,(cache_head)
    inc a
    cp CACHE_ROWS
    jr c,demo_head_ok
    xor a
demo_head_ok:
    ld (cache_head),a
    ld a,CACHE_ROWS-1
    jr demo_row_write
demo_row_space:
    inc a
    ld (cache_count),a
    dec a
demo_row_write:
    call ring_addr
    ex de,hl
    pop hl
    ld bc,12
    ldir
    xor a
    ld (de),a
    ret

demo_snap_tail:
    ld a,(cache_count)
    dec a
    ld (cursor_off),a
    sub 5
    jr nc,demo_view
    xor a
demo_view:
    ld (view_off),a
    ret

; Hard-wrap "YOU: " + question into 12-column rows (rx_frame is scratch),
; then append a canned reply.
demo_answer:
    ld hl,rx_frame
    ld (hl),' '
    ld de,rx_frame+1
    ld bc,59
    ldir
    ld hl,demo_you
    ld de,rx_frame
    ld bc,5
    ldir
    ld hl,input_buf
    ld a,(input_len)
    ld c,a
    ldir
    ld a,(input_len)
    add a,5+11             ; rows = (5 + len + 11) / 12
    ld b,0
demo_count_rows:
    cp 12
    jr c,demo_rows_known
    sub 12
    inc b
    jr demo_count_rows
demo_rows_known:
    ld hl,rx_frame
demo_question_loop:
    push bc
    call demo_append_row
    pop bc
    djnz demo_question_loop
    ld hl,demo_reply
    ld b,DEMO_REPLY_ROWS
demo_reply_loop:
    push bc
    call demo_append_row
    pop bc
    djnz demo_reply_loop
    xor a
    ld (input_mode),a
    call demo_snap_tail
    jp draw_history

demo_you:       .db "YOU: "
demo_reply:
    .db "PC: Demo    "
    .db "build, no PC"
    .db "link.       "
DEMO_REPLY_ROWS EQU 3
; Generated with bridge_v03.text_rows, so wrapping matches real history.
demo_rows:
    .db "YOU: HELLO  "
    .db "PC: WORLD   "
    .db "YOU: WHAT IS"
    .db "CHAT83      "
    .db "PC: A retro "
    .db "chat        "
    .db "terminal for"
    .db "the TI-83   "
    .db "Plus. A PC  "
    .db "bridge talks"
    .db "to the LLM  "
    .db "for you.    "
    .db "YOU: HOW    "
    .db "FAST        "
    .db "PC: About 3 "
    .db "seconds per "
    .db "six lines at"
    .db "the default "
    .db "35 ms link  "
    .db "gap.        "
    .db "YOU: DEMO   "
    .db "PC: Offline "
    .db "UI preview. "
    .db "Use UP and  "
    .db "DOWN to     "
    .db "scroll,     "
    .db "ENTER to    "
    .db "type.       "
DEMO_ROW_COUNT  EQU 28
#endif

; ---- text UI ----------------------------------------------------------
; Screen map (16 x 8 cells of 6 x 8 pixels):
;   row 0      inverse title bar, model status (AI / ERR) on the right
;   rows 1-6   history: 12 text columns + 2 blank; selected row inverse
;   row 7      inverse key-hint bar
;   x 88-95    scrollbar over rows 1-6, drawn straight to the LCD driver
; The LCD is cleared only when the screen changes (enter_screen), so
; scrolling and live updates overwrite cells in place without flicker.
SCREEN_HISTORY  EQU 1
SCREEN_EDITOR   EQU 2
SCREEN_LOADING  EQU 3
SCREEN_ERROR    EQU 4

; A = character. Draws at (curRow, curCol) with _PutMap, which never wraps
; or scrolls (a full-width bar on row 7 would scroll with _PutC), then
; advances curCol. Nothing is drawn past column 15. Preserves BC, DE, HL.
put_char:
    push af
    ld a,(curCol)
    cp 16
    jr nc,put_char_skip
    pop af
    push bc
    push de
    push hl
    bcall(_PutMap)
    pop hl
    pop de
    pop bc
    ld a,(curCol)
    inc a
    ld (curCol),a
    ret
put_char_skip:
    pop af
    ret

; _PutS replacement. A bcall maps the OS ROM page over 4000h-7FFFh, so an
; App's own strings are unreadable from inside _PutS; print per character.
; HL = NUL-terminated string; returns HL past the terminator.
put_str:
    ld a,(hl)
    inc hl
    or a
    ret z
    call put_char
    jr put_str

; Print spaces until curCol reaches A.
pad_to:
    ld b,a
pad_loop:
    ld a,(curCol)
    cp b
    ret nc
    ld a,' '
    call put_char
    jr pad_loop

inverse_on:
    set textInverse,(iy+textFlags)
    ret
inverse_off:
    res textInverse,(iy+textFlags)
    ret

set_row:
    ld (curRow),a
    xor a
    ld (curCol),a
    ret

; A = row, HL = text: full-width inverse bar.
draw_bar:
    call set_row
    call inverse_on
    call put_str
    ld a,16
    call pad_to
    jp inverse_off

; A = column, HL = text: inverse text on the current row (bar overlays).
draw_bar_tag:
    ld (curCol),a
    call inverse_on
    call put_str
    jp inverse_off

; A = row, HL = text: normal text starting at column 1.
put_line:
    call set_row
    ld a,1
    ld (curCol),a
    jp put_str

; A = screen id. Clears the LCD only when switching screens.
enter_screen:
    ld b,a
    ld a,(screen_kind)
    cp b
    ret z
    ld a,b
    ld (screen_kind),a
    bcall(_ClrLCDFull)
    ret

draw_loading:
    ld a,SCREEN_LOADING
    call enter_screen
    xor a
    ld hl,title
    call draw_bar
    ld a,3
    ld hl,connect_text
    call put_line
    ld a,4
    ld hl,connect_text2
    call put_line
    ld a,7
    ld hl,quit_hint
    jp draw_bar

draw_error:
    ld a,SCREEN_ERROR
    call enter_screen
    xor a
    ld hl,error_title
    call draw_bar
    ld hl,error_text
    ld de,error_text2
    ld a,(error_flag)
    cp ERROR_SEND
    jr nz,error_lines
    ld hl,send_error_text
    ld de,send_error_text2
error_lines:
    push de
    ld a,2
    call put_line
    pop hl
    ld a,3
    call put_line
    ld a,5
    ld hl,retry_text
    call put_line
    ld a,6
    ld hl,quit_text
    call put_line
    ld a,7
    ld hl,retry_hint
    jp draw_bar

draw_status_bars:
    xor a
    ld hl,title
    call draw_bar
    ld a,(model_error)
    or a
    jr z,status_no_error
    ld a,13
    ld hl,err_label
    call draw_bar_tag
    jr draw_hint_bar
status_no_error:
    ld a,(busy_flag)
    or a
    jr z,status_not_busy
    ld a,14
    ld hl,live_label
    call draw_bar_tag
    jr draw_hint_bar
status_not_busy:
    ld a,(request_kind)
    cp 'Q'
    jr nz,draw_hint_bar
    ld a,13
    ld hl,wait_label         ; question sent, first reply not yet in
    call draw_bar_tag

; Row 7: MODE:STOP while the model generates; GRAPH:END when the newest
; row is not selected (scrolled up, or newer rows only on the PC).
draw_hint_bar:
    ld hl,stop_hint
    ld a,(busy_flag)
    or a
    jr nz,hint_draw
    ld hl,end_hint
    ld a,(page_flags)
    and 2
    jr nz,hint_draw
    ld a,(cache_count)
    or a
    jr z,hint_ask
    dec a
    ld b,a
    ld a,(cursor_off)
    cp b
    jr nz,hint_draw
hint_ask:
    ld hl,ask_hint
hint_draw:
    ld a,7
    jp draw_bar

draw_history:
    ld a,SCREEN_HISTORY
    call enter_screen
    call draw_status_bars
    ld a,(view_off)
    ld (draw_index),a
    ld a,1
    ld (draw_row),a
draw_row_loop:
    ld a,(draw_index)
    ld b,a
    ld a,(cache_count)
    cp b
    jr z,draw_blank_row
    jr c,draw_blank_row
    ld a,(draw_index)
    call draw_history_row
    jr draw_row_next
draw_blank_row:
    ld a,(draw_row)
    call set_row
    ld a,14
    call pad_to
draw_row_next:
    ld a,(draw_index)
    inc a
    ld (draw_index),a
    ld a,(draw_row)
    inc a
    ld (draw_row),a
    cp 7
    jr c,draw_row_loop
    ld a,(cache_count)
    or a
    jr nz,draw_scrollbar
    ld a,3
    ld hl,empty_text
    call put_line
    jp draw_scrollbar

; A = logical cache index inside the viewport. Draws its 12 characters on
; its screen row, inverted (with one trailing cell) when it is selected.
draw_history_row:
    ld (paint_index),a
    ld b,a
    ld a,(view_off)
    ld c,a
    ld a,b
    sub c
    inc a
    call set_row
    ld a,(paint_index)
    ld b,a
    ld a,(cursor_off)
    cp b
    call z,inverse_on
    ld a,(paint_index)
    call ring_addr
    call put_str
    ld a,13
    call pad_to
    call inverse_off
    ld a,14
    jp pad_to

; Scrollbar over the 48-pixel history area (LCD rows 8-55), in LCD byte
; column 11 (x 88-95): a dotted track at x 92 and a 3-pixel thumb at
; x 91-93 sized and placed by the viewport within the cached rows.
draw_scrollbar:
    xor a
    ld (thumb_top),a
    ld (thumb_len),a         ; no rows: track only
    ld a,(cache_count)
    or a
    jr z,scroll_paint
    cp 7
    jr nc,scroll_scaled
    ld a,48                  ; everything fits: full-length thumb
    ld (thumb_len),a
    jr scroll_paint
scroll_scaled:
    ld c,a
    ld hl,48*6
    call div_hl_c            ; length = 48 * 6 / rows
    ld (thumb_len),a
    ld b,a
    ld a,48
    sub b
    ld e,a                   ; free track pixels
    ld a,(view_off)
    call mul_a_e
    ld a,(cache_count)
    sub 6
    ld c,a
    call div_hl_c            ; top = free * view / (rows - 6)
    ld (thumb_top),a
scroll_paint:
    di
    ld a,05h                 ; auto-increment the row (OS default mode)
    call lcd_command
    ld a,20h+11
    call lcd_command
    ld a,80h+8
    call lcd_command
    ld b,0
scroll_paint_loop:
    ld a,(thumb_top)
    ld c,a
    ld a,b
    sub c
    jr c,scroll_track
    ld c,a
    ld a,(thumb_len)
    cp c
    jr z,scroll_track
    jr c,scroll_track
    ld a,1Ch
    jr scroll_write
scroll_track:
    ld a,b
    and 1
    ld a,08h
    jr z,scroll_write
    xor a
scroll_write:
    call lcd_data
    inc b
    ld a,b
    cp 48
    jr c,scroll_paint_loop
    ei
    ret

; Write A to the LCD command / data port after the ROM's driver delay.
; AF and BC are saved around the delay so callers need not rely on it.
lcd_command:
    call lcd_delay
    out (10h),a
    ret
lcd_data:
    call lcd_delay
    out (11h),a
    ret
lcd_delay:
    push af
    push bc
    call LCD_BUSY_QUICK
    pop bc
    pop af
    ret

; HL = A * E (A, E small). Destroys D.
mul_a_e:
    ld hl,0
    ld d,0
    or a
    ret z
mul_loop:
    add hl,de
    dec a
    jr nz,mul_loop
    ret

; A = HL / C, C > 0, quotient < 256. Destroys B, DE, HL.
div_hl_c:
    ld b,0
    ld e,c
    ld d,0
    or a
div_loop:
    sbc hl,de
    jr c,div_done
    inc b
    jr div_loop
div_done:
    ld a,b
    ret

#ifdef CHAT83_UI_DEMO
title:          .db " CHAT83 DEMO",0
#else
title:          .db " CHAT83 V0.5",0
#endif
ask_title:      .db " NEW MESSAGE",0
ask_label:      .db "YOU:",0
connect_text:   .db "Connecting to",0
connect_text2:  .db "the PC...",0
error_title:    .db " LINK ERROR",0
error_text:     .db "No valid reply",0
error_text2:    .db "from the PC.",0
send_error_text: .db "Could not send",0
send_error_text2: .db "to the PC/Uno.",0
retry_text:     .db "MODE:  retry",0
quit_text:      .db "CLEAR: quit",0
empty_text:     .db "No history.",0
ask_hint:       .db " ENTER:ASK",0
end_hint:       .db " ENTER GRAPH:END",0
stop_hint:      .db " MODE:STOP",0
loading_hint:   .db " LOADING...",0
quit_hint:      .db " CLEAR:QUIT",0
retry_hint:     .db " MODE:RETRY",0
live_label:     .db "AI",0
err_label:      .db "ERR",0
wait_label:     .db "...",0
count_suffix:   .db "/48",0
alpha_hint:     .db " A-Z",0
number_hint:    .db " 0-9",0
send_hint:      .db "ENTER:SEND",0
wait_hint:      .db "AI WORKING",0

; ---- RAM state -------------------------------------------------------
; Not part of the program image: an App executes from read-only Flash.
; history_cache (48 rows x 13 bytes) uses plotSScreen, the graph buffer;
; exit_program marks the graph for redraw. Everything else uses
; appBackUpScreen. Both are 768 bytes and zero-filled at start.
; Do not call ROM graph routines (_ILine, _IPoint, _GrBufCpy ...): they
; write plotSScreen.
history_cache   EQU plotSScreen
ram_vars        EQU appBackUpScreen
rx_pos          EQU ram_vars+0   ; 1
crc_state       EQU ram_vars+1   ; 1
rx_expected     EQU ram_vars+2   ; 1
request_kind    EQU ram_vars+3   ; 1
error_flag      EQU ram_vars+4   ; 1
exit_flag       EQU ram_vars+5   ; 1
last_key        EQU ram_vars+6   ; 1
pending_enter   EQU ram_vars+7   ; 1
pending_cancel  EQU ram_vars+8   ; 1
cache_head      EQU ram_vars+9   ; 1
cache_count     EQU ram_vars+10  ; 1
cache_start     EQU ram_vars+11  ; 4
cursor_off      EQU ram_vars+15  ; 1
view_off        EQU ram_vars+16  ; 1
page_flags      EQU ram_vars+17  ; 1
direction       EQU ram_vars+18  ; 1
pending_dir     EQU ram_vars+19  ; 1
fetch_count     EQU ram_vars+20  ; 1
safe_space      EQU ram_vars+21  ; 1
evicted_flag    EQU ram_vars+22  ; 1
busy_flag       EQU ram_vars+23  ; 1
model_error     EQU ram_vars+24  ; 1
follow_tail     EQU ram_vars+25  ; 1
poll_timer      EQU ram_vars+26  ; 2
retry_count     EQU ram_vars+28  ; 1
input_mode      EQU ram_vars+29  ; 1
input_cursor    EQU ram_vars+30  ; 1
scan_key        EQU ram_vars+31  ; 1
temp_char       EQU ram_vars+32  ; 1
editor_row      EQU ram_vars+33  ; 1
editor_offset   EQU ram_vars+34  ; 1
input_line      EQU ram_vars+35  ; 13
alpha_mode      EQU ram_vars+48  ; 1
retry_wire      EQU ram_vars+49  ; 3
cancel_wire     EQU ram_vars+52  ; 2
question_wire   EQU ram_vars+54  ; 52
idle_ticks      EQU ram_vars+106 ; 2
repeat_ticks    EQU ram_vars+108 ; 2
pending_scroll  EQU ram_vars+110 ; 1
prior_cursor    EQU ram_vars+111 ; 1
prior_view      EQU ram_vars+112 ; 1
update_wire     EQU ram_vars+113 ; 6
sequence        EQU ram_vars+119 ; 1
expect_seq      EQU ram_vars+120 ; 1
stage_index     EQU ram_vars+121 ; 1
rows_to_copy    EQU ram_vars+122 ; 1
draw_index      EQU ram_vars+123 ; 1
draw_row        EQU ram_vars+124 ; 1
input_len       EQU ram_vars+125 ; 1
input_buf       EQU ram_vars+126 ; 49
send_ptr        EQU ram_vars+175 ; 2
send_left       EQU ram_vars+177 ; 1
fetch_start     EQU ram_vars+178 ; 4
calc_addr       EQU ram_vars+182 ; 4
fetch_wire      EQU ram_vars+186 ; 9
rx_frame        EQU ram_vars+195 ; 81
screen_kind     EQU ram_vars+276 ; 1
paint_index     EQU ram_vars+277 ; 1
thumb_top       EQU ram_vars+278 ; 1
thumb_len       EQU ram_vars+279 ; 1
RAM_VARS_SIZE   EQU 280

#ifdef CHAT83_APP
    validate
#endif
.end
