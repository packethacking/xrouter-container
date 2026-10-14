#!/usr/bin/env python3
"""Stand-alone reproductions of the XRouter bugs found by regress/.

    regress/repro/start-node.sh ./xrlin64v505o-static   # fresh node from a published binary
    python3 regress/repro/repro.py 13                   # run one reproduction
    kill -9 $(cat xrrepro-node/xrouter.pid)             # stop it

Python 3.8+, standard library only. Each reproduction prints what it sends
and receives, then a verdict line:
    BUG PRESENT: ...   (exit 1)    or    NOT REPRODUCED: ...   (exit 0)
Start a fresh node before each one: some leave mail behind, and #12 hangs
the node.

   2  RHP bind reply is not valid JSON
   3  RHP send / sendto on a listening socket reply without the socket handle
   4  INPBCINTERVAL has no effect on full INP3 updates (takes ~5 minutes)
   5  the node advertises itself in INP3 with trip time 0
   6  scheduled NODES broadcasts go out on the first port only (takes ~3 minutes)
   7  the first INP3 RIP for a newly learnt node has no alias option
  11  AGW 'M' (unproto) from a client that has not registered a callsign is not sent
  12  an undecodable compressed (FA) BBS message hangs the whole node
  13  R n shows no body for a forwarded message with no blank line after its R: lines
  14  after a client sends an FBB SID, user commands get no answer at all
  22  FBB ASCII forwarding out (FB) ends the message with /EX instead of Ctrl-Z
  23  MBL forwarding out puts a NUL byte before /EX
"""

from __future__ import annotations

import re
import socket
import struct
import sys
import time

HOST = "127.0.0.1"
TELNET, AGW, UDP_SNIFF, UDP_SNIFF2, RHP = 8023, 8000, 9999, 9998, 9000
XR_UDP1, XR_UDP2 = 10093, 10094          # the node's UDPLOCAL for ports 1 and 2
NODECALL = "PN0RPR"
START = time.time()


class Telnet:
    """Line-mode telnet to XRouter: log in with a callsign, send lines, read."""

    def __init__(self, call: str):
        self.s = socket.create_connection((HOST, TELNET), timeout=5)
        self.s.settimeout(0.3)
        self.read(3, until=b"Callsign:")
        self.send(call)
        self.read(2)

    def send(self, line: str | bytes, end: bytes = b"\r") -> None:
        data = line.encode("latin-1") if isinstance(line, str) else line
        data = data.replace(b"\xff", b"\xff\xff")       # telnet IAC escaping
        print(f"  -> {data + end!r}")
        self.s.sendall(data + end)

    def read(self, quiet: float = 2.0, until: bytes | None = None, limit: float = 20.0) -> bytes:
        out, last, end = b"", time.time(), time.time() + limit
        while time.time() < end:
            try:
                d = self.s.recv(4096)
                if not d:
                    break
                out += d
                last = time.time()
                if until and until in out:
                    break
            except socket.timeout:
                if time.time() - last > quiet:
                    break
            except OSError:
                break
        out = re.sub(rb"\xff[\xfb-\xfe].", b"", out)      # drop option negotiation
        if out:
            print(f"  <- {out!r}")
        return out

    def connected(self) -> bool:
        try:
            self.s.settimeout(0.5)
            return self.s.recv(1, socket.MSG_PEEK) != b""
        except socket.timeout:
            return True
        except OSError:
            return False

    def close(self) -> None:
        self.s.close()


def bbs(call: str) -> Telnet:
    t = Telnet(call)
    t.send("BBS")
    t.read(2)
    return t


def checksum(lines: list[str]) -> str:
    """FBB proposal checksum: two's complement of the sum of the proposal bytes and CRs."""
    return f"{(-sum(sum(l.encode()) + 13 for l in lines)) & 0xFF:02X}"


def verdict(bug: bool, text: str) -> int:
    print(("BUG PRESENT: " if bug else "NOT REPRODUCED: ") + text)
    return 1 if bug else 0


# ---------------------------------------------------------------- 2, 3

