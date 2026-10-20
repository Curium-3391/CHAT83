"""CHAT83 v0.5 app frames (Z80 <---> PC over the Uno byte-forwarder).

Fetch: U32 absolute offsets, CRC8 instead of v0.4 XOR.
    S                  sync to latest six rows
    F SEQ DIR START4 COUNT CRC8  -> 9 bytes
    Q LEN ASCII LATEST CRC8  request text and delta safety
    U START4 CRC8      poll newest live rows (6 bytes)
    R SEQ CRC8         request retransmit of last response (3 bytes)
    K CRC8             cancel current LLM generation
Reply:
    C SEQ START4 COUNT FLAGS ASCII[12*COUNT] CRC8

FLAGS: 0x01 older, 0x02 newer, 0x04 reset, 0x08 generating,
       0x10 model error. Only RESET may contain no data in v0.4; v0.5
       also allows zero-row poll/fetch responses.
Sequence zero for S/Q/U; request seq for F; one outstanding F at a time.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from usb_v05 import crc8

MAX_ROWS = 6
WIDTH = 12
OLDER, NEWER, RESET, BUSY, MODEL_ERROR = 1, 2, 4, 8, 16


@dataclass(frozen=True)
class RangeRequest:
    seq: int
    newer: bool
    start: int
    count: int


@dataclass(frozen=True)
class Chunk:
    seq: int
    start: int
    flags: int
    rows: tuple[str, ...]

    @property
    def busy(self):
        return bool(self.flags & BUSY)


def encode_fetch(req: RangeRequest) -> bytes:
    if not 1 <= req.seq <= 255 or not 1 <= req.count <= MAX_ROWS or not 0 <= req.start < 2**32:
        raise ValueError("invalid fetch attributes")
    msg = b"F" + bytes([req.seq, int(req.newer)]) + struct.pack("<I", req.start) + bytes([req.count])
    return msg + bytes([crc8(msg)])


def decode_fetch(data: bytes) -> RangeRequest:
    if len(data) != 9 or data[0:1] != b"F" or crc8(data) != 0:
        raise ValueError("invalid fetch or CRC8")
    seq, direction, count = data[1], data[2], data[7]
    if not seq or direction not in (0, 1) or not 1 <= count <= MAX_ROWS:
        raise ValueError("invalid fetch header")
    return RangeRequest(seq, bool(direction), struct.unpack("<I", data[3:7])[0], count)


def encode_update(start: int) -> bytes:
    if not 0 <= start < 2**32:
        raise ValueError("out-of-range update cursor")
    data = b"U" + struct.pack("<I", start)
    return data + bytes([crc8(data)])


def decode_update(data: bytes) -> int:
    if len(data) != 6 or data[:1] != b"U" or crc8(data) != 0:
        raise ValueError("invalid update / checksum")
    return struct.unpack("<I", data[1:5])[0]


def encode_retry(seq: int) -> bytes:
    if not 0 <= seq <= 255:
        raise ValueError("bad retry sequence")
    d = bytes([ord("R"), seq])
    return d + bytes([crc8(d)])


def decode_retry(data: bytes) -> int:
    if len(data) != 3 or data[:1] != b"R" or crc8(data):
        raise ValueError("invalid retry")
    return data[1]


def encode_cancel() -> bytes:
    return b"K" + bytes([crc8(b"K")])


def encode_chunk(chunk: Chunk) -> bytes:
    if not 0 <= chunk.seq <= 255 or not 0 <= chunk.start < 2**32 or not 0 <= chunk.flags < 32:
        raise ValueError("bad chunk header")
    if len(chunk.rows) > MAX_ROWS:
        raise ValueError("too many rows")
    rawrows = []
    for row in chunk.rows:
        if len(row) != WIDTH or not row.isascii() or not row.isprintable():
            raise ValueError("each row must be exactly 12 printable ASCII characters")
        rawrows.append(row.encode("ascii"))
    data = b"C" + bytes([chunk.seq]) + struct.pack("<I", chunk.start) \
           + bytes([len(chunk.rows), chunk.flags]) + b"".join(rawrows)
    return data + bytes([crc8(data)])


def decode_chunk(data: bytes) -> Chunk:
    if len(data) < 9 or data[:1] != b"C" or crc8(data):
        raise ValueError("invalid chunk CRC8")
    seq, start, count, flags = data[1], struct.unpack("<I", data[2:6])[0], data[6], data[7]
    if count > MAX_ROWS or flags >= 32 or len(data) != 9 + 12 * count:
        raise ValueError("bad chunk length / header")
    rawrows = data[8:-1]
    if any(b < 32 or b > 126 for b in rawrows):
        raise ValueError("non-printable display row")
    return Chunk(seq, start, flags, tuple(
        rawrows[i:i + 12].decode("ascii") for i in range(0, len(rawrows), 12)))
