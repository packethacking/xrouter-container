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
TELNET, AGW, UDP_SNIFF = 8023, 8000, 9999


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
    repros = {"11": repro_11, "12": repro_12, "13": repro_13, "14": repro_14, "22": repro_22, "23": repro_23}
    if len(sys.argv) != 2 or sys.argv[1] not in repros:
        print(__doc__)
        return 2
    return repros[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
