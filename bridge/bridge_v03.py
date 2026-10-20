"""CHAT83 v0.3.1 experimental PC bridge with persistent remote history.

No LLM API in this release. Python 3.9+ and pyserial required.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import textwrap
import time

PAGE_SIZE = 24
ROW_WIDTH = 12
SCREEN_ROWS = 6
PAGE_STEP = PAGE_SIZE - SCREEN_ROWS
MAX_QUESTION_BYTES = 12
DEFAULT_DB = Path(__file__).resolve().parent / "chat83.sqlite3"


def db_connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    db = sqlite3.connect(str(path))
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS display_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL REFERENCES messages(id),
            text TEXT NOT NULL
        );
    """)
    return db


def text_rows(role: str, content: str) -> list[str]:
    """Render a full message as 12-character ASCII rows."""
    prefix = "YOU: " if role == "user" else "PC: "
    safe = content.encode("ascii", "replace").decode("ascii")
    logical_lines = safe.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output = []
    for index, section in enumerate(logical_lines):
        line = (prefix if index == 0 else "") + section
        output.extend(textwrap.wrap(line, width=ROW_WIDTH,
                                    break_long_words=True,
                                    break_on_hyphens=False,
                                    drop_whitespace=True) or [""])
    return [s[:ROW_WIDTH].ljust(ROW_WIDTH) for s in output]


def save_message(db: sqlite3.Connection, role: str, content: str) -> None:
    with db:
        cur = db.execute("INSERT INTO messages(role, content) VALUES (?, ?)",
                         (role, content))
        db.executemany("INSERT INTO display_lines(message_id, text) VALUES (?, ?)",
                       [(cur.lastrowid, line) for line in text_rows(role, content)])


def demo_reply(question: str) -> str:
    if question.upper() == "HELLO":
        return "WORLD"
    if question.upper() == "PING":
        return "PONG"
    if question.upper() == "DEMO":
        return ("THIS IS A LONG DEMONSTRATION OF CHAT83 REMOTE HISTORY. "
                "THE CALCULATOR KEEPS ONLY TWENTY FOUR LINES IN RAM. "
                "PYTHON STORES THE FULL CONVERSATION ON THE COMPUTER. "
                "PRESS UP TO REQUEST OLDER PAGES AND DOWN FOR NEWER PAGES. "
                "THE NEXT PHASE WILL CONNECT A REAL LANGUAGE MODEL.")
    return "PC GOT: " + question.upper()


