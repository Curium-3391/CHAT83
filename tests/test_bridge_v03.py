"""No-hardware v0.3 tests: PYTHONPATH=bridge python -m unittest discover -s tests -v."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge_v03 import (Conversation, PAGE_SIZE, ROW_WIDTH, db_connect,
                        encode_page, handle_command, read_exact, save_message,
                        text_rows)


class FakeSerial:
    def __init__(self, incoming=b""):
        self.incoming = bytearray(incoming)
        self.outgoing = bytearray()

    def read(self, count):
        chunk = bytes(self.incoming[:count])
        del self.incoming[:count]
        return chunk

    def write(self, chunk):
        self.outgoing.extend(chunk)

    def flush(self):
        pass


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.db = db_connect(":memory:")
        self.conversation = Conversation(self.db)

    def tearDown(self):
        self.db.close()

    def test_empty_sync(self):
        self.assertEqual(encode_page(self.conversation.sync()), b"P\x00\x00\x00")

    def test_question_and_persistence(self):
        ser = FakeSerial(b"\x05HELLO")
        with patch("bridge_v03.time.sleep"):
            status = handle_command(ser, self.conversation, b"Q", 0)
        self.assertIn("2 rows", status)
        self.assertEqual(ser.outgoing[:3], b"P\x02\x00\x00")
        self.assertEqual(len(ser.outgoing), 4 + 2 * ROW_WIDTH)
        self.assertIn(b"WORLD", ser.outgoing)
        roles = self.db.execute("SELECT role FROM messages ORDER BY id").fetchall()
        self.assertEqual(roles, [("user",), ("assistant",)])

    def test_scroll_more_than_one_cache(self):
        for i in range(100):
            save_message(self.db, "assistant", f"TEST {i:03d}")
        view, latest, flags = self.conversation.sync()
        self.assertEqual((view, len(latest), flags), (18, PAGE_SIZE, 1))
        self.assertIn("TEST 099", latest[-1])
        view, older, flags = self.conversation.older()
        self.assertEqual((view, len(older), flags), (17, PAGE_SIZE, 3))
        self.assertIn("TEST 058", older[0])
        view, newer, flags = self.conversation.newer()
        self.assertEqual((view, len(newer), flags), (1, PAGE_SIZE, 1))
        self.assertIn("TEST 099", newer[-1])

    def test_clamped_ends(self):
        for i in range(3):
            save_message(self.db, "user", str(i))
        self.assertEqual(self.conversation.sync()[0], 0)
        self.assertEqual(self.conversation.older()[0], 0)
        self.assertEqual(self.conversation.newer()[0], 0)

    def test_boundary_flags_prevent_redundant_transfers(self):
        for i in range(50):
            save_message(self.db, "assistant", f"LINE{i}")
        # Latest page: no newer page, but older pages exist.
        view, rows, flags = self.conversation.sync()
        self.assertEqual((len(rows), flags), (24, 1))
        # Move to absolute start and verify older bit cleared.
        while self.conversation.page_start > 0:
            _, rows, flags = self.conversation.older()
        self.assertEqual(flags & 1, 0)
        self.assertEqual(flags & 2, 2)
        # Asking for older page anyway cannot move the boundary.
        old_start = self.conversation.page_start
        self.conversation.older()
        self.assertEqual(self.conversation.page_start, old_start)

    def test_page_flag_encoding(self):
        packet = encode_page((0, ["TEST".ljust(12)], 3))
        self.assertEqual(packet[:4], bytes([80, 1, 0, 3]))
        self.assertEqual(len(packet), 16)
        with self.assertRaises(ValueError):
            encode_page((0, [], 4))

    def test_long_reply_and_ascii(self):
        self.conversation.ask("DEMO")
        self.assertGreater(self.conversation.total_lines(), PAGE_SIZE)
        self.assertTrue(all(len(s) == ROW_WIDTH
                            for s in text_rows("assistant", "中文\nOK")))

    def test_invalid_requests(self):
        with patch("bridge_v03.time.sleep"):
            with self.assertRaises(ValueError):
                handle_command(FakeSerial(b"\x00"), self.conversation, b"Q", 0)
            with self.assertRaises(ValueError):
                handle_command(FakeSerial(), self.conversation, b"X", 0)
            with self.assertRaises(TimeoutError):
                read_exact(FakeSerial(b"A"), 2)

    def test_db_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "history.db"
            with db_connect(path) as conn:
                save_message(conn, "user", "HELLO")
            with db_connect(path) as reopened:
                self.assertEqual(Conversation(reopened).total_lines(), 1)


if __name__ == "__main__":
    unittest.main()
