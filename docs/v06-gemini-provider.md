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
- **Experimental GEMINI> display:** for `--provider gemini`, the bridge
  writes a separate, padded `GEMINI>` row to SQLite **as soon as the question
  is accepted**, before streaming starts. Answer text begins on the *next*
  row at column 0, using **all 12 characters** instead of reserving the
  four-column `PC: ` prefix. Each committed row remains immutable, so
  `SYNC`, `FETCH OLDER`, `FETCH NEWER` and live `UPDATE` use the
  existing packet format and consistent absolute row offsets.
  No Z80 App or Uno firmware update is required, only the Python bridge.
  `demo` and existing historical `PC:` display rows are unchanged.
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



### GEMINI> answer layout (experimental display improvement)

This is an example of the **12-character history text rows** carried by
the wire protocol, not a full LCD screenshot. A `GEMINI>` header is one
independent, persisted 12-character row:

```text
YOU: HELLO
GEMINI>
HELLO WORLD!
FROM GEMINI.
```

The answer begins at the first column of the row after `GEMINI>`.
For comparison, the former inline `PC: ` prefix left only eight cells for
the first part of the answer. The model itself still receives only plain
question/assistant message content, with no `GEMINI>` artificial text.
Older assistant rows in an existing `chat83.sqlite3` DB remain unchanged.

**Verification:** dedicated offline tests cover the 12-column width,
immediate header while streaming is busy, multiple questions, legacy
database rows, the immutable history indexes and `F`/`U` reply frames.
Real TI-83 Plus LCD presentation of this **new layout** still needs user
acceptance. Preserve known-good `--gap-ms 35 --reply-delay-ms 250`
while checking it.


### TI-83 Plus power-cycle / Windows Bridge restart: stale `R` recovery

**2026-10-21 real-device report:** Gemini `GEMINI>` heading worked, but after
powering off / reconnecting and scrolling backward until `LOADING`, a newly
started Bridge printed only `rx=3, tx=0` then terminated with
`LINK ERROR: cannot retry unknown/exhausted frame` before any new `SYNC`.
A three-byte `R + SEQ + CRC8` is an application retry. The TI may still
be waiting on a reply from before the PC process restarted, while the PC
has **no** `last_reply` in memory. This is a state-resynchronization error,
not an API-key or SQLite failure. Physical proof of the calculator's
exact state at power-off is not available.

**Bridge resilience fix (this branch):** CRC-validated `R` that has no
matching cached reply (including retries exhausted in this PC process) is
ignored with a bounded `[RESYNC NEEDED]` warning; the Windows serial loop
keeps listening. This preserves the SQLite conversation and does **not**
pretend that a `FETCH` reply can be reconstructed from `R`: the retry
contains a SEQ but not the original historical START. Replaying a
`SYNC` C with SEQ=0 during an active F would break the Z80 client's
response validation. A correct, matching retry still resends the original
exact bytes, including CRC, without issuing another LLM request.

**What to do on the calculator:**
- Start the Windows Bridge first; then exit CHAT83 using `CLEAR` (if
  permitted by the current screen) and reopen it from APPS / `Asm(prgmC83V5)`
  to start a fresh `S` request.
- If the calculator already displays its own `LINK ERROR` screen, press
  `MODE` to retry with a new `S`. If it is still on `LOADING`, allow
  its finite retries to finish before using MODE.
- Keep `--gap-ms 35 --reply-delay-ms 250` during the test, and look
  for `[RESYNC NEEDED]` followed eventually by
  `[TX-BEGIN] SYNC ...` and `SYNC -> ...`.
- Do not delete `chat83.sqlite3`, don't manually send a fabricated C
  reply, and don't repeatedly restart Windows when one stale R arrives.

**Limit:** This is safe recovery of the *Windows Bridge*, not fully
automatic restoration of a suspended TI history scroll. Automatic
restoration requires a compatible Z80 client change that can initiate a
fresh S after exhausting a request whose old reply is unavailable.
Validation of the original device after power cycles is still pending.
