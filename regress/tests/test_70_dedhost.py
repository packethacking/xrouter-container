"""XRouter's WA8DED host-mode emulation (MAN DEDHOST), as host-mode
programs such as tsthost use it (PA2SNK, groups.io 4385/4400, runs tsthost
1.43 with XRouter and reported "beacon digi (unproto request)" problems).

The emulated TNC is on a pty that socat bridges to TCP. Host mode frames:
to the TNC  [channel][0 info | 1 command][length-1][data]; from the TNC
[channel][code] then a NUL-terminated text (codes 1-5) or [length-1][data]
(codes 6, 7), or nothing (code 0).
"""

from __future__ import annotations

import socket
import time

import pytest

from conftest import DED_TCP, HOST


class HostMode:
    def __init__(self):
        self.s = socket.create_connection((HOST, DED_TCP), timeout=10)
        self.s.settimeout(5)
        self.buf = b""

    def raw(self, data: bytes) -> None:
        self.s.sendall(data)

    def _need(self, n: int, timeout: float) -> bool:
        end = time.time() + timeout
        while len(self.buf) < n and time.time() < end:
            try:
                d = self.s.recv(4096)
            except socket.timeout:
                continue
            if not d:
                raise ConnectionError("host mode link closed")
            self.buf += d
        return len(self.buf) >= n

    def reply(self, timeout: float = 5.0):
        """One response frame: (channel, code, data)."""
        if not self._need(2, timeout):
            return None
        ch, code = self.buf[0], self.buf[1]
        if code == 0:
            self.buf = self.buf[2:]
            return ch, 0, b""
        if code in (6, 7):
            if not self._need(3, timeout):
                return None
            n = self.buf[2] + 1
            self._need(3 + n, timeout)
            data, self.buf = self.buf[3:3 + n], self.buf[3 + n:]
            return ch, code, data
        end = time.time() + timeout
        while b"\0" not in self.buf[2:] and time.time() < end:
            self._need(len(self.buf) + 1, 0.5)
        i = self.buf.index(b"\0", 2)
        data, self.buf = self.buf[2:i], self.buf[i + 1:]
        return ch, code, data

    def cmd(self, ch: int, text: str, timeout: float = 5.0):
        b = text.encode()
        self.raw(bytes([ch, 1, len(b) - 1]) + b)
        return self.reply(timeout)

    def info(self, ch: int, data: bytes, timeout: float = 5.0):
        self.raw(bytes([ch, 0, len(data) - 1]) + data)
        return self.reply(timeout)

    def close(self):
        self.s.close()


@pytest.fixture(scope="module")
def host(dednode):
    h = HostMode()
    # Leave any half-typed terminal-mode line, then enter host mode.
    h.raw(b"\r\x1bJHOST1\r")
    time.sleep(1.5)
    h.buf = b""
    try:
        h.s.recv(4096)
    except socket.timeout:
        pass
    yield h, dednode
    h.close()


def test_dedhost_enters_host_mode(host):
    h, _ = host
    r = h.cmd(0, "V")
    assert r is not None and r[1] in (0, 1), f"no host-mode reply to V: {r!r}"


def test_dedhost_set_mycall(host):
    h, _ = host
    r = h.cmd(0, "I PN0DED")
    assert r is not None and r[1] in (0, 1), r
    r = h.cmd(0, "I")
    assert r is not None and b"PN0DED" in r[2].upper(), r


def test_dedhost_unproto_beacon(host):
    """Channel 0: C sets the unproto destination; info on channel 0 is sent
    as a UI frame, which is how host-mode programs send beacons."""
    h, probe = host
    h.cmd(0, "I PN0DED")
    r = h.cmd(0, "C BEACON")
    assert r is not None and r[1] in (0, 1), r
    t = time.time()
    h.info(0, b"ded beacon text\r")
    f = probe.wait(lambda f: f.dst == "BEACON" and b"ded beacon text" in f.info, 10, t)
    assert f is not None, "no UI frame after a host-mode unproto send"
    assert f.type == "UI" and f.src == "PN0DED", str(f)


def test_dedhost_unproto_beacon_via_digi(host):
    h, probe = host
    h.cmd(0, "I PN0DED")
    r = h.cmd(0, "C BEACON PN0ZZ")
    assert r is not None and r[1] in (0, 1), r
    t = time.time()
    h.info(0, b"ded beacon via\r")
    f = probe.wait(lambda f: f.dst == "BEACON" and b"ded beacon via" in f.info, 10, t)
    assert f is not None, "no UI frame after a host-mode unproto send via a digi"
    assert [d for d, _ in f.digis] == ["PN0ZZ"], str(f)


def test_dedhost_connect_sends_sabm(host):
    h, probe = host
    h.cmd(1, "I PN0DED")
    t = time.time()
    r = h.cmd(1, "C PN0QQ")
    assert r is not None and r[1] in (0, 1), r
    f = probe.wait(lambda f: f.dst == "PN0QQ" and f.type == "SABM", 10, t)
    assert f is not None, "no SABM after a host-mode connect on channel 1"
    h.cmd(1, "D")
