"""Regression test: prevent shipping the impossible TiLP-after-v0.5 install order.

The Arduino v0.5 protocol is COBS/CRC8 at 115200, not TiLP's
serial2ti83 transport; only the old firmware or a separate TI cable
may transfer the C83V5.8xp calculator program.
"""
from pathlib import Path
import unittest


class BootstrapInstructionsTests(unittest.TestCase):
    def test_tilp_transfer_precedes_flashing_custom_uno(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "docs/v05-integrated-terminal.md").read_text(encoding="utf-8")
        section = text.split("## 第一次安裝：", 1)[1].split("### 啟動 LLM", 1)[0]
        self.assertIn("serial2ti83", section)
        self.assertIn("timeout occurred while reading from the device", section)
        self.assertLess(section.index("使用 TiLP 傳入"), section.index("重新上傳新的 v0.5"))
        self.assertIn("關閉 TiLP", section)
        self.assertIn("再刷回", section)

    def test_new_firmware_does_not_claim_tilp_compatibility(self):
        root = Path(__file__).resolve().parents[1]
        sketch = (root / "arduino/CHAT83_Uno_v05/CHAT83_Uno_v05.ino").read_text(encoding="utf-8")
        self.assertIn("This is NOT TiLP firmware", sketch)


if __name__ == "__main__":
    unittest.main()