class Rhp:
    """RHP: JSON requests, each with a 2-byte big-endian length in front."""

    def __init__(self):
        self.s = socket.create_connection((HOST, RHP), timeout=5)
        self.next_id = 1

    def request(self, msg: dict) -> tuple[dict | None, str]:
        import json
        msg = {"id": self.next_id, **msg}
        self.next_id += 1
        body = json.dumps(msg, separators=(",", ":")).encode()
        print(f"  -> {body.decode()}")
        self.s.sendall(struct.pack(">H", len(body)) + body)
        (n,) = struct.unpack(">H", self._exact(2))
        raw = self._exact(n).decode("latin-1")
        print(f"  <- {raw}")
        try:
            return json.loads(raw), raw
        except ValueError:
            return None, raw

    def _exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            d = self.s.recv(n - len(buf))
            if not d:
                raise ConnectionError("RHP connection closed")
            buf += d
        return buf


def repro_2() -> int:
    r = Rhp()
    sock, _ = r.request({"type": "socket", "pfam": "ax25", "mode": "stream"})
    reply, raw = r.request({"type": "bind", "handle": sock["handle"], "local": "PN0RPR-7"})
    if reply is None:
        return verdict(True, "the bind reply is not valid JSON")
    bug = reply.get("type") != "bindReply"
    return verdict(bug, f"bind reply has type {reply.get('type')!r}, not 'bindReply'" if bug else "valid bindReply")


def listening_socket(r: Rhp) -> int:
    sock, _ = r.request({"type": "socket", "pfam": "ax25", "mode": "stream"})
    h = sock["handle"]
    r.request({"type": "bind", "handle": h, "local": "PN0RPR-7"})
    r.request({"type": "listen", "handle": h, "flags": 0})
    return h


def repro_3() -> int:
    r = Rhp()
    h = listening_socket(r)
    send, _ = r.request({"type": "send", "handle": h, "data": "x"})
    sendto, _ = r.request({"type": "sendto", "handle": h, "data": "x", "remote": "PN0XX", "port": 1})
    missing = [n for n, rep in (("send", send), ("sendto", sendto)) if rep is None or rep.get("handle") != h]
    return verdict(bool(missing), f"{' and '.join(missing)} reply without handle {h}" if missing
                   else f"both replies carry handle {h}")


# ---------------------------------------------------------------- 4, 5, 7: INP3

