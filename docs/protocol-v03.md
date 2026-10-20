# CHAT83 v0.3.1 remote-history protocol (experimental)

**Both the Z80 program and Python bridge must be updated together.** The older v0.3 protocol used a three-byte page header; this revision adds a fourth byte.

## Transport

TI-83 Plus ⇄ Arduino Uno with jw0k/serial2ti83 ⇄ Windows Python ⇄ SQLite.

The calculator caches 24 lines, each 12 ASCII characters plus one NUL terminator (312 bytes of writable program RAM). Windows retains all messages and separately wrapped display lines in SQLite. On-screen history has six rows.

## TI-83 Plus → PC

- `S`: synchronize newest 24 display lines.
- `O`: get older page.
- `N`: get newer page.
- `Q LEN ASCII`: send a question, length 1–12 bytes.

## PC → TI-83 Plus

```text
byte 0      ASCII 'P'
byte 1      COUNT (0 to 24)
byte 2      VIEW, top row of visible cache window
byte 3      FLAGS: bit0=older data exists, bit1=newer data exists
bytes 4..   COUNT × 12 printable, space-padded ASCII characters
```

Full page size: 292 bytes. Arduino serial pacing is currently 35 ms per byte, so a full page takes around 10 seconds.

**Boundary fix:** at the oldest line, if FLAGS bit0 is 0, UP stays local rather than needlessly requesting another 24-line page. Similarly, at the newest line, if bit1 is 0, DOWN stays local. At a real page boundary, downloading an older/newer page still takes time.

**Cursor controls:** a `>` at LCD column 14 marks the selected history line; UP and DOWN move the cursor, scrolling the viewing window when needed. ENTER opens input; the `_` caret after the typed message is steady (not blinking); DEL removes a letter; CLEAR in input returns to history, while CLEAR in history exits.

## Test procedure

1. Keep the working v0.2 for rollback.
2. Upload the latest v0.3.1 `CHAT83.8xp` from CI, close TiLP.
3. Launch `py bridge/bridge_v03.py --port COM2`, then `Asm(prgmCHAT83)`.
4. Type HELLO, then DEMO. Use UP to reach HELLO; repeatedly press UP. **There should be no extra OLDER log line at the oldest record.**
5. Go DOWN to the newest line and press DOWN again; no unnecessary NEWER request.
6. Verify `>` follows history navigation; enter the input screen and verify `_` moves with typing and DEL.
7. Restart both programs to confirm SQLite history survives.

## Limitations

This remains a local canned-reply demonstration, not an LLM integration. The ROM link routines are blocking; no ACK, CRC, retransmission, stream recovery, Unicode, or blinking text caret yet. The Python database (`chat83.sqlite3`) may contain private messages and must remain outside Git.
