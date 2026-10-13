"""XRouter's WA8DED host-mode emulation (MAN DEDHOST), which serves an
application (APPL 2 here) over a serial line.

As 505c implements it, a connect on channel 1 lands in the node's own
command shell ("CONNECTED to PN0DUT"), from which the application issues
node commands, including C to go further. Channel 0 is unproto, as on a
real WA8DED TNC.

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


def wait_reply(h, ch, code, timeout=10.0):
    """Poll channel ch with G until a frame with this code arrives."""
    end = time.time() + timeout
    got = []
    while time.time() < end:
        r = h.cmd(ch, "G")
        if r is None:
            continue
        got.append(r)
        if r[1] == code:
            return r, got
        if r[1] == 0:
            time.sleep(0.3)
    return None, got


def test_dedhost_status(host):
    h, _ = host
    r = h.cmd(1, "L")
    assert r is not None and r[1] == 1 and len(r[2].split()) >= 5, f"no channel status from L: {r!r}"


def test_dedhost_unproto_beacon(host):
    """Channel 0: C sets the unproto destination; info on channel 0 goes out
    as a UI frame. This is how host-mode programs send beacons."""
    h, probe = host
    h.cmd(0, "I PN0DED")
    r = h.cmd(0, "C BEACON")
    assert r is not None and r[1] in (0, 1), r
    t = time.time()
    h.info(0, b"ded beacon text\r")
    f = probe.wait(lambda f: f.dst == "BEACON" and b"ded beacon text" in f.info, 10, t)
    assert f is not None, "no UI frame after a host-mode unproto send"


def test_dedhost_connect_reaches_node(host):
    h, _ = host
    r = h.cmd(1, "C PN0QQ")
    assert r is not None and r[1] == 0, r
    r, got = wait_reply(h, 1, 3)
    assert r is not None and b"CONNECTED to PN0DUT" in r[2], got


def test_dedhost_node_command(host):
    h, _ = host
    h.info(1, b"P\r")
    out = b""
    end = time.time() + 10
    while time.time() < end and b"Probe A" not in out:
        r = h.cmd(1, "G")
        if r and r[1] == 7:
            out += r[2]
        elif not r or r[1] == 0:
            time.sleep(0.3)
    assert b"Probe A" in out, out


def test_dedhost_connect_onward_sends_sabm(host):
    h, probe = host
    t = time.time()
    h.info(1, b"C 1 PN0QQ\r")
    f = probe.wait(lambda f: f.dst == "PN0QQ" and f.type == "SABM", 10, t)
    assert f is not None, "no SABM after C from the host-mode session"
    h.cmd(1, "D")