def fcs16(data: bytes) -> int:
    """CRC-16/X.25, the AX.25 frame check sequence AXUDP carries."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def addr(call: str, last: bool = False, cmd: bool = False) -> bytes:
    base, _, ssid = call.partition("-")
    return (bytes(ord(c) << 1 for c in base.ljust(6)) +
            bytes([0x60 | int(ssid or 0) << 1 | last | (0x80 if cmd else 0)]))


def call_of(raw: bytes) -> str:
    base = "".join(chr(b >> 1) for b in raw[:6]).strip()
    ssid = raw[6] >> 1 & 0x0F
    return f"{base}-{ssid}" if ssid else base


def decode_rif(info: bytes) -> list[tuple[str, int, int, str | None]]:
    """A RIF (0xFF, then RIPs: call, hops, trip time, options, 0) as
    (call, hops, trip time, alias or None)."""
    rips, p = [], 1
    while p + 10 <= len(info):
        call, hops, tt = call_of(info[p:p + 7]), info[p + 7], int.from_bytes(info[p + 8:p + 10], "big")
        p += 10
        alias = None
        while p < len(info) and info[p] != 0:
            n, kind = info[p], info[p + 1]
            if kind == 0:
                alias = info[p + 2:p + n].decode("latin-1")
            p += n
        p += 1
        rips.append((call, hops, tt, alias))
    return rips


def show_rif(rips) -> str:
    return ", ".join(f"{a or ''}:{c} hops {h} tt {t}" for c, h, t, a in rips)


class Inp3Neighbour:
    """A fake INP3 neighbour on one of the node's AXUDP ports: it broadcasts
    NODES so the node opens a link to it, answers on that link (UA, RR),
    reflects the node's L3RTT probes, sends one L3RTT of its own and one RIF
    with its call and alias, and keeps every RIF the node sends it."""

    def __init__(self, call: str, alias: str, listen: int, node_port: int):
        import threading
        self.call, self.alias, self.peer = call, alias, (HOST, node_port)
        self.u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.u.bind((HOST, listen))
        self.u.settimeout(0.2)
        self.connected, self.vs, self.vr = False, 0, 0
        self.rifs: list[tuple[float, list]] = []
        threading.Thread(target=self._run, daemon=True).start()

    def _tx(self, ctl: int, pid: int | None = None, info: bytes = b"", dst: str = NODECALL, cmd: bool = True) -> None:
        body = addr(dst, cmd=cmd) + addr(self.call, last=True, cmd=not cmd) + bytes([ctl])
        if pid is not None:
            body += bytes([pid])
        body += info
        c = fcs16(body + b"")
        self.u.sendto(body + bytes([c & 0xFF, c >> 8]), self.peer)

    def send_i(self, info: bytes) -> None:
        self._tx(self.vs << 1 | self.vr << 5, 0xCF, info)
        self.vs = (self.vs + 1) & 7

    def broadcast_nodes(self) -> None:
        # One entry (our BBS at SSID 7): the node ignores a NODES with none.
        bbs = addr(f"{self.call}-7")[:6] + bytes([addr(f"{self.call}-7")[6] & 0x1E | 0x60])
        me = addr(self.call)[:6] + bytes([addr(self.call)[6] & 0x1E | 0x60])
        info = b"\xff" + self.alias.ljust(6).encode() + bbs + (self.alias[:5] + "B").ljust(6).encode() + me + bytes([200])
        self._tx(0x03, 0xCF, info, dst="NODES")

    def _netrom(self, info: bytes) -> None:
        if info[:1] == b"\xff":
            rips = decode_rif(info)
            self.rifs.append((time.time(), rips))
            print(f"  {time.time() - START:6.1f} s  {NODECALL} -> {self.call} RIF: {show_rif(rips)}")
        elif len(info) >= 20 and call_of(info[7:14]) == "L3RTT" and call_of(info[0:7]) != self.call:
            self.send_i(info[:14] + bytes([max(info[14] - 1, 0)]) + info[15:])     # reflect it

    def _say_hello(self) -> None:
        time.sleep(1)
        me = addr(self.call)[:6] + bytes([addr(self.call)[6] & 0x1E | 0x60])
        rtt = addr("L3RTT")[:6] + bytes([addr("L3RTT")[6] & 0x1E | 0x60])
        text = (f"L3RTT: {int(time.time() * 100) % 1000000:10d} {0:10d} {0:10d} {1:10d} "
                f"{self.alias:<6} LEVEL3_V2.1 REPRO01 $M9000 $N $H4\r").encode()
        self.send_i(me + rtt + bytes([2, 0, 0, 0, 0, 5]) + text)
        time.sleep(1)
        a = self.alias.encode()
        self.send_i(b"\xff" + me + bytes([1]) + (1).to_bytes(2, "big") + bytes([len(a) + 2, 0]) + a + b"\x00")

    def _run(self) -> None:
        import threading
        next_nodes = 0.0
        while True:
            if time.time() >= next_nodes:
                self.broadcast_nodes()
                next_nodes = time.time() + 30
            try:
                pkt, _ = self.u.recvfrom(4096)
            except socket.timeout:
                continue
            body = pkt[:-2]
            if len(body) < 15 or call_of(body[0:7]) != self.call:
                continue
            ctl = body[14]
            pf = ctl & 0x10
            if ctl & ~0x10 == 0x2F:                                   # SABM
                self.connected, self.vs, self.vr = True, 0, 0
                self._tx(0x63 | pf, cmd=False)                        # UA
                threading.Thread(target=self._say_hello, daemon=True).start()
            elif ctl & ~0x10 == 0x43:                                 # DISC
                self.connected = False
                self._tx(0x63 | pf, cmd=False)
            elif ctl & ~0x10 == 0xAF:                                 # XID: not supported
                self._tx(0x87 | pf, info=bytes([ctl, 0, 0]), cmd=False)
            elif ctl & 1 == 0:                                        # I frame
                if (ctl >> 1 & 7) == self.vr:
                    self.vr = (self.vr + 1) & 7
                    if body[15] == 0xCF:
                        self._netrom(body[16:])
                self._tx(0x01 | self.vr << 5 | pf, cmd=False)         # RR
            elif ctl & 3 == 1 and pf and body[6] & 0x80:              # RR/RNR/REJ poll
                self._tx(0x01 | self.vr << 5 | 0x10, cmd=False)


def wait_for(cond, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.5)
    return False


def repro_5() -> int:
    """Trip time of the node's own RIP in the first RIF it sends."""
    nb = Inp3Neighbour("PN0NBA", "NBA", UDP_SNIFF, XR_UDP1)
    print(f"Fake INP3 neighbour PN0NBA on port 1; waiting for {NODECALL}'s first RIF ...")
    if not wait_for(lambda: nb.rifs, 120):
        return verdict(False, "no RIF from the node in 120 s (not taken as an INP3 neighbour)")
    own = [r for r in nb.rifs[0][1] if r[0] == NODECALL]
    if not own:
        return verdict(False, f"the first RIF has no RIP for {NODECALL}")
    tt = own[0][2]
    return verdict(tt == 0, f"{NODECALL} advertises itself with trip time 0 (range is 1-60000)" if tt == 0
                   else f"{NODECALL} advertises itself with trip time {tt}")


