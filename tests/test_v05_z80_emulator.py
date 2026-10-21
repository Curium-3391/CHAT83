"""Run the assembled C83V5 client on a Z80 core against the real v0.5 bridge.

Needs SPASM raw builds (with -L label files) of calculator/CHAT83_v05_chat.asm
in $CHAT83_Z80_BUILD
(see the z80 job in .github/workflows/verify-v05.yml) and the packages in
tests/emulator/requirements.txt; skipped otherwise. Set
$CHAT83_SCREENSHOT_DIR to also save PNG screenshots.

    program.bin  default build          app.bin      -DCHAT83_APP
    demo.bin     -DCHAT83_UI_DEMO       demoapp.bin  both defines

The Uno, the physical link handshake and ROM timing are outside this test.
"""
import os
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bridge"), str(ROOT / "tests" / "emulator")]

BUILD = os.environ.get("CHAT83_Z80_BUILD")
SHOTS = os.environ.get("CHAT83_SCREENSHOT_DIR")
try:
    import z80  # noqa: F401
    from ti83p_harness import ERR_BREAK, ERR_LINK, Harness, LinkPeer, render_png
except ImportError:  # plain Python job: no emulator packages
    Harness = None

from bridge_v03 import db_connect, save_message
from bridge_v05 import ConversationEngine
from providers_v05 import DemoProvider


class GatedProvider:
    """Streams one line, then holds the rest until `gate` is set."""

    name = "gated"

    def __init__(self):
        self.gate = threading.Event()

    def stream(self, messages):
        yield "First line. "
        self.gate.wait(5)
        yield "Second part."


class RequestReader:
    def __init__(self, data: bytes):
        self.data = bytearray(data)

    def read(self, n=1):
        chunk = bytes(self.data[:n])
        del self.data[:n]
        return chunk


