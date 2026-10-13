"""HTTP pages, the REST API, RHP and the AGW emulator.

The test process reaches the DUT through docker port mappings, so it
connects from the docker gateway (172.28.78.1, a LAN address): no auth is
needed for HTTP writes or RHP.
"""

from __future__ import annotations

import json
import re
import socket
import struct
import time
import urllib.error
import urllib.request

import pytest

from conftest import DUT_AGW, DUT_HTTP, DUT_RHP, HOST

BASE = f"http://{HOST}:{DUT_HTTP}"


def get(path: str, timeout: float = 10):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read().decode("latin-1")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read().decode("latin-1")


def post_json(path: str, body: dict):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("latin-1")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("latin-1")


# ---------------------------------------------------------------- HTTP pages

def test_http_root_summary(stack):
    st, ct, body = get("/")
    assert st == 200, (st, body[:300])
    assert re.search(r"<title>[^<]*DUT:PN0DUT[^<]*</title>", body, re.I), body[:500]


@pytest.mark.parametrize("page", ["/info", "/ports", "/links", "/routes", "/nodes", "/stats", "/users"])
def test_http_fullfat_page(stack, page):
    st, ct, body = get(page)
    assert st == 200, (st, body[:300])
    assert "html" in ct.lower(), ct


def test_http_404(stack):
    st, _, body = get("/no/such/page.htm")
    assert st == 404, (st, body[:200])


def test_http_exec_command(stack):
    st, _, body = get("/exec?cmd=v")
    assert st == 200 and re.search(r"v\s*50\d[a-z]", body), (st, body[:500])


# ---------------------------------------------------------------- REST

def test_rest_nodes(stack):
    st, ct, body = get("/api/v1/netrom/nodes")
    assert st == 200, (st, body[:300])
    nodes = json.loads(body)
    assert isinstance(nodes, list) and all({"id", "alias"} <= set(n) for n in nodes), body[:500]
    assert any(n["alias"] == "DUTAPP" for n in nodes), body[:500]


def test_rest_node_detail(stack):
    st, _, body = get("/api/v1/netrom/nodes/PN0DUT-1")
    assert st == 200, (st, body[:300])
    d = json.loads(body)
    assert d.get("alias") == "DUTAPP", d


def test_rest_routes(stack):
    st, _, body = get("/api/v1/netrom/routes")
    assert st == 200, (st, body[:300])
    assert isinstance(json.loads(body), list), body[:300]


def test_rest_circuits(stack):
    st, _, body = get("/api/v1/netrom/circuits")
    assert st == 200, (st, body[:300])
    assert isinstance(json.loads(body), list), body[:300]


def test_rest_unknown_is_404(stack):
    st, _, _ = get("/api/v1/nosuch")
    assert st == 404


def test_rest_mail_post_and_get(stack):
    st, body = post_json("/api/v1/mail/msgs", {"from": "PN0API", "to": "PN0DUT", "type": "P",
                                               "subject": "regress rest subject", "text": "rest body\n"})
    assert st in (200, 201), (st, body)
    mid = json.loads(body)["id"]
    st, _, body = get(f"/api/v1/mail/msgs/{mid}")
    assert st == 200, (st, body)
    msg = json.loads(body)
    assert msg.get("subject") == "regress rest subject" and "rest body" in msg.get("text", ""), msg
    st, _, body = get("/api/v1/mail/msgs")
    assert st == 200
    lst = json.loads(body)
    msgs = lst["msgs"] if isinstance(lst, dict) else lst
    assert any(str(m.get("id")) == str(mid) for m in msgs), f"posted id {mid!r} not listed: {body[:800]}"


