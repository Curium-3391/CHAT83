"""v0.5 protocol/USB/LLM integration tests -- no calculator or API key needed."""
from __future__ import annotations

from threading import Event
import time
import unittest

from bridge_v03 import db_connect, save_message
from bridge_v05 import ConversationEngine, StableRows
from protocol_v05 import (
    BUSY, NEWER, RESET, Chunk, RangeRequest,
    encode_chunk, decode_chunk, encode_fetch, decode_fetch,
    encode_update, decode_update, encode_cancel, encode_retry,
)
from providers_v05 import DemoProvider
from usb_v05 import (
    LinkFailure, UnoUsb, cobs_encode, cobs_decode,
    make_frame, decode_frame, crc8,
)


class MockUsbSerial:
    def __init__(self):
        self.out = bytearray()
        self.calc_sent = bytearray()
        self.gap = 0

    def write(self, wire):
        decoded = decode_frame(wire[:-1])
        k = decoded[:1]
        if k == b"P":
            self.out.extend(make_frame(b"H\x00\x05\x10"))
        elif k == b"G":
            self.gap = decoded[1]
            self.out.extend(make_frame(b"A\x00\x00"))
        elif k == b"D":
            self.debug_enabled = bool(decoded[1])
            self.out.extend(make_frame(b"A\x00\x00"))
        elif k == b"T":
            seq, count = decoded[1], decoded[2]
            if count != len(decoded) - 3:
                raise AssertionError("bad outbound TX length")
            self.calc_sent.extend(decoded[3:])
            self.out.extend(make_frame(b"A" + bytes([seq, 0])))
        else:
            raise AssertionError(f"unknown host packet {decoded!r}")
        return len(wire)

    def flush(self):
        pass

    def read(self, n):
        if not self.out:
            return b""
        chunk = self.out[:n]
        del self.out[:n]
        return bytes(chunk)

    def from_calc(self, data):
        for b in data:
            self.out.extend(make_frame(b"R" + bytes([b])))


class UsbTests(unittest.TestCase):
    def test_crc8_reference_vector(self):
        self.assertEqual(crc8(b"123456789"), 0xF4)

    def test_cobs_with_zeroes(self):
        for data in (b"", b"A", b"\x00", b"A\x00\x00B", bytes(range(256))):
            self.assertEqual(cobs_decode(cobs_encode(data)[:-1]), data)
        with self.assertRaises(LinkFailure):
            cobs_decode(b"\x05AB")

    def test_usb_rx_frames_and_acknowledged_tx(self):
        serial = MockUsbSerial()
        link = UnoUsb(serial, gap_ms=35, timeout=0.02)
        link.connect()
        self.assertEqual(serial.gap, 35)
        msg = bytes(range(81))
        self.assertEqual(link.write(msg), 81)
        self.assertEqual(serial.calc_sent, msg)
        self.assertEqual(link.tx_count, 81)
        serial.from_calc(b"HELLO")
        self.assertEqual(b"".join(link.read(1) for _ in range(5)), b"HELLO")
        self.assertEqual(link.rx_count, 5)

    def test_optional_link_debug_counters(self):
        import contextlib
        import io
        serial = MockUsbSerial()
        link = UnoUsb(serial, timeout=0.01)
        link.connect()
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            link.enable_link_diagnostics()
            self.assertTrue(serial.debug_enabled)
            report = bytes([ord('J'), 8, 0, 8, 0, 1, 0,
                            0, 0, 0, 0, 0, 3, ord('S')])
            serial.out.extend(make_frame(report))
            self.assertEqual(link.read(1), b'')
        self.assertIn("start=8 ack=8 rx_bytes=1", capture.getvalue())
        self.assertIn("last_rx=0x53", capture.getvalue())

    def test_bad_usb_crc_rejected(self):
        raw = bytearray(make_frame(b"Rz"))
        raw[-2] ^= 1
        with self.assertRaises(LinkFailure):
            decode_frame(bytes(raw[:-1]))


