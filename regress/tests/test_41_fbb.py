"""FBB forwarding protocol at the BBS (groups.io 4385, 4400: 505o's BBS does
compressed forwarding with tsthost, but "msg retrieval does not work
correctly after asking for the msg nr by tsthost the bbs disconnects").

505o's SID is [XR-505o-BFHM$]: FBB protocol (F) and compressed forwarding
(B, i.e. B0). 505c's was [XR-505c-HM$]. The forwarding tests are skipped on
a version whose SID has no F. Each test uses a fresh throwaway BBS node
(fixture fbbnode), since one of them can hang XRouter.

The LZHUF codec (lzhuf.py) is byte-exact with LinFBB's lzhuf.c.
"""

from __future__ import annotations

import re
import socket
import time

import pytest

from ax25 import L2Session
from conftest import FBB_TELNET, HOST, dexec
from lzhuf import b1_wrap, encode, fbb_blocks, fbb_text

PMSCALL = "PN0DUT-2"
PARTNER = "PN0FWD"


def checksum(lines: list[str]) -> str:
    s = sum(sum(l.encode()) + 13 for l in lines)
    return f"{(-s) & 0xFF:02X}"


def connect(probe, call=PARTNER):
    s = L2Session(probe, call, PMSCALL)
    assert s.connect(), f"no UA from {PMSCALL}"
    greeting = s.read(2.5, 10)
    m = re.search(r"\[([^\]]+)\]", greeting)
    return s, (m.group(1) if m else ""), greeting


def needs_fbb(sid: str) -> None:
    flags = sid.rsplit("-", 1)[-1]
    if "F" not in flags:
        pytest.skip(f"BBS SID [{sid}] has no F: no FBB forwarding in this version")


def node_alive(timeout: float = 5) -> bool:
    try:
        with socket.create_connection((HOST, FBB_TELNET), timeout=timeout) as c:
            c.settimeout(timeout)
            return bool(c.recv(100))
    except OSError:
        return False


def propose(s, kind: str, mid: str, size: int, to: str = "PN0DUT") -> str:
    prop = [f"{kind} P {PARTNER} PN0DUT {to} {mid} {size}"]
    s.line(prop[0])
    s.line("F> " + checksum(prop))
    return s.read(3, 10)


def list_as_sysop(text: str) -> str:
    from conftest import SYSOP_PASSWORD
    from xrconsole import XRConsole
    c = XRConsole(HOST, FBB_TELNET, "PN0TST", name="fbb-sysop")
    try:
        c.sysop(SYSOP_PASSWORD)
        c.cmd("BBS", 2)
        return c.cmd(text, 2)
    finally:
        c.close()


def test_bbs_sid(fbbnode):
    s, sid, greeting = connect(fbbnode)
    s.disconnect()
    assert re.match(r"XR-50\d[a-z]-[A-Z0-9]*\$$", sid), greeting


def test_fbb_ascii_forward_in(fbbnode):
    s, sid, _ = connect(fbbnode)
    needs_fbb(sid)
    s.line("[TST-1.0-FHM$]")
    s.read(2, 5)
    assert propose(s, "FB", "5001_PN0FWD", 40).strip() == "FS +"
    s.send("fbb ascii subject\rfbb ascii body\r\x1a\r")
    assert "FF" in s.read(3, 10)
    s.line("FF")
    assert "FQ" in s.read(3, 10)
    out = list_as_sysop("L")
    assert "fbb ascii subject" in out, out


def test_fbb_compressed_b0_forward_in(fbbnode):
    s, sid, _ = connect(fbbnode)
    needs_fbb(sid)
    if "B" not in sid.rsplit("-", 1)[-1]:
        pytest.skip("no B in the BBS SID")
    s.line("[TST-1.0-BFHM$]")
    s.read(2, 5)
    text = fbb_text(b"R:261013/1900Z @:PN0FWD #:1 [Test] $:5002_PN0FWD\ncompressed body line\n")
    assert propose(s, "FA", "5002_PN0FWD", len(text)).strip() == "FS +"
    s.send(fbb_blocks("fbb compressed subject", encode(text)))
    assert "FF" in s.read(4, 10)
    s.line("FF")
    assert "FQ" in s.read(3, 10)
    out = list_as_sysop("L")
    assert "fbb compressed subject" in out, out
    n = re.search(r"^\s*(\d+)\s.*fbb compressed subject", out, re.M).group(1)
    out = list_as_sysop(f"RH {n}")
    assert "compressed body line" in out, f"compressed message stored without its text:\n{out}"


