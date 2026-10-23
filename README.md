# CHAT83

**Gemini AI on an original TI-83 Plus — over a 2.5 mm link cable.**

[![Latest release](https://img.shields.io/github/v/release/Curium-3391/CHAT83?label=release)](https://github.com/Curium-3391/CHAT83/releases/latest)
[![CI](https://github.com/Curium-3391/CHAT83/actions/workflows/verify-v05.yml/badge.svg)](https://github.com/Curium-3391/CHAT83/actions/workflows/verify-v05.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**[Download v0.6.0](https://github.com/Curium-3391/CHAT83/releases/tag/v0.6.0)** · **[繁體中文安裝指南](docs/quickstart.zh-TW.md)** · **[Release notes](docs/releases/v0.6.0.md)**

CHAT83 turns a vintage **TI-83 Plus** into a keypad-operated, text-only AI chat terminal. A custom Arduino Uno interface carries the TI Link handshake to a Windows Python bridge, which streams Gemini responses back to the calculator. The calculator handles editing, display and history navigation; **inference and API credentials stay on the PC**.

> **Compatibility:** Original **TI-83 Plus only**. The current Z80 client is **not compatible** with TI-83 Plus Silver Edition or TI-84 models (different I/O port behavior). This is a hardware-tested first public release, **not** a guarantee of trouble-free operation on every setup.

## What works in v0.6.0

- **Live Gemini API chat:** multi-turn prompts and incremental replies, observed on real TI-83 Plus hardware.
- **Readable conversation view:** an independent `GEMINI>` row followed by full-width **12-character** response rows; selected-row highlight, scrollbar and older/newer history navigation.
- **48-character editor:** four rows of input, ALPHA/number modes, moving cursor and DEL. v0.6.0 clears the complete editor buffer between questions.
- **Persistent SQLite history:** saved on Windows; reload older messages without keeping everything in the calculator's limited RAM.
- **Robust transport:** CRC8-checked application and USB frames, bounded retransmissions, Uno cooperative TI Link handshake and recovery guidance for an interrupted session.
- **Other providers:** offline `demo`, optional OpenAI API or local Ollama. The demonstrated cloud hardware path is Gemini; these alternatives are not equally hardware-qualified.
- **Optional experiments:** `--word-wrap` for word-aware streaming lines, `--batch-pause-ms` to diagnose long FETCH delays, and `--debug-link` for electrical/link counters.

### How it fits together

```text
Original TI-83 Plus                Windows PC
 CHAT83.8xk / C83V5.8xp            Python bridge_v05.py
 Z80 editor + history              SQLite conversation history
          │                                  │
          │ 2.5 mm TI Link                   └── HTTPS → Gemini API
          │ TIP / RING / GND
          ▼
 Arduino Uno (custom CHAT83_Uno_v05 firmware)
          │
          └──────── USB serial 115200 baud ────────► PC
```

**Verified physical pin mapping:** TI Link **TIP → Uno D3**, **RING → Uno D6**, **sleeve → GND**. These are open-drain-style Link signals, **not TTL UART RX/TX**; do not drive the TI Link wires high with push-pull outputs.

## Get started (Windows)

### 1. Hardware and files

| You need | Notes |
| --- | --- |
| Original TI-83 Plus | Flash App `CHAT83.8xk`, or `C83V5.8xp` program |
| Arduino Uno and 2.5 mm TI Link cable | TIP=D3, RING=D6, sleeve=GND |
| Windows PC with USB and Python 3 | Tested serial setup: COM2 at 115200 baud |
| A way to transfer TI files | TiLP with a compatible adapter, or a separate TI-compatible transfer cable |
| Gemini API key and Internet | Required only for the Gemini provider; [Google AI Studio](https://aistudio.google.com/app/apikey) |

Download **[CHAT83-v0.6.0-Windows.zip](https://github.com/Curium-3391/CHAT83/releases/download/v0.6.0/CHAT83-v0.6.0-Windows.zip)** and extract it, for example into `Downloads\CHAT83-v0.6.0-Windows`.

**Install order matters:** the bundled **CHAT83 Uno v0.5** firmware is *not* TiLP-compatible. If the Uno is your only transfer adapter, first flash a [`serial2ti83`](https://github.com/jw0k/serial2ti83) sketch configured for your physical **D3/D6** wiring, transfer `CHAT83.8xk` with TiLP, **close TiLP**, and then reflash the bundled `CHAT83_Uno_v05.ino` before using the AI terminal. Disconnect the TI Link plug while reflashing. A separate TI transfer cable avoids swapping Uno firmware.

For a complete walkthrough, see the [繁體中文安裝指南](docs/quickstart.zh-TW.md) or the [detailed hardware procedure](docs/v05-integrated-terminal.md).

### 2. Install the Windows dependencies

In **PowerShell**, from the extracted folder:

```powershell
cd "$HOME\Downloads\CHAT83-v0.6.0-Windows"
py -m pip install -r .\requirements-v05-gemini.txt
```

Create a Gemini key in [Google AI Studio](https://aistudio.google.com/app/apikey), then set `GEMINI_API_KEY` in **Windows user environment variables** and open a new PowerShell session. **Never paste your key into GitHub, issues, screenshots, logs, Arduino firmware or the calculator.**

### 3. Start the bridge

```powershell
py .\bridge_v05.py --port COM2 --provider gemini --model gemini-3.5-flash-lite --gap-ms 35 --reply-delay-ms 250
```

Change `COM2` if Windows assigned a different port. The default model name shown above reflects the **tested project configuration**; available model names and API terms depend on your Google account and may change.

You should see `CHAT83 Uno v0.5 handshake OK` and `Listening for TI-83 Plus`. On the calculator, launch **APPS → CHAT83**, or run `Asm(prgmC83V5)` if you installed the program build.

Each new Gemini answer appears in separate 12-column history rows, for example:

```text
YOU: HELLO
GEMINI>
HELLO WORLD!
```

The illustrated text is only a display-format example; actual wording depends on the model.

### 4. Keyboard controls

| Key | Action |
| --- | --- |
| **ENTER** | Open the editor from history; send a question from the editor |
| **ALPHA** | Toggle letters and number/symbol input |
| **2nd** | Insert a space in the editor |
| **← / →** | Move the input cursor |
| **DEL** | Delete the character before the cursor |
| **↑ / ↓** | Browse history; fetch older/newer rows when needed |
| **GRAPH** | Jump to the newest messages |
| **MODE** | Cancel an active generation; on a `LINK ERROR` screen, request a fresh sync |
| **CLEAR** | Leave the editor or exit the terminal |

The input limit is **48 printable ASCII characters**. The host stores the full conversation; the TI displays a **48-row cache** and receives up to **six 12-character rows per reply frame**.

## Troubleshooting and limitations

| Symptom | What to check |
| --- | --- |
| `Uno handshake` fails | COM port, USB cable, correct custom Uno firmware; stop TiLP/Serial Monitor |
| TiLP cannot upload the App | CHAT83 Uno firmware does **not** emulate a TiLP cable; use the transfer adapter/firmware first |
| `LINK ERROR` or `LOADING` after reconnect | Reopen CHAT83, or press **MODE** from its `LINK ERROR` screen for a new SYNC; Windows can ignore obsolete retry requests but cannot automatically restore the interrupted scroll |
| `FETCH OLDER` times out | Keep `--gap-ms 35 --reply-delay-ms 250`; optional `--batch-pause-ms 150` is **diagnostic**, not a proven universal fix |
| Garbled/non-English reply | The renderer is **ASCII-only**; unsupported Unicode may be transliterated or replaced with `?` |
| Gemini request fails | Check `GEMINI_API_KEY`, Internet access, model availability and API quotas; the offline demo needs no API key |

**Known-safe starting point for this tested unit:** `--gap-ms 35 --reply-delay-ms 250`. Lower delays, long-running stability and fully automatic power-cycle/history recovery are **not** generally validated. Enabling `--adaptive` or changing multiple timing settings at once is not recommended during first setup.

Use `--word-wrap` if you want Gemini's English text wrapped at word boundaries, while preserving the standalone `GEMINI>` row. Do not run the App on unsupported calculator models.

## Project files and documentation

| Directory / file | Purpose |
| --- | --- |
| [`calculator/CHAT83_v05_chat.asm`](calculator/CHAT83_v05_chat.asm) | TI-83 Plus Z80 client, built as Flash App and Asm program |
| [`arduino/CHAT83_Uno_v05/`](arduino/CHAT83_Uno_v05/) | Custom Uno TI Link ↔ USB bridge |
| [`bridge/bridge_v05.py`](bridge/bridge_v05.py) | Windows serial, streaming and SQLite conversation engine |
| [`bridge/providers_v05.py`](bridge/providers_v05.py) | Gemini, demo, OpenAI and Ollama providers |
| [`windows/start-chat83-v05.ps1`](windows/start-chat83-v05.ps1) | Optional PowerShell launcher |
| [`docs/releases/v0.6.0.md`](docs/releases/v0.6.0.md) | Release notes and known limitations |
| [`docs/v05-wire-protocol.md`](docs/v05-wire-protocol.md) | Current TI Link / USB packet format (still v0.5-compatible) |
| [§docs/hardware.md§](docs/hardware.md) | Verified D3/D6 wiring and differences between TiLP upload and chat firmware |
| [`docs/v05-integrated-terminal.md`](docs/v05-integrated-terminal.md) | Hardware setup, detailed UI controls and debugging notes |
| [`docs/development-log.md`](docs/development-log.md) | Earlier prototypes and engineering history |
| [`tests/`](tests/) | Python integration, Z80 emulator and Uno Link mock tests |

**Why the `v05` filenames?** v0.6.0 extends the v0.5 architecture and **keeps its wire protocol and binary names** for compatibility; the **release tag** (`v0.6.0`) is the public software version.

## Verification, contributing and license

The v0.6.0 release commit passed **88 Python tests**, **15 Z80 emulator tests**, Uno compilation, a TI Link handshake simulation and Windows package generation. The [CI workflow](https://github.com/Curium-3391/CHAT83/actions/workflows/verify-v05.yml) builds these artifacts. Real-device Gemini chat and the standalone header have been observed on one original TI-83 Plus setup; this does not establish universal hardware reliability.

Issues and reproducible hardware logs are welcome. Please include the calculator model, pin mapping, firmware/software revision and sanitized Link diagnostic output, **never API keys**.

Project code and documentation: [MIT License](LICENSE). Thanks to [jw0k/serial2ti83](https://github.com/jw0k/serial2ti83) for the separate upstream transfer firmware, [SPASM-ng](https://github.com/alberthdev/spasm-ng) for Z80 assembly, and the other tools used to build and test the App.

For historic v0.2–v0.5 experiments, see the [development log](docs/development-log.md), [older protocol notes](docs/protocol-v03.md) and [cooperative Link design](docs/v04-cooperative-link.md).
