"""AX.25 frames over AXUDP, from the test process's side.

`Probe` is an AXUDP endpoint the tests own: XRouter's port is pointed at it,
so the tests can send any frame XRouter would hear on that port (UI frames,
NODES broadcasts, IP datagrams) and see everything XRouter sends there.
`L2Session` is a deliberately small AX.25 v2.0 connected-mode client (mod 8,
no SREJ, one frame in flight at a time on our side) so a test can connect to
the node, its PMS or an application the way a radio user would.
"""

from __future__ import annotations

import queue
import socket
import threading
import time
from dataclasses import dataclass, field


def fcs16(data: bytes) -> int:
    """CRC-16/X.25 as AX.25 uses it (init 0xFFFF, reflected, final xor)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def enc_call(call: str, last: bool = False, hbit: bool = False, cmd: bool = False) -> bytes:
    """'CALL-SSID' to the 7-byte AX.25 address field. `cmd` sets the C bit
    (bit 7 of the SSID byte), `hbit` the has-been-repeated bit for digis
    (same bit position, so pass at most one)."""
    base, _, ssid = call.upper().partition("-")
    out = bytes((ord(c) << 1) for c in base.ljust(6)[:6])
    s = 0x60 | ((int(ssid or 0) & 0x0F) << 1)
    if last:
        s |= 1
    if hbit or cmd:
        s |= 0x80
    return out + bytes([s])


def dec_call(raw: bytes) -> str:
    call = "".join(chr(b >> 1) for b in raw[:6]).strip()
    ssid = (raw[6] >> 1) & 0x0F
    return f"{call}-{ssid}" if ssid else call


U_TYPES = {0x03: "UI", 0x0F: "DM", 0x2F: "SABM", 0x43: "DISC", 0x63: "UA",
           0x6F: "SABME", 0x87: "FRMR", 0xAF: "XID", 0xE3: "TEST"}
U_CODES = {v: k for k, v in U_TYPES.items()}


@dataclass
class Frame:
    dst: str
    src: str
    digis: list[tuple[str, bool]] = field(default_factory=list)   # (call, has-been-repeated)
    ctl: int = 0x03
    pid: int | None = 0xF0
    info: bytes = b""
    command: bool = True          # C bit in dst (v2 command), else response
    t: float = 0.0

    # -- classification ---------------------------------------------------

    @property
    def type(self) -> str:
        if self.ctl & 1 == 0:
            return "I"
        if self.ctl & 3 == 1:
            return {0: "RR", 1: "RNR", 2: "REJ", 3: "SREJ"}[(self.ctl >> 2) & 3]
        return U_TYPES.get(self.ctl & ~0x10, f"U?{self.ctl:02x}")

    @property
    def pf(self) -> bool:
        return bool(self.ctl & 0x10)

    @property
    def ns(self) -> int:
        return (self.ctl >> 1) & 7

    @property
    def nr(self) -> int:
        return (self.ctl >> 5) & 7

    @property
    def text(self) -> str:
        return self.info.decode("latin-1")

    # -- wire format ------------------------------------------------------

    def encode(self) -> bytes:
        addr = enc_call(self.dst, cmd=self.command)
        last_src = not self.digis
        src = enc_call(self.src, last=last_src, cmd=not self.command)
        addr += src
        for i, (d, h) in enumerate(self.digis):
            addr += enc_call(d, last=i == len(self.digis) - 1, hbit=h)
        body = addr + bytes([self.ctl])
        if self.pid is not None:
            body += bytes([self.pid])
        body += self.info
        return body

    def axudp(self) -> bytes:
        body = self.encode()
        c = fcs16(body)
        return body + bytes([c & 0xFF, c >> 8])

    @classmethod
    def decode(cls, data: bytes, has_fcs: bool = True) -> "Frame":
        if has_fcs:
            body, fcs = data[:-2], data[-2:]
            if fcs16(body) != (fcs[0] | fcs[1] << 8):
                raise ValueError("bad FCS")
        else:
            body = data
        addrs = []
        p = 0
        while True:
            a = body[p:p + 7]
            if len(a) < 7:
                raise ValueError("short address")
            addrs.append(a)
            p += 7
            if a[6] & 1:
                break
        ctl = body[p]
        p += 1
        f = cls(dst=dec_call(addrs[0]), src=dec_call(addrs[1]), ctl=ctl,
                command=bool(addrs[0][6] & 0x80) and not addrs[1][6] & 0x80)
        f.digis = [(dec_call(a), bool(a[6] & 0x80)) for a in addrs[2:]]
        is_i = ctl & 1 == 0
        is_ui = (ctl & ~0x10) == 0x03
        if is_i or is_ui:
            f.pid = body[p]
            f.info = body[p + 1:]
        else:
            f.pid = None
            f.info = body[p:]
        return f

    def __str__(self) -> str:
        path = "".join(f",{d}{'*' if h else ''}" for d, h in self.digis)
        extra = ""
        if self.type == "I":
            extra = f" ns{self.ns} nr{self.nr}"
        elif self.type in ("RR", "RNR", "REJ"):
            extra = f" nr{self.nr}"
        pid = f" pid{self.pid:02X}" if self.pid is not None else ""
        info = f" {self.info[:80]!r}" if self.info else ""
        return f"{self.src}>{self.dst}{path} {self.type}{'+' if self.pf else ''}{extra}{pid}{info}"


def ui(dst: str, src: str, info: bytes | str, digis=(), pid: int = 0xF0) -> Frame:
    if isinstance(info, str):
        info = info.encode("latin-1")
    return Frame(dst=dst, src=src, digis=[(d, False) for d in digis], ctl=0x03, pid=pid, info=info)


class Probe:
    """One AXUDP endpoint: binds a UDP port and talks to one XRouter port.

    Every frame received is kept (with its arrival time) so a test can look
    back at what XRouter sent, and fed to any open L2Session it belongs to.
    """

    def __init__(self, name: str, bind: tuple[str, int], peer: tuple[str, int], log=None):
        self.name = name
        self.peer = peer
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(bind)
        self.sock.settimeout(0.2)
        self.frames: list[Frame] = []
        self.lock = threading.Lock()
        self.sessions: dict[tuple[str, str], "L2Session"] = {}
        self.log = log
        self._stop = False
        self.thread = threading.Thread(target=self._run, name=f"probe-{name}", daemon=True)
        self.thread.start()

    def _note(self, direction: str, f: Frame) -> None:
        if self.log:
            self.log(f"{f.t:.3f} {self.name} {direction} {f}")

    def _run(self) -> None:
        while not self._stop:
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                f = Frame.decode(data)
            except (ValueError, IndexError):
                continue
            f.t = time.time()
            with self.lock:
                self.frames.append(f)
            self._note("<-", f)
            sess = self.sessions.get((f.dst, f.src))
            if sess:
                sess._incoming(f)

    def send(self, f: Frame) -> None:
        f.t = time.time()
        self._note("->", f)
        self.sock.sendto(f.axudp(), self.peer)

    def received(self, since: float = 0.0, pred=None) -> list[Frame]:
        with self.lock:
            return [f for f in self.frames if f.t >= since and (pred is None or pred(f))]

    def wait(self, pred, timeout: float = 10.0, since: float = 0.0) -> Frame | None:
        end = time.time() + timeout
        while time.time() < end:
            got = self.received(since, pred)
            if got:
                return got[0]
            time.sleep(0.05)
        return None

    def close(self) -> None:
        self._stop = True
        for s in list(self.sessions.values()):
            s.abort()
        self.sock.close()


class L2Session:
    """Connected-mode AX.25 from `mycall` to `remote` through a Probe.

    Small on purpose: we send one I frame at a time and wait for it to be
    acknowledged, acknowledge everything XRouter sends in order, and answer
    polls. That is enough for interactive sessions with the node.
    """

    def __init__(self, probe: Probe, mycall: str, remote: str, digis=(), t1: float = 3.0, delay: float = 0.0):
        self.probe = probe
        self.mycall = mycall.upper()
        self.remote = remote.upper()
        self.digis = list(digis)
        self.t1 = t1
        self.delay = delay   # seconds added before every frame we send (a slow link)
        self.vs = 0          # next N(S) we send
        self.vr = 0          # next N(S) we expect
        self.va = 0          # oldest unacknowledged
        self.state = "idle"
        self.rx = queue.Queue()
        self.text = ""
        self.events: list[Frame] = []
        self.lock = threading.Lock()
        probe.sessions[(self.mycall, self.remote)] = self

    def _tx(self, f: Frame) -> None:
        if self.delay:
            threading.Timer(self.delay, self.probe.send, (f,)).start()
        else:
            self.probe.send(f)

    def _f(self, ctl: int, command: bool = True, pid=None, info=b"") -> Frame:
        return Frame(dst=self.remote, src=self.mycall, digis=[(d, False) for d in self.digis],
                     ctl=ctl, pid=pid, info=info, command=command)

    def _incoming(self, f: Frame) -> None:
        with self.lock:
            self.events.append(f)
            t = f.type
            if t == "UA" and self.state == "connecting":
                self.state = "connected"
            elif t == "DM":
                self.state = "disconnected"
            elif t == "DISC":
                self._tx(self._f(U_CODES["UA"] | (0x10 if f.pf else 0), command=False))
                self.state = "disconnected"
            elif t == "SABM":
                # Remote (re)established the link: reset sequence numbers.
                self.vs = self.vr = self.va = 0
                self._tx(self._f(U_CODES["UA"] | (0x10 if f.pf else 0), command=False))
                self.state = "connected"
            elif t == "I":
                if f.ns == self.vr:
                    self.vr = (self.vr + 1) & 7
                    self.text += f.info.decode("latin-1")
                self.va = f.nr
                self._tx(self._f(0x01 | (self.vr << 5) | (0x10 if f.pf else 0), command=False))
            elif t in ("RR", "RNR", "REJ"):
                self.va = f.nr
                if f.pf and f.command:
                    self._tx(self._f(0x01 | (self.vr << 5) | 0x10, command=False))

    # -- API ----------------------------------------------------------------

    def connect(self, timeout: float = 15.0) -> bool:
        self.state = "connecting"
        end = time.time() + timeout
        while time.time() < end and self.state == "connecting":
            self._tx(self._f(U_CODES["SABM"] | 0x10))
            t = time.time() + self.t1
            while time.time() < t and self.state == "connecting":
                time.sleep(0.05)
        return self.state == "connected"

    def send(self, data: str | bytes, timeout: float = 15.0) -> None:
        if isinstance(data, str):
            data = data.encode("latin-1")
        for i in range(0, len(data), 200):
            chunk = data[i:i + 200]
            ns = self.vs
            self.vs = (self.vs + 1) & 7
            end = time.time() + timeout
            first = True
            while time.time() < end:
                ctl = (ns << 1) | (self.vr << 5) | (0 if first else 0x10)
                self._tx(self._f(ctl, pid=0xF0, info=chunk))
                first = False
                t = time.time() + self.t1
                while time.time() < t:
                    if self.va == self.vs or self.state != "connected":
                        break
                    time.sleep(0.05)
                if self.va == self.vs or self.state != "connected":
                    break
            if self.state != "connected":
                return

    def line(self, text: str) -> None:
        self.send(text + "\r")

    def read(self, quiet: float = 1.5, limit: float = 15.0) -> str:
        """Collect text until nothing new for `quiet` seconds; consume it."""
        end = time.time() + limit
        last_len = len(self.text)
        last = time.time()
        while time.time() < end:
            time.sleep(0.1)
            if len(self.text) != last_len:
                last_len = len(self.text)
                last = time.time()
            elif time.time() - last > quiet:
                break
        out, self.text = self.text, ""
        return out.replace("\r", "\n")

    def expect(self, needle: str, timeout: float = 15.0) -> str:
        import re
        rx = re.compile(needle, re.I | re.M)
        end = time.time() + timeout
        while time.time() < end:
            if rx.search(self.text.replace("\r", "\n")):
                return self.read(0.8, 5)
            if self.state == "disconnected":
                break
            time.sleep(0.1)
        out, self.text = self.text, ""
        return out.replace("\r", "\n")

    def disconnect(self, timeout: float = 8.0) -> None:
        if self.state != "connected":
            self.abort()
            return
        end = time.time() + timeout
        while time.time() < end and self.state == "connected":
            self._tx(self._f(U_CODES["DISC"] | 0x10))
            t = time.time() + self.t1
            while time.time() < t and self.state == "connected":
                time.sleep(0.05)
                if any(e.type in ("UA", "DM") for e in self.events[-3:]):
                    self.state = "disconnected"
        self.abort()

    def abort(self) -> None:
        self.state = "disconnected"
        self.probe.sessions.pop((self.mycall, self.remote), None)