@pytest.mark.parametrize("payload", ["b1-after-b0", "junk"])
def test_fbb_bad_compressed_data_does_not_hang_node(fbbnode, payload):
    """Undecodable compressed data (block checksum correct) must be rejected,
    FBB style with a disconnect, and the node must stay alive."""
    s, sid, _ = connect(fbbnode)
    needs_fbb(sid)
    s.line("[TST-1.0-BFHM$]")
    s.read(2, 5)
    # Long enough that a misread length field (B1's CRC taken as length
    # bytes, or junk) is many megabytes.
    text = fbb_text(b"bad data test line\n" * 60)
    data = b1_wrap(encode(text)) if payload == "b1-after-b0" else bytes(range(256)) * 2
    assert propose(s, "FA", "5003_PN0FWD", len(text)).strip() == "FS +"
    s.send(fbb_blocks("bad data subject", data))
    s.read(5, 10)
    cpu = dexec("xrr-fbb", "ps -o stat=,pcpu= -C xrouter").stdout.strip()
    alive = node_alive()
    s.abort()
    assert alive, f"node stopped answering telnet after undecodable compressed data (xrouter: {cpu})"


def test_user_command_after_fbb_sid_gets_an_answer(fbbnode):
    """A client that sends an FBB SID and then a user command (R 1) gets some
    answer: 505c disconnects; silence leaves the client hanging."""
    s, sid, _ = connect(fbbnode, "PN0SID")
    s.line("[TSTHOST-1.43-B1FHM$]")
    s.read(2, 5)
    s.line("R 1")
    out = s.read(5, 10)
    state = s.state
    s.disconnect()
    assert out.strip() or state != "connected", "no answer at all to 'R 1' after an FBB SID"


def forward_fb(s, mid: str, subject: str, body: str) -> None:
    s.line("[TST-1.0-FHM$]")
    s.read(2, 5)
    assert propose(s, "FB", mid, len(body)).strip() == "FS +"
    s.send(subject + "\r" + body.replace("\n", "\r") + "\x1a\r")
    assert "FF" in s.read(3, 10)
    s.line("FF")
    s.read(3, 10)


@pytest.mark.parametrize("how", ["ascii", "compressed"])
def test_read_forwarded_message_shows_body(fbbnode, how):
    """R n (read without routing headers) of a forwarded message whose R:
    lines run straight into the body, as FBB messages do, shows the body."""
    s, sid, _ = connect(fbbnode)
    needs_fbb(sid)
    body = "R:261013/1900Z @:PN0FWD #:1 [Test] $:5300_PN0FWD\nforwarded body line\n"
    if how == "ascii":
        forward_fb(s, "5300_PN0FWD", "read test subject", body)
    else:
        s.line("[TST-1.0-BFHM$]")
        s.read(2, 5)
        text = fbb_text(body.encode())
        assert propose(s, "FA", "5300_PN0FWD", len(text)).strip() == "FS +"
        s.send(fbb_blocks("read test subject", encode(text)))
        assert "FF" in s.read(4, 10)
        s.line("FF")
        s.read(3, 10)
    s.disconnect()
    out = list_as_sysop("R 1")
    assert "forwarded body line" in out, f"R 1 shows no body:\n{out}"


def test_read_mbl_forwarded_message_shows_body(fbbnode):
    """The same with MBL/RLI forwarding (SID without F, S command), which
    505c also supports."""
    s, _, _ = connect(fbbnode)
    s.line("[TST-1.0-HM$]")
    s.read(2, 5)
    s.line("SP PN0DUT < PN0FWD $5301_PN0FWD")
    s.read(2, 5)
    s.line("mbl read subject")
    s.read(2, 5)
    s.send("R:261013/1900Z @:PN0FWD #:1 [Test] $:5301_PN0FWD\rmbl body line\r/EX\r")
    s.read(3, 10)
    s.disconnect()
    out = list_as_sysop("R 1")
    assert "mbl body line" in out, f"R 1 shows no body:\n{out}"


# ---------------------------------------------------------------- reverse forwarding