def repro_4() -> int:
    """Full updates (RIFs that include the node itself) with INPBCINTERVAL=120."""
    nb = Inp3Neighbour("PN0NBA", "NBA", UDP_SNIFF, XR_UDP1)
    print(f"Fake INP3 neighbour PN0NBA on port 1. XROUTER.CFG has INPBCINTERVAL=120.")
    print(f"Watching for 300 s after the first RIF for full updates (RIFs that include {NODECALL}) ...")
    if not wait_for(lambda: nb.rifs, 120):
        return verdict(False, "no RIF from the node in 120 s (not taken as an INP3 neighbour)")
    first = nb.rifs[0][0]
    time.sleep(max(0.0, first + 300 - time.time()))
    full = [round(t - first) for t, rips in nb.rifs if any(r[0] == NODECALL for r in rips)]
    print(f"  full updates at (s after the first RIF): {full}")
    t = Telnet("PN0USR")
    t.send("N BC T")
    t.read(2)
    t.close()
    later = [s for s in full if s >= 30]
    bug = not later
    return verdict(bug, "no full update within 300 s, although INPBCINTERVAL=120" if bug
                   else f"full updates after set-up at {later} s")


def repro_7() -> int:
    """Two fake INP3 neighbours: B's link is up and settled, then A appears.
    The first positive RIP (trip time below 60000) for A that the node sends
    B should carry A's alias."""
    b = Inp3Neighbour("PN0NBB", "NBB", UDP_SNIFF, XR_UDP1)
    print("Fake INP3 neighbour PN0NBB (alias NBB) on port 1; waiting for its link and first RIF ...")
    if not wait_for(lambda: b.rifs, 120):
        return verdict(False, "no RIF to PN0NBB in 120 s (not taken as an INP3 neighbour)")
    time.sleep(20)
    print("Now fake INP3 neighbour PN0NBA (alias NBA) on port 2 ...")
    mark = len(b.rifs)
    a = Inp3Neighbour("PN0NBA", "NBA", UDP_SNIFF2, XR_UDP2)
    about_a = lambda: [r for _, rips in b.rifs[mark:] for r in rips if r[0] == "PN0NBA" and r[2] < 60000]  # noqa: E731
    if not wait_for(about_a, 120):
        return verdict(False, "no positive RIP for PN0NBA sent to PN0NBB in 120 s")
    rip = about_a()[0]
    print(f"  first positive RIP for PN0NBA sent to PN0NBB: {show_rif([rip])}")
    bug = rip[3] is None
    return verdict(bug, "the first positive RIP for PN0NBA sent to PN0NBB has no alias option" if bug
                   else f"the first positive RIP for PN0NBA carries alias {rip[3]}")


# ---------------------------------------------------------------- 6

