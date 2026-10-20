"""v0.4 no-hardware smoke tests and ring-cache invariants."""
import unittest
from unittest.mock import patch

from prefetch_v04 import (Cache, CAPACITY, LOOKAHEAD, Fetch, encode_fetch,
                          decode_fetch, encode_chunk, decode_chunk)
from probe_v04 import expected_values, make_payload, send_probe


def row(i):
    return f"LINE{i:08d}"  # exactly twelve ASCII characters


class FakeSerial:
    def __init__(self):
        self.bytes_sent = bytearray()

    def write(self, data):
        self.bytes_sent.extend(data)

    def flush(self):
        pass


class ProbeTests(unittest.TestCase):
    def test_probe_expected_result(self):
        p = make_payload(128)
        self.assertEqual(expected_values(p), (128, 127, 0))
        with self.assertRaises(ValueError):
            make_payload(0)

    def test_probe_pacing_and_no_implicit_rx_ack(self):
        ser = FakeSerial()
        with patch("probe_v04.time.sleep"):
            send_probe(ser, make_payload(8), pace=0.055)
        self.assertEqual(ser.bytes_sent, bytes(range(8)))
        with self.assertRaises(ValueError):
            send_probe(ser, b"A", pace=0.02)


class FrameTests(unittest.TestCase):
    def test_fetch_roundtrip_and_corruption(self):
        req = Fetch(-1, 0x12345678, 6, 7)
        raw = encode_fetch(req)
        self.assertEqual(len(raw), 9)
        self.assertEqual(decode_fetch(raw), req)
        bad = bytearray(raw)
        bad[4] ^= 0x01
        with self.assertRaises(ValueError):
            decode_fetch(bytes(bad))

    def test_chunk_roundtrip_and_corruption(self):
        req = Fetch(1, 500, 6, 9)
        rows = [row(i) for i in range(500, 506)]
        wire = encode_chunk(req, rows, 3)
        self.assertEqual(len(wire), 9 + 6 * 12)
        self.assertEqual(decode_chunk(wire), (9, 500, 3, rows))
        bad = bytearray(wire)
        bad[-2] ^= 1
        with self.assertRaises(ValueError):
            decode_chunk(bytes(bad))
        with self.assertRaises(ValueError):
            decode_chunk(wire[:-1])

    def test_chunk_rejects_nonascii_and_oversize(self):
        req = Fetch(-1, 0, 1, 1)
        with self.assertRaises(ValueError):
            encode_chunk(req, ["中文".ljust(12)], 0)
        with self.assertRaises(ValueError):
            encode_chunk(Fetch(-1, 0, 7, 1), [row(i) for i in range(7)], 0)


class RingTests(unittest.TestCase):
    def test_up_prefetch_keeps_viewport_and_selection(self):
        c = Cache()
        c.load(100, [row(i) for i in range(100, 124)])
        for _ in range(17):
            self.assertTrue(c.move(-1))
        old_selected = c.cursor
        old_visible = c.visible()
        req = c.plan(total=200, direction=-1)
        self.assertIsNotNone(req)
        self.assertEqual((req.start, req.count), (94, LOOKAHEAD))
        c.commit(req, [row(i) for i in range(94, 100)])
        self.assertEqual((c.start, c.end()), (94, 118))
        self.assertEqual(c.cursor, old_selected)
        self.assertEqual(c.visible(), old_visible)
        self.assertEqual(c.at(94), row(94))
        self.assertEqual(c.at(117), row(117))

    def test_down_prefetch_keeps_selection(self):
        c = Cache()
        c.load(100, [row(i) for i in range(100, 124)])
        old_cursor = c.cursor
        old_visible = c.visible()
        req = c.plan(200, +1)
        self.assertIsNotNone(req)
        self.assertEqual((req.start, req.count), (124, 6))
        c.commit(req, [row(i) for i in range(124, 130)])
        self.assertEqual((c.start, c.end()), (106, 130))
        self.assertEqual(c.cursor, old_cursor)
        self.assertEqual(c.visible(), old_visible)
        self.assertEqual(c.at(129), row(129))

    def test_no_two_inflight_and_malformed_response_is_atomic(self):
        c = Cache()
        c.load(100, [row(i) for i in range(100, 124)])
        req = c.plan(200, 1)
        self.assertIsNone(c.plan(200, -1))
        before = (c.start, c.end(), c.rows[:], c.head)
        with self.assertRaises(ValueError):
            c.commit(req, [row(124)])  # wrong number of rows
        self.assertEqual((c.start, c.end(), c.rows[:], c.head), before)
        c.commit(req, [row(i) for i in range(124, 130)])

    def test_cannot_evict_current_view_after_user_moves_during_fetch(self):
        c = Cache()
        c.load(100, [row(i) for i in range(100, 124)])
        req = c.plan(200, 1)
        for _ in range(18):
            self.assertTrue(c.move(-1))
        prior = (c.start, c.end(), c.rows[:], c.head)
        with self.assertRaisesRegex(ValueError, "overwrite a visible row"):
            c.commit(req, [row(i) for i in range(124, 130)])
        self.assertEqual((c.start, c.end(), c.rows[:], c.head), prior)

    def test_page_boundaries_no_speculation(self):
        c = Cache()
        c.load(0, [row(i) for i in range(24)])
        for _ in range(19):
            c.move(-1)
        self.assertIsNone(c.plan(24, -1))
        c.load(90, [row(i) for i in range(90, 100)])
        self.assertIsNone(c.plan(100, 1))

    def test_repeated_upward_prefetch(self):
        c = Cache()
        c.load(180, [row(i) for i in range(180, 204)])
        for _ in range(90):
            c.move(-1)
            req = c.plan(250, -1)
            if req:
                c.commit(req, [row(i) for i in range(req.start, req.start + req.count)])
            c.check()
        self.assertLess(c.cursor, 180)
        self.assertEqual(c.at(c.cursor), row(c.cursor))


if __name__ == "__main__":
    unittest.main()
