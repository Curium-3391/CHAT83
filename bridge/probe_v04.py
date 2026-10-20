"""CHAT83 v0.4 raw link-assist hardware probe (NOT the chat bridge).

Purpose:
  Send test bytes slowly to TI-83 Plus while its Z80 continuously polls
  the hardware receive-assist latch and scans the keyboard via _GetCSC.
  The Uno still runs upstream jw0k/serial2ti83, unchanged.

Start this program first; THEN run CHAT83_v04_rx_probe.asm on the calculator.
The probe sends 'S' as a ready message. This script then sends bytes 0..127.
The TI screen should show RX:80 LAST:7F XOR:00, while UP/DOWN increment KEY.
"""
from __future__ import annotations

import argparse
import functools
import operator
import time


def make_payload(count: int = 128) -> bytes:
    if not 1 <= count <= 255:
        raise ValueError("probe count must be 1..255")
    return bytes(range(count))


def expected_values(payload: bytes) -> tuple[int, int, int]:
    if not payload:
        raise ValueError("payload must not be empty")
    return len(payload) % 256, payload[-1], functools.reduce(operator.xor, payload, 0)


def send_probe(ser, payload: bytes, pace: float = 0.055) -> None:
    if pace < 0.035:
        raise ValueError("pace below 35ms is not supported by this probe")
    for i, value in enumerate(payload, 1):
        ser.write(bytes([value]))
        ser.flush()
        time.sleep(pace)
        if i % 16 == 0 or i == len(payload):
            print(f"PC transmitted {i}/{len(payload)} bytes", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="CHAT83 v0.4 cooperative receive hardware probe")
    parser.add_argument("--port", default="COM2")
    parser.add_argument("--pace", type=float, default=0.055,
                        help="seconds between bytes; 0.055 seconds by default")
    parser.add_argument("--count", type=int, default=128, help="1..255 (default 128)")
    args = parser.parse_args()
    if args.pace < 0.035:
        parser.error("--pace must be at least 0.035")
    try:
        payload = make_payload(args.count)
    except ValueError as exc:
        parser.error(str(exc))

    import serial
    print(f"CHAT83 v0.4 LAB ONLY | {args.port}, 9600 bps | Ctrl+C to exit")
    print("Start the Z80 RX LAB program after 'Listening' appears.")
    with serial.Serial(args.port, 9600, timeout=5, write_timeout=5) as ser:
        time.sleep(2.5)  # Uno typically resets when opening its COM port
        ser.reset_input_buffer()
        print("Listening for Z80 ready byte 'S'...", flush=True)
        while True:
            if ser.read(1) == b"S":
                break
        # The Z80 must finish _SendAByte and enable port-0 receive assist.
        time.sleep(0.3)
        print("Sending probe; press UP/DOWN repeatedly during transmission!")
        send_probe(ser, payload, args.pace)
        count, last, checksum = expected_values(payload)
        print(f"PC SENT (not confirmed by calculator): "
              f"RX:{count:02X} LAST:{last:02X} XOR:{checksum:02X}")
        print("Confirm these on TI LCD; KEY should increment for UP/DOWN.")
        print("Press CLEAR on calculator to exit. Then Ctrl+C here if needed.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user")
    except Exception as exc:
        print(f"Probe failed: {exc}")
        raise
