# CHAT83 Gemini API provider — experimental Windows-only integration

Baseline: CHAT83 v0.5 has **physically passed** `HELLO` → `PC: WORLD` with
an original TI-83 Plus, TIP=D3, RING=D6, `--gap-ms 35`,
`--reply-delay-ms 250`. This addition changes **only Python**.
Existing `C83V5.8xp` / `CHAT83.8xk` and Uno firmware remain unchanged.

## Setup — Windows PowerShell

1. Create an API key at [Google AI Studio](https://aistudio.google.com/app/apikey).
   Do **not** paste the secret into chat, GitHub, the firmware, or a screenshot.
2. Install the optional SDK once:

   ```powershell
   py -m pip install -r "$HOME\Downloads\CHAT83_v05\requirements-v05-gemini.txt"
   ```

3. Configure `GEMINI_API_KEY` **locally**: in Windows search for
   **Environment Variables** → under **User variables** add `GEMINI_API_KEY`
   with the Google AI Studio key as its value. Open a **new PowerShell**
   afterward so the process picks it up. Keep the key out of shell history,
   GitHub, screenshots, code, and chat; do not print it.
4. Start the bridge **before** launching CHAT83 on the calculator:

   ```powershell
   py "$HOME\Downloads\CHAT83_v05\bridge_v05.py" --port COM2 --provider gemini --model gemini-3.5-flash-lite --gap-ms 35 --reply-delay-ms 250
   ```

   You can use `--model gemini-3.8-flash` if available to your project.
   Google can change availability and pricing; check Google AI Studio.

5. On TI-83 Plus launch `CHAT83` from APPS or `Asm(prgmC83V5)`.
   Ask a short ASCII question. On the Windows bridge, check for
   `Q '...'`, `UPDATE`, and no error; on TI LCD confirm that the answer
   appears and is readable.

## Provider and encoding details

- Uses the **official** `google-genai` SDK's
  `client.models.generate_content_stream` API.
- Converts SQLite `user` messages to Gemini role `user`, and prior
  SQLite `assistant` messages to Gemini role `model`; preserves order.
- `DEFAULT_SYSTEM` requests concise plain-English ASCII; the existing
  `ascii_text` sanitizer and 12-column `StableRows` apply downstream,
  so non-ASCII output may display as `?`.
- All key material stays in the PC process. Never store API key in GitHub,
  SQLite messages, requests sent across the TI Link, or the calculator.
- Missing `GEMINI_API_KEY` fails on provider startup; missing
  `google-genai` reports an explicit pip installation suggestion.
  API errors appear through existing `[AI ERROR]` flow.
- Streaming HTTP generation continues in a worker thread. No new serial
  framing, pin mapping, CRC, or Z80 changes are required.
- Default `--provider demo` continues working without any cloud key.

## Verification status

Unit tests mock the SDK and verify role translation, streaming,
dependency/key handling and provider registration. **CI does not call the
real Gemini API** and does not have credentials.

**2026-10-21 user-confirmed real hardware milestone:** The user reported
Gemini working on the original TI-83 Plus and provided a Windows Bridge
log proving real `--provider gemini` requests with streaming `UPDATE`
frames on the TI Link, including two successive prompts. See the trace
below. This confirms an initial real-device Gemini session, but it does
not yet establish LCD character-perfect display, long-term stability,
every model variant, or provider cost limits.

Code change remains isolated on `feat/v06-gemini-provider`, a PR
against `main`. **Do not merge until the user explicitly approves.**

### Gemini real-device log (2026-10-21)

Windows `COM2`, `--provider gemini --model gemini-3.5-flash-lite`,
`--gap-ms 35 --reply-delay-ms 250 --debug-link`, physical Uno
`TIP=D3, RING=D6`:

```text
CHAT83 Uno v0.5 handshake OK; gap 35ms
SYNC -> 0 rows, flags=04, 9 bytes
Q 'HELLO' -> 1 rows, flags=08, 21 bytes
UPDATE @1 -> 2 rows, flags=09, 33 bytes
UPDATE @3 -> 1 rows, flags=01, 21 bytes
Q 'HOW ARE YOU' -> 2 rows, flags=09, 33 bytes
UPDATE @6 -> 6 rows, flags=03, 81 bytes
UPDATE @12 -> 1 rows, flags=01, 21 bytes
Uno link statistics: {'tx': 228, 'rx': 55, 'errors': 0, 'gap_ms': 35, 'rx_timeout_events': 0}
Stopped
```

The user described the test as successful (`有了耶`). Consecutive
calculator `Q` requests and subsequent streamed `U` requests reached
the PC; all printed confirmed reply batches completed. `BUSY=0x08`
was present while generation was ongoing and absent in the final frames.
The longest visible reply was 81 bytes (six rows). Uno bit counters
reached `start=440`, `ack=440`, `rx_bytes=55`, with
`rx_to=0`, `tx_to=0`, `errors=0`.

Notably one `[TX-BEGIN] UPDATE @1: 9 bytes` event did not have its own
matching completion log in the supplied excerpt before the next
`UPDATE @1` request; do not interpret every `TX-BEGIN` as a
completed frame. The successful subsequent `UPDATE @1` and final
counters establish the tested transport's progress.

