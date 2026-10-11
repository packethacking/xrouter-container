"""XRouter's RHP (remote host protocol) API answers with well-formed replies.

RHP frames are JSON with a 2-byte big-endian length in front, on RHPPORT.
These checks only need XRouter, not the INP3 network. Error codes and texts
are deliberately not pinned: the author changed some on purpose in 505d
(LISTEN on a listening socket, SEND or SENDTO on a listener now answer 16,
"Operation not supported"). What every reply must still do is parse as JSON
and carry the socket handle it is about.
"""

from __future__ import annotations

import json
import os
import socket
import struct

import pytest

from conftest import HOST
from wire import wait_for

RHP_PORT = int(os.environ.get("XRI_XR_RHP", "17090"))


class Rhp:
    def __init__(self):
        self.sock = socket.create_connection((HOST, RHP_PORT), timeout=10)
        self.next_id = 1

    def close(self):
        self.sock.close()

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("RHP connection closed")
            buf += chunk
        return buf

    def request(self, msg: dict) -> tuple[dict | None, str]:
        """Send one request; return (parsed reply or None if not valid JSON, raw reply text)."""
        msg = {"id": self.next_id, **msg}
        self.next_id += 1
        body = json.dumps(msg, separators=(",", ":")).encode()
        self.sock.sendall(struct.pack(">H", len(body)) + body)
        (n,) = struct.unpack(">H", self._recv_exact(2))
        raw = self._recv_exact(n).decode("latin-1")
        try:
            return json.loads(raw), raw
        except json.JSONDecodeError:
            return None, raw

    def handle(self, mode: str = "stream") -> int:
        reply, raw = self.request({"type": "socket", "pfam": "ax25", "mode": mode})
        assert reply and reply.get("errCode") == 0, f"socket request failed: {raw}"
        return reply["handle"]


@pytest.fixture
def rhp(stack):
    def up():
        try:
            socket.create_connection((HOST, RHP_PORT), timeout=2).close()
            return True
        except OSError:
            return False

    assert wait_for(up, 30), f"XRouter RHP port {RHP_PORT} not open"
    c = Rhp()
    yield c
    c.close()


def test_rhp_bind_reply_is_valid_json(rhp):
    h = rhp.handle()
    reply, raw = rhp.request({"type": "bind", "handle": h, "local": "PN9TST-1"})
    assert reply is not None, f"bind reply is not valid JSON: {raw}"
    assert reply.get("type") == "bindReply", f"bind reply has the wrong type: {raw}"
    assert reply.get("errCode") == 0 and reply.get("errText") == "Ok", f"bind failed: {raw}"
    assert reply.get("handle") == h, f"bind reply does not carry handle {h}: {raw}"


def _listening_socket(rhp: Rhp, call: str) -> int:
    h = rhp.handle()
    rhp.request({"type": "bind", "handle": h, "local": call})  # reply checked by the bind test
    reply, raw = rhp.request({"type": "listen", "handle": h, "flags": 0})
    assert reply and reply.get("errCode") == 0, f"listen failed: {raw}"
    return h


def test_rhp_send_on_listener_reply_carries_handle(rhp):
    h = _listening_socket(rhp, "PN9TST-2")
    reply, raw = rhp.request({"type": "send", "handle": h, "data": "x"})
    assert reply is not None, f"send reply is not valid JSON: {raw}"
    assert reply.get("type") == "sendReply" and reply.get("errCode") != 0, f"expected a sendReply error: {raw}"
    assert reply.get("handle") == h, f"send reply does not carry handle {h}: {raw}"


def test_rhp_sendto_on_listener_reply_carries_handle(rhp):
    h = _listening_socket(rhp, "PN9TST-3")
    reply, raw = rhp.request({"type": "sendto", "handle": h, "data": "x", "remote": "PN9XYZ", "port": "1"})
    assert reply is not None, f"sendto reply is not valid JSON: {raw}"
    assert reply.get("type") == "sendtoReply" and reply.get("errCode") != 0, f"expected a sendtoReply error: {raw}"
    assert reply.get("handle") == h, f"sendto reply does not carry handle {h}: {raw}"
