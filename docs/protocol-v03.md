# CHAT83 v0.3 remote-history protocol (experimental)

This protocol is **not** compatible with the v0.2 client or bridge. Keep v0.2 files unchanged. Start **bridge_v03.py** before the v0.3 assembly program.

## Architecture

TI-83 Plus Z80 client (24 rows of local display cache) ↔ upstream jw0k/serial2ti83 on an Arduino Uno ↔ Python bridge ↔ persistent SQLite database.

The 96×64 LCD displays a title, six cached lines of text and a one-line footer. Each cached row occupies exactly **13 bytes** (12 ASCII chars + NUL for the ROM display routine). The full 24-row cache occupies **312 bytes** inside the Z80 program's RAM allocation. The SQLite database retains complete messages, plus separately wrapped display rows.

**Important:** The 24 lines are a paging cache, not a 24-line conversation limit. The database is not an infinite LLM context window; LLM integration is not yet implemented.

## Request bytes, TI → PC

| Request | Wire format | Meaning |
| --- | --- | --- |
| Sync | ASCII \`S\` | Fetch the most recent 24 display lines. |
| Older | ASCII \`O\` | Fetch overlapping older cache page, if available. |
| Newer | ASCII \`N\` | Fetch overlapping newer cache page, if available. |
| Ask | ASCII \`Q\`, LENGTH (1 byte), ASCII payload | Submit 1–12 printable ASCII bytes, persist messages, fetch most recent page. |

All commands return one page response.

## Page reply, PC → TI

\`\`\`text
byte 0        ASCII 'P' (0x50)
byte 1        row count, 0..24
byte 2        viewport first row, 0..max(0,count-6)
bytes 3..     count * 12 printable ASCII bytes, spaces padded
\`\`\`

A full page is **291 bytes**, not 312; the client adds 24 NUL terminators locally. The bridge sends each byte with a conservative default **35 ms delay** to reduce the risk of overflowing the unmodified Arduino UART buffer.

Scrolling within the current 24-line cache is local. When its boundary is reached, the client sends \`O\` or \`N\` and the PC returns an overlapping new page. SQLite stores messages and display rows across Python restarts; the local cache and scrolling cursor do not survive a calculator restart. \`S\` reloads the latest history.

### Known limitations

- Both the Z80 and Arduino communication paths use blocking routines.
- **No checksum, ACK, retry, packet ID or reconnection resynchronization yet.** A corrupted byte or timeout can desync the connection. Restart the calculator program and Python script together.
- Every page can require up to roughly **10 seconds** to transmit (plus OS and adapter overhead). Waiting is expected, not necessarily a hang.
- Only calculator ASCII keyboard entry, 12 characters max. Text from the PC is forced to ASCII.
- Python demo backend is not yet an LLM; \`DEMO\` intentionally generates a long sample response.
- SQL persistence does not imply safe simultaneous database modification by multiple clients, and very large histories may need indexed page browsing.

## Test plan

1. Make sure v0.2 still works separately.
2. Run \`bridge_v03.py\` with \`--port COM2\`, then launch v0.3 on the calculator. Empty database should display NO HISTORY.
3. ENTER to input; type HELLO and press ENTER. Check that YOU: HELLO and PC: WORLD are in the history.
4. Repeat with PING, 123 and DEMO. DEMO should span many pages.
5. Press UP repeatedly into previous cache pages, then DOWN back to the latest page.
6. Quit calculator and PC bridge, restart both. Recent history should return from SQLite.

If a page response fails, leave v0.2 as the fallback and share the observed LCD and PC log.
