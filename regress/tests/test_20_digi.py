"""Digipeating and UI relaying (groups.io 4400: "beacon digi (unproto
request) is not relayed anymore" on 505o).

Probe A is on port 1 (DIGIFLAG left at its default, 7), probe B on port 2
(DIGIFLAG=771: UI, non-UI, UITRACE and UIFLOOD; PORTALIAS2=RELAY;
BCAST=MAIL,FBB). The probe's station is PN0TS. Each test sends a frame
and looks for XRouter's repeat of it: the same frame with XRouter's call
(or the alias it was sent via) marked as repeated.
"""

from __future__ import annotations

import time

import pytest

from ax25 import Frame, ui
from conftest import DUT_ALIAS, DUT_CALL

SRC = "PN0TS"


def repeated(probe, since, dst, info, timeout=8.0):
    """The first frame XRouter sends after `since` that carries our info to dst."""
    return probe.wait(lambda f: f.dst == dst and f.info == info and f.src == SRC, timeout, since)


def path(f: Frame) -> str:
    return ",".join(d + ("*" if h else "") for d, h in f.digis)


def test_ui_digipeat_via_nodecall(probe_a):
    info = b"digi via nodecall %d" % time.time()
    t = time.time()
    probe_a.send(ui("BEACON", SRC, info, digis=[DUT_CALL]))
    f = repeated(probe_a, t, "BEACON", info)
    assert f is not None, "UI frame sent via the node call was not digipeated on port 1"
    assert f.digis == [(DUT_CALL, True)], f"repeated with path {path(f)}"


def test_ui_digipeat_via_nodealias(probe_a):
    info = b"digi via alias %d" % time.time()
    t = time.time()
    probe_a.send(ui("BEACON", SRC, info, digis=[DUT_ALIAS]))
    f = repeated(probe_a, t, "BEACON", info)
    assert f is not None, "UI frame sent via the node alias was not digipeated on port 1"
    assert f.digis and f.digis[0][1], f"repeated with path {path(f)}"


def test_ui_digipeat_two_hops_first_is_us(probe_a):
    """A path of two digis with us first: repeated with us marked, the
    second digi still to go."""
    info = b"digi two hops %d" % time.time()
    t = time.time()
    probe_a.send(ui("BEACON", SRC, info, digis=[DUT_CALL, "PN0ZZ"]))
    f = repeated(probe_a, t, "BEACON", info)
    assert f is not None, "UI frame via node call then another digi was not digipeated"
    assert f.digis == [(DUT_CALL, True), ("PN0ZZ", False)], f"repeated with path {path(f)}"


def test_ui_not_digipeated_when_not_in_path(probe_a):
    info = b"no digi %d" % time.time()
    t = time.time()
    probe_a.send(ui("BEACON", SRC, info, digis=["PN0ZZ"]))
    assert repeated(probe_a, t, "BEACON", info, timeout=4) is None


def test_ui_digipeat_via_portalias2(probe_b):
    info = b"digi via RELAY %d" % time.time()
    t = time.time()
    probe_b.send(ui("BEACON", SRC, info, digis=["RELAY"]))
    f = repeated(probe_b, t, "BEACON", info)
    assert f is not None, "UI frame sent via PORTALIAS2 RELAY was not digipeated on port 2"
    assert f.digis and f.digis[0][1], f"repeated with path {path(f)}"


def test_ui_digipeat_via_nodecall_port2(probe_b):
    info = b"digi via nodecall p2 %d" % time.time()
    t = time.time()
    probe_b.send(ui("BEACON", SRC, info, digis=[DUT_CALL]))
    f = repeated(probe_b, t, "BEACON", info)
    assert f is not None, "UI frame sent via the node call was not digipeated on port 2"


def test_uiflood_wide2_2(probe_b):
    """UIFLOOD (DIGIFLAG 512, default alias WIDE): WIDE2-2 is repeated as WIDE2-1."""
    info = b"wide2-2 %d" % time.time()
    t = time.time()
    probe_b.send(ui("APRS", SRC, info, digis=["WIDE2-2"]))
    f = repeated(probe_b, t, "APRS", info)
    assert f is not None, "WIDE2-2 UI frame was not flood-digipeated on port 2"
    calls = [d for d, _ in f.digis]
    assert "WIDE2-1" in calls, f"repeated with path {path(f)}"


