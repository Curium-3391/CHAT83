"""Standalone GEMINI> row layout, streaming and persisted history regressions.

All tests are offline: no API key, network, Uno or calculator hardware.
"""
import time
import threading
import unittest

from bridge_v03 import db_connect, save_message
from bridge_v05 import ConversationEngine, StableRows
from protocol_v05 import BUSY, Chunk, RangeRequest, decode_chunk, encode_fetch
from providers_v05 import DemoProvider


class FakeGemini:
    name = "gemini"

    def __init__(self, chunks=("ABCDEFGHIJ", "KLMNO")):
        self.chunks = chunks
        self.contexts = []

    def stream(self, messages):
        self.contexts.append(messages)
        yield from self.chunks


class GatedGemini:
    name = "gemini"

    def __init__(self):
        self.gate = threading.Event()

    def stream(self, messages):
        self.gate.wait(3)
        yield "HELLO"


class GeminiLayoutTests(unittest.TestCase):
    def setUp(self):
        self.db = db_connect(":memory:")

    def tearDown(self):
        self.db.close()

    def settled(self, engine):
        deadline = time.monotonic() + 3
        while engine.generating and time.monotonic() < deadline:
            engine.drain()
            time.sleep(0.002)
        engine.drain()
        self.assertFalse(engine.generating)

    def lines(self):
        return [r[0] for r in self.db.execute(
            "SELECT text FROM display_lines ORDER BY id"
        ).fetchall()]

    def test_formatter_without_prefix_uses_all_twelve_columns(self):
        formatter = StableRows(prefix="")
        self.assertEqual(formatter.feed("ABCDEFGHIJ"), [])
        self.assertEqual(formatter.feed("KLM"), ["ABCDEFGHIJKL"])
        self.assertEqual(formatter.feed("NO"), [])
        self.assertEqual(formatter.finish(), ["MNO".ljust(12)])
        self.assertEqual(formatter.finish(), [])
        self.assertEqual(StableRows().feed("HELLO WORLD"), ["PC: HELLO WO"])
        with self.assertRaises(ValueError):
            StableRows(prefix="X" * 13)

    def test_gemini_header_occupies_own_row_before_full_width_stream(self):
        engine = ConversationEngine(self.db, FakeGemini())
        packet = decode_chunk(engine.ask("HELLO", True))
        self.assertIn("GEMINI>".ljust(12), packet.rows)
        self.settled(engine)
        rows = self.lines()
        self.assertEqual(rows, [
            "YOU: HELLO".ljust(12),
            "GEMINI>".ljust(12),
            "ABCDEFGHIJKL",
            "MNO".ljust(12),
        ])
        self.assertTrue(all(len(row) == 12 for row in rows))
        self.assertTrue(all("PC: " not in row for row in rows[1:]))
        self.assertEqual(
            self.db.execute("SELECT role, content FROM messages ORDER BY id").fetchall(),
            [("user", "HELLO"), ("assistant", "ABCDEFGHIJKLMNO")]
        )

        # Six-row C, old-page FETCH and live UPDATE all read exactly the same
        # append-only SQLite row IDs. No changes to the TI Link wire protocol.
        older = decode_chunk(engine.fetch(encode_fetch(RangeRequest(7, False, 1, 3))))
        self.assertEqual(older.seq, 7)
        self.assertEqual(older.rows, tuple(rows[1:]))
        live = decode_chunk(engine.update(1))
        self.assertEqual(live.rows, tuple(rows[1:]))
        self.assertEqual(decode_chunk(engine.sync()).rows, tuple(rows))

    def test_header_is_immediately_visible_while_gemini_is_busy(self):
        model = GatedGemini()
        engine = ConversationEngine(self.db, model)
        try:
            immediate = decode_chunk(engine.ask("HELLO", True))
            self.assertTrue(immediate.flags & BUSY)
            self.assertEqual(immediate.rows,
                             ("YOU: HELLO".ljust(12), "GEMINI>".ljust(12)))
            self.assertEqual(self.lines()[-1], "GEMINI>".ljust(12))
            model.gate.set()
            self.settled(engine)
            self.assertEqual(self.lines()[-1], "HELLO".ljust(12))
        finally:
            model.gate.set()

    def test_old_records_unchanged_and_each_new_answer_gets_header(self):
        save_message(self.db, "assistant", "LEGACY")
        model = FakeGemini(("WORLD",))
        engine = ConversationEngine(self.db, model)
        engine.ask("HELLO", True)
        self.settled(engine)
        engine.ask("AGAIN", True)
        self.settled(engine)
        rows = self.lines()
        self.assertEqual(rows[0], "PC: LEGACY".ljust(12))
        self.assertEqual(rows.count("GEMINI>".ljust(12)), 2)
        self.assertEqual(rows.count("WORLD".ljust(12)), 2)
        self.assertEqual(rows[-2:], ["GEMINI>".ljust(12), "WORLD".ljust(12)])
        messages = self.db.execute(
            "SELECT role,content FROM messages ORDER BY id").fetchall()
        self.assertEqual(messages, [
            ("assistant", "LEGACY"),
            ("user", "HELLO"), ("assistant", "WORLD"),
            ("user", "AGAIN"), ("assistant", "WORLD"),
        ])
        self.assertEqual([m["role"] for m in model.contexts[-1]],
                         ["assistant", "user", "assistant", "user"])
        self.assertEqual(model.contexts[-1][2]["content"], "WORLD")

    def test_word_wrap_preserves_gemini_header_and_all_twelve_columns(self):
        # PR #11 optional word-wrap must not reintroduce PC: from its
        # pre-Gemini standalone implementation. Never rewrite committed IDs.
        engine = ConversationEngine(
            self.db, FakeGemini(("ABCDEFGHIJ", "KLMNO")), word_wrap=True)
        engine.ask("HELLO", True)
        self.settled(engine)
        rows = self.lines()
        self.assertEqual(rows, [
            "YOU: HELLO".ljust(12),
            "GEMINI>".ljust(12),
            "ABCDEFGHIJKL",
            "MNO".ljust(12),
        ])
        self.assertNotIn("PC:", "".join(rows))
        self.assertEqual(
            self.db.execute("SELECT content FROM messages "
                            "WHERE role='assistant'").fetchone()[0],
            "ABCDEFGHIJKLMNO")

    def test_word_wrap_on_multiple_plain_words_no_prefix(self):
        engine = ConversationEngine(
            self.db, FakeGemini(("HELLO WOR", "LD GOOD", "BYE")), word_wrap=True)
        engine.ask("HELLO", True)
        self.settled(engine)
        rows = self.lines()
        self.assertEqual(rows[:2], ["YOU: HELLO".ljust(12), "GEMINI>".ljust(12)])
        self.assertEqual(rows[2:], ["HELLO WORLD".ljust(12), "GOODBYE".ljust(12)])
        self.assertTrue(all(len(row) == 12 for row in rows))

    def test_demo_provider_remains_backward_compatible(self):
        engine = ConversationEngine(self.db, DemoProvider())
        engine.ask("HELLO", True)
        self.settled(engine)
        rows = self.lines()
        self.assertIn("PC: WORLD".ljust(12), rows)
        self.assertNotIn("GEMINI>".ljust(12), rows)


if __name__ == "__main__":
    unittest.main()
