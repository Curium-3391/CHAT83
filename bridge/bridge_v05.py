"""CHAT83 v0.5 integrated Windows bridge.

Run after flashing CHAT83_Uno_v05 and transferring the v0.5 TI-83+
program. Compatible with the v0.3 SQLite schema. LLM runs in a worker
thread; the serial/DB event loop stays single-threaded.

Protocol:
  TI Link: compact 6-row CRC8 'C' replies, 9-byte F, poll U for live rows.
  USB: COBS/CRC8 with Arduino batch-completion ACKs and configurable gap.

This is experimental firmware/software until tested on real hardware.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event, Thread
import time
import unicodedata

from bridge_v03 import DEFAULT_DB, db_connect, read_exact, save_message, text_rows
from protocol_v05 import (
    BUSY, MODEL_ERROR, NEWER, OLDER, RESET, Chunk, MAX_ROWS,
    decode_fetch, decode_retry, decode_update, encode_chunk,
)
from providers_v05 import provider_factory
from usb_v05 import LinkFailure, UnoUsb, crc8


def ascii_text(text: str) -> str:
    """Portable 12-column fallback; controls/newlines normalized."""
    normalized = unicodedata.normalize("NFKD", text)
    out = []
    for ch in normalized:
        if ch in "\r\n":
            out.append("\n" if ch == "\n" else "")
        elif 32 <= ord(ch) <= 126:
            out.append(ch)
        elif unicodedata.combining(ch):
            continue
        else:
            out.append("?")
    return "".join(out)


class StableRows:
    """Commit only completed rows; never rewrite earlier line IDs during streaming."""

    def __init__(self):
        self.partial = "PC: "

    def feed(self, text: str) -> list[str]:
        ready = []
        for ch in ascii_text(text):
            if ch == "\n":
                ready.append(self.partial[:12].ljust(12))
                self.partial = ""
            else:
                self.partial += ch
                if len(self.partial) == 12:
                    ready.append(self.partial)
                    self.partial = ""
        return ready

    def finish(self) -> list[str]:
        result = [self.partial.ljust(12)] if self.partial else []
        self.partial = ""
        return result


class ConversationEngine:
    def __init__(self, db, provider, *, max_context_chars: int = 8000):
        self.db = db
        self.provider = provider
        self.max_context_chars = max_context_chars
        self.stream_queue = SimpleQueue()
        self.worker = None
        self.cancel_event = Event()
        self.generating = False
        self.ai_error = None
        self.assistant_id = None
        self.assistant_text = ""
        self.row_builder = None
        self.last_reply = b""
        self.retry_count = 0
        self.last_activity = time.monotonic()

    def total(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM display_lines").fetchone()[0]

    def rows(self, start, count) -> tuple[str, ...]:
        return tuple(x[0] for x in self.db.execute(
            "SELECT text FROM display_lines ORDER BY id LIMIT ? OFFSET ?",
            (count, start)).fetchall())

    def _append_rows(self, lines: list[str]):
        if not lines:
            return
        with self.db:
            self.db.executemany(
                "INSERT INTO display_lines(message_id,text) VALUES (?,?)",
                [(self.assistant_id, x) for x in lines])

    def _messages_for_llm(self):
        messages = self.db.execute(
            "SELECT role,content FROM messages WHERE content != '' ORDER BY id DESC LIMIT 48"
        ).fetchall()
        total = 0
        items = []
        for role, content in messages:
            total += len(content)
            if items and total > self.max_context_chars:
                break
            items.append({"role": role, "content": content})
        return list(reversed(items))

    def _run_generation(self, context):
        try:
            for part in self.provider.stream(context):
                if self.cancel_event.is_set():
                    break
                if part:
                    self.stream_queue.put(("delta", str(part)))
            self.stream_queue.put(("done", None))
        except Exception as exc:
            self.stream_queue.put(("error", f"{type(exc).__name__}: {exc}"))

    def drain(self, max_parts: int = 256):
        for _ in range(max_parts):
            try:
                kind, value = self.stream_queue.get_nowait()
            except Empty:
                return
            if kind == "delta":
                self.assistant_text += value
                self._append_rows(self.row_builder.feed(value))
            elif kind in ("done", "error"):
                if kind == "error":
                    self.ai_error = str(value)[:160]
                    self.assistant_text += "\n[AI ERROR]"
                    self._append_rows(self.row_builder.feed("\n[AI ERROR]"))
                if self.cancel_event.is_set() and kind == "done":
                    self.assistant_text += "\n[CANCELLED]"
                    self._append_rows(self.row_builder.feed("\n[CANCELLED]"))
                self._append_rows(self.row_builder.finish())
                with self.db:
                    self.db.execute(
                        "UPDATE messages SET content=? WHERE id=?",
                        (self.assistant_text or "[NO OUTPUT]", self.assistant_id))
                self.generating = False
                self.cancel_event.clear()
                return

    def packet(self, start: int, count: int, *, seq: int = 0, reset: bool = False) -> bytes:
        self.drain()
        total = self.total()
        if start < 0 or start > total or not 0 <= count <= MAX_ROWS:
            raise ValueError("range out of bounds")
        rows = self.rows(start, count)
        flags = (OLDER if start > 0 else 0) | (NEWER if start + len(rows) < total else 0)
        if reset:
            flags |= RESET
        if self.generating:
            flags |= BUSY
        if self.ai_error:
            flags |= MODEL_ERROR
        return encode_chunk(Chunk(seq, start, flags, rows))

    def sync(self):
        self.drain()
        total = self.total()
        n = min(total, MAX_ROWS)
        return self.packet(total - n, n, reset=True)

    def fetch(self, request: bytes):
        req = decode_fetch(request)
        self.drain()
        if req.start >= self.total():
            # Never send a SEQ=0 RESET to a client waiting for this F seq.
            # Such a mismatch must be reported, not silently accepted.
            raise ValueError("fetch range beyond SQLite history; resync required")
        return self.packet(req.start, req.count, seq=req.seq)

    def update(self, start: int):
        self.drain()
        total = self.total()
        if start > total:
            return self.sync()
        return self.packet(start, min(MAX_ROWS, total - start))

    def ask(self, question: str, at_latest: bool):
        self.drain()
        if self.generating:
            # User may continue reading/cancelling, but only one model request
            # is allowed in flight to preserve context and message ordering.
            return self.packet(max(0, self.total() - MAX_ROWS), min(self.total(), MAX_ROWS),
                               reset=True)
        self.ai_error = None
        initial_total = self.total()
        save_message(self.db, "user", question)
        with self.db:
            cur = self.db.execute("INSERT INTO messages(role,content) VALUES('assistant','')")
            self.assistant_id = cur.lastrowid
        self.row_builder = StableRows()
        self.assistant_text = ""
        self.generating = True
        self.cancel_event.clear()
        context = self._messages_for_llm()
        self.worker = Thread(target=self._run_generation, args=(context,), daemon=True)
        self.worker.start()
        self.drain()
        count = self.total() - initial_total
        if at_latest and 0 < count <= MAX_ROWS:
            return self.packet(initial_total, count)
        return self.sync()

    def cancel(self):
        if self.generating:
            self.cancel_event.set()
        # Explicitly RESET: the host may have completed more rows than the
        # calculator has pulled at the instant a cancel is requested.
        return self.sync()

    def reply_retry(self, data: bytes):
        seq = decode_retry(data)
        if not self.last_reply or self.last_reply[1] != seq or self.retry_count >= 3:
            raise ValueError("cannot retry unknown/exhausted frame")
        self.retry_count += 1
        return self.last_reply

    def dispatch(self, ser, first: bytes) -> tuple[bytes, str, bool]:
        if first == b"S":
            return self.sync(), "SYNC", False
        if first == b"F":
            raw = first + read_exact(ser, 8)
            req = decode_fetch(raw)
            return self.fetch(raw), f"FETCH {'NEWER' if req.newer else 'OLDER'} @{req.start} ({req.count})", False
        if first == b"U":
            start = decode_update(first + read_exact(ser, 5))
            return self.update(start), f"UPDATE @{start}", False
        if first == b"Q":
            length = read_exact(ser, 1)[0]
            if not 1 <= length <= 48:
                raise ValueError("bad question length")
            raw = read_exact(ser, length)
            latest = read_exact(ser, 1)[0]
            check = read_exact(ser, 1)[0]
            if crc8(b"Q" + bytes([length]) + raw + bytes([latest, check])):
                raise ValueError("bad Q frame CRC8; question NOT stored")
            if latest not in (0, 1) or any(not 32 <= x <= 126 for x in raw):
                raise ValueError("invalid question")
            question = raw.decode("ascii")
            return self.ask(question, bool(latest)), f"Q {question!r}", False
        if first == b"R":
            return self.reply_retry(first + read_exact(ser, 2)), "RETRY", True
        if first == b"K":
            if crc8(first + read_exact(ser, 1)):
                raise ValueError("bad CANCEL checksum")
            return self.cancel(), "CANCEL", False
        raise ValueError(f"unknown command {first!r}")


def serve(link: UnoUsb, engine: ConversationEngine, *, verbose: bool = False,
          adaptive: bool = False, reply_delay_ms: int = 0):
    """Main thread owns UART and SQLite. Implicit next requests confirm receipt.

    reply_delay_ms inserts host-side turnaround BEFORE the first TI byte of
    EVERY application reply. This isolates calculator screen redraw/receive
    assist starvation without changing inter-byte timing or Uno firmware.
    The default remains zero until physical timing is validated.

    Adaptive pacing is conservative: with eight successful full exchanges,
    reduce only 2 ms at a time to a 12 ms floor. On an application CRC retry,
    slow by 5 ms (50 ms maximum) and reset the success streak. A byte lost
    at the physical level may never produce a reply, so this is not a
    substitute for packet timeouts and hardware verification.
    """
    print("Listening for TI-83 Plus. Run Asm(prgmC83V5). Ctrl+C exits.", flush=True)
    streak = 0
    while True:
        incoming = link.read(1)
        if not incoming:
            engine.drain()
            continue
        packet, label, is_retry = engine.dispatch(link, incoming)
        if adaptive:
            if is_retry:
                streak = 0
                target = min(50, link.gap_ms + 5)
                if target != link.gap_ms:
                    link.set_gap(target)
                    print(f"CRC retry -> slowing Uno to {target} ms/byte")
            else:
                streak += 1
                if streak >= 8 and link.gap_ms > 12:
                    target = max(12, link.gap_ms - 2)
                    link.set_gap(target)
                    print(f"8 successful requests -> Uno gap now {target} ms/byte")
                    streak = 0
        if not is_retry:
            engine.last_reply = packet
            engine.retry_count = 0
        if verbose or link.debug_link:
            print(f"[TX-BEGIN] {label}: {len(packet)} bytes "
                  f"({(len(packet) + 15) // 16} batches), "
                  f"turnaround={reply_delay_ms}ms", flush=True)
        if reply_delay_ms:
            time.sleep(reply_delay_ms / 1000.0)
        # Don't print the success label until the entire TI Link batch
        # has been ACKed. TX-BEGIN makes failures identifiable by request.
        link.write(packet)
        info = f"{label} -> {packet[6]} rows, flags={packet[7]:02X}, {len(packet)} bytes"
        if verbose or not label.startswith("UPDATE") or packet[6] or not packet[7] & BUSY:
            print(info, flush=True)


def main():
    ap = argparse.ArgumentParser(description="CHAT83 v0.5 LLM terminal bridge")
    ap.add_argument("--port", default="COM2")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--provider", choices=("demo", "openai", "ollama"), default="demo")
    ap.add_argument("--model", default="")
    ap.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    ap.add_argument("--gap-ms", type=int, default=35,
                    help="Uno inter-byte Link gap (2..50 ms; first hardware test keep 35)")
    ap.add_argument("--max-context-chars", type=int, default=8000)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--debug-link", action="store_true",
                    help="ask patched Uno to report physical link counters every 500ms")
    ap.add_argument("--reply-delay-ms", type=int, default=0,
                    help="experiment: wait 0..1500 ms before PC sends a reply to TI; "
                         "try 250 to test slow calculator redraw")
    ap.add_argument("--adaptive", action="store_true",
                    help="experimental rate tuning; enable only after baseline hardware validation")
    args = ap.parse_args()
    if not 2 <= args.gap_ms <= 50:
        ap.error("--gap-ms must be 2..50")
    if not 0 <= args.reply_delay_ms <= 1500:
        ap.error("--reply-delay-ms must be 0..1500")
    model = args.model or {"demo": "offline", "openai": "gpt-4.1-mini",
                           "ollama": "llama3.2"}[args.provider]
    provider = provider_factory(args.provider, model, args.ollama_url)
    import serial
    args.db.parent.mkdir(parents=True, exist_ok=True)
    with db_connect(args.db) as db:
        engine = ConversationEngine(db, provider, max_context_chars=args.max_context_chars)
        print(f"CHAT83 v0.5 | COM={args.port} | provider={args.provider} | model={model} | DB={args.db}")
        with serial.Serial(args.port, baudrate=115200, timeout=0.02,
                           write_timeout=5) as ser:
            time.sleep(2.5)  # Arduino Uno auto-reset on serial open.
            ser.reset_input_buffer()
            link = UnoUsb(ser, gap_ms=args.gap_ms, timeout=10)
            link.connect()  # refuses to run with upstream serial2ti83 firmware.
            print(f"CHAT83 Uno v0.5 handshake OK; gap {args.gap_ms}ms")
            if args.debug_link:
                link.enable_link_diagnostics()
            try:
                serve(link, engine, verbose=args.verbose, adaptive=args.adaptive,
                      reply_delay_ms=args.reply_delay_ms)
            finally:
                print(f"Uno link statistics: {link.stats()}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped")
    except (TimeoutError, LinkFailure, ValueError) as exc:
        print(f"\nLINK ERROR: {exc}\nCheck Uno v0.5 firmware, COM port and restart both endpoints.")
        raise SystemExit(2)