def test_uitrace_trace2_2(probe_b):
    """UITRACE (DIGIFLAG 256, default alias TRACE): our call is inserted and
    the SSID decremented."""
    info = b"trace2-2 %d" % time.time()
    t = time.time()
    probe_b.send(ui("APRS", SRC, info, digis=["TRACE2-2"]))
    f = repeated(probe_b, t, "APRS", info)
    assert f is not None, "TRACE2-2 UI frame was not trace-digipeated on port 2"
    calls = [d for d, _ in f.digis]
    assert DUT_CALL in calls and "TRACE2-1" in calls, f"repeated with path {path(f)}"


def test_uiflood_not_on_default_port(probe_a):
    """Port 1 has the default DIGIFLAG (7), which does not include UIFLOOD."""
    info = b"wide on p1 %d" % time.time()
    t = time.time()
    probe_a.send(ui("APRS", SRC, info, digis=["WIDE2-2"]))
    assert repeated(probe_a, t, "APRS", info, timeout=4) is None


def test_bcast_mail_beacon_relayed_to_port1(probe_a, probe_b):
    """BCAST: a UI frame to MAIL heard on port 2 (BCAST=MAIL,FBB) is re-sent on
    every port whose BCAST list has MAIL, here port 1. A BBS mail beacon."""
    info = b"mail for PN0XX %d" % time.time()
    t = time.time()
    probe_b.send(ui("MAIL", "PN0BBS", info))
    f = probe_a.wait(lambda f: f.dst == "MAIL" and f.info == info, 8, t)
    assert f is not None, "UI frame to MAIL on port 2 was not re-broadcast on port 1"


def test_bcast_fbb_beacon_rebroadcast_on_same_port(probe_b):
    """FBB is only in port 2's list, so it goes out again on port 2 alone
    (MAN BCAST: 'If no matching ports are found, the frame is broadcast only
    on the port upon which it is received')."""
    info = b"FBB beacon %d" % time.time()
    t = time.time()
    probe_b.send(ui("FBB", "PN0BBS", info))
    f = probe_b.wait(lambda f: f.dst == "FBB" and f.info == info and f.src == "PN0BBS", 8, t)
    assert f is not None, "UI frame to FBB on port 2 was not re-broadcast"


def test_bcast_not_relayed_from_port_without_list(probe_a, probe_b):
    """Port 1 has only MAIL in its list: FBB heard there goes nowhere."""
    info = b"fbb on p1 %d" % time.time()
    t = time.time()
    probe_a.send(ui("FBB", "PN0BBS", info))
    assert probe_b.wait(lambda f: f.info == info, 4, t) is None


def test_bcast_other_dest_not_relayed(probe_a, probe_b):
    info = b"not for bcast %d" % time.time()
    t = time.time()
    probe_b.send(ui("CQ", "PN0BBS", info))
    assert probe_a.wait(lambda f: f.info == info, 4, t) is None


def test_sabm_digipeated_via_nodecall(probe_a):
    """Non-UI digipeating (DIGIFLAG 2, in the default 7): a SABM to another
    station via the node is repeated."""
    t = time.time()
    f = Frame(dst="PN0XX", src=SRC, digis=[(DUT_CALL, False)], ctl=0x2F | 0x10, pid=None)
    probe_a.send(f)
    got = probe_a.wait(lambda g: g.dst == "PN0XX" and g.src == SRC and g.type == "SABM", 8, t)
    assert got is not None, "SABM via the node call was not digipeated"
    assert got.digis == [(DUT_CALL, True)], f"repeated with path {path(got)}"


def test_send_command_ui(dut, probe_a):
    """SEND <port> <dest> <text> transmits a UI frame (MAN SEND)."""
    t = time.time()
    out = dut.cmd("SEND 1 BEACON hello from send")
    f = probe_a.wait(lambda f: f.dst == "BEACON" and b"hello from send" in f.info, 8, t)
    assert f is not None, f"no UI frame after SEND; console said {out!r}"
    assert f.type == "UI"


def test_send_command_ui_via_digi(dut, probe_a):
    t = time.time()
    out = dut.cmd("SEND 1 BEACON V PN0ZZ,PN0YY hello via digis")
    f = probe_a.wait(lambda f: f.dst == "BEACON" and b"hello via digis" in f.info, 8, t)
    assert f is not None, f"no UI frame after SEND via digis; console said {out!r}"
    assert [d for d, _ in f.digis] == ["PN0ZZ", "PN0YY"], f"sent with path {path(f)}"


def test_id_beacon_sent(probe_a):
    """XRouter sends its IDTEXT as a UI frame to ID (IDINTERVAL); the first
    one comes soon after boot, so look back over everything heard."""
    f = probe_a.wait(lambda f: f.src == DUT_CALL and f.type == "UI" and f.dst == "ID", 120, 0)
    assert f is not None, "no ID beacon on port 1"
    assert b"regress test node" in f.info, f.info
