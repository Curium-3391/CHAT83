# CHAT83

**A retro serial terminal for the TI-83 Plus, on the road to LLM connectivity.**

> **Current status:** v0.2 text exchange has been tested on real hardware. **LLM integration is planned, not yet implemented.** This is experimental Z80 software.

CHAT83 lets a TI-83 Plus talk to a Windows PC through an Arduino Uno running [jw0k/serial2ti83](https://github.com/jw0k/serial2ti83). The calculator runs a Z80 Assembly client built with SPASM-ng; the PC runs a Python/pyserial application-level bridge.

```text
TI-83 Plus (Z80) <-- 2.5 mm link --> Arduino Uno
     <-- USB / serial, 9600 baud --> Windows Python bridge
                                      |
                                      +--> local test replies (now)
                                      +--> LLM API (future)
```

## Features (v0.2, tested)

- Input up to **12 ASCII characters** using the calculator keypad.
- Send a length-prefixed request to the PC.
- Receive up to **48 ASCII characters** and display the reply.
- Continue sending messages without restarting the PC bridge.
- Key examples confirmed in a real test: `HELLO` → `WORLD`, `123` → `PC GOT: 123`, `A` → `PC GOT: A`.

**Current limitation (v0.2):** the calculator clears the previous message when starting another. Experimental v0.3 adds paging and SQLite history and has passed automated compilation, but still needs real-device testing.

## Project layout

```text
calculator/
  CHAT83_v02.asm      # known working reference client
bridge/
  bridge.py           # Python / serial2ti83 responder
  requirements.txt
docs/
  protocol.md         # application-level wire format and limits
  hardware.md         # wiring notes and upstream credit
  development-log.md  # observed tests, open work and roadmap
```

## Quick start

**You need:** TI-83 Plus, Arduino Uno-compatible serial2ti83 adapter, USB connection to Windows, SPASM-ng with `ti83plus.inc`, TiLP for uploading calculator programs, Python 3.

1. Flash and wire upstream [serial2ti83](https://github.com/jw0k/serial2ti83); verify you can send `.8xp` programs with TiLP.
2. Assemble `calculator/CHAT83_v02.asm` into a TI-83 Plus `.8xp` program called `CHAT83`. For a local SPASM-ng install, see the assembler's instructions and include path; e.g. `spasm-ng calculator/CHAT83_v02.asm CHAT83.8xp` with `ti83plus.inc` available.
3. Transfer `CHAT83.8xp` using TiLP. **Quit TiLP** before opening serial communication from Python.
4. Install the PC requirement: `py -m pip install -r bridge/requirements.txt`.
5. Edit `PORT = "COM2"` near the top of `bridge/bridge.py` if Windows assigned a different serial port.
6. Run `py bridge/bridge.py` and wait for `Listening on COM2 at 9600 baud`.
7. On the TI-83 Plus, execute `Asm(prgmCHAT83)`, type `HELLO` (use ALPHA for letters), and press ENTER. Expect `WORLD`.

Controls: **ENTER** submits a request (and starts the next one when viewing the reply); **DEL** removes a character; **CLEAR** exits.

The original Arduino sketch provides byte-level transport, not delivery acknowledgment or retries. Do not assume data integrity from the presence of a PC log alone. See [protocol details](docs/protocol.md) for limitations and timing.

## Experimental v0.3.1: Remote History + Cursors

This is a **hardware-untested refinement** of v0.3 on branch `feat/remote-history-v03`. The old v0.3 was reported working on real TI-83 Plus hardware (SYNC, HELLO, DEMO). v0.3.1 adds:

- A `>` history cursor at the right of the currently selected row.
- A steady `_` text-entry cursor, which follows typing and DEL.
- Server-provided **older/newer boundary flags** so pressing UP at the oldest record or DOWN at the newest record no longer starts a pointless ~10-second transfer.
- A new four-byte page header: `P COUNT VIEW FLAGS`. **Old v0.3 binaries and Python bridge are NOT wire-compatible with this refinement.**

Relevant files: `calculator/CHAT83_v03_remote.asm`, `bridge/bridge_v03.py`, [protocol details](docs/protocol-v03.md). The CI workflow builds a downloadable experimental `CHAT83.8xp` artifact.

To test, first install v0.3.1 `CHAT83.8xp` with TiLP, close TiLP, and replace the old local Python file with the v0.3.1 `bridge_v03.py` before launching:

```powershell
py -m pip install -r bridge/requirements.txt
py bridge/bridge_v03.py --port COM2
```

On the calculator run `Asm(prgmCHAT83)`, send `HELLO` and `DEMO`, then scroll UP to the oldest record and press UP a few more times. The PC log should show no extra `OLDER` request at the global beginning. Scroll to the newest record and verify no redundant `NEWER` request. The `>` and `_` cursors should track navigation and typing.

Persistent conversations are stored in a gitignored `chat83.sqlite3` file beside the Python script. The SQLite schema is unchanged; the existing database from v0.3 can be reused. The LLM connection is still planned, **not yet implemented**.

## Roadmap

- Verify the history/scrolling prototype against SPASM-ng and real TI-83 Plus hardware.
- Improve LCD input UX and longer messages.
- Implement resilient packets with acknowledgments / retransmission.
- Connect the Python backend to an LLM provider; keep API credentials on the PC, not on the calculator.
- Replace the PC bridge with an RP2040/ESP32-class Wi-Fi MCU later.

## Credits and license

- Link hardware bridge: [jw0k/serial2ti83](https://github.com/jw0k/serial2ti83) (upstream MIT license, separate project).
- Calculator toolchain: [SPASM-ng](https://github.com/alberthdev/spasm-ng).
- This repository's original code and docs: [MIT License](LICENSE). No upstream Arduino source is copied into this repo.

See the [development log](docs/development-log.md) for the distinction between confirmed results and planned features.