def repro_6() -> int:
    """Every port gets a NODES broadcast at start-up; with NODESINTERVAL=1
    the scheduled ones should follow on both ports about every minute."""
    socks = {}
    for name, port in (("port 1", UDP_SNIFF), ("port 2", UDP_SNIFF2)):
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.bind((HOST, port))
        u.settimeout(0.2)
        socks[name] = u
    counts = {name: 0 for name in socks}
    print("Counting NODES broadcasts (UI frames to NODES) on each port for 180 s ...")
    end = time.time() + 180
    nodes_dest = bytes(c << 1 for c in b"NODES ")          # AX.25 address field of NODES
    while time.time() < end:
        for name, u in socks.items():
            try:
                pkt, _ = u.recvfrom(2048)
            except socket.timeout:
                continue
            if pkt[:6] == nodes_dest:
                counts[name] += 1
                print(f"  {time.strftime('%H:%M:%S')} NODES on {name}")
    print(f"  totals: {counts}")
    bug = counts["port 1"] >= 2 and counts["port 2"] == 0
    return verdict(bug, "scheduled NODES broadcasts went out on port 1 only" if bug else
                   f"counts {counts}")


# ---------------------------------------------------------------- 11

def agw_frame(kind: str, port: int = 0, frm: str = "", to: str = "", data: bytes = b"") -> bytes:
    return (struct.pack("<B3xBxBx", port, ord(kind), 0xF0) + frm.encode().ljust(10, b"\0")
            + to.encode().ljust(10, b"\0") + struct.pack("<II", len(data), 0) + data)


def heard_on_air(sniff: socket.socket, text: bytes, seconds: float = 4) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        try:
            pkt, _ = sniff.recvfrom(2048)
        except socket.timeout:
            continue
        if text in pkt:
            print(f"  air: {pkt!r}")
            return True
    return False


def repro_11() -> int:
    sniff = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sniff.bind((HOST, UDP_SNIFF))
    sniff.settimeout(0.5)
    print("Client 1: no X (register) frame, just M (send unproto) on AGW port 0")
    with socket.create_connection((HOST, AGW), timeout=5) as a:
        a.sendall(agw_frame("M", 0, "PN0AGW", "BEACON", b"unregistered hello"))
        unreg = heard_on_air(sniff, b"unregistered hello")
    print(f"  transmitted: {unreg}")
    print("Client 2 (control): X to register PN0AGX, then the same M")
    with socket.create_connection((HOST, AGW), timeout=5) as a:
        a.sendall(agw_frame("X", 0, "PN0AGX"))
        time.sleep(0.5)
        a.sendall(agw_frame("M", 0, "PN0AGX", "BEACON", b"registered hello"))
        reg = heard_on_air(sniff, b"registered hello")
    print(f"  transmitted: {reg}")
    return verdict(reg and not unreg,
                   "unproto from an unregistered AGW client is dropped; the same after X is sent"
                   if reg and not unreg else f"unregistered sent={unreg}, registered sent={reg}")


# ---------------------------------------------------------------- 12

def node_answers() -> bool:
    try:
        with socket.create_connection((HOST, TELNET), timeout=5) as s:
            s.settimeout(5)
            return b"Callsign" in s.recv(200)
    except OSError:
        return False


def repro_12() -> int:
    print("Node answers telnet before:", node_answers())
    t = bbs("PN0FWD")
    t.send("[TST-1.0-BFHM$]")
    t.read(2)
    prop = ["FA P PN0FWD PN0RPR PN0USR 1201_PN0FWD 2000"]
    t.send(prop[0])
    t.send("F> " + checksum(prop))
    if b"FS +" not in t.read(3):
        return verdict(False, "the BBS did not accept the FA proposal (needs 505o or later)")
    # One message, FBB block framing: SOH header, STX data blocks, EOT checksum.
    # The data is not a valid LZHUF stream; the block checksum is correct.
    junk = bytes(i % 255 for i in range(512))
    title = b"bad data\0     0\0"
    raw = b"\x01" + bytes([len(title)]) + title
    for i in range(0, len(junk), 250):
        blk = junk[i:i + 250]
        raw += b"\x02" + bytes([len(blk)]) + blk
    raw += b"\x04" + bytes([(-sum(junk)) & 0xFF])
    t.send(raw, end=b"")
    t.read(5)
    time.sleep(3)
    alive = node_answers()
    print("Node answers telnet after:", alive)
    return verdict(not alive, "the node stopped answering after undecodable compressed data "
                              "(kill it and start a fresh one)" if not alive else "node still answers")


