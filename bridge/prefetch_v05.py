"""Pure Python model of the CHAT83 v0.5 predictive 48-row ring buffer.

Copied from prefetch_v04.py with PREFETCH_THRESHOLD raised from 8 to 16.
Not the Z80 implementation: tests/test_v05_stress.py uses Cache to check
cache / cursor / viewport invariants. The frame codec at the bottom is the
legacy v0.4 XOR format; the v0.5 bridge uses protocol_v05.py (CRC8) instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

CAPACITY = 48
VISIBLE = 6
LOOKAHEAD = 6
PREFETCH_THRESHOLD = 16


@dataclass(frozen=True)
class Fetch:
    direction: int   # -1 older, +1 newer
    start: int       # absolute zero-based display-row index
    count: int       # 1..6 rows
    sequence: int


@dataclass
class Cache:
    rows: list[Optional[str]] = field(default_factory=lambda: [None] * CAPACITY)
    head: int = 0
    start: int = 0
    size: int = 0
    cursor: int = 0
    view: int = 0
    next_sequence: int = 1
    inflight: Optional[Fetch] = None

    def end(self) -> int:
        return self.start + self.size

    def at(self, index: int) -> str:
        if not self.start <= index < self.end():
            raise IndexError(index)
        value = self.rows[(self.head + index - self.start) % CAPACITY]
        assert value is not None
        return value

    def visible(self) -> list[str]:
        if self.size == 0:
            return []
        return [self.at(i) for i in range(self.view, min(self.view + VISIBLE, self.end()))]

    def load(self, start: int, lines: list[str]) -> None:
        if start < 0 or len(lines) > CAPACITY:
            raise ValueError("invalid cache load")
        self.rows = [None] * CAPACITY
        self.head = 0
        self.start = start
        self.size = len(lines)
        for idx, line in enumerate(lines):
            self.rows[idx] = line
        self.cursor = start + max(0, len(lines) - 1)
        self.view = start + max(0, len(lines) - VISIBLE)
        self.inflight = None
        self.check()

    def check(self) -> None:
        assert 0 <= self.head < CAPACITY
        assert 0 <= self.size <= CAPACITY
        if self.size:
            assert self.start <= self.cursor < self.end()
            assert self.start <= self.view < self.end()
            assert self.view <= self.cursor < self.view + VISIBLE
        else:
            assert self.inflight is None

    def move(self, delta: int) -> bool:
        """Local-only cursor movement. Returns False if off cache."""
        if not self.size or not self.start <= self.cursor + delta < self.end():
            return False
        self.cursor += delta
        if self.cursor < self.view:
            self.view = self.cursor
        elif self.cursor >= self.view + VISIBLE:
            self.view = self.cursor - VISIBLE + 1
        self.check()
        return True

    def _protected(self) -> tuple[int, int]:
        """Protect the visible six-row viewport plus current selection."""
        return min(self.cursor, self.view), max(self.cursor + 1, min(self.view + VISIBLE, self.end()))

    def plan(self, total: int, direction: int) -> Optional[Fetch]:
        """Prepare one bounded speculative fetch (no unsolicited streaming).

        A current inflight fetch is never overwritten. The caller may mark it
        cancelled when direction reverses, but must drain/ACK the old packet.
        """
        if direction not in (-1, 1):
            raise ValueError("direction must be -1 or +1")
        if self.inflight or self.size == 0:
            return None
        low, high = self._protected()
        if direction == -1:
            if self.cursor - self.start > PREFETCH_THRESHOLD or self.start == 0:
                return None
            count = min(LOOKAHEAD, self.start)
            # Prevent evicting anything currently visible/selected.
            if self.size == CAPACITY and self.end() - count < high:
                return None
            start = self.start - count
        else:
            if self.end() - 1 - self.cursor > PREFETCH_THRESHOLD or self.end() >= total:
                return None
            count = min(LOOKAHEAD, total - self.end())
            if self.size == CAPACITY and self.start + count > low:
                return None
            start = self.end()
        request = Fetch(direction, start, count, self.next_sequence)
        self.next_sequence = (self.next_sequence % 255) + 1
        self.inflight = request
        return request

    def commit(self, request: Fetch, lines: list[str]) -> None:
        """Atomic staging-to-ring commit. No state change on malformed data."""
        if request != self.inflight:
            raise ValueError("out of order / cancelled prefetch")
        if len(lines) != request.count or any(not isinstance(x, str) or len(x) != 12 for x in lines):
            raise ValueError("invalid staging rows")
        if request.direction == -1 and request.start + request.count != self.start:
            raise ValueError("noncontiguous older fetch")
        if request.direction == 1 and request.start != self.end():
            raise ValueError("noncontiguous newer fetch")
        keep_low, keep_high = self._protected()
        if request.direction == -1:
            evict = max(0, self.size + request.count - CAPACITY)
            if self.end() - evict < keep_high:
                raise ValueError("would overwrite a visible row")
        else:
            evict = max(0, self.size + request.count - CAPACITY)
            if self.start + evict > keep_low:
                raise ValueError("would overwrite a visible row")

        # Validated. Commit without shifting the existing 48×13 logical lines.
        if request.direction == -1:
            for line in reversed(lines):
                self.head = (self.head - 1) % CAPACITY
                self.rows[self.head] = line
                self.start -= 1
                self.size = min(self.size + 1, CAPACITY)
        else:
            for line in lines:
                if self.size == CAPACITY:
                    self.head = (self.head + 1) % CAPACITY
                    self.start += 1
                    self.size -= 1
                self.rows[(self.head + self.size) % CAPACITY] = line
                self.size += 1
        self.inflight = None
        self.check()


# Legacy v0.4 XOR frame codec, kept for parity with prefetch_v04.py.
# Not used by bridge_v05.py; see protocol_v05.py for the v0.5 CRC8 frames.
# Each frame is small enough to stage in six 13-byte Z80 row slots.
# All integer offsets are little-endian unsigned 32-bit global line indices.
import struct


def _xor(data: bytes) -> int:
    value = 0
    for item in data:
        value ^= item
    return value


def encode_fetch(req: Fetch) -> bytes:
    """F + SEQ + DIRECTION(0 older,1 newer) + START(u32) + COUNT + XOR."""
    if not (1 <= req.sequence <= 255 and req.direction in (-1, 1)
            and 0 <= req.start <= 0xFFFFFFFF and 1 <= req.count <= LOOKAHEAD):
        raise ValueError("invalid fetch request")
    raw = b"F" + bytes([req.sequence, int(req.direction == 1)]) \
        + struct.pack("<I", req.start) + bytes([req.count])
    return raw + bytes([_xor(raw)])


def decode_fetch(raw: bytes) -> Fetch:
    if len(raw) != 9 or raw[0:1] != b"F" or _xor(raw) != 0:
        raise ValueError("malformed fetch request or checksum")
    seq, direction = raw[1], raw[2]
    if not seq or direction not in (0, 1) or not 1 <= raw[7] <= LOOKAHEAD:
        raise ValueError("invalid fetch request attributes")
    return Fetch(1 if direction else -1, struct.unpack("<I", raw[3:7])[0],
                 raw[7], seq)


def encode_chunk(req: Fetch, rows: list[str], flags: int) -> bytes:
    """C + SEQ + START(u32) + COUNT + FLAGS + 12*COUNT ASCII + XOR."""
    if not 0 <= flags <= 7 or len(rows) != req.count:
        raise ValueError("bad chunk length or flags")
    if not 0 <= req.count <= LOOKAHEAD or (not req.count and not (flags & 4)):
        raise ValueError("chunk count must be 1..6, or zero for an empty RESET")
    if any(len(r) != 12 or not r.isascii() or not r.isprintable() for r in rows):
        raise ValueError("chunk lines must be printable 12-byte ASCII")
    raw = b"C" + bytes([req.sequence]) + struct.pack("<I", req.start) \
        + bytes([req.count, flags]) + "".join(rows).encode("ascii")
    return raw + bytes([_xor(raw)])


def decode_chunk(raw: bytes) -> tuple[int, int, int, list[str]]:
    if len(raw) < 9 or raw[:1] != b"C" or _xor(raw) != 0:
        raise ValueError("malformed chunk or checksum")
    seq = raw[1]
    start = struct.unpack("<I", raw[2:6])[0]
    count, flags = raw[6], raw[7]
    if not 0 <= count <= LOOKAHEAD or flags > 7 or (not count and not (flags & 4)):
        raise ValueError("invalid chunk header")
    if len(raw) != 9 + count * 12:
        raise ValueError("invalid chunk size")
    payload = raw[8:-1]
    if any(not 32 <= ch <= 126 for ch in payload):
        raise ValueError("non-printable chunk payload")
    lines = [payload[x:x + 12].decode("ascii") for x in range(0, len(payload), 12)]
    return seq, start, flags, lines
