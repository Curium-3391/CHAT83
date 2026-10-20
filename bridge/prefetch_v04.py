"""Pure Python model for CHAT83 v0.4 predictive 24-row ring buffer.

Not the physical Z80 implementation yet: this deterministic model is used to
prove cache / cursor / viewport invariants before touching TI-83 Plus RAM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

CAPACITY = 24
VISIBLE = 6
LOOKAHEAD = 6
PREFETCH_THRESHOLD = 8


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

        # Validated. Commit without shifting the existing 24×13 logical lines.
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
