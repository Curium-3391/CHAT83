"""Deterministic v0.5 cache and corruption stress tests, independent of hardware."""
import random
import unittest
from pathlib import Path

from prefetch_v05 import Cache, CAPACITY, PREFETCH_THRESHOLD
from protocol_v05 import (RangeRequest, Chunk, encode_fetch, decode_fetch,
                          encode_chunk, decode_chunk)
from usb_v05 import (make_frame, decode_frame, cobs_encode, cobs_decode)


def line(i):
    return f"ROW{i:09d}"  # exactly twelve characters


class StressTests(unittest.TestCase):
    def test_48_row_cache_can_wrap_a_long_conversation(self):
        c = Cache()
        c.load(400, [line(i) for i in range(400, 448)])
        self.assertEqual(CAPACITY, 48)
        self.assertEqual(PREFETCH_THRESHOLD, 16)
        for _ in range(120):
            moving = c.move(-1)
            req = c.plan(1000, -1)
            if req is not None:
                c.commit(req, [line(i) for i in range(req.start, req.start + req.count)])
            if not moving:
                c.move(-1)
            c.check()
            self.assertEqual(c.at(c.cursor), line(c.cursor))
        self.assertLess(c.cursor, 400)
        for _ in range(150):
            moved = c.move(1)
            req = c.plan(1000, +1)
            if req:
                c.commit(req, [line(i) for i in range(req.start, req.start + req.count)])
            if not moved:
                c.move(1)
            c.check()
            self.assertEqual(c.at(c.cursor), line(c.cursor))

    def test_random_reverse_direction_preserves_active_rows(self):
        rng = random.Random(0x83)
        c = Cache()
        c.load(500, [line(i) for i in range(500, 548)])
        for _ in range(2000):
            direction = rng.choice((-1, 1))
            c.move(direction)
            req = c.plan(1000, direction)
            if req:
                # Simulate direction change DURING in-flight reception.
                for _ in range(rng.randrange(0, 5)):
                    c.move(-direction)
                original_visible = c.visible()
                original_cursor = c.cursor
                try:
                    c.commit(req, [line(i) for i in range(req.start, req.start + req.count)])
                except ValueError:
                    # Validated staging may be discarded when it would overwrite
                    # visible/current rows. Caller must eventually reissue.
                    c.inflight = None
                else:
                    self.assertEqual(c.visible(), original_visible)
                    self.assertEqual(c.cursor, original_cursor)
            c.check()
            self.assertEqual(c.at(c.cursor), line(c.cursor))

    def test_random_crc_and_cobs_corruption_is_detected(self):
        rng = random.Random(83)
        for _ in range(100):
            seq = rng.randrange(1, 256)
            offset = rng.randrange(0, 1000000)
            fetch = encode_fetch(RangeRequest(seq, bool(seq & 1), offset, 6))
            self.assertEqual(decode_fetch(fetch).start, offset)
            bad = bytearray(fetch)
            bad[rng.randrange(1, len(bad) - 1)] ^= 1 << rng.randrange(8)
            with self.assertRaises(ValueError):
                decode_fetch(bytes(bad))
            rows = tuple(line(offset + i) for i in range(6))
            packet = encode_chunk(Chunk(seq, offset, rng.randrange(0, 32), rows))
            self.assertEqual(decode_chunk(packet).rows, rows)
            damaged = bytearray(packet)
            damaged[rng.randrange(1, len(damaged) - 1)] ^= 1 << rng.randrange(8)
            with self.assertRaises(ValueError):
                decode_chunk(bytes(damaged))
            usb = make_frame(packet[:16])
            self.assertEqual(decode_frame(usb[:-1]), packet[:16])

    def test_z80_program_is_not_using_blocking_getkey(self):
        src = Path(__file__).resolve().parents[1] / "calculator" / "CHAT83_v05_chat.asm"
        text = src.read_text(encoding="utf-8")
        self.assertNotIn("bcall(_GetKey)", text)
        self.assertIn("bcall(_GetCSC)", text)
        self.assertIn("CACHE_ROWS EQU 48", text)
        self.assertIn("MAX_INPUT EQU 48", text)
        self.assertIn("crc8_update:", text)
        self.assertIn("poll_live:", text)
        self.assertIn("retry_frame:", text)
        self.assertIn("cursor_refresh:", text)


if __name__ == "__main__":
    unittest.main()
