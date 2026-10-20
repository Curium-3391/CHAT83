# CHAT83 serial protocol (v0.2)

This document describes the **hardware-tested v0.2 application-level protocol** between `calculator/CHAT83_v02.asm` and `bridge/bridge.py`.

## Transport

- TI-83 Plus 2.5 mm link port → Arduino Uno running [jw0k/serial2ti83](https://github.com/jw0k/serial2ti83) → PC USB serial port
- Arduino firmware baud rate: **9600**, 8-bit serial data.
- The Arduino transports raw link-port bytes; it does **not** interpret CHAT83 messages.
- No `.8xp` transfers occur during a chat session; TiLP is only used to install calculator code.

## Request: calculator → PC

```text
+------------+----------------------+
| LENGTH (1) | ASCII DATA (1..12 B)|
+------------+----------------------+
```

The length is one unsigned byte. The PC expects 1..12 bytes of ASCII payload.

## Response: PC → calculator

```text
+------------+----------------------+
| LENGTH (1) | ASCII DATA (0..48 B)|
+------------+----------------------+
```

The calculator rejects a response length greater than 48 bytes. The Python bridge limits responses to 48 ASCII bytes. The current Z80 application does not implement sophisticated timeout recovery.

## Known test cases

- `HELLO` → `WORLD`
- `PING` → `PONG`
- `123` → `PC GOT: 123`
- `A` → `PC GOT: A`

## Timing and caveats

The Python bridge waits approximately 150 ms before sending its response and pauses about 20 ms between payload bytes to accommodate the original Arduino bridge. These delays are empirical, not an acknowledgment or a reliable delivery guarantee.

**Not implemented:** checksum, framing resynchronization, ACK/NAK, retransmission, message IDs, multi-packet replies, UTF-8, streaming, secure transport, and LLM API calls.

The future protocol should support MCU and PC bridges without changing the calculator UI.
