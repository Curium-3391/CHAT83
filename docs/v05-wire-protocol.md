# CHAT83 v0.5 wire protocol

**Status:** experimental, implemented, CI-validated, hardware acceptance pending.
The protocol is intentionally **not backward compatible** with v0.3/v0.4.

## A. Physical link

Original TI-83 Plus only. Its Port 00h bit 2 enables Link Receive Assist;
Port 00h bit 3 indicates a completed byte; `IN A,(05h)` reads the byte.
Z80 uses cooperative `_GetCSC` for keyboard and `_SendAByte` for short
outgoing commands. UNO TIP pin D2; RING D3; output always LOW or released
INPUT_PULLUP (never actively driven high). No extra Arduino-to-TI wires.

UNO sends bytes LSb-first on the TI open-drain handshake, and receives
the reciprocal handshake without blocking loops. TX batch completion ACK
does not claim that a C frame has been committed into the calculator's UI.

## B. Windows USB UART to Uno

Baud rate **115200, 8N1**. Every UART packet has a nonzero COBS-encoded body,
followed by delimiter `0x00`. Decode COBS, then inspect bytes:

```text
TYPE | PAYLOAD bytes... | CRC8(poly=0x07, init=0x00)
```

CRC8 covers the type and payload; no escaping of data beyond COBS.

| Origin | TYPE | PAYLOAD | Meaning |
|---|---|---|---|
| PC→Uno | P | none | Request firmware version |
| Uno→PC | H | major=0, minor=5, max_batch=16 | Version hello |
| PC→Uno | G | gap_ms 2..50 | Configure physical byte gap |
| Uno→PC | A | seq=0,status=0 | Confirm gap |
| PC→Uno | D | on (0 or 1) | Enable/disable link diagnostics (`--debug-link`) |
| Uno→PC | A | seq=0,status=0 | Confirm diagnostics setting |
| PC→Uno | T | seq 1..255,count 1..16, count bytes | Transmit byte batch to TI |
| Uno→PC | A | seq,status | Sent all bytes / error code |
| Uno→PC | R | one byte | Byte received from TI |
| Uno→PC | E | reason | Unexpected hardware/protocol error |
| Uno→PC | J | 13 bytes, see below | Link diagnostics, every 500 ms while D=1 |

UNO ACK statuses: 0=OK all bytes, 1=physical timeout, 2=busy,
3=malformed, E error class 1=bad CRC, 2=unknown/invalid host frame,
3=bad COBS, 4=overlong UART frame, 5=RX half-byte timeout, 6=RX queue
overflow. A batch must finish before the next T; the application aborts on
uncertain partial delivery, because repeating arbitrary partial link bytes
would be unsafe without a resync.

`J` payload (all u16 little-endian, free-running snapshots):
`rx_starts, rx_acked_bits, rx_bytes, rx_timeouts, tx_timeouts` (5×u16),
then `state` (0 IDLE, 1 RX_WAIT_RELEASE, 2 RX_ACK_SETTLE, 3 TX_WAIT_ACK,
4 TX_WAIT_RELEASE), `levels` (bit0 TIP high, bit1 RING high) and the last
received TI byte. The bridge prints it as a `[UNO-DIAG]` line.

UNO `R` packets use a separate 64-byte queue to prevent USB
`Serial.write` back-pressure from blocking the TI bit handshake.

## C. Calculator ↔ Python application frames (over the forwarded bytes)

Integers `START` are *little-endian unsigned 32-bit absolute display-row
indices*, not SQLite primary keys and not cache-relative offsets.

**Requests calculator→Python:**

```text
S                                       Bootstrap SYNC
F SEQ DIR START[4] COUNT CRC8             Prefetch 1..6 rows; DIR=0 older, 1 newer
Q LEN ASCII[LEN] LATEST CRC8               User question 1..48 chars, LATEST=0/1
U START[4] CRC8                           Poll live new rows from local cache end
R SEQ CRC8                                Retransmit previous answer (CRC failure)
K CRC8                                    Cancel current LLM generation
```

S is the one-byte bootstrap exception and has no additional app CRC.
All the other multibyte requests include CRC8 over the entire preceding
application frame, including its type. Neither the model prompt nor the
LATEST bit is written to SQLite if Q checksum is invalid.

**Replies Python→calculator:**

```text
C SEQ START[4] COUNT FLAGS ROW0[12] ... ROW(COUNT-1)[12] CRC8
```

COUNT 0..6, length `9+12×COUNT` bytes (9..81 total). Each row contains
exactly twelve printable 7-bit ASCII bytes, padded with spaces.
SEQ is zero for S/Q/U/K, or matches the F SEQ. F requests are never
answered with an unrelated SEQ=0 full reset.

FLAGS:
- bit0 0x01 older rows exist at PC (before first returned row);
- bit1 0x02 newer rows exist (after the returned range);
- bit2 0x04 RESET: discard current ring and load a fresh page;
- bit3 0x08 LLM is generating;
- bit4 0x10 LLM generation failed.

The Z80 receives into 81-byte staging storage, verifies final CRC8
and relevant START/SEQ, then updates its 48×13-byte ring. On a corrupted
complete frame it sends R with the previous response's sequence, limited
to three retries; the PC resends the **same bytes**, not an additional
question or LLM call.

The PC SQLite DB contains a persistent `messages` table and append-only
`display_lines`, allowing stable indices even while the model generates.
The worker publishes only fully completed 12-character lines and one padded
tail line when the model finishes. Hence historical row numbering stays stable.

When `--provider gemini`, an independent `GEMINI>` (space-padded to
12 bytes) row is appended before model generation; all following assistant
text rows start at column 0 with no inline `PC: ` label. The `GEMINI>`
row is attached to the same assistant `message_id` in SQLite and is
visible through the unchanged `C` reply format in SYNC/FETCH/UPDATE.
The assistant `messages.content` remains only model output, not the
visual heading; existing saved `PC:` rows are not rewritten.
Demo/other providers retain the previous prefix.

## D. Live delivery and bounded scheduling

After a Q, C reports `BUSY`. The client, while following the newest
cached row, issues periodic U + cache_end; if zero new finalized lines
exist, PC may respond with zero-row C; when new rows appear, C appends
at most six. If the user is viewing older history, no unsolicited PC
payload overwrites the screen: scrolling must request ranges through F.

F requests are made at the first/last 16 rows of a 48-row cache, one
in-flight request at a time, with safe six-visible-row eviction.
At a cache boundary, up to 12 extra arrow presses may be queued until
new rows have passed CRC validation. The UI displays LOADING while
waiting for uncached rows.

### Hardware limitations

This design is **cooperative**, not an RTOS or fully interrupt-driven
Z80 sender. `_SendAByte` still blocks briefly for a short command or
up to 48-character outgoing prompt. UNO TX batch ACKs cover physical
link handshakes, not application display acceptance. The default
35ms/byte gap is conservative. Adaptive tuning (opt-in after validation)
may reach 12ms but cannot guarantee a specific effective 6-row latency.
