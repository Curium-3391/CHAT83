# Hardware and TI Link wiring (CHAT83 v0.6.0)

[← README](../README.md) · [繁體中文安裝指南](quickstart.zh-TW.md) · [Detailed technical setup](v05-integrated-terminal.md)

## Current CHAT83 configuration

The public **v0.6.0** build runs on the **original TI-83 Plus** and an Arduino Uno loaded with the bundled custom `arduino/CHAT83_Uno_v05/CHAT83_Uno_v05.ino` firmware. This is a **115200-baud USB/COBS/CRC8** bridge, *not* the 9600-baud historical `serial2ti83` interface.

| TI Link 2.5 mm conductor | Arduino Uno pin |
| --- | --- |
| TIP | **D3** |
| RING | **D6** |
| Sleeve / shield | **GND** |

The Link uses a bidirectional, open-drain-style handshake. The Uno firmware switches pins between pulling LOW and releasing the line; it must **not** actively drive a high voltage onto the calculator's Link signals. Do not wire TIP/RING directly to UART push-pull TX/RX.

**PC ↔ Uno:** standard USB to Windows (`COM2` was observed on the real tested setup; use whichever COM port your system assigns). The Windows Python bridge opens it at **115200 baud** and waits for the Uno's serial-port reset before its handshake.

## Transferring the App vs running CHAT83

These are **two different Uno firmware modes**:

1. **Transfer mode (external upstream project):** [jw0k/serial2ti83](https://github.com/jw0k/serial2ti83) is used as a TiLP-compatible cable. Its example pinout defaults to **TIP=D2, RING=D3**. When using the CHAT83 D3/D6 cable, change **both** constants in the upstream sketch to TIP=3 and RING=6, or rewire accordingly. Upload `CHAT83.8xk` or `C83V5.8xp` via TiLP, then **close TiLP**.
2. **Chat mode:** disconnect the calculator Link cable before reflashing the Uno with the **bundled CHAT83 v0.5 sketch**, close the serial monitor and reconnect the calculator. Start `bridge_v05.py` at **115200 baud**, then open CHAT83 from APPS (or run `Asm(prgmC83V5)`).

CHAT83's custom Uno firmware **does not support TiLP transfers**. A separate TI-compatible transfer cable removes the need to switch Uno firmware.

## Conservative timing and known limitations

The demonstrated working physical setup uses **`--gap-ms 35 --reply-delay-ms 250`**. Power-cycle/reconnect recovery is not fully automatic, and an 81-byte historical FETCH has previously exhibited a handshake timeout. Optional `--batch-pause-ms` is for diagnosis, not a guaranteed cure. See [release notes](releases/v0.6.0.md) and the [TI Link protocol](v05-wire-protocol.md).

The Z80 client relies on the original TI-83 Plus I/O port behavior and is **not compatible** with TI-83 Plus Silver Edition or TI-84 models. No ESP32 or RP2040 adaptation is verified here.

## Credit

The upstream [`jw0k/serial2ti83`](https://github.com/jw0k/serial2ti83) project is a **separate MIT-licensed transfer firmware**. The custom CHAT83 Uno sketch is part of this repository; no upstream Arduino source has been vendored as CHAT83 code.