# ---------------------------------------------------------------- 13

def repro_13() -> int:
    print("PN0FWD forwards a message to PN0USR by MBL (S command), R: line straight into the body")
    t = bbs("PN0FWD")
    t.send("[TST-1.0-HM$]")
    t.read(2)
    t.send("SP PN0USR < PN0FWD $1301_PN0FWD")
    t.read(2)
    t.send("forwarded subject")
    t.read(2)
    t.send("R:261014/1200Z @:PN0FWD #:1 [Test] $:1301_PN0FWD\rthe body line\r/EX")
    t.read(3)
    t.close()
    print("PN0USR reads it")
    u = bbs("PN0USR")
    u.send("L")
    lst = u.read(2)
    m = re.search(rb"^\s*(\d+)\s.*forwarded subject", lst, re.M)
    if not m:
        return verdict(False, "the forwarded message did not arrive")
    n = m.group(1).decode()
    u.send(f"R {n}")
    plain = u.read(2)
    u.send(f"RH {n}")
    full = u.read(2)
    bug = b"the body line" not in plain and b"the body line" in full
    return verdict(bug, f"R {n} shows no body; RH {n} shows it" if bug else
                   f"R {n} shows the body" if b"the body line" in plain else "unexpected output")


# ---------------------------------------------------------------- 14

def repro_14() -> int:
    t = bbs("PN0USR")
    t.send("[TSTHOST-1.43-B1FHM$]")
    t.read(3)
    t.send("L")
    out = t.read(6)
    up = t.connected()
    bug = not out.strip() and up
    return verdict(bug, "no answer at all to L after an FBB SID, link left up" if bug else
                   f"the BBS answered: {out[:60]!r}" if out.strip() else "the BBS disconnected")


# ---------------------------------------------------------------- 22, 23

def leave_mail_for_partner() -> None:
    print("PN0USR leaves mail @PN0FWD (DISTRIB.SYS queues it for partner PN0FWD)")
    u = bbs("PN0USR")
    u.send("SP PN0BOB @ PN0FWD")
    u.read(2)
    u.send("partner subject")
    u.read(2)
    u.send("the body line")
    u.send("/EX")
    u.read(3)
    u.close()


def repro_22() -> int:
    leave_mail_for_partner()
    print("PN0FWD collects it by FBB, ASCII (no B in its SID)")
    t = bbs("PN0FWD")
    t.send("[TST-1.0-FHM$]")
    t.read(2)
    t.send("FF")
    out = t.read(3)
    if b"FB P" not in out:
        return verdict(False, "no FB proposal (needs 505o or later)")
    t.send("FS +")
    msg = t.read(4)
    bug = b"the body line" in msg and b"\x1a" not in msg and b"/EX" in msg
    return verdict(bug, "the FBB ASCII message ends with /EX, not Ctrl-Z" if bug else
                   "ends with Ctrl-Z" if b"\x1a" in msg else "unexpected output")


def repro_23() -> int:
    leave_mail_for_partner()
    print("PN0FWD collects it by MBL (no F in its SID), F> asks the BBS to send")
    t = bbs("PN0FWD")
    t.send("[TST-1.0-HM$]")
    t.read(2)
    t.send("F>")
    if not t.read(3).strip().startswith(b"SP "):
        return verdict(False, "no SP command from the BBS")
    t.send("OK")
    msg = t.read(4)
    bug = b"\x00" in msg
    return verdict(bug, "NUL byte in the forwarded text" if bug else "no NUL byte")


def main() -> int:
    repros = {"2": repro_2, "3": repro_3, "4": repro_4, "5": repro_5, "6": repro_6, "7": repro_7, "11": repro_11, "12": repro_12, "13": repro_13, "14": repro_14, "22": repro_22, "23": repro_23}
    if len(sys.argv) != 2 or sys.argv[1] not in repros:
        print(__doc__)
        return 2
    return repros[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
