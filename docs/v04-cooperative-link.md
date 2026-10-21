# CHAT83 v0.4 — Cooperative Link / Predictive Prefetch

Status: **experimental engineering branch**. Not a replacement for hardware-tested v0.3.2 and not a complete UI implementation yet.

## Critical discovery on the original TI-83 Plus

The *original* TI-83 Plus (not SE/84+) provides a receive-assist mode:
- Port 0x00 bit 2 enables the byte receiver: \`LD A,04h / OUT (00h),A\`.
- Port 0x00 bit 3 indicates an RX byte is complete.
- Read port 0x05 to obtain and acknowledge that byte.

These details come from [WikiTI Port 00](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:00) and [WikiTI Port 05](https://wikiti.brandonw.net/index.php?title=83Plus:Ports:05). **On TI-83+ SE / TI-84+, port 05 is RAM paging**: this specific probe MUST NOT be run on those models.

The same calculator ROM provides \`_GetCSC\`, a scan-code routine that does not block waiting for a key. A cooperative loop can poll RX readiness and keyboard each iteration, without \`_RecAByteIO\` blocking the entire reply.

The Uno's existing upstream sketch can remain unchanged *if the hardware receive assist interoperates reliably with its bit handshake*. This has **not yet been validated physically**.

## Stage 1 — hardware receive + keyboard probe (implemented)

Files:
- \`calculator/CHAT83_v04_rx_probe.asm\` (assemble under program name \`C83RX\`)
- \`bridge/probe_v04.py\` (Windows Python 3, pyserial)

Procedure:
1. Leave the v0.3.2 files and your SQLite database alone.
2. Assemble the probe or download CI's \`C83RX.8xp\` artifact and transfer it with TiLP, then **fully close TiLP**.
3. Start \`py bridge/probe_v04.py --port COM2\` on Windows.
4. Run \`Asm(prgmC83RX)\` on the *original* TI-83 Plus.
5. After a one-byte 'S' ready request, the Python script sends **128 bytes** at 55 ms intervals (takes ~7 seconds). While RX increases, press UP and DOWN a few times.
6. Expected final display: \`RX:80\`, \`LAST:7F\`, \`XOR:00\`; \`KEY:xx\` increases with presses. These values are hexadecimal. Use CLEAR to exit and release the link port.
7. Compare actual LCD, whether the display freezes during transmission, and Python logs. A Python log of \`PC transmitted\` only proves PC transmission, **not successful reception**.

The probe does not send chat questions, load SQLite history, or preload 24 rows. It tests the prerequisite for *real* non-blocking RX.

### Failure cases

If RX stays at zero or skips bytes, don't install the v0.4 design as the chat program. Likely causes include receiver-assist handshake differences, OS/keyboard interference, the Uno's 50 ms bit timeout, or the single-byte RX latch being overwritten. The probe intentionally avoids relying on a software RX FIFO before this is measured.

## Stage 2 — predictive cache reference model (implemented in Python)

Files:
- \`bridge/prefetch_v04.py\`
- \`tests/test_v04.py\`

24-row logical ring, 6 visible rows, upper/lower 8-row prefetch thresholds, six-row staging requests. Every selected line, viewport position and requested page is in *absolute display-row units*. The model rejects a commit that would evict currently visible text.

\`\`\`text
     24 × 13 bytes active ring (312 B)
  ┌────────┬────────┬────────┐
  │  0..7  │ 8..15  │ 16..23 │
  │  UP    │ center │ DOWN   │
  └────────┴────────┴────────┘
            ↕
   6 × 13 bytes staging buffer (78 B)
\`\`\`

The host-side proposed prefetch protocol (not yet wired to Z80) uses:

Request: \`F + SEQ + DIRECTION + START:u32le + COUNT + XOR\`
- 9 bytes total, DIRECTION 0=older 1=newer, COUNT 1..6.
- START is an absolute line offset within the conversation, not a cache-relative pointer.

Response: \`C + SEQ + START:u32le + COUNT + FLAGS + (COUNT×12 ASCII) + XOR\`
- 9+12×COUNT bytes; 81 bytes for a six-row chunk.
- Checksummed, validates sequence/offset before committing staging rows.
- Only one inflight request; full-frame ACK/credit and cancellation mechanics are *still TODO*.
- On cursor reversal, do not overwrite protected rows; either validate and commit harmlessly or discard staging safely after the frame finishes.

## Stage 3 — integrate real prefetch with the calculator UI (not yet implemented)

After Stage 1 passes actual hardware:
1. Add staged \`C\` reception to the cooperative RX loop and a bounded per-frame parser; do **not** repaint the whole LCD on each byte.
2. Integrate six-row staging buffer and active ring into \`CHAT83_v03_remote.asm\`-derived UI.
3. Arrange requests ahead of the selected cursor reaching cache limits (upward: index ≤8, downward: ≥15), with hysteresis.
4. Introduce ACK/credit, timeout and reset/resync handling and test hardware timing before reducing Python pacing.
5. Keep input responsiveness while receiving and benchmark rapid reverse scrolling, low-memory/history edges, and long replies. Do not merge experimental hardware I/O into \`main\` until the real TI-83 Plus confirms it.

**What cannot be guaranteed:** Remote data unavailable locally cannot appear with zero latency. Smoothness means the UI remains responsive, even if an unavailable row needs a short LOAD indication.


## Stage 3 experimental integrated chat client — NOW IMPLEMENTED, HARDWARE-UNTESTED

A separate hardware-testable interactive terminal has been added. It does **not**
replace the working v0.3.2 calculator app and has a different program name:

- \`calculator/CHAT83_v04_chat.asm\` → compiled artifact \`C83V4.8xp\`
- \`bridge/bridge_v04.py\` (depends on \`bridge_v03.py\` and \`prefetch_v04.py\` in the **same folder**)
- \`tests/test_bridge_v04.py\` checks initialization, Q, historical Q reset, chunk framing, bounds/CRC

The original v0.4 hardware RX probe \`C83RX\` was physically verified:
128 bytes accepted, LAST=7F, XOR=00 and KEY increased **during** transmission.
That verifies the underlying receive-assist approach, not this integrated chat app.

### Protocol v0.4

The v0.4 chat client is **NOT wire-compatible** with either the v0.3.2 Python
bridge or \`probe_v04.py\`. Run exactly \`bridge_v04.py\`.

Client → PC:
- \`S\` initial sync, respond with newest **at most six rows**.
- \`F SEQ DIR START:u32le COUNT XOR\` bounded fetch (9 bytes).
- \`Q LENGTH ASCII LATEST\` user question plus one byte (0/1) indicating
  whether client currently holds the newest history.

PC → Client:
- \`C SEQ START:u32le COUNT FLAGS COUNT×12 ASCII XOR\`.
- \`SEQ=0\` for S/Q, or the requested sequence number for F.
- \`COUNT=0..6\`; zero count is only legal if FLAGS contains RESET.
- FLAGS bit0=older rows exist; bit1=newer rows exist; bit2=replace active cache.
- For a latest-page \`HELLO\` / \`WORLD\`, append only the two new rows.
  For lengthy DEMO responses or asking from old history, send a RESET frame of
  the newest six lines. The SQLite conversation continues to store everything.

Port 00h RX hardware assist is enabled after the client's short outbound
command completes. During the whole reply the main loop polls port 00h/05h
and \`_GetCSC\`, so UP/DOWN can move inside cached rows while six-row frames
arrive. The received frame is staged (max 81 bytes), checksum checked, and
applied as a single logical ring update.

Prefetch triggers on entering the upper/lower third of the 24-row cache,
depending on the most recent scroll direction. The client computes a safe
prefetch size \`1..6\`, bounded by free capacity plus rows that would not
overwrite the currently visible six-line viewport. Reversing direction
during a transfer may cause a validated frame to be discarded rather than
overwriting the user's selection. Only one request is in flight.

**Current limitations:** the input editor still uses ROM \`_GetKey\`,
so entering INPUT is deferred until the in-flight prefetch completes.
Sending Q/F uses a short blocking ROM \`_SendAByte\`. Received bytes and
scrolling are cooperative, not interrupt-driven. This is an experimental
prototype; future work should include robust timeouts, cancellation/credit
ACK, rolling checksum stronger than XOR, debouncing and smoothing.

### Hardware smoke test — when CI has passed

1. Download the v0.4 CI artifact \`C83V4.8xp\`, not \`C83RX.8xp\`.
2. Transfer it via TiLP, then close TiLP so COM2 is free.
3. Place \`bridge_v04.py\`, \`bridge_v03.py\`, and \`prefetch_v04.py\` from
   branch \`feat/v04-cooperative-link\` together in e.g. Downloads.
4. Start \`py "$HOME\Downloads\bridge_v04.py" --port COM2 --db "$HOME\Downloads\chat83_v04_trial.sqlite3"\`
   (using a new database for first smoke tests protects prior conversations).
5. Run \`Asm(prgmC83V4)\` on the ORIGINAL TI-83 Plus. The client starts with an
   initial six-row sync. Watch PowerShell for \`SYNC -> 0 rows\` and LCD
   \`NO HISTORY\`.
6. ENTER, type HELLO, ENTER. Expect a two-row \`Q 'HELLO'\` response and the
   same YOU/PC content as previous versions; short frames should finish
   within a few seconds at this conservative 55ms/byte pacing.
7. Type DEMO to create long history. Scroll upward and back downward while
   PowerShell logs FETCH OLDER/NEWER. The UI must respond to UP/DOWN while a
   FETCH is still transmitting. Some off-cache rows may remain unavailable
   until the chunk arrives; do not expect zero latency for uncached text.
8. Press CLEAR to exit. If the UI shows LINK ERROR, note PC log, LCD state,
   and last successful request; restart Python and calculator together.

**Do not merge the integrated v0.4 client to main until this device smoke test
and longer stress tests pass.**


## v0.4 follow-up: 48-line ring to reduce refetch thrashing

After a successful real-device demonstration of the integrated chat client, the user reported that fast scrolling sometimes runs ahead of available rows. Their PC log showed repeated `FETCH OLDER @0 (6)` and `FETCH NEWER @24 (6)` during back-and-forth navigation. With the original 24-line ring, switching direction can evict rows that need to be fetched again.

This branch now uses **48×13 = 624 bytes** of Z80 active cache, rather than 24×13 = 312 bytes. The six-line staging frame remains at most 81 bytes, and the host's 55 ms/byte default is unchanged. The Python ring-reference model and its test assertions have been updated to a matching 48-row capacity.

Why this helps: the trial conversation is approximately 30 visible rows, so once loaded it can fit in the entire 48-row cache. That should eliminate repeated `@0` ⇄ `@24` fetches for the same history, **without re-downloading rows when switching directions**. This is an expected improvement, not yet confirmed on device for the enlarged build.

What this **does not** solve: a six-row cold fetch is still 81 bytes × 55 ms = **4.455 seconds minimum from the fixed PC pacing**, and a user can outrun remote data. The long-term target remains a receiver-credit/ACK protocol with safe adaptive pacing, explicit unavailable-row indication, and measured input latency while TX/RX is active. Reducing pace blindly may corrupt bytes on the Uno/TI Link connection.
