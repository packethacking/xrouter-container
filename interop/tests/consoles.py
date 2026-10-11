"""Tiny telnet clients for the XRouter and LinBPQ consoles.

telnetlib left the standard library in Python 3.13, and both nodes speak
only a little telnet, so this is a plain socket with IAC handling: we
refuse every option and strip the negotiation out of the text.
"""

from __future__ import annotations

import re
import socket
import time

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240


class Console:
    def __init__(self, host: str, port: int, name: str, timeout: float = 10.0):
        self.name = name
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(0.2)
        self.buf = ""
        self.transcript: list[str] = []

    # -- low level --------------------------------------------------------

    def _pump(self) -> bool:
        try:
            data = self.sock.recv(4096)
        except (socket.timeout, BlockingIOError):
            return False
        if not data:
            raise ConnectionError(f"{self.name}: connection closed")
        out = bytearray()
        i = 0
        while i < len(data):
            b = data[i]
            if b == IAC and i + 1 < len(data):
                cmd = data[i + 1]
                if cmd in (DO, DONT, WILL, WONT) and i + 2 < len(data):
                    opt = data[i + 2]
                    if cmd == DO:
                        self.sock.sendall(bytes([IAC, WONT, opt]))
                    elif cmd == WILL:
                        self.sock.sendall(bytes([IAC, DONT, opt]))
                    i += 3
                    continue
                if cmd == SB:
                    end = data.find(bytes([IAC, SE]), i)
                    i = len(data) if end < 0 else end + 2
                    continue
                if cmd == IAC:
                    out.append(IAC)
                i += 2
                continue
            out.append(b)
            i += 1
        text = out.decode("latin-1").replace("\r\n", "\n").replace("\r", "\n")
        self.buf += text
        self.transcript.append(text)
        return True

    def send(self, line: str) -> None:
        self.transcript.append(f"\n>>> {line}\n")
        self.sock.sendall(line.encode("latin-1") + b"\r")

    def expect(self, pattern: str, timeout: float = 10.0) -> str:
        """Wait until `pattern` (regex) appears; return and consume text up to it."""
        rx = re.compile(pattern, re.I | re.M)
        deadline = time.time() + timeout
        while True:
            m = rx.search(self.buf)
            if m:
                text = self.buf[:m.end()]
                self.buf = self.buf[m.end():]
                return text
            if time.time() > deadline:
                raise TimeoutError(
                    f"{self.name}: no {pattern!r} within {timeout}s; got {self.buf[-600:]!r}")
            self._pump()

    def drain(self, quiet: float = 0.8, limit: float = 10.0) -> str:
        """Collect output until nothing new arrives for `quiet` seconds."""
        end = time.time() + limit
        last = time.time()
        while time.time() < end:
            if self._pump():
                last = time.time()
            elif time.time() - last > quiet:
                break
        text, self.buf = self.buf, ""
        return text

    def ask(self, line: str, pattern: str, timeout: float = 20.0) -> str:
        """Send a line and wait for `pattern`. Returns everything received; on a
        timeout it returns what did arrive, so a failed assert can show it."""
        self.drain(0.2, 2)
        self.send(line)
        try:
            text = self.expect(pattern, timeout)
        except TimeoutError:
            text, self.buf = self.buf, ""
            return text
        return text + self.drain(0.5, 3)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class XRouterConsole(Console):
    """XRouter telnet (ACCESS.SYS lets any valid callsign in, no password)."""

    PROMPT = r"\}\s*$|=>\s*$"

    def __init__(self, host: str, port: int, call: str = "PN0TST"):
        super().__init__(host, port, "xrouter")
        self.expect(r"(callsign|login|user).*:", 15)
        self.send(call)
        # XRouter answers a login with its CTEXT and no prompt.
        self.expect(r"\S", 15)
        self.drain()

    def cmd(self, line: str, wait: float = 1.0) -> str:
        self.drain(0.2, 2)
        self.send(line)
        return self.drain(wait, 15)


class BpqConsole(Console):
    """LinBPQ telnet with the sysop user from bpq32.cfg."""

    def __init__(self, host: str, port: int, user: str = "sysop", password: str = "sysop",
                 name: str = "linbpq"):
        super().__init__(host, port, name)
        self.expect(r"user", 15)
        self.send(user)
        self.expect(r"password", 10)
        self.send(password)
        self.expect(r"(Connected to|\}|>)", 15)
        self.drain()

    def cmd(self, line: str, wait: float = 1.0) -> str:
        self.drain(0.2, 2)
        self.send(line)
        return self.drain(wait, 15)
