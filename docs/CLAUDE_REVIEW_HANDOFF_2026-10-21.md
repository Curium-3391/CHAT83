# CHAT83 v0.5 — External Review Handoff (2026-10-21)

**Purpose:** Give Claude or another independent code reviewer the full state of the integrated experimental project and the unresolved **native TI-83 Plus `ERR:LINK`** fault.

## Repository / branch / do-not-merge rule

- Repo: `Curium-3391/CHAT83`
- Development branch: `feat/v05-integrated-terminal`
- Active **Draft** pull request: [#7](https://github.com/Curium-3391/CHAT83/pull/7) targeting `main`.
- Previously demonstrated, stable, real-hardware v0.3.2 release on `main`; v0.4 cooperative-link branch/PR [#6](https://github.com/Curium-3391/CHAT83/pull/6) established successful background RX, navigation and 48-row cache on original TI-83 Plus.
- **Do not merge PR #7 or declare the full v0.5 hardware working until its physical Link handshake and end-to-end serial exchange are validated.**
- All code/docs/CI changes described below are **already pushed to this branch**. Do not assume files present on the user's Windows computer have been fetched by the connector; use GitHub as the source of truth.

## Architecture and code entry points

| Layer | Actual file | Function |
|---|---|---|
| TI-83 Plus Z80 | [calculator/CHAT83_v05_chat.asm](../calculator/CHAT83_v05_chat.asm) | TI OS `_SendAByte` for initial `S`, Port 00/05 receive assist, `_GetCSC`, four-row input editor, 48-row ring/prefetch, CRC8 live updates |
| Uno firmware | [arduino/CHAT83_Uno_v05/CHAT83_Uno_v05.ino](../arduino/CHAT83_Uno_v05/CHAT83_Uno_v05.ino) | D2=TIP, D3=RING, cooperative open-drain Link FSM, 115200-baud USB COBS/CRC8, physical bit diagnostics |
| PC bridge | [bridge/bridge_v05.py](../bridge/bridge_v05.py) | USB COM port, SQLite, live answer polls, commands, `--debug-link` |
| USB codec | [bridge/usb_v05.py](../bridge/usb_v05.py) | COBS/CRC8, sixteen-byte USB TX batches, `D` debug enable, `J` periodic telemetry |
| App protocol | [bridge/protocol_v05.py](../bridge/protocol_v05.py) | `S/F/Q/U/R/K` requests, six-row `C` replies, CRC8/seq/absolute offsets |
| LLMs | [bridge/providers_v05.py](../bridge/providers_v05.py) | Offline demo; optional OpenAI Responses/Ollama streaming |
| AVR mock | [tests/avr_mock/test_uno_rx.cpp](../tests/avr_mock/test_uno_rx.cpp) | Native compile of actual .ino against 60us virtual pullup/ACK line delay |
| AVR GPIO mock | [tests/avr_mock/Arduino.h](../tests/avr_mock/Arduino.h) | Stub USB and open-drain pin timing for native FSM test |
| Test suite | [tests/test_v05.py](../tests/test_v05.py), [tests/test_v05_stress.py](../tests/test_v05_stress.py) | Python integration and randomized protocol/cache tests |
| CI | [.github/workflows/verify-v05.yml](../.github/workflows/verify-v05.yml) | Python, Uno AVR build, Z80 SPASM-ng assembly, real .ino native GPIO simulation, Windows ZIP |
| Technical spec | [docs/v05-wire-protocol.md](v05-wire-protocol.md) | Detailed wire and app framing |
| User install instructions | [docs/v05-integrated-terminal.md](v05-integrated-terminal.md) | Exact install flow, known faults, hardware checklist |

### Upstream reference / working baseline

[Original jw0k/serial2ti83](https://github.com/jw0k/serial2ti83/blob/master/serial2ti83.ino) successfully handled the same user's original TI-83 Plus via Uno D2/D3/GND for v0.3/v0.4. The new firmware is **not** a transparent serial-to-TI passthrough; it only understands COBS/CRC8 packets at 115200 baud. The old firmware is 9600-baud passthrough and is required for transferring `.8xp` files via TiLP if a separate TI Graph Link cable is unavailable.

## Ground-truth physical hardware observations (do not overinterpret)

**Hardware:** Original TI-83 Plus, Arduino Uno with USB-SERIAL CH340 on **COM2**, existing 2.5mm TI link connected to D2 TIP, D3 RING, common GND. The same wiring previously supported successful v0.4 calculator↔PC exchange.

### 1. Initial installation issue, now documented

Flashing Uno v0.5 *before* sending `C83V5.8xp` made TiLP time out because the firmware is incompatible. Correct installation: use original `serial2ti83` for TiLP transfer first, close TiLP, then flash Uno v0.5. The user successfully transferred `C83V5.8xp`, then flashed v0.5 Uno.

### 2. Confirmed USB transport success

PowerShell (actual user log):
```text
py "$HOME\Downloads\CHAT83_v05\bridge_v05.py" --port COM2 --provider demo --gap-ms 35 --verbose
CHAT83 v0.5 | COM=COM2 | provider=demo | model=offline | DB=...\chat83.sqlite3
CHAT83 Uno v0.5 handshake OK; gap 35ms
Listening for TI-83 Plus. Run Asm(prgmC83V5). Ctrl+C exits.
```

`py -m serial.tools.list_ports -v` returned:
```text
COM2
    desc: USB-SERIAL CH340 (COM2)
    hwid: USB VID:PID=1A86:7523 ...
```

**Meaning:** the host successfully sent its USB `P` and `G` packets, decoded the Uno `H` and `A` replies. **This does not establish electrical or protocol communication with the TI.**

### 3. Confirmed calculator fault

**When `Asm(prgmC83V5)` is run after Python is Listening**, the TI-83 Plus reports its **native ROM exception**:
```text
ERR:LINK
1:Quit
2:Goto
```

No `SYNC -> ...` log was observed from Python. The app's own `LINK ERROR` UI is not what appeared. From the source, immediately after boot variables and `draw_loading`, the client calls:
```asm
ld a,'S'
ld (request_kind),a
bcall(_SendAByte)
call enable_rx
```

Likely fault interval: around ROM `_SendAByte` while transmitting initial ASCII `S` (`0x53`), but **not conclusively proven**, because no post-failure physical trace has been supplied.

### 4. Important nuance: diagnostic zero counters were recorded only BEFORE touching the calculator

Actual user log with latest --debug-link option:
```text
CHAT83 Uno v0.5 handshake OK; gap 35ms
[UNO-DIAG] enabled: counts are bit attempts/acks/bytes/errors
Listening for TI-83 Plus. Run Asm(prgmC83V5). Ctrl+C exits.
[UNO-DIAG] start=0 ack=0 rx_bytes=0 rx_to=0 tx_to=0 state=0 TIP=H RING=H last_rx=0x00
... (same idle report repeated)
Uno link statistics: {'tx': 0, 'rx': 0, 'errors': 0, 'gap_ms': 35}
Stopped
```

**User explicitly stated they had NOT yet run the TI program during those zero-counter reports.** They subsequently said the calculator still displays `ERR:LINK`, but **no post-error `[UNO-DIAG]` counters have been provided**. Do not claim that Uno saw zero bits during the TI fault.

## Recent attempted mitigation — outcome unknown on real hardware

New Uno firmware has an explicit **`RX_ACK_SETTLE` 100µs guard** between releasing the ACK wire and returning to `IDLE`, to avoid reading a weak-pullup falling/rising tail on the Uno's *own* ACK line as a fresh TI bit. This is a **hypothesis and candidate fix, not established root cause**. A full diagnostic mode over USB `D,1` sends periodic `J` frames whose fields are printed in Python as:

```text
[UNO-DIAG] start=<bit-starts> ack=<acknowledged-bits> rx_bytes=<full-bytes>
           rx_to=<timeouts> tx_to=<timeouts> state=<fsm-state>
           TIP=<H/L> RING=<H/L> last_rx=0x<hex-byte>
```

Python usage:
```powershell
py "$HOME\Downloads\CHAT83_v05\bridge_v05.py" --port COM2 --provider demo --gap-ms 35 --debug-link
```

The native C++ harness **compiled the actual Uno `.ino`**, applying a modeled 60µs RC pullup delay and sending `0x53,0x00,0x7F,0xFF` one bit at a time. All four tests achieved exactly 8 starts and 8 ACKs. This does **not** validate real TI ROM timing or electrical waveforms.

CI on [run 39467576480](https://github.com/Curium-3391/CHAT83/actions/runs/39467576480): 51 Python unit tests passed, native virtual Link test passed, Uno AVR compiled, Z80 program assembled, test kit packaged.

## Explicit review request / preferred investigation order

1. **Independently inspect the original UNO firmware vs v0.5** for state machine and physical handshake differences: who pulls which pin low, ACK timing, acknowledge/release detection, `RX_ACK_SETTLE`, idle gap, and whether any paths can fail to see the first `0x53` bit.
2. **Inspect the actual Z80 `start` path**, TI OS `_SendAByte` assumptions and register/I/O mode invariants, and how native ROM ERR:LINK escapes assembly when handshake fails. Distinguish the original v0.4 behavior from changes in v0.5.
3. Evaluate if the **virtual 60µs rise-time mock is representative enough**, and suggest a targeted oscilloscope/logic analyzer or on-Uno probe with actionable measurements; do not assume CI hardware simulation proves the real device works.
4. Re-examine the **USB debug counter meaning** and event reporting; if a specific protocol bug emerges, propose the *minimum deterministic patch* with a corresponding regression test and hardware-repro command.
5. Review **end-to-end frame timing** independently, including Python UnoUsb `read(1)` behavior, batching, `S`/response sequencing, CRC errors, and whether incomplete sends can deadlock after an earlier fault.
6. Maintain the stable `main` branch unchanged; work only in `feat/v05-integrated-terminal` or an additional proposed branch/PR, and don't mark the current Draft PR ready prematurely.

### Missing single most useful observation

Run `bridge_v05.py --debug-link`, **leave it running**, execute `Asm(prgmC83V5)` on calculator, and collect ~2 seconds of **POST-`ERR:LINK`** `[UNO-DIAG]` output. If
- `start=0` afterward: initial low edge not seen (ROM execution, physical pin/wiring, timing).
- `start>0, ack<8`: physical bit-level ACK/handshake incomplete.
- `start=8, ack=8, rx_bytes=1, last_rx=0x53`: initial TI→Uno byte complete, investigate Uno→PC `R` queue and host receipt or subsequent ROM behavior.
- `rx_to>0`: stalled bit handshake detected.

**These are diagnostic hypotheses, not observed device results.**

---

This review handoff documents code committed in GitHub and first-party reported device logs. It intentionally **does not contain API keys, credentials, or private user identifiers**.


## Update 2026-10-21: GPIO D6 discovery and hard E5 evidence

- User confirmed their physical Uno **RING is D6**, not the earlier D3 assumption. The v0.5 Uno source in this branch has been updated to use **D6**; upstream serial2ti83 defaults to D3 and must be adjusted when that cable is reused for TiLP.
- Their latest run after making local D6 modifications reached `CHAT83 Uno v0.5 handshake OK` and then, following prolonged idle `J` snapshots of `start=0 ack=0`, Python terminated with:
  ```text
  Uno link statistics: {'tx': 0, 'rx': 0, 'errors': 1, 'gap_ms': 35}
  LINK ERROR: Arduino error code 5
  ```
- Firmware E5 is emitted inside `RX_WAIT_RELEASE` only when the incoming TI-driven bit line remains LOW for at least 30ms after Uno begins ACK. This proves Uno entered RX state, but because Python previously immediately exited, **no post-event counters** were captured. Do not mistake earlier idle zeros for evidence of no bit start.
- `bridge/usb_v05.py` now, **only with `--debug-link`**, reports E5 as a rate-limited warning and continues polling the 500ms `J` telemetry instead of tearing down COM2. Normal mode still raises E5. Next action: update **only usb_v05.py**, keep the user's locally configured D6 Uno in place, run debug bridge, trigger calculator, wait two seconds, collect snapshots, Ctrl+C. Exact E5 cause (missing ACK? source held LOW? transient pin race?) not yet known; do not merge Draft PR #7.
