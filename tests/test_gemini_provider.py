"""Gemini provider regressions without real Google credentials or network calls."""
from __future__ import annotations

import os
import sys
from types import ModuleType, SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from bridge_v03 import db_connect
from bridge_v05 import ConversationEngine
from providers_v05 import GeminiProvider, provider_factory, DEFAULT_SYSTEM


class GeminiProviderTests(TestCase):
    def fake_sdk(self):
        """Inject minimal SDK objects; no extra package needed to run CI."""
        state = {"calls": [], "keys": [], "closed": 0}
        types = ModuleType("google.genai.types")

        class Content:
            def __init__(self, role, parts):
                self.role, self.parts = role, parts

        class Part:
            @staticmethod
            def from_text(*, text):
                return SimpleNamespace(text=text)

        class GenerateContentConfig:
            def __init__(self, **kwargs):
                self.options = kwargs

        class Models:
            def generate_content_stream(self, **kwargs):
                state["calls"].append(kwargs)
                yield SimpleNamespace(text="WO")
                yield SimpleNamespace(text=None)  # non-text chunk
                yield SimpleNamespace(text="RLD")

        class Client:
            def __init__(self, *, api_key):
                state["keys"].append(api_key)
                self.models = Models()

            def close(self):
                state["closed"] += 1

        types.Content = Content
        types.Part = Part
        types.GenerateContentConfig = GenerateContentConfig

        genai = ModuleType("google.genai")
        genai.types = types
        genai.Client = Client
        google = ModuleType("google")
        google.genai = genai

        return state, {"google": google, "google.genai": genai, "google.genai.types": types}

    def test_fails_fast_without_api_key(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                GeminiProvider()

    def test_factory_maps_gemini_and_preserves_model(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy"}):
            provider = provider_factory("gemini", "gemini-3.8-flash")
        self.assertIsInstance(provider, GeminiProvider)
        self.assertEqual(provider.name, "gemini")
        self.assertEqual(provider.model, "gemini-3.8-flash")

    def test_streaming_uses_history_roles_and_skips_empty_chunks(self):
        state, modules = self.fake_sdk()
        history = [
            {"role": "user", "content": "HELLO"},
            {"role": "assistant", "content": "HI"},
            {"role": "user", "content": "SAY WORLD"},
        ]
        with patch.dict(os.environ, {"GEMINI_API_KEY": "example-not-real"}), \
             patch.dict(sys.modules, modules):
            provider = GeminiProvider("gemini-3.5-flash-lite")
            self.assertEqual(list(provider.stream(history)), ["WO", "RLD"])
        self.assertEqual(state["keys"], ["example-not-real"])
        self.assertEqual(state["closed"], 1)
        call = state["calls"][0]
        self.assertEqual(call["model"], "gemini-3.5-flash-lite")
        self.assertEqual([x.role for x in call["contents"]], ["user", "model", "user"])
        self.assertEqual([x.parts[0].text for x in call["contents"]],
                         ["HELLO", "HI", "SAY WORLD"])
        self.assertEqual(call["config"].options["system_instruction"], DEFAULT_SYSTEM)
        self.assertLessEqual(call["config"].options["max_output_tokens"], 1024)

    def test_rejects_context_ending_with_assistant(self):
        state, modules = self.fake_sdk()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy"}), \
             patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(ValueError, "latest nonempty user"):
                list(GeminiProvider().stream([{"role": "assistant", "content": "HI"}]))
        self.assertEqual(state["calls"], [])

    def test_with_real_chat83_engine_and_sqlite(self):
        import time
        state, modules = self.fake_sdk()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy"}), \
             patch.dict(sys.modules, modules):
            db = db_connect(":memory:")
            try:
                engine = ConversationEngine(db, GeminiProvider())
                engine.ask("HELLO", True)
                until = time.monotonic() + 2
                while engine.generating and time.monotonic() < until:
                    engine.drain()
                    time.sleep(0.002)
                engine.drain()
                self.assertFalse(engine.generating)
                self.assertEqual(
                    db.execute("SELECT role, content FROM messages ORDER BY id").fetchall(),
                    [("user", "HELLO"), ("assistant", "WORLD")]
                )
                rows = [r[0] for r in db.execute(
                    "SELECT text FROM display_lines ORDER BY id"
                )]
                self.assertEqual(rows[1], "GEMINI>".ljust(12))
                self.assertEqual(rows[2], "WORLD".ljust(12))
                self.assertNotIn("PC: ", "".join(rows[1:]))
                self.assertTrue(all(len(row) == 12 for row in rows))
            finally:
                db.close()


if __name__ == "__main__":
    import unittest
    unittest.main()
