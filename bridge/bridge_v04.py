"""CHAT83 v0.4 cooperative prefetch bridge (EXPERIMENTAL).

Dedicated protocol, intentionally incompatible with v0.3.2.
Original TI-83 Plus only for the matching RX-assist client.

TI requests:
 S                              recent up-to-six rows, RESET response
 F SEQ DIR START:u32 COUNT XOR   bounded speculative fetch, one outstanding
 Q LEN TEXT                     new conversation entry; delta if <=6 lines

PC replies:
 C SEQ START:u32 COUNT FLAGS 12*COUNT ASCII XOR
 Flags: bit0 older exists, bit1 newer exists, bit2 RESET/cache replace.

The calculator retains its own keyboard control while receiving bytes through
the TI-83+ receive-assist latch. Keep a conservative inter-byte pacing until
the exact device handshake and latch behavior are tested.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import time

from bridge_v03 import (
    DEFAULT_DB, ROW_WIDTH, MAX_QUESTION_BYTES,
    db_connect, demo_reply, read_exact, save_message, text_rows,
)
from prefetch_v04 import (
    Fetch, LOOKAHEAD, decode_fetch, encode_chunk,
)

RESET_FLAG = 4


class Server:
    def __init__(self, db):
        self.db = db

    def total(self):
        return self.db.execute("SELECT COUNT(*) FROM display_lines").fetchone()[0]

    def rows(self, start, count):
        return [x[0] for x in self.db.execute(
            "SELECT text FROM display_lines ORDER BY id LIMIT ? OFFSET ?",
            (count, start),
        ).fetchall()]

    def packet(self, start, count, *, sequence=0, reset=False):
        if not 0 <= start <= self.total() or not 0 <= count <= LOOKAHEAD:
            raise ValueError("invalid remote row range")
        rows = self.rows(start, count)
        flags = (1 if start > 0 else 0)
        flags |= (2 if start + len(rows) < self.total() else 0)
        if reset:
            flags |= RESET_FLAG
        return encode_chunk(Fetch(1, start, len(rows), sequence), rows, flags)

    def sync(self):
        total = self.total()
        n = min(total, LOOKAHEAD)
        return self.packet(total - n, n, reset=True)

    def fetch(self, raw):
        req = decode_fetch(raw)
        if req.start >= self.total():
            raise ValueError("out-of-range fetch")
        return self.packet(req.start, req.count, sequence=req.sequence)

    def ask(self, question):
        old_total = self.total()
        reply = demo_reply(question)
        new_rows = text_rows("user", question) + text_rows("assistant", reply)
        save_message(self.db, "user", question)
        save_message(self.db, "assistant", reply)
        if len(new_rows) <= LOOKAHEAD:
            return self.packet(old_total, len(new_rows))
        # A very long answer cannot fit in the six-row staging buffer.
        return self.sync()


def decode_one(ser, first, server):
    if first == b"S":
        return server.sync(), "SYNC"
    if first == b"F":
        raw = first + read_exact(ser, 8)
        request = decode_fetch(raw)
        return server.fetch(raw), f"FETCH {'OLDER' if request.direction == -1 else 'NEWER'} @{request.start} ({request.count})"
    if first == b"Q":
        length = read_exact(ser, 1)[0]
        if not 1 <= length <= MAX_QUESTION_BYTES:
            raise ValueError(f"bad question length {length}")
        raw = read_exact(ser, length)
        if any(not 32 <= b <= 126 for b in raw):
            raise ValueError("non-ASCII input")
        question = raw.decode("ascii")
        return server.ask(question), f"Q {question!r}"
    raise ValueError(f"bad command {first.hex()}")


def transmit(ser, data, pace):
    if pace < 0.035:
        raise ValueError("the RX-assist experiment requires >=35 ms byte spacing")
    time.sleep(0.15)  # calculator enables RX-assist after ROM _SendAByte
    for byte in data:
        ser.write(bytes([byte]))
        ser.flush()
        time.sleep(pace)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM2")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--pace", type=float, default=0.055,
                    help="interbyte seconds, default 55 ms until hardware-tested")
    args = ap.parse_args()
    if args.pace < 0.035:
        ap.error("--pace must be >= 0.035")

    import serial
    args.db.parent.mkdir(parents=True, exist_ok=True)
    with db_connect(args.db) as db:
        server = Server(db)
        print(f"CHAT83 v0.4 LAB | COM={args.port} | DB={args.db}")
        with serial.Serial(args.port, 9600, timeout=5, write_timeout=5) as ser:
            time.sleep(2.5)
            ser.reset_input_buffer()
            print("Listening. Start v0.4 Z80 client. Ctrl+C exits.", flush=True)
            while True:
                incoming = ser.read(1)
                if not incoming:
                    continue
                try:
                    packet, label = decode_one(ser, incoming, server)
                    transmit(ser, packet, args.pace)
                    print(f"{label} -> {packet[6]} rows, flags={packet[7]:02x}, {len(packet)} bytes",
                          flush=True)
                except (ValueError, TimeoutError, serial.SerialException) as exc:
                    print(f"LINK ERROR: {exc}; restart both programs")
                    break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped")
