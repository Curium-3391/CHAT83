"""v0.5 protocol/USB/LLM integration tests -- no calculator or API key needed."""
from __future__ import annotations

from threading import Event
import time
import unittest

from bridge_v03 import db_connect, save_message
from bridge_v05 import ConversationEngine, StableRows, WordRows, serve
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

    def test_extra_pause_only_between_acknowledged_16byte_batches(self):
        from unittest.mock import patch
        serial = MockUsbSerial()
        link = UnoUsb(serial, gap_ms=35, timeout=0.02, batch_pause_ms=150)
        link.connect()
        payload = bytes(range(33))
        with patch("usb_v05.time.sleep") as sleeper:
            self.assertEqual(link.write(payload), len(payload))
        self.assertEqual(serial.calc_sent, payload)
        self.assertEqual(link.tx_count, 33)
        self.assertEqual(sleeper.call_count, 2)
        sleeper.assert_any_call(0.15)
        self.assertEqual(link.stats()["batch_pause_ms"], 150)

    def test_batch_pause_default_preserves_existing_transport(self):
        from unittest.mock import patch
        serial = MockUsbSerial()
        link = UnoUsb(serial, gap_ms=35, timeout=0.02)
        link.connect()
        with patch("usb_v05.time.sleep") as sleeper:
            link.write(bytes(range(81)))
        sleeper.assert_not_called()
        self.assertEqual(serial.calc_sent, bytes(range(81)))
        for invalid in (-1, 1001):
            with self.assertRaisesRegex(ValueError, "batch_pause_ms"):
                UnoUsb(serial, batch_pause_ms=invalid)

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

    def test_rx_timeout_e5_does_not_end_diagnostic_session(self):
        import contextlib
        import io
        serial = MockUsbSerial()
        link = UnoUsb(serial, timeout=0.005)
        link.connect()
        serial.out.extend(make_frame(bytes([ord("E"), 5])))
        with self.assertRaisesRegex(LinkFailure, "Arduino error code 5"):
            link.read(1)  # normal operation must remain fail-fast

        link.enable_link_diagnostics()
        serial.out.extend(make_frame(bytes([ord("E"), 5])))
        # Diagnostic counters reflect one observed start, no completed ACK,
        # a receive timeout and one LOW line at the time of the snapshot.
        report = bytes([ord('J'), 1, 0, 0, 0, 0, 0,
                        1, 0, 0, 0, 2, 2, 0])
        serial.out.extend(make_frame(report))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(link.read(1), b"")
        self.assertIn("E5 RX handshake timeout", output.getvalue())
        self.assertIn("start=1 ack=0 rx_bytes=0 rx_to=1", output.getvalue())
        self.assertIn("TIP=L RING=H", output.getvalue())
        self.assertEqual(link.rx_timeout_events, 1)
        self.assertEqual(link.link_errors, 2)

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


class WordWrapTests(unittest.TestCase):
    def test_streaming_chunks_preserve_words_and_committed_rows(self):
        wrapped = WordRows()
        self.assertEqual(wrapped.feed("HEL"), [])
        self.assertEqual(wrapped.feed("LO WOR"), [])
        self.assertEqual(wrapped.feed("LD GOO"), ["PC: HELLO".ljust(12)])
        self.assertEqual(wrapped.feed("DBYE "), ["WORLD".ljust(12)])
        self.assertEqual(wrapped.finish(), ["GOODBYE".ljust(12)])
        self.assertEqual(wrapped.finish(), [])

    def test_full_width_ascii_word_no_overflow(self):
        wrapped = WordRows()
        rows = wrapped.feed("ABCDEFGHIJKLMNO")
        rows += wrapped.finish()
        self.assertEqual(rows, ["PC: ABCDEFGH", "IJKLMNO".ljust(12)])
        self.assertTrue(all(len(row) == 12 for row in rows))

    def test_unicode_newlines_and_original_default_unchanged(self):
        wrapped = WordRows()
        self.assertEqual(wrapped.feed("CAFÉ\nX"), ["PC: CAFE".ljust(12)])
        self.assertEqual(wrapped.finish(), ["X".ljust(12)])
        unwrapped = StableRows()
        self.assertEqual(unwrapped.feed("HELLO WORLD"), ["PC: HELLO WO"])
        self.assertEqual(unwrapped.finish(), ["RLD".ljust(12)])

    def test_engine_saves_wrapped_rows_without_mutating_history(self):
        from providers_v05 import DemoProvider
        from bridge_v03 import db_connect
        import time
        db = db_connect(":memory:")
        try:
            engine = ConversationEngine(db, DemoProvider(), word_wrap=True)
            engine.ask("HELLO", True)
            deadline = time.monotonic() + 2
            while engine.generating and time.monotonic() < deadline:
                engine.drain()
                time.sleep(0.002)
            engine.drain()
            self.assertFalse(engine.generating)
            self.assertEqual(engine.word_wrap, True)
            rows = [x[0] for x in db.execute("SELECT text FROM display_lines ORDER BY id")]
            self.assertTrue(rows)
            self.assertTrue(all(len(row) == 12 for row in rows))
            self.assertIn("PC: WORLD", "".join(rows))
        finally:
            db.close()


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

    def test_host_turnaround_delay_and_pre_tx_request_log(self):
        import contextlib
        import io
        from unittest.mock import patch
        class Once:
            debug_link = True
            gap_ms = 35
            def __init__(self):
                self.called = False
                self.sent = []
            def read(self, n):
                if not self.called:
                    self.called = True
                    return b"S"
                raise KeyboardInterrupt
            def write(self, packet):
                self.sent.append(packet)
                return len(packet)
        link = Once()
        captured = io.StringIO()
        with patch("bridge_v05.time.sleep") as delay, contextlib.redirect_stdout(captured):
            with self.assertRaises(KeyboardInterrupt):
                serve(link, self.engine, reply_delay_ms=250)
        delay.assert_called_once_with(0.25)
        self.assertEqual(len(link.sent), 1)
        self.assertEqual(len(link.sent[0]), 9)
        self.assertIn("[TX-BEGIN] SYNC: 9 bytes", captured.getvalue())
        self.assertIn("turnaround=250ms", captured.getvalue())
        self.assertIn("SYNC -> 0 rows", captured.getvalue())

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
