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
