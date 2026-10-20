# Hardware and link setup

## Proven hardware path

1. TI-83 Plus (2.5 mm stereo link connector).
2. Arduino Uno or compatible board running [jw0k/serial2ti83](https://github.com/jw0k/serial2ti83).
3. USB connection to Windows PC.
4. Python bridge, currently configured for `COM2` at 9600 baud (edit `PORT` if needed).

The upstream sketch uses **tip → Arduino pin 2**, **ring → Arduino pin 3**, and **sleeve → GND**. Follow the original wiring guide and firmware carefully. The calculator link wires are not ordinary UART TX/RX pins. Do not attach them directly to a push-pull MCU UART.

### Notes

- First verify file transfer with TiLP (GrayLink compatibility) before using CHAT83.
- **Close TiLP** before starting the Python bridge; both programs cannot own the COM port simultaneously.
- The Arduino may reset when its serial port opens; the Python program waits 2.5 seconds.
- Neither an ESP32 nor RP2040 is tested in this repository yet. Adapting the electrical interface requires correct voltage and open-drain/tri-state behavior.

## Upstream credit

`serial2ti83` was created by **jw0k**, licensed under MIT in the upstream repository. This project uses the upstream firmware externally; it does not claim authorship of or vendor a copy of that firmware.
