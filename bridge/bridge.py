"""CHAT83 v0.2 test bridge; no LLM API yet."""
import time
import serial

PORT = "COM2"
BAUD = 9600
MAX_REPLY = 48


def read_exact(ser, length):
    result = bytearray()
    while len(result) < length:
        piece = ser.read(length - len(result))
        if not piece:
            raise TimeoutError(f"Expected {length} bytes, got {len(result)}")
        result.extend(piece)
    return bytes(result)


def get_reply(question):
    # Replace this function with an LLM request in the next phase.
    if question.upper() == "HELLO":
        return "WORLD"
    if question.upper() == "PING":
        return "PONG"
    return "PC GOT: " + question.upper()


def main():
    print("CHAT83 bridge v0.2 | Ctrl+C to exit")
    with serial.Serial(PORT, BAUD, timeout=5, write_timeout=5) as ser:
        time.sleep(2.5)  # Arduino Uno resets when COM port opens
        ser.reset_input_buffer()
        print(f"Listening on {PORT} at {BAUD} baud")
        while True:
            try:
                header = ser.read(1)
                if not header:
                    continue
                length = header[0]
                if not 1 <= length <= 12:
                    print(f"Unexpected request length {length}; resync needed")
                    continue
                raw = read_exact(ser, length)
                question = raw.decode("ascii", errors="replace")
                print(f"TI > {question!r}")
                reply = get_reply(question).encode("ascii", errors="replace")[:MAX_REPLY]
                # Give the calculator time to enter its receive routine.
                time.sleep(0.15)
                ser.write(bytes([len(reply)]))
                ser.flush()
                # Send slowly to avoid overrunning the original Uno bridge.
                for char in reply:
                    ser.write(bytes([char]))
                    ser.flush()
                    time.sleep(0.02)
                print(f"PC > {reply.decode('ascii')!r}")
            except TimeoutError as exc:
                print(f"Timeout: {exc}; restart test on both sides")
                break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped")
    except serial.SerialException as exc:
        print(f"Serial port error: {exc}")
