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

## Roadmap

1. Verify/fix v0.3 history display and RAM layout.
2. Add input UX improvements and robust LCD scrolling.
3. Add framing/error recovery and long replies.
4. Integrate an LLM provider through the PC bridge with API keys kept off calculator.
5. Port bridge to MCU Wi-Fi hardware after PC protocol stabilizes.
