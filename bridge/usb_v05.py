"""COBS + CRC8 USB transport for the CHAT83 v0.5 cooperative Uno firmware.

The 115200-baud USB protocol is distinct from the TI Link application
protocol. Each Arduino 'T' batch is at most 16 bytes and fully acknowledged
AFTER physical TI Link completion. USB R frames carry individual calculator
bytes. Arduino never needs a >64-byte SoftwareSerial buffer.
"""
from __future__ import annotations

from collections import deque
import time

MAX_BATCH = 16
MAX_RAW = 35


class LinkFailure(RuntimeError):
    pass


def crc8(data: bytes) -> int:
    c = 0
    for byte in data:
        c ^= byte
        for _ in range(8):
            c = ((c << 1) ^ 7) & 255 if c & 128 else (c << 1) & 255
    return c


def cobs_encode(data: bytes) -> bytes:
    if not data:
        return b"\x01\x00"
    out = bytearray(b"\x00")
    code_at = 0
    code = 1
    for byte in data:
        if byte == 0:
            out[code_at] = code
            code_at = len(out)
            out.append(0)
            code = 1
        else:
            out.append(byte)
            code += 1
            if code == 0xff:
                out[code_at] = code
                code_at = len(out)
                out.append(0)
                code = 1
    out[code_at] = code
    out.append(0)
    return bytes(out)


def cobs_decode(block: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(block):
        n = block[i]
        i += 1
        if not n or i + n - 1 > len(block):
            raise LinkFailure("invalid COBS code")
        out.extend(block[i:i + n - 1])
        i += n - 1
        if n != 255 and i < len(block):
            out.append(0)
    return bytes(out)


def make_frame(message: bytes) -> bytes:
    if not message or len(message) > MAX_RAW - 1:
        raise ValueError("invalid USB packet length")
    return cobs_encode(message + bytes([crc8(message)]))


def decode_frame(block: bytes) -> bytes:
    raw = cobs_decode(block)
    if len(raw) < 2 or crc8(raw) != 0:
        raise LinkFailure("bad USB frame CRC")
    return raw[:-1]


class UnoUsb:
    """Serial.read/write-compatible object for the TI application bridge."""

    def __init__(self, serial_port, *, gap_ms: int = 35, timeout: float = 6.0):
        if not 2 <= gap_ms <= 50:
            raise ValueError("gap_ms must be in 2..50")
        self.ser = serial_port
        self.timeout = timeout
        self.gap_ms = gap_ms
        self.buf = bytearray()
        self.calc = deque()
        self.events = deque()
        self.next_seq = 1
        self.tx_count = 0
        self.rx_count = 0
        self.link_errors = 0

    def _send(self, message: bytes):
        self.ser.write(make_frame(message))
        self.ser.flush()

    def _poll(self, deadline: float) -> tuple[bytes | None, bool]:
        """Return one complete received USB payload or a timeout indicator."""
        while time.monotonic() < deadline:
            b = self.ser.read(1)
            if not b:
                continue
            if b == b"\x00":
                if not self.buf:
                    continue
                data = bytes(self.buf)
                self.buf.clear()
                try:
                    return decode_frame(data), False
                except LinkFailure:
                    self.link_errors += 1
                    raise
            self.buf.extend(b)
            if len(self.buf) > MAX_RAW + 2:
                self.buf.clear()
                self.link_errors += 1
                raise LinkFailure("overlong USB frame")
        return None, True

    def _dispatch(self, deadline):
        packet, expired = self._poll(deadline)
        if expired:
            return False
        assert packet
        k = packet[:1]
        if k == b"R" and len(packet) == 2:
            self.calc.append(packet[1])
            self.rx_count += 1
        elif k == b"E" and len(packet) == 2:
            self.link_errors += 1
            raise LinkFailure(f"Arduino error code {packet[1]}")
        else:
            self.events.append(packet)
        return True

    def _wait_for(self, kind: bytes, seq: int | None = None):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            for _ in range(len(self.events)):
                item = self.events.popleft()
                if item[:1] == kind and (seq is None or len(item) > 1 and item[1] == seq):
                    return item
                self.events.append(item)
            if not self._dispatch(deadline):
                break
        raise TimeoutError(f"timed out waiting for Uno USB {kind!r} seq {seq}")

    def connect(self):
        self._send(b"P")
        packet = self._wait_for(b"H")
        if len(packet) != 4 or tuple(packet[1:3]) != (0, 5) or packet[3] < MAX_BATCH:
            raise LinkFailure(f"not CHAT83 v0.5 Uno firmware: {packet!r}")
        self._send(bytes([ord("G"), self.gap_ms]))
        ack = self._wait_for(b"A", seq=0)
        if len(ack) != 3 or ack[2] != 0:
            raise LinkFailure(f"Uno rejected gap setting: {ack!r}")

    def read(self, size: int = 1) -> bytes:
        if size <= 0:
            return b""
        deadline = time.monotonic() + self.timeout
        while not self.calc:
            if not self._dispatch(deadline):
                return b""
        return bytes(self.calc.popleft() for _ in range(min(size, len(self.calc))))

    def write(self, data: bytes) -> int:
        for pos in range(0, len(data), MAX_BATCH):
            chunk = data[pos:pos + MAX_BATCH]
            seq = self.next_seq
            self.next_seq = 1 if seq == 255 else seq + 1
            self._send(b"T" + bytes([seq, len(chunk)]) + chunk)
            ack = self._wait_for(b"A", seq=seq)
            if len(ack) != 3 or ack[2] != 0:
                raise LinkFailure(f"Uno TI TX failed at {pos}: {ack!r}")
            self.tx_count += len(chunk)
        return len(data)

    def flush(self):
        """The .write method already waits for completed link handshakes."""
        pass

    def stats(self):
        return dict(tx=self.tx_count, rx=self.rx_count, errors=self.link_errors,
                    gap_ms=self.gap_ms)