def queue_mail_for_partner(probe) -> None:
    """A user leaves personal mail @PN0FWD; DISTRIB.SYS (fbb_config_dir)
    queues it for the partner PN0FWD."""
    u = L2Session(probe, "PN0USR", PMSCALL)
    assert u.connect()
    u.read(2.5, 10)
    u.line("SP PN0BOB @ PN0FWD")
    u.read(2, 5)
    u.line("rev subject")
    u.read(2, 5)
    u.line("reverse body line")
    u.line("/EX")
    out = u.read(3, 10)
    assert "saved" in out, out
    u.disconnect()


def test_fbb_reverse_forward_compressed(fbbnode):
    """The partner sends FF; the BBS proposes the queued mail as FA (B0) and
    sends it compressed. The text decodes and carries the body."""
    from lzhuf import decode, parse_fbb_blocks
    queue_mail_for_partner(fbbnode)
    s, sid, _ = connect(fbbnode)
    needs_fbb(sid)
    s.line("[TST-1.0-BFHM$]")
    s.read(2, 5)
    s.line("FF")
    out = s.read(4, 10)
    props = [l for l in out.splitlines() if l.startswith(("FA", "FB"))]
    assert props and props[0].startswith("FA P PN0USR PN0FWD PN0BOB "), f"no FA proposal after FF:\n{out}"
    s.line("FS +")
    raw = s.read_raw(5, 15)
    title, offset, payload, ok = parse_fbb_blocks(raw)
    assert ok and title == "rev subject", (title, ok, raw[:80])
    text = decode(payload)
    assert b"reverse body line" in text, text
    s.line("FF")
    assert "FQ" in s.read(3, 10)


def test_fbb_reverse_forward_ascii_ends_with_ctrl_z(fbbnode):
    """Without B in the partner's SID the BBS proposes FB and sends plain text,
    which in the FBB protocol ends with Ctrl-Z (as the BBS itself expects on
    receipt), not /EX."""
    queue_mail_for_partner(fbbnode)
    s, sid, _ = connect(fbbnode)
    needs_fbb(sid)
    s.line("[TST-1.0-FHM$]")
    s.read(2, 5)
    s.line("FF")
    out = s.read(4, 10)
    assert any(l.startswith("FB P PN0USR PN0FWD PN0BOB ") for l in out.splitlines()), out
    s.line("FS +")
    raw = s.read_raw(5, 15)
    s.disconnect()
    assert b"reverse body line" in raw, raw
    assert b"\x1a" in raw, f"FBB ASCII message not ended with Ctrl-Z: {raw[-60:]!r}"


def test_mbl_reverse_forward(fbbnode):
    """MBL/RLI reverse forwarding (SID without F, partner sends F>): the BBS
    sends an S command, then the message, ending /EX, with no stray bytes."""
    queue_mail_for_partner(fbbnode)
    s, _, _ = connect(fbbnode)
    s.line("[TST-1.0-HM$]")
    s.read(2, 5)
    s.line("F>")
    out = s.read(4, 10)
    assert out.strip().startswith("SP PN0BOB @ PN0FWD < PN0USR $"), out
    s.line("OK")
    msg = s.read_raw(4, 15)
    s.disconnect()
    assert b"reverse body line" in msg and msg.rstrip().endswith(b"/EX"), msg
    assert b"\x00" not in msg, f"NUL byte in the forwarded text: {msg!r}"


def test_fbb_reverse_forward_bulletin(fbbnode):
    """A bulletin @WW is queued for the partner (DISTRIB.SYS `B * WW PN0FWD`)
    and proposed as FA B ... WW <category>. Categories are cut to 6 chars."""
    u = L2Session(fbbnode, "PN0USR", PMSCALL)
    assert u.connect()
    u.read(2.5, 10)
    u.line("SB FWDTEST @ WW")
    u.read(2, 5)
    u.line("bulletin subject")
    u.read(2, 5)
    u.line("bulletin body")
    u.line("/EX")
    assert "saved" in u.read(3, 10)
    u.disconnect()
    s, sid, _ = connect(fbbnode)
    needs_fbb(sid)
    s.line("[TST-1.0-BFHM$]")
    s.read(2, 5)
    s.line("FF")
    out = s.read(4, 10)
    s.disconnect()
    assert re.search(r"^FA B PN0USR WW FWDTES \S+ \d+", out, re.M), out