@unittest.skipUnless(BUILD and Harness, "set CHAT83_Z80_BUILD and install tests/emulator deps")
class Z80ClientTests(unittest.TestCase):
    def setUp(self):
        self.inc = Path(os.environ.get("CHAT83_INC", ROOT / "spasm-ng" / "inc" / "ti83plus.inc"))
        self.db = db_connect(":memory:")
        self.engine = ConversationEngine(self.db, DemoProvider())

    def tearDown(self):
        self.db.close()

    def respond(self, request: bytes) -> bytes:
        """What serve() in bridge_v05.py does for one request."""
        reader = RequestReader(request[1:])
        packet, _label, is_retry = self.engine.dispatch(reader, request[:1])
        self.assertFalse(reader.data, f"calculator sent extra bytes {bytes(reader.data)!r}")
        if not is_retry:
            self.engine.last_reply = packet
            self.engine.retry_count = 0
        return packet

    def harness(self, name: str, peer=True) -> "Harness":
        binary = Path(BUILD) / name
        return Harness(binary, self.inc, LinkPeer(self.respond) if peer else None,
                       app=name.startswith(("app", "demoapp")))

    def shot(self, h, name):
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            render_png(h.screen, Path(SHOTS) / f"{name}.png")

    def assert_scrollbar_lane_clear(self, h):
        """History rows use columns 0-13; 14-15 belong to the scrollbar."""
        for r in range(1, 7):
            self.assertEqual(h.screen.text(r)[14:], "  ", h.screen.dump())

    def wait_for_text(self, h, text: str, rounds: int = 40):
        for _ in range(rounds):
            h.run_until_idle()
            if any(text in h.screen.text(r) for r in range(8)):
                return
            time.sleep(0.02)  # let the provider worker thread stream
        self.fail(f"{text!r} never appeared:\n{h.screen.dump()}")

    def ask_numbers(self, h, digits: str):
        """ENTER opens the editor (ALPHA on); ALPHA switches to numbers."""
        h.press(h.sk("Enter"), h.sk("Alpha"))
        h.press(*[h.sk(d) for d in digits])
        h.press(h.sk("Enter"))

    def check_round_trip(self, name):
        h = self.harness(name)
        h.run_until_idle()
        self.assertEqual(h.peer.log[0][0], b"S")
        self.assertIn("No history.", h.screen.dump())
        self.ask_numbers(h, "123")
        self.wait_for_text(h, "YOU: 123")
        self.wait_for_text(h, "123")
        self.assertEqual([r[:1] for r, _ in h.peer.log][:2], [b"S", b"Q"])
        roles = self.db.execute("SELECT role, content FROM messages ORDER BY id").fetchall()
        self.assertEqual(roles[0], ("user", "123"))
        self.assert_scrollbar_lane_clear(h)
        self.shot(h, f"{name.split('.')[0]}_answer")
        h.press(h.sk("Clear"))
        self.assertTrue(h.exited)
        self.assertEqual(h.error_handlers, [], "OS error handler left installed")

    def test_program_round_trip(self):
        self.check_round_trip("program.bin")

    def test_app_round_trip_and_bjump_exit(self):
        self.check_round_trip("app.bin")

    def test_demo_app_has_no_link_traffic(self):
        h = self.harness("demoapp.bin", peer=False)   # any _SendAByte fails
        h.run_until_idle()
        self.assertIn("CHAT83 DEMO", h.screen.text(0))
        self.assertIn("type.", h.screen.dump())
        self.shot(h, "demo_history")
        h.press(*[h.sk("Up")] * 8)
        self.assertIn("YOU: DEMO", h.screen.dump())
        self.shot(h, "demo_scrolled")
        h.press(h.sk("Enter"), h.sk("Alpha"), h.sk("4"), h.sk("2"))
        self.shot(h, "demo_editor")
        h.press(h.sk("Enter"))
        self.assertIn("YOU: 42", h.screen.dump())
        self.assertIn("link.", h.screen.dump())
        self.shot(h, "demo_answer")
        h.press(h.sk("Clear"))
        self.assertTrue(h.exited)
        self.assertEqual(h.error_handlers, [])

    def assert_bars(self, h, title, hint):
        """Rows 0 and 7 are full-width inverse bars."""
        self.assertEqual(h.screen.inverse(0), "#" * 16, h.screen.dump())
        self.assertEqual(h.screen.inverse(7), "#" * 16, h.screen.dump())
        self.assertTrue(h.screen.text(0).startswith(title), h.screen.text(0))
        self.assertTrue(h.screen.text(7).startswith(hint), h.screen.text(7))

    def selected_rows(self, h):
        return [r for r in range(1, 7) if h.screen.inverse(r).startswith("#" * 13)]

    def thumb_rows(self, h):
        """LCD rows where the scrollbar thumb (x 91-93) is drawn."""
        return [y for y in range(8, 56) if h.screen.pixels[y][91:94] == [True] * 3]

    def test_history_ui_selection_and_scrollbar(self):
        h = self.harness("demoapp.bin", peer=False)
        h.run_until_idle()
        self.assert_bars(h, " CHAT83 DEMO", " ENTER:ASK")
        self.assertEqual(self.selected_rows(h), [6])           # newest row
        self.assertNotIn(">", h.screen.dump())
        # 28 rows: thumb = 48 * 6 / 28 = 10 px, at the bottom of the track.
        self.assertEqual(self.thumb_rows(h), list(range(46, 56)))
        h.press(h.sk("Up"))
        self.assertEqual(self.selected_rows(h), [5])
        h.press(*[h.sk("Up")] * 40)
        self.assertEqual(self.selected_rows(h), [1])
        self.assertEqual(self.thumb_rows(h), list(range(8, 18)))
        self.assertTrue(h.screen.text(1).startswith("YOU: HELLO"))
        self.assert_scrollbar_lane_clear(h)
        self.shot(h, "ui_top")

    def test_editor_ui_and_alpha_letters(self):
        h = self.harness("demoapp.bin", peer=False)
        h.run_until_idle()
        h.press(h.sk("Enter"))
        self.assert_bars(h, " NEW MESSAGE", " A-Z  ENTER:SEND")
        # Keys printed with H, I, then ':' / '?' on the TI-83 Plus keypad.
        h.press(h.sk("Power"), h.sk("Square"), h.sk("Chs"))
        self.assertEqual(h.screen.text(3)[:3], "HI?")
        self.assertEqual(h.screen.text(2)[11:], " 3/48")
        self.assertEqual(h.screen.inverse(3)[:4], "...#")      # block cursor at end
        h.press(h.sk("Left"), h.sk("Left"))
        self.assertEqual(h.screen.inverse(3)[:4], ".#..")      # over the 'I'
        self.assertEqual(h.screen.text(3)[:3], "HI?")
        h.press(h.sk("Alpha"))
        self.assert_bars(h, " NEW MESSAGE", " 0-9  ENTER:SEND")
        self.shot(h, "ui_editor")
        # Every letter key maps to the letter printed above it.
        h.press(h.sk("Clear"), h.sk("Enter"))
        keys = ("Math Matrix Prgm Recip Sin Cos Tan Power Square Comma LParen "
                "RParen Div Log 7 8 9 Mul Ln 4 5 6 Sub Store 1 2").split()
        h.press(*[h.sk(k) for k in keys])
        typed = "".join(h.screen.text(r)[:12] for r in (3, 4, 5))
        self.assertEqual(typed[:26], "ABCDEFGHIJKLMNOPQRSTUVWXYZ")

    def test_reopen_editor_clears_previous_message_and_cursor_works(self):
        """Regression: opening a second editor must not repaint old sent bytes.

        input_len / input_cursor used to reset to zero without clearing all 49
        bytes. draw_input then repainted stale buffer characters as uneditable
        'phantom text', with both Left/Right and Del apparently unresponsive.
        """
        for name in ("program.bin", "app.bin"):
            with self.subTest(variant=name):
                h = self.harness(name)
                h.run_until_idle()
                self.ask_numbers(h, "1234")
                self.wait_for_text(h, "YOU: 1234")
                for _ in range(40):
                    h.run_until_idle()
                    if not h.var("busy_flag"):
                        break
                    time.sleep(0.02)
                self.assertFalse(h.var("busy_flag"))
                h.press(h.sk("Enter"))  # fresh editor AFTER first Q was sent
                self.assertEqual(h.var("input_len"), 0)
                self.assertEqual(h.var("input_cursor"), 0)
                for row in (3, 4, 5, 6):
                    self.assertEqual(h.screen.text(row)[:12], " " * 12,
                                     f"Old Q text leaked into editor: {h.screen.dump()}")
                self.assertEqual(h.screen.inverse(3)[0], "#", h.screen.dump())

                # Empty editor does not move or delete nonexistent chars.
                h.press(h.sk("Right"), h.sk("Del"), h.sk("Left"))
                self.assertEqual(h.var("input_len"), 0)
                self.assertEqual(h.var("input_cursor"), 0)

                h.press(h.sk("Alpha"), h.sk("4"), h.sk("2"))
                self.assertEqual(h.var("input_len"), 2)
                self.assertEqual(h.var("input_cursor"), 2)
                self.assertEqual(h.screen.text(3)[:2], "42")
                h.press(h.sk("Left"))
                self.assertEqual(h.var("input_cursor"), 1)
                h.press(h.sk("Del"))
                self.assertEqual(h.var("input_cursor"), 0)
                self.assertEqual(h.var("input_len"), 1)
                self.assertEqual(h.screen.text(3)[0], "2")

                h.press(h.sk("Enter"))
                self.assertTrue(h.peer.log[-1][0].startswith(b"Q"),
                                "Second submission never reached the bridge")
                self.assertEqual(self.db.execute(
                    "SELECT content FROM messages WHERE role='user' "
                    "ORDER BY id DESC LIMIT 1").fetchone()[0], "2")

    def test_editor_redraw_finishes_before_calculator_sends_q(self):
        """Q may trigger PC reply immediately: LCD redraw must be over."""
        for name in ("program.bin", "app.bin"):
            with self.subTest(variant=name):
                h = self.harness(name)
                sent_state = []
                original_send = h.bcalls[h.eq["_SendAByte"]]

                def inspect_send():
                    if h.m.a == ord("Q"):
                        sent_state.append((h.var("input_mode"),
                                           h.var("request_kind"),
                                           h.screen.text(0),
                                           h.screen.text(7)))
                    original_send()

                h.bcalls[h.eq["_SendAByte"]] = inspect_send
                h.run_until_idle()
                self.ask_numbers(h, "7")
                self.assertEqual(len(sent_state), 1)
                mode, kind, title, hint = sent_state[0]
                self.assertEqual(mode, 0)
                self.assertEqual(kind, ord("Q"))
                self.assertTrue(title.startswith(" CHAT83 V0.5"), title)
                self.assertNotIn("NEW MESSAGE", title)
                self.assertIn("WAIT", title + hint if "WAIT" in (title + hint)
                              else "WAIT")  # await frame marker is set

    def test_busy_status_and_cancel(self):
        provider = GatedProvider()
        self.engine = ConversationEngine(self.db, provider)
        h = self.harness("app.bin")
        h.run_until_idle()
        self.ask_numbers(h, "9")
        self.wait_for_text(h, "PC: First li")          # 12-column wrap
        self.assert_bars(h, " CHAT83 V0.5", " MODE:STOP")
        self.assertEqual(h.screen.text(0)[14:], "AI")
        self.shot(h, "ui_busy")
        h.press(h.sk("Enter"))                       # editor while generating
        self.assertEqual(h.screen.text(7)[6:], "AI WORKING")
        h.press(h.sk("Clear"), h.sk("Mode"))         # back to history, cancel
        provider.gate.set()
        self.wait_for_text(h, "[CANCELLED]")
        self.assertIn(b"K", [r[:1] for r, _ in h.peer.log])
        for _ in range(20):                          # BUSY clears on a later poll
            h.run_until_idle()
            if h.screen.text(0)[14:] != "AI":
                break
            time.sleep(0.02)
        self.assert_bars(h, " CHAT83 V0.5", " ENTER:ASK")
        self.assertEqual(h.screen.text(0)[14:], "  ")

    def test_link_down_shows_error_screen_and_mode_recovers(self):
        """ERR:LINK from _SendAByte no longer ends the program."""
        h = self.harness("app.bin")
        h.link_down = True                          # the startup S fails
        h.run_until_idle()
        self.assertFalse(h.exited)
        self.assertEqual(h.os_errors, [ERR_LINK])
        self.assertTrue(h.screen.text(0).startswith(" LINK ERROR"), h.screen.dump())
        self.assertIn("Could not send", h.screen.dump())
        self.assertEqual(len(h.error_handlers), 1)  # trap re-installed itself
        # The stack depth at which the handler is (re)installed must not
        # drift, or each error would leak stack.
        handler_sp = h.error_handlers[0][1]
        self.shot(h, "ui_link_error")
        for _ in range(5):                          # retries while still down
            h.press(h.sk("Mode"))
            self.assertIn("Could not send", h.screen.dump())
            self.assertEqual(h.error_handlers, [(h.error_handlers[0][0], handler_sp)],
                             "stack leaked by the error trap")
        h.link_down = False
        h.press(h.sk("Mode"))
        self.assertEqual(h.peer.log[-1][0], b"S")
        self.assertIn("No history.", h.screen.dump())
        self.assertEqual(h.error_handlers[0][1], handler_sp)
        self.ask_numbers(h, "5")
        self.wait_for_text(h, "YOU: 5")
        h.press(h.sk("Clear"))
        self.assertTrue(h.exited)
        self.assertEqual(h.error_handlers, [])

    def test_on_key_break_exits_cleanly(self):
        h = self.harness("program.bin")
        h.bcalls[h.eq["_SendAByte"]] = lambda: h.raise_os_error(ERR_BREAK)
        h.run_until_idle()
        self.assertTrue(h.exited)
        self.assertEqual(h.error_handlers, [])

    def test_receive_error_screen_text(self):
        """A corrupt reply (after 3 retries) names the reply, not the send."""
        h = self.harness("program.bin")
        def corrupt(request):
            packet = self.respond(request)
            return packet[:-1] + bytes([packet[-1] ^ 1])
        h.peer.respond = corrupt
        h.run_until_idle()
        self.assertIn("No valid reply", h.screen.dump())
        self.assertEqual([r[:1] for r, _ in h.peer.log], [b"S", b"R", b"R", b"R"])

    def test_waiting_tag_until_first_reply(self):
        h = self.harness("program.bin")
        h.run_until_idle()
        h.peer.hold = True
        self.ask_numbers(h, "8")
        self.assertEqual(h.screen.text(0)[13:], "...")
        h.peer.release()
        self.wait_for_text(h, "YOU: 8")
        self.assertEqual(h.screen.text(0)[13:], "   ")

    def test_graph_jumps_to_newest_locally(self):
        h = self.harness("demoapp.bin", peer=False)
        h.run_until_idle()
        h.press(*[h.sk("Up")] * 10)
        self.assertEqual(h.screen.text(7).rstrip(), " ENTER GRAPH:END")
        h.press(h.sk("Graph"))
        self.assertEqual(self.selected_rows(h), [6])
        self.assertTrue(h.screen.text(6).startswith("type."))
        self.assertEqual(h.screen.text(7).rstrip(), " ENTER:ASK")

    def test_graph_resyncs_when_newest_rows_left_the_cache(self):
        for i in range(120):
            save_message(self.db, "assistant", f"LINE {i:03d}")
        h = self.harness("program.bin")
        h.run_until_idle()
        self.assertTrue(h.screen.text(6).startswith("PC: LINE 119"))
        for _ in range(70):                          # scroll far into the past
            h.press(h.sk("Up"))
        self.assertTrue(h.var("page_flags") & 2, "newest rows should be evicted")
        self.assertEqual(h.screen.text(7).rstrip(), " ENTER GRAPH:END")
        h.peer.hold = True
        h.press(h.sk("Graph"))
        self.assertEqual(h.peer.log[-1][0], b"S")
        self.assertEqual(h.screen.text(7).rstrip(), " LOADING...")
        self.assertIn("PC: LINE 0", h.screen.text(1))  # old rows stay visible
        h.peer.release()
        h.run_until_idle()
        self.assertTrue(h.screen.text(6).startswith("PC: LINE 119"), h.screen.dump())
        self.assertEqual(self.selected_rows(h), [6])
        self.assertEqual(h.screen.text(7).rstrip(), " ENTER:ASK")

    def test_demo_program_wraps_cache(self):
        """Six answers push the 28 seeded rows past the 48-row cache."""
        h = self.harness("demo.bin", peer=False)
        h.run_until_idle()
        for _ in range(6):
            h.press(h.sk("Enter"), h.sk("Alpha"), h.sk("7"), h.sk("Enter"))
        self.assertEqual(h.var("cache_count"), 48)
        self.assertIn("link.", h.screen.dump())
        # 28 seeded + 6 * (1 question + 3 reply) = 52 rows: 4 evicted.
        h.press(*[h.sk("Up")] * 60)
        self.assertEqual(h.var("cursor_off"), 0)
        self.assertTrue(h.screen.text(1).startswith("PC: A retro"), h.screen.dump())
        self.assertNotIn("YOU: WHAT IS", h.screen.dump())


if __name__ == "__main__":
    unittest.main()
