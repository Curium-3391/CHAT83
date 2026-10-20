"""Pluggable LLM generators for CHAT83 v0.5.

- demo: offline, deterministic, no secrets needed.
- openai: Responses API via official optional openai SDK.
- ollama: optional local HTTP streaming, no cloud credentials.
All generation runs on a worker; USB serial traffic stays on the main thread.
"""
from __future__ import annotations

import json
import os
from typing import Iterable
from urllib import request, error


DEFAULT_SYSTEM = (
    "You are answering a user typing on a vintage TI-83 Plus calculator. "
    "The display is 12 printable ASCII characters wide and can show six rows. "
    "Prefer concise plain-English responses, short paragraphs, and ASCII. "
    "If you do not know something, say so."
)


class DemoProvider:
    name = "demo"

    def stream(self, messages: list[dict[str, str]]) -> Iterable[str]:
        from bridge_v03 import demo_reply
        question = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        response = demo_reply(question)
        for i in range(0, len(response), 8):
            yield response[i:i + 8]


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str = "gpt-4.1-mini"):
        self.model = model
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("Set OPENAI_API_KEY in your PC environment; never put the key in the calculator or repository")

    def stream(self, messages: list[dict[str, str]]) -> Iterable[str]:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install optional LLM dependency: py -m pip install openai") from exc
        client = OpenAI(timeout=90, max_retries=2)
        input_items = [{"role": m["role"], "content": m["content"]} for m in messages]
        events = client.responses.create(model=self.model, input=input_items, stream=True,
                                         instructions=DEFAULT_SYSTEM)
        for event in events:
            if event.type == "response.output_text.delta":
                yield event.delta
            elif event.type in ("response.failed", "error"):
                raise RuntimeError("LLM generation failed")


class OllamaProvider:
    name = "ollama"

    def __init__(self, model: str = "llama3.2", url: str = "http://127.0.0.1:11434"):
        self.model = model
        self.url = url.rstrip("/")

    def stream(self, messages: list[dict[str, str]]) -> Iterable[str]:
        req = request.Request(
            self.url + "/api/chat",
            data=json.dumps({"model": self.model, "messages": [
                {"role": "system", "content": DEFAULT_SYSTEM}, *messages],
                "stream": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=120) as resp:
            for raw in resp:
                if not raw.strip():
                    continue
                item = json.loads(raw)
                if item.get("error"):
                    raise RuntimeError(str(item["error"]))
                part = item.get("message", {}).get("content", "")
                if part:
                    yield part
                if item.get("done"):
                    break


def provider_factory(name: str, model: str, ollama_url: str = "http://127.0.0.1:11434"):
    if name == "demo":
        return DemoProvider()
    if name == "openai":
        return OpenAIProvider(model)
    if name == "ollama":
        return OllamaProvider(model, ollama_url)
    raise ValueError(f"unknown provider {name!r}; choose demo/openai/ollama")