class AppWireTests(unittest.TestCase):
    def test_six_row_payload_crc(self):
        packet = encode_chunk(Chunk(3, 0x00010203, BUSY | NEWER, ("ABC".ljust(12),)))
        self.assertEqual(len(packet), 21)
        self.assertEqual(decode_chunk(packet).start, 0x00010203)
        broken = bytearray(packet)
        broken[-2] ^= 0x40
        with self.assertRaises(ValueError):
            decode_chunk(bytes(broken))

    def test_fetch_update_cancel_retry(self):
        req = RangeRequest(17, False, 65541, 6)
        self.assertEqual(decode_fetch(encode_fetch(req)), req)
        self.assertEqual(decode_update(encode_update(123456789)), 123456789)
        self.assertEqual(len(encode_cancel()), 2)
        self.assertEqual(encode_retry(0)[:2], b"R\x00")


class StreamingTests(unittest.TestCase):
    def test_partial_row_does_not_mutate_old_rows(self):
        fmt = StableRows()
        self.assertEqual(fmt.feed("HEL"), [])
        first = fmt.feed("LO WORLD")
        self.assertEqual(first, ["PC: HELLO WO"])
        self.assertEqual(fmt.feed("!"), [])
        self.assertEqual(fmt.finish(), ["RLD!".ljust(12)])

    def test_unicode_and_newline(self):
        fmt = StableRows()
        self.assertEqual(fmt.feed("CAFÉ\nX"), ["PC: CAFE".ljust(12)])
        self.assertEqual(fmt.finish(), ["X".ljust(12)])


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.db = db_connect(":memory:")
        self.engine = ConversationEngine(self.db, DemoProvider())

    def tearDown(self):
        self.db.close()

    def _settle(self):
        until = time.monotonic() + 2
        while self.engine.generating and time.monotonic() < until:
            self.engine.drain()
            time.sleep(0.001)
        self.assertFalse(self.engine.generating)

    def test_end_to_end_hello_stream_and_persistent_rows(self):
        self.assertEqual(decode_chunk(self.engine.sync()).flags, RESET)
        packet = self.engine.ask("HELLO", True)
        self.assertIn("YOU", "".join(decode_chunk(packet).rows))
        self._settle()
        all_rows = self.engine.rows(0, self.engine.total())
        self.assertIn("PC: WORLD", "".join(all_rows))
        messages = self.db.execute("SELECT role,content FROM messages ORDER BY id").fetchall()
        self.assertEqual(messages, [("user", "HELLO"), ("assistant", "WORLD")])

    def test_live_updates_and_six_row_clamp(self):
        first = self.engine.ask("DEMO", True)
        self.assertTrue(len(decode_chunk(first).rows) <= 6)
        self._settle()
        curs = 0
        seen = []
        for _ in range(30):
            frame = decode_chunk(self.engine.update(curs))
            seen.extend(frame.rows)
            curs += len(frame.rows)
            if not frame.flags & NEWER:
                break
        self.assertEqual(curs, self.engine.total())
        self.assertGreater(curs, 6)
        self.assertTrue(any("PC:" in row for row in seen))

    def test_context_is_bounded_and_saved_history(self):
        for i in range(60):
            save_message(self.db, "assistant", "Z" * 200 + str(i))
        engine = ConversationEngine(self.db, DemoProvider(), max_context_chars=500)
        context = engine._messages_for_llm()
        self.assertLess(len(context), 10)

    def test_retry_reuses_same_packet(self):
        response = self.engine.sync()
        self.engine.last_reply = response
        self.assertEqual(self.engine.reply_retry(encode_retry(response[1])), response)
        with self.assertRaises(ValueError):
            self.engine.reply_retry(encode_retry(47))

    def test_parse_q_request(self):
        serial = MockUsbSerial()
        # Decode-one compatibility adapter: serial port exposes raw bytes.
        class Bytes:
            def __init__(self, b):
                self.b = bytearray(b)
            def read(self, size):
                x = self.b[:size]
                del self.b[:size]
                return bytes(x)
        request = b"Q\x05HELLO\x01"
        response, label, retry = self.engine.dispatch(
            Bytes(request[1:] + bytes([crc8(request)])), b"Q")
        self.assertEqual(label, "Q 'HELLO'")
        self.assertFalse(retry)
        self.assertGreaterEqual(len(decode_chunk(response).rows), 1)
        corrupted = request[1:] + bytes([crc8(request) ^ 1])
        before = self.engine.total()
        with self.assertRaisesRegex(ValueError, "CRC8"):
            self.engine.dispatch(Bytes(corrupted), b"Q")
        self.assertEqual(self.engine.total(), before)


if __name__ == "__main__":
    unittest.main()
