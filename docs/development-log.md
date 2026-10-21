# Development log

## 2026-10-20 — v0.1 link test

- TiLP could transfer `.8xp` to an actual TI-83 Plus through serial2ti83.
- A Z80 test application sent `HELLO`; a Windows Python bridge on `COM2` received it.
- Windows sent `WORLD` and the calculator displayed it.
- **Status: hardware-confirmed in the development session.**

## 2026-10-20 — v0.2 interactive terminal

- Calculator keyboard entry, English letters, numerals, and short messages tested.
- The PC log recorded `HELLO`, `123`, and `A`, with matching PC replies.
- Calculator display of `PC GOT: 123` confirmed by the tester.
- **Status: hardware-confirmed for the scenarios above.** This is not a comprehensive reliability test.

## 2026-10-20 — v0.3 history prototype

- Prototype idea: retain and scroll recent dialogue in RAM.
- Initial assembly produced `SE113: Unknown opcode '.ds'` on SPASM-ng.
- The proposed fix replaces `.ds` with explicit `.db` bytes.
- **Status: not yet confirmed to assemble and run correctly on device.** Do not treat as release-quality firmware.
- Follow-up: `.ds` was replaced and CI assembles the client with SPASM-ng. v0.3 was later reported working on real hardware (SYNC, HELLO, DEMO).

## v0.3.1 / v0.3.2 — cursors, boundary flags, delta replies

- v0.3.1 added `>`/`_` cursors and older/newer page flags; v0.3.2 added `D` delta replies (27 bytes for HELLO/WORLD instead of 292).
- **Status:** merged to `main`. The v0.5 review handoff describes v0.3.2 as the stable, hardware-demonstrated release.

## v0.4 — cooperative link (branch `feat/v04-cooperative-link`, PR #6)

- Non-blocking RX via the original TI-83 Plus Port 00h/05h receive assist, `_GetCSC` keyboard polling and a 48-row predictive cache, still using upstream serial2ti83.
- **Status:** background RX, navigation and the 48-row cache were reported working on an original TI-83 Plus. Not merged.

## 2026-10-21 — v0.5 integrated terminal (branch `feat/v05-integrated-terminal`, PR #7)

- New Uno firmware (115200-baud COBS/CRC8), CRC8 app frames, streaming LLM providers, four-line editor.
- CI: Python tests, Arduino Uno compile, SPASM-ng assembly, native Uno handshake mock and a Windows test kit all pass.
- Hardware: PC↔Uno USB handshake confirmed on COM2 (CH340). Running `Asm(prgmC83V5)` shows the ROM `ERR:LINK` and no `SYNC` reaches the PC. The `RX_ACK_SETTLE` guard is an unverified candidate fix.
- **Status: not working on hardware.** The next step is the `--debug-link` counters captured *after* `ERR:LINK` (see [CLAUDE_REVIEW_HANDOFF_2026-10-21.md](CLAUDE_REVIEW_HANDOFF_2026-10-21.md)).

## 2026-10-21 — v0.5 Flash App and UI polish

- The calculator client also builds as a signed Flash App (`CHAT83.8xk`, APPS menu). Writable state moved out of the program image into `plotSScreen`/`appBackUpScreen`; `_PutS` was replaced because a bcall hides App strings from the OS.
- UI: inverse title/hint bars, inverse selected row, pixel scrollbar, block cursor and length counter, flicker-free redraws. Fixed the ALPHA letter table, which was shifted from D onward.
- `C83DEMO` offline build and a ROM-free Z80 harness that runs the real builds against `bridge_v05.ConversationEngine` in CI.
- **Status:** CI- and emulator-tested only. Not yet run on a physical TI-83 Plus, and the v0.5 `ERR:LINK` is still open.

## Roadmap

1. Resolve the v0.5 `ERR:LINK` on the Uno ↔ TI-83 Plus link.
2. Run the v0.5 hardware acceptance checklist (editor, demo, streaming, wraparound, cancel/recovery, real LLM, speed).
3. Port bridge to MCU Wi-Fi hardware after PC protocol stabilizes.
