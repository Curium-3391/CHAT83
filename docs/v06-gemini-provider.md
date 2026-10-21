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

3. Configure `GEMINI_API_KEY` **locally** in Windows user environment variables;
   open a new PowerShell afterward. For a temporary test in a single terminal
   session, enter `$env:GEMINI_API_KEY = Read-Host "Gemini API key"` and keep
   that terminal private. Prefer Windows Credential/Environment Variables
   for routine use. Never print the secret.
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

Unit tests can simulate the SDK and verify role translation, streaming,
dependency/key handling and provider registration. **Real Gemini API
calls have not been run by CI** (no credentials available). Physical
Gemini-on-calculator generation requires the user's own API key and
real-device testing.

Code change is intentionally isolated on `feat/v06-gemini-provider`, a new
PR against `main`. Do **not** claim Gemini hardware/API validation merely
because the established demo test succeeded.
