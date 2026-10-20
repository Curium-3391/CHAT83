"""v0.4 bridge protocol tests, independent of physical calculator."""
import unittest

from bridge_v03 import db_connect, save_message
from bridge_v04 import Server, decode_one, RESET_FLAG
from prefetch_v04 import Fetch, decode_chunk, encode_fetch, LOOKAHEAD


class FakeSerial:
    def __init__(self, content=b""):
        self.data = bytearray(content)

    def read(self, count):
        out = self.data[:count]
        del self.data[:count]
        return bytes(out)


class BridgeV04Tests(unittest.TestCase):
    def setUp(self):
        self.db = db_connect(":memory:")
        self.server = Server(self.db)

    def tearDown(self):
        self.db.close()

    def test_initial_empty_sync(self):
        packet = self.server.sync()
        self.assertEqual(len(packet), 9)
        seq, offset, flags, rows = decode_chunk(packet)
        self.assertEqual((seq, offset, flags, rows), (0, 0, RESET_FLAG, []))

    def test_initial_sync_is_six_rows_at_most(self):
        for i in range(60):
            save_message(self.db, "user", f"X{i:02}")
        seq, start, flags, rows = decode_chunk(self.server.sync())
        self.assertEqual((seq, start, len(rows)), (0, 54, LOOKAHEAD))
        self.assertEqual(flags, RESET_FLAG | 1)

    def test_incremental_question_and_history(self):
        save_message(self.db, "user", "ONE")
        packet = self.server.sync()
        self.assertEqual(decode_chunk(packet)[1], 0)
        reply, label = decode_one(FakeSerial(b"\x05HELLO\x01"), b"Q", self.server)
        seq, start, flags, rows = decode_chunk(reply)
        self.assertEqual(label, "Q 'HELLO'")
        self.assertEqual(seq, 0)
        self.assertEqual(start, 1)
        self.assertEqual(len(rows), 2)
        self.assertIn("WORLD", rows[-1])
        self.assertEqual(self.server.total(), 3)
        self.assertEqual(flags, 1)

    def test_fetch_by_absolute_offset(self):
        for i in range(60):
            save_message(self.db, "assistant", f"LINE{i}")
        request = Fetch(-1, 48, 6, 13)
        payload, text = decode_one(FakeSerial(encode_fetch(request)[1:]), b"F", self.server)
        seq, start, flags, rows = decode_chunk(payload)
        self.assertEqual((seq, start, len(rows)), (13, 48, 6))
        self.assertEqual(flags, 3)
        self.assertIn("LINE48", rows[0])
        self.assertIn("OLDER", text)

    def test_asking_from_older_page_forces_reset(self):
        for i in range(20):
            save_message(self.db, "user", f"X{i}")
        packet, _ = decode_one(FakeSerial(b"\x05HELLO\x00"), b"Q", self.server)
        seq, start, flags, lines = decode_chunk(packet)
        self.assertTrue(flags & RESET_FLAG)
        self.assertEqual(len(lines), 6)

    def test_long_answer_resets(self):
        # DEMO response is longer than 6 display rows.
        packet, _ = decode_one(FakeSerial(b"\x04DEMO\x01"), b"Q", self.server)
        self.assertEqual(decode_chunk(packet)[2] & RESET_FLAG, RESET_FLAG)
        self.assertLessEqual(decode_chunk(packet)[3].__len__(), 6)

    def test_request_checks_checksum_and_range(self):
        for i in range(7):
            save_message(self.db, "user", str(i))
        bad = bytearray(encode_fetch(Fetch(-1, 0, 6, 1)))
        bad[-1] ^= 0x04
        with self.assertRaises(ValueError):
            decode_one(FakeSerial(bad[1:]), b"F", self.server)
        with self.assertRaises(ValueError):
            self.server.fetch(encode_fetch(Fetch(1, 700, 6, 2)))


if __name__ == "__main__":
    unittest.main()
