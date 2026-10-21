# CHAT83

**A retro serial terminal for the TI-83 Plus, on the road to LLM connectivity.**

> **Current status:** v0.2 and v0.3.2 work on real hardware, and the v0.4 cooperative RX has also been demonstrated on real hardware. The v0.5 build adds the LLM integration but is **not yet working on hardware**: the calculator reports `ERR:LINK` with the new Uno firmware. This is experimental Z80 software.

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

**Current limitation (v0.2):** the calculator clears the previous message when starting another. v0.3.x adds remote paging and SQLite history; see below.

## Project layout

```text
calculator/
  CHAT83_v02.asm          # v0.2 reference client (hardware-tested)
  CHAT83_v03_remote.asm   # v0.3.2 remote-history client
  CHAT83_v04_rx_probe.asm # v0.4 receive-assist probe (C83RX)
  CHAT83_v04_chat.asm     # v0.4 cooperative chat client (C83V4)
  CHAT83_v05_chat.asm     # v0.5 integrated terminal (C83V5)
arduino/
  CHAT83_Uno_v05/         # v0.5 Uno firmware (replaces serial2ti83)
bridge/
  bridge.py               # v0.2 serial2ti83 responder
  bridge_v03.py           # v0.3.2 SQLite history bridge
  bridge_v04.py, probe_v04.py, prefetch_v04.py
  bridge_v05.py           # v0.5 bridge: SQLite + demo/OpenAI/Ollama
  protocol_v05.py         # v0.5 app frames (CRC8)
  usb_v05.py              # v0.5 USB COBS/CRC8 transport to the Uno
  providers_v05.py        # v0.5 LLM providers
  prefetch_v05.py         # 48-row cache model used by tests
  requirements*.txt
windows/
  start-chat83-v05.ps1    # v0.5 PowerShell launcher
tests/                    # Python unit tests, native Uno handshake mock,
                          # Z80 emulator tests (tests/emulator/)
tools/
  ti_0104_pubkey.py       # public app-signing key for RabbitSign checks
docs/
  protocol.md             # v0.2 wire format
  protocol-v03.md         # v0.3.1/v0.3.2 wire format
  v04-cooperative-link.md # v0.4 design and test procedure
  v05-integrated-terminal.md # v0.5 install, operation, known faults
  v05-wire-protocol.md    # v0.5 USB and app framing
  hardware.md             # wiring notes and upstream credit
  development-log.md      # observed tests, open work and roadmap
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

## Experimental v0.3.2: Fast incremental replies

The earlier v0.3.1 re-sent **all 24 cached rows after every question**, creating an approximately 10-second wait for even `HELLO`. v0.3.2 changes this when the user is on the newest page:

- Python sends a `D COUNT FLAGS ROWS` **delta** containing only new text rows.
- Z80 shifts existing cached rows as needed and appends the new ones.
- A two-row `HELLO` / `WORLD` exchange now requires only 27 return bytes (previously 292 when history was full).
- Requests from an older page, or answers spanning more than 24 lines, still use the original full `P` page; history `SYNC`, `OLDER` and `NEWER` are also unchanged.
- The `chat83.sqlite3` database schema and history persist unchanged.

**Both sides must use v0.3.2.** Update the calculator from `calculator/CHAT83_v03_remote.asm` and PC from `bridge/bridge_v03.py` from the same revision, then test after closing TiLP. The new protocol extension is documented in [protocol-v03.md](docs/protocol-v03.md). Experimental until real-device testing passes.

## Experimental v0.4 and v0.5

- **v0.4** (`C83V4`, `bridge_v04.py`, upstream serial2ti83): non-blocking receive through the original TI-83 Plus Port 00h/05h receive assist, `_GetCSC` keyboard polling and a 48-row predictive cache. See [v04-cooperative-link.md](docs/v04-cooperative-link.md).
- **v0.5** (`CHAT83.8xk` App or `C83V5.8xp`, `CHAT83_Uno_v05.ino`, `bridge_v05.py`): new 115200-baud COBS/CRC8 Uno firmware, CRC8 application frames with retransmission, a four-line 48-character editor, and streaming replies from demo, OpenAI or Ollama providers. The calculator client is a signed Flash App launched from the **APPS** menu, with inverse title/hint bars, a highlighted selection and a scrollbar. `C83DEMO.8xk` is an offline UI preview for emulators. **Not working on hardware yet**: Uno reported RX timeout E5; the user's actual RING is on D6 (not upstream D3). Use `--debug-link` with current Python codec for post-error counters. **Install order matters**: transfer `C83V5.8xp` with TiLP under the original serial2ti83 *before* flashing the v0.5 Uno firmware, because the v0.5 firmware does not support TiLP. See [v05-integrated-terminal.md](docs/v05-integrated-terminal.md) and [v05-wire-protocol.md](docs/v05-wire-protocol.md).

Both run on the **original TI-83 Plus only**; port 05h means something different on the TI-83 Plus SE and TI-84 Plus.

## Roadmap

- Verify the history/scrolling prototype against SPASM-ng and real TI-83 Plus hardware.
- Improve LCD input UX and longer messages.
- Implement resilient packets with acknowledgments / retransmission.
- Get the v0.5 Uno ↔ TI link working on hardware (`ERR:LINK`), then validate the LLM terminal end to end. API credentials stay on the PC, never on the calculator.
- Replace the PC bridge with an RP2040/ESP32-class Wi-Fi MCU later.

## Credits and license

- Link hardware bridge: [jw0k/serial2ti83](https://github.com/jw0k/serial2ti83) (upstream MIT license, separate project).
- Calculator toolchain: [SPASM-ng](https://github.com/alberthdev/spasm-ng).
- This repository's original code and docs: [MIT License](LICENSE). No upstream Arduino source is copied into this repo.

See the [development log](docs/development-log.md) for the distinction between confirmed results and planned features.