def read_exact(ser, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        chunk = ser.read(count - len(data))
        if not chunk:
            raise TimeoutError(f"serial read timeout: {len(data)}/{count} bytes")
        data.extend(chunk)
    return bytes(data)


class Conversation:
    """Ephemeral paging state over persistent SQLite messages."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.page_start = 0

    def total_lines(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM display_lines").fetchone()[0]

    def _page(self, start: int, viewport: int) -> tuple[int, list[str], int]:
        total = self.total_lines()
        last_start = max(0, total - PAGE_SIZE)
        self.page_start = max(0, min(start, last_start))
        rows = [r[0] for r in self.db.execute(
            "SELECT text FROM display_lines ORDER BY id LIMIT ? OFFSET ?",
            (PAGE_SIZE, self.page_start)).fetchall()]
        max_view = max(0, len(rows) - SCREEN_ROWS)
        # Bit 0: older content exists; bit 1: newer content exists.
        flags = (1 if self.page_start > 0 else 0)
        flags |= (2 if self.page_start + len(rows) < total else 0)
        return max(0, min(viewport, max_view)), rows, flags

    def sync(self) -> tuple[int, list[str], int]:
        return self._page(max(0, self.total_lines() - PAGE_SIZE),
                          PAGE_SIZE - SCREEN_ROWS)

    def older(self) -> tuple[int, list[str], int]:
        old_start = self.page_start
        if old_start == 0:
            return self._page(0, 0)
        new_start = max(0, old_start - PAGE_STEP)
        return self._page(new_start, old_start - 1 - new_start)

    def newer(self) -> tuple[int, list[str], int]:
        old_start = self.page_start
        last_start = max(0, self.total_lines() - PAGE_SIZE)
        if old_start >= last_start:
            return self._page(old_start, PAGE_SIZE - SCREEN_ROWS)
        new_start = min(last_start, old_start + PAGE_STEP)
        return self._page(new_start, old_start + PAGE_STEP + 1 - new_start)

    def ask(self, question: str) -> tuple[int, list[str], int]:
        save_message(self.db, "user", question)
        save_message(self.db, "assistant", demo_reply(question))
        return self.sync()


def encode_page(page: tuple[int, list[str], int]) -> bytes:
    viewport, rows, flags = page
    if not 0 <= flags <= 3:
        raise ValueError("invalid paging flags")
    if not 0 <= len(rows) <= PAGE_SIZE:
        raise ValueError("invalid row count")
    if not 0 <= viewport <= max(0, len(rows) - SCREEN_ROWS):
        raise ValueError("invalid viewport")
    chunks = [row.encode("ascii", "replace") for row in rows]
    if any(len(row) != ROW_WIDTH for row in chunks):
        raise ValueError("all display rows must be exactly 12 bytes")
    return b"P" + bytes([len(rows), viewport, flags]) + b"".join(chunks)


def paced_write(ser, packet: bytes, delay: float) -> None:
    # serial2ti83 has no app-level ACK; this reduces Uno UART overrun risk.
    for value in packet:
        ser.write(bytes([value]))
        ser.flush()
        if delay:
            time.sleep(delay)


def handle_command(ser, conversation: Conversation, command: bytes,
                   delay: float) -> str:
    if command == b"S":
        packet = encode_page(conversation.sync())
        description = "SYNC"
    elif command == b"O":
        packet = encode_page(conversation.older())
        description = "OLDER"
    elif command == b"N":
        packet = encode_page(conversation.newer())
        description = "NEWER"
    elif command == b"Q":
        length = read_exact(ser, 1)[0]
        if not 1 <= length <= MAX_QUESTION_BYTES:
            raise ValueError(f"invalid question length {length}; restart required")
        raw = read_exact(ser, length)
        if any(not 32 <= value <= 126 for value in raw):
            raise ValueError("non-printable ASCII request; restart required")
        question = raw.decode("ascii")
        packet = encode_page(conversation.ask(question))
        description = f"Q {question!r}"
    else:
        raise ValueError(f"unknown command 0x{command.hex()}; restart required")

    # Brief time for the Z80 client to enter _RecAByteIO.
    time.sleep(0.15)
    paced_write(ser, packet, delay)
    return f"{description} -> {packet[1]} rows, view={packet[2]}, flags={packet[3]}"


def main() -> None:
    parser = argparse.ArgumentParser(description="CHAT83 v0.3.1 persistent history bridge")
    parser.add_argument("--port", default="COM2", help="Arduino USB serial port")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--pace", type=float, default=0.035,
                        help="seconds between each byte, default 35 ms")
    args = parser.parse_args()
    if args.pace < 0:
        parser.error("--pace must be >= 0")

    import serial  # Pure protocol tests do not require physical hardware.
    args.db.parent.mkdir(parents=True, exist_ok=True)
    with db_connect(args.db) as db:
        conversation = Conversation(db)
        print(f"CHAT83 v0.3.1 EXPERIMENTAL | COM={args.port} | DB={args.db}")
        with serial.Serial(args.port, args.baud, timeout=5,
                           write_timeout=5) as ser:
            time.sleep(2.5)  # Uno resets after opening COM
            ser.reset_input_buffer()
            print("Listening. Start the calculator program now. Ctrl+C exits.")
            while True:
                command = ser.read(1)
                if not command:
                    continue
                try:
                    print(handle_command(ser, conversation, command, args.pace))
                except (ValueError, TimeoutError, serial.SerialException) as err:
                    print(f"LINK/PROTOCOL ERROR: {err}")
                    print("Stop Python and restart calculator to resync.")
                    break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped")