def test_rest_mail_post_needs_json(stack):
    req = urllib.request.Request(BASE + "/api/v1/mail/msgs", data=b"x=1", method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        urllib.request.urlopen(req, timeout=10)
        code = 200
    except urllib.error.HTTPError as e:
        code = e.code
    assert code == 415, code


# ---------------------------------------------------------------- RHP

class Rhp:
    def __init__(self):
        self.sock = socket.create_connection((HOST, DUT_RHP), timeout=10)
        self.next_id = 1

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("RHP connection closed")
            buf += chunk
        return buf

    def recv(self):
        (n,) = struct.unpack(">H", self._recv_exact(2))
        raw = self._recv_exact(n).decode("latin-1")
        try:
            return json.loads(raw), raw
        except json.JSONDecodeError:
            return None, raw

    def request(self, msg):
        msg = {"id": self.next_id, **msg}
        self.next_id += 1
        body = json.dumps(msg, separators=(",", ":")).encode()
        self.sock.sendall(struct.pack(">H", len(body)) + body)
        return self.recv()

    def close(self):
        self.sock.close()


@pytest.fixture
def rhp(stack):
    r = Rhp()
    yield r
    r.close()


def test_rhp_socket_reply(rhp):
    reply, raw = rhp.request({"type": "socket", "pfam": "ax25", "mode": "stream"})
    assert reply and reply.get("type") == "socketReply" and reply.get("errCode") == 0, raw
    assert isinstance(reply.get("handle"), int), raw


def test_rhp_open_passive_listener(rhp):
    """RHP2 `open` with flags 0 is a listener on a local address."""
    reply, raw = rhp.request({"type": "open", "pfam": "ax25", "mode": "stream", "port": 1,
                              "local": "PN0DUT-9", "flags": 0})
    assert reply and reply.get("type") == "openReply" and reply.get("errCode") == 0, raw


def test_rhp_open_active_connect_and_close(rhp, probe_a):
    """An active `open` makes XRouter send a SABM on the port."""
    t = time.time()
    reply, raw = rhp.request({"type": "open", "pfam": "ax25", "mode": "stream", "port": 1,
                              "local": "PN0DUT-9", "remote": "PN0QQ", "flags": 128})
    assert reply and reply.get("errCode") == 0, raw
    f = probe_a.wait(lambda f: f.dst == "PN0QQ" and f.type == "SABM", 10, t)
    assert f is not None, "no SABM after RHP active open"
    h = reply["handle"]
    reply, raw = rhp.request({"type": "close", "handle": h})
    assert reply and reply.get("type") == "closeReply" and reply.get("handle") == h, raw


def test_rhp_bad_type(rhp):
    reply, raw = rhp.request({"type": "nosuch"})
    assert reply is not None and reply.get("errCode") == 2, raw


def test_rhp_bind_listen_reply(rhp):
    reply, raw = rhp.request({"type": "socket", "pfam": "ax25", "mode": "stream"})
    h = reply["handle"]
    reply, raw = rhp.request({"type": "bind", "handle": h, "local": "PN0DUT-7"})
    assert reply is not None, f"bind reply is not JSON: {raw}"
    assert reply.get("type") == "bindReply" and reply.get("errCode") == 0, raw
    reply, raw = rhp.request({"type": "listen", "handle": h, "flags": 0})
    assert reply and reply.get("type") == "listenReply" and reply.get("errCode") == 0, raw


def test_rhp_status_request(rhp):
    """505c answers a status request with a `status` message (seqno, handle,
    flags), not a statusReply."""
    reply, _ = rhp.request({"type": "socket", "pfam": "ax25", "mode": "stream"})
    h = reply["handle"]
    reply, raw = rhp.request({"type": "status", "handle": h})
    assert reply and reply.get("type") in ("status", "statusReply") and reply.get("handle") == h, raw
    assert "flags" in reply, raw


# ---------------------------------------------------------------- AGW

def agw_frame(kind: str, port: int = 0, call_from: str = "", call_to: str = "", data: bytes = b"") -> bytes:
    return (struct.pack("<B3xB3x", port, ord(kind)) + call_from.encode().ljust(10, b"\0")
            + call_to.encode().ljust(10, b"\0") + struct.pack("<II", len(data), 0) + data)


def agw_read(sock, timeout=5):
    sock.settimeout(timeout)
    hdr = b""
    while len(hdr) < 36:
        hdr += sock.recv(36 - len(hdr))
    n = struct.unpack("<I", hdr[28:32])[0]
    data = b""
    while len(data) < n:
        data += sock.recv(n - len(data))
    return chr(hdr[4]), data


def test_agw_version(stack):
    with socket.create_connection((HOST, DUT_AGW), timeout=5) as s:
        s.sendall(agw_frame("R"))
        kind, data = agw_read(s)
        assert kind == "R" and len(data) == 8, (kind, data)


def test_agw_port_info(stack):
    with socket.create_connection((HOST, DUT_AGW), timeout=5) as s:
        s.sendall(agw_frame("G"))
        kind, data = agw_read(s)
        assert kind == "G", kind
        text = data.decode("latin-1")
        assert text.split(";")[0].strip("\0").isdigit() and int(text.split(";")[0]) >= 3, text


def test_agw_send_ui(stack, probe_a):
    """'M' sends an unproto frame on a port (AGW port 0 is XRouter port 1)."""
    t = time.time()
    with socket.create_connection((HOST, DUT_AGW), timeout=5) as s:
        s.sendall(agw_frame("M", 0, "PN0AGW", "BEACON", b"agw hello"))
        time.sleep(2)
    f = probe_a.wait(lambda f: f.dst == "BEACON" and b"agw hello" in f.info, 8, t)
    assert f is not None, "no UI frame after AGW 'M'"
