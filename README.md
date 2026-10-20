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

## Experimental v0.3: Remote History

**v0.3 is assembled and CI-tested but has NOT been tested on the actual TI-83 Plus yet.** It is on branch `feat/remote-history-v03` so that the proven v0.2 in `main` remains untouched.

- Calculator source: `calculator/CHAT83_v03_remote.asm`
- PC source: `bridge/bridge_v03.py`
- Protocol and packet layout: [v0.3 remote history](docs/protocol-v03.md)
- GitHub Actions produces a downloadable experimental `CHAT83.8xp` artifact.

Build the Z80 application with SPASM-ng as **CHAT83** and transfer it by TiLP, or get the experimental `.8xp` from the passing CI run. **Close TiLP** before starting the Python bridge. Install Python dependencies via `py -m pip install -r bridge/requirements.txt`, then start:

```powershell
py bridge/bridge_v03.py --port COM2
```

Start `Asm(prgmCHAT83)` on the calculator after Python says it is listening. Expect a delay while the 24-row cache loads.

- In history: **UP/DOWN** scroll (automatically fetch remote pages); **ENTER** opens input; **CLEAR** exits.
- In input: **ALPHA** for letters, digits and SPACE; **DEL** erases; **ENTER** sends; **CLEAR** returns to history.
- Try `HELLO`, `PING` and `DEMO`. `DEMO` intentionally generates more than 24 lines to exercise remote paging.
- All messages are kept in `bridge/chat83.sqlite3` on Windows (gitignored). Restarting both programs should fetch recent history again.

This is **not yet an LLM client**. v0.3 uses canned test answers. Never pair the v0.2 calculator program with the v0.3 Python bridge or vice versa; their wire protocols differ.

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
