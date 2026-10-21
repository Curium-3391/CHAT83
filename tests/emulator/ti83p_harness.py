"""Minimal TI-83 Plus harness for running CHAT83 Z80 builds without a ROM.

This is NOT a calculator emulator. It runs the assembled program on a Z80
core (the `z80` PyPI package) and replaces only what CHAT83 touches:

- bcall (rst 28h) for _PutC, _PutMap, _ClrLCDFull, _HomeUp, _GetCSC and
  _SendAByte, plus bjump(_JForceCmdNoChar) for the App exit path.
- APP_PUSH_ERRORH / APP_POP_ERRORH (call 59h / 5Ch) and OS error delivery:
  `link_down` makes _SendAByte raise ERR:LINK, `raise_os_error` injects
  any error. Like the OS, an error restores SP to its value when the
  handler was installed, drops the handler and jumps to it with A = code.
  The real OS keeps the frame on the stack; here it is kept in Python.
- Port 00h/05h receive assist: bit 3 of port 00h reports a byte waiting,
  IN (05h) takes it. Bytes are only offered while bit 2 (assist) is on.
- Ports 10h/11h: enough of the T6A04 LCD driver for direct pixel writes.

Text is kept as a 16x8 grid of (character, inverse) cells, so tests can
assert on screen contents. `render_png` draws it with a desktop font: the
layout, inversion and direct pixels are faithful, the glyph shapes are not.

ROM timing, the real link handshake, interrupts and APD are not modeled.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Callable, Optional

import z80

ROWS, COLS = 8, 16
SENTINEL = 0x0100          # return address pushed for the program's final RET
# OS error codes as delivered in A (ti83plus.inc: E_EDIT = 80h).
ERR_BREAK = 0x80 | 6       # E_Break: ON pressed
ERR_LINK = 0x80 | 31       # E_LnkErr: _SendAByte handshake failed


class Equates(dict):
    """Case-insensitive, like SPASM labels (the include has `_homeup`)."""

    def __getitem__(self, name: str) -> int:
        return super().__getitem__(name.lower())


def load_equates(inc_path: Path) -> Equates:
    """Parse `name EQU 1234h` and `name = $1234` lines from ti83plus.inc."""
    equates = Equates()
    pattern = re.compile(
        r"^\s*([A-Za-z_][\w]*)\s*(?:EQU|=)\s*(?:\$([0-9A-Fa-f]+)|([0-9A-Fa-f]+)h|(\d+))\b",
        re.I)
    for line in inc_path.read_text(errors="replace").splitlines():
        m = pattern.match(line)
        if not m:
            continue
        name, dollar, hexh, dec = m.groups()
        value = int(dollar or hexh, 16) if (dollar or hexh) else int(dec)
        equates.setdefault(name.lower(), value)
    return equates


@dataclass
class Screen:
    cells: list[list[tuple[str, bool]]] = field(
        default_factory=lambda: [[(" ", False)] * COLS for _ in range(ROWS)])
    # Pixels written through the LCD data port; None = owned by text cells.
    pixels: list[list[Optional[bool]]] = field(
        default_factory=lambda: [[None] * 96 for _ in range(64)])

    def clear(self):
        self.__init__()

    def put(self, row: int, col: int, char: str, inverse: bool):
        if 0 <= row < ROWS and 0 <= col < COLS:
            self.cells[row][col] = (char, inverse)
            for y in range(row * 8, row * 8 + 8):
                for x in range(col * 6, col * 6 + 6):
                    self.pixels[y][x] = None

    def text(self, row: int) -> str:
        return "".join(c for c, _ in self.cells[row])

    def inverse(self, row: int) -> str:
        """'#' where a cell is inverted, '.' elsewhere."""
        return "".join("#" if inv else "." for _, inv in self.cells[row])

    def dump(self) -> str:
        return "\n".join(f"{self.text(r)}|{self.inverse(r)}" for r in range(ROWS))


class LinkPeer:
    """Fake PC side: frames bytes sent by the calculator and queues replies.

    `respond` receives the complete request bytes when the calculator turns
    the receive assist back on (CHAT83 always finishes a request first) and
    returns the reply bytes.
    """

    def __init__(self, respond: Callable[[bytes], bytes]):
        self.respond = respond
        self.request = bytearray()
        self.incoming = deque()
        self.log: list[tuple[bytes, bytes]] = []
        self.hold = False          # queue replies until release()
        self.held = deque()

    def calc_sent(self, value: int):
        self.request.append(value)

    def assist_enabled(self):
        if not self.request:
            return
        request = bytes(self.request)
        self.request.clear()
        reply = self.respond(request)
        self.log.append((request, reply))
        (self.held if self.hold else self.incoming).extend(reply)

    def release(self):
        self.hold = False
        self.incoming.extend(self.held)
        self.held.clear()


class Harness:
    def __init__(self, binary: Path, inc_path: Path, peer: Optional[LinkPeer] = None,
                 *, app: bool = False):
        """`binary` is SPASM raw output (.bin). Programs load at userMem-2 and
        start at userMem; an App (-DCHAT83_APP) loads at 4000h and starts
        after its 128-byte header. Unstubbed bcalls such as _PutS fail the
        run, which also catches App code passing Flash pointers to the OS."""
        self.eq = load_equates(inc_path)
        # SPASM -L writes NAME = $XXXX labels next to the binary.
        self.labels = Equates()
        lab = binary.with_suffix(".lab")
        if lab.exists():
            for line in lab.read_text().splitlines():
                name, _, value = line.partition(" = $")
                if value:
                    self.labels[name.strip().lower()] = int(value, 16)
        self.m = z80.Z80Machine()
        self.screen = Screen()
        self.peer = peer
        self.keys: deque[int] = deque()
        self.idle_csc = 0          # consecutive _GetCSC calls that returned 0
        self.exited = False
        self.port0 = 0
        self.error_handlers: list[tuple[int, int]] = []   # (handler, sp)
        self.link_down = False
        self.os_errors: list[int] = []                     # errors raised
        self.lcd_x = 0             # row (0..63)
        self.lcd_y = 0             # byte column (0..11)
        self.lcd_mode = 0x05       # OS default: X (row) auto-increment
        self.bcalls = {
            self.eq["_PutC"]: self._put_c,
            self.eq["_PutMap"]: self._put_map,
            self.eq["_ClrLCDFull"]: self._clear,
            self.eq["_HomeUp"]: self._home_up,
            self.eq["_GetCSC"]: self._get_csc,
            self.eq["_SendAByte"]: self._send_a_byte,
        }
        image = binary.read_bytes()
        base = 0x4000 if app else self.eq["userMem"] - 2
        self.m.set_memory_block(base, image)
        self.m.set_memory_block(0x000B, b"\xC9")   # LCD_BUSY_QUICK: ret
        for addr in (0x28, 0x50, 0x59, 0x5C, SENTINEL):
            self.m.set_breakpoint(addr)
        self.m.iy = self.eq["flags"]
        self.m.sp = 0xFFF0
        self._push(SENTINEL)
        self.m.pc = 0x4080 if app else self.eq["userMem"]
        self.m.set_input_callback(self._in)
        self.m.set_output_callback(self._out)

    # ---- memory helpers -------------------------------------------------
    def peek(self, addr: int) -> int:
        return self.m.memory[addr]

    def poke(self, addr: int, value: int):
        self.m.memory[addr] = value & 0xFF

    def _push(self, value: int):
        self.m.sp = (self.m.sp - 2) & 0xFFFF
        self.poke(self.m.sp, value)
        self.poke(self.m.sp + 1, value >> 8)

    def _pop(self) -> int:
        value = self.peek(self.m.sp) | (self.peek(self.m.sp + 1) << 8)
        self.m.sp = (self.m.sp + 2) & 0xFFFF
        return value

    def var(self, label: str) -> int:
        """Byte at a program label (needs the SPASM -L .lab file)."""
        return self.peek(self.labels[label])

    def flag(self, offset_name: str, bit_name: str) -> bool:
        return bool(self.peek(self.eq["flags"] + self.eq[offset_name]) >> self.eq[bit_name] & 1)

    # ---- bcall stubs ----------------------------------------------------
    def _cursor(self) -> tuple[int, int]:
        return self.peek(self.eq["curRow"]), self.peek(self.eq["curCol"])

    def _put_map(self):
        row, col = self._cursor()
        self.screen.put(row, col, chr(self.m.a), self.flag("textFlags", "textInverse"))

    def _put_c(self):
        self._put_map()
        row, col = self._cursor()
        col += 1
        if col >= COLS:
            col, row = 0, row + 1
        self.poke(self.eq["curRow"], min(row, ROWS - 1))
        self.poke(self.eq["curCol"], col)

    def _clear(self):
        self.screen.clear()

    def _home_up(self):
        self.poke(self.eq["curRow"], 0)
        self.poke(self.eq["curCol"], 0)

    def _get_csc(self):
        if self.keys:
            self.m.a = self.keys.popleft()
            self.idle_csc = 0
        else:
            self.m.a = 0
            self.idle_csc += 1

    def raise_os_error(self, code: int):
        """What the OS does on an error inside a bcall."""
        self.os_errors.append(code)
        if not self.error_handlers:
            raise AssertionError(f"OS error {code:02X} escaped to the OS (no handler)")
        handler, sp = self.error_handlers.pop()
        self.m.sp = sp
        self.m.a = code
        self.m.pc = handler

    def _send_a_byte(self):
        if self.link_down:
            self.raise_os_error(ERR_LINK)
            return
        if self.peer is None:
            raise AssertionError("program sent a link byte, but no peer is attached")
        self.peer.calc_sent(self.m.a)

    # ---- ports ----------------------------------------------------------
    def _in(self, port: int) -> int:
        port &= 0xFF
        if port == 0x00:
            ready = bool(self.port0 & 4 and self.peer and self.peer.incoming)
            return 0x03 | (0x08 if ready else 0)
        if port == 0x05:
            if self.peer and self.peer.incoming:
                return self.peer.incoming.popleft()
            return 0
        if port == 0x10:
            return 0
        return 0xFF

    def _out(self, port: int, value: int):
        port &= 0xFF
        if port == 0x00:
            was = self.port0
            self.port0 = value
            if value & 4 and not was & 4 and self.peer:
                self.peer.assist_enabled()
        elif port == 0x10:
            if 0x20 <= value <= 0x2B:
                self.lcd_y = value - 0x20
            elif 0x80 <= value <= 0xBF:
                self.lcd_x = value - 0x80
            elif value in (0x04, 0x05, 0x06, 0x07):
                self.lcd_mode = value
        elif port == 0x11:
            for bit in range(8):
                x = self.lcd_y * 8 + bit
                if x < 96 and self.lcd_x < 64:
                    self.screen.pixels[self.lcd_x][x] = bool(value & (0x80 >> bit))
            if self.lcd_mode == 0x05:
                self.lcd_x = (self.lcd_x + 1) % 64
            elif self.lcd_mode == 0x07:
                self.lcd_y = (self.lcd_y + 1) % 12

    # ---- execution ------------------------------------------------------
    def _handle_breakpoint(self):
        pc = self.m.pc
        if pc == SENTINEL:
            self.exited = True
            return
        ret = self._pop()
        if pc == 0x59:                      # APP_PUSH_ERRORH, HL = handler
            self.error_handlers.append((self.m.hl, self.m.sp))
            self.m.pc = ret
            return
        if pc == 0x5C:                      # APP_POP_ERRORH
            if not self.error_handlers:
                raise AssertionError("APP_POP_ERRORH without a handler")
            self.error_handlers.pop()
            self.m.pc = ret
            return
        target = self.peek(ret) | (self.peek(ret + 1) << 8)
        if pc == 0x50 and target == self.eq["_JForceCmdNoChar"]:
            self.exited = True
            return
        stub = self.bcalls.get(target)
        if stub is None:
            raise AssertionError(f"unsupported bcall {target:04X} from {ret - 1:04X}")
        self.m.pc = (ret + 2) & 0xFFFF
        stub()                              # may redirect pc (OS error)

    def run(self, max_instructions_ticks: int = 2_000_000):
        """Run for at most the given number of CPU ticks (stops on exit)."""
        self.m.ticks_to_stop = max_instructions_ticks
        while not self.exited:
            events = self.m.run()
            if events & self.m._BREAKPOINT_HIT:
                self._handle_breakpoint()
                continue
            if events & self.m._TICKS_LIMIT_HIT:
                return

    def run_until_idle(self, idle_polls: int = 3, limit_ticks: int = 400_000_000):
        """Run until the program has polled the keyboard `idle_polls` times in a
        row with no key queued and no link bytes pending."""
        spent = 0
        step = 2_000_000
        while not self.exited and spent < limit_ticks:
            self.idle_csc = 0
            self.run(step)
            spent += step
            busy_link = self.peer is not None and (self.peer.incoming or self.peer.request)
            if not self.keys and not busy_link and self.idle_csc >= idle_polls:
                return
        if not self.exited:
            raise TimeoutError("program did not become idle")

    def press(self, *scan_codes: int, settle: bool = True):
        """Queue keys. Each key is followed by a released (0) scan, because
        CHAT83 ignores a held key until its auto-repeat threshold."""
        for code in scan_codes:
            self.keys.append(code)
            self.keys.append(0)
        if settle:
            self.run_until_idle()

    def sk(self, name: str) -> int:
        return self.eq["sk" + name]


def render_png(screen: Screen, path: Path, scale: int = 4):
    """Draw the 96x64 screen. Text uses a desktop monospace font."""
    from PIL import Image, ImageDraw, ImageFont

    on, off = (34, 40, 32), (163, 178, 150)
    border = 6 * scale
    img = Image.new("RGB", (96 * scale + 2 * border, 64 * scale + 2 * border), (60, 64, 56))
    draw = ImageDraw.Draw(img)
    draw.rectangle([border, border, border + 96 * scale - 1, border + 64 * scale - 1], fill=off)
    font = None
    for candidate in ("DejaVuSansMono-Bold.ttf", "DejaVuSansMono.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        try:
            font = ImageFont.truetype(candidate, 7 * scale)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    for r in range(ROWS):
        for c in range(COLS):
            char, inverse = screen.cells[r][c]
            x0, y0 = border + c * 6 * scale, border + r * 8 * scale
            if inverse:
                draw.rectangle([x0, y0, x0 + 6 * scale - 1, y0 + 8 * scale - 1], fill=on)
            if char != " ":
                draw.text((x0 + scale // 2, y0), char, font=font, fill=off if inverse else on)
    for y in range(64):
        for x in range(96):
            value = screen.pixels[y][x]
            if value is not None:
                x0, y0 = border + x * scale, border + y * scale
                draw.rectangle([x0, y0, x0 + scale - 1, y0 + scale - 1], fill=on if value else off)
    img.save(path)
