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
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "bridge"), str(ROOT / "tests" / "emulator")]

BUILD = os.environ.get("CHAT83_Z80_BUILD")
SHOTS = os.environ.get("CHAT83_SCREENSHOT_DIR")
try:
    import z80  # noqa: F401
    from ti83p_harness import Harness, LinkPeer, render_png
except ImportError:  # plain Python job: no emulator packages
    Harness = None

from bridge_v03 import db_connect
from bridge_v05 import ConversationEngine
from providers_v05 import DemoProvider


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
        self.assertIn("NO HISTORY", h.screen.dump())
        self.ask_numbers(h, "123")
        self.wait_for_text(h, "YOU: 123")
        self.wait_for_text(h, "123")
        self.assertEqual([r[:1] for r, _ in h.peer.log][:2], [b"S", b"Q"])
        roles = self.db.execute("SELECT role, content FROM messages ORDER BY id").fetchall()
        self.assertEqual(roles[0], ("user", "123"))
        self.shot(h, f"{name.split('.')[0]}_answer")
        h.press(h.sk("Clear"))
        self.assertTrue(h.exited)

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
