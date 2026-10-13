"""NET/ROM basics: NODES broadcasts, the neighbour link, L4 circuits.

The INP3 details are interop/'s job; these check the everyday things a user
of the DUT relies on, against the neighbour XRouter PN0NB on port 3.
"""

from __future__ import annotations

import re
import time

import pytest

from conftest import DUT_CALL, NBR_CALL
from fakenode import nodes_broadcast
from ax25 import ui


def nodes_from(probe, since=0.0):
    return probe.received(since, lambda f: f.dst == "NODES" and f.src == DUT_CALL and f.pid == 0xCF
                          and f.info[:1] == b"\xff")


def entries(info: bytes):
    out = []
    body = info[7:]
    while len(body) >= 21:
        e = body[:21]
        body = body[21:]
        call = "".join(chr(b >> 1) for b in e[:6]).strip()
        ssid = (e[6] >> 1) & 0x0F
        out.append((f"{call}-{ssid}" if ssid else call, e[7:13].decode("latin-1").strip(), e[20]))
    return out


def test_dut_broadcasts_nodes_on_port1(probe_a):
    end = time.time() + 90
    got = []
    while time.time() < end and not got:
        got = nodes_from(probe_a)
        time.sleep(1)
    assert got, "no NODES broadcast from the DUT on port 1 in 90 s"
    f = got[-1]
    assert f.info[1:7].decode().strip() == "DUT", f.info[1:7]
    names = {alias for _, alias, _ in entries(f.info)}
    assert {"DUTAPP", "DUTPMS", "DUTCHT"} <= names, entries(f.info)


def test_dut_broadcasts_nodes_on_port2(probe_b):
    """Known: XRouter's scheduled NODES go only on its first port (interop finding 6)."""
    end = time.time() + 90
    got = []
    while time.time() < end and not got:
        got = probe_b.received(0, lambda f: f.dst == "NODES" and f.src == DUT_CALL)
        time.sleep(1)
    assert got, "no NODES broadcast from the DUT on port 2 in 90 s"


def test_dut_learns_node_from_broadcast(probe_b, dut):
    """A NODES broadcast heard on port 2 gives a route to the sender with its
    nodes (R), and the nodes are known (N <call>). Plain N does not list them
    until the route has opened, and nothing answers the DUT's SABMs here."""
    info = nodes_broadcast("BBSNOD", [("PN0FAR", "FARNOD", "PN0BX", 200)])
    for _ in range(2):
        probe_b.send(ui("NODES", "PN0BX", info, pid=0xCF))
        time.sleep(1)
    out = dut.cmd("R", 1.5)
    assert re.search(r"2\s+PN0BX\s+150\s+2", out), out
    out = dut.cmd("N PN0FAR", 1.5)
    assert re.search(r"FARNOD:PN0FAR", out) and "PN0BX" in out, out


def test_dut_ignores_empty_nodes_broadcast(probe_b, dut):
    """Both 505c and 505o ignore a NODES broadcast with no entries (a lone
    node's): the sender gets no route."""
    for _ in range(2):
        probe_b.send(ui("NODES", "PN0BY", nodes_broadcast("LONE"), pid=0xCF))
        time.sleep(1)
    out = dut.cmd("R", 1.5)
    assert "PN0BY" not in out, out


def test_neighbour_route_open(dut):
    end = time.time() + 120
    out = ""
    while time.time() < end:
        out = dut.cmd("R", 1.5)
        if re.search(rf">\s*3\s+{NBR_CALL}", out):
            return
        time.sleep(5)
    pytest.fail(f"route to {NBR_CALL} on port 3 never opened:\n{out}")


def test_dut_knows_neighbour_node(dut):
    end = time.time() + 120
    out = ""
    while time.time() < end:
        out = dut.cmd("N", 1.5)
        if f"NBR:{NBR_CALL}" in out:
            return
        time.sleep(5)
    pytest.fail(f"NBR:{NBR_CALL} never appeared in N:\n{out}")


@pytest.fixture
def dut1(stack):
    from conftest import DUT_TELNET, HOST, SYSOP_PASSWORD
    from xrconsole import XRConsole
    c = XRConsole(HOST, DUT_TELNET, "PN0TSA", name="dut-l4")
    yield c
    c.close()


@pytest.fixture
def nbr1(stack):
    from conftest import HOST, NBR_TELNET
    from xrconsole import XRConsole
    c = XRConsole(HOST, NBR_TELNET, "PN0TSB", name="nbr-l4")
    yield c
    c.close()


def bye(c):
    try:
        c.send("B")
        c.drain(1.5, 5)
    except (ConnectionError, OSError):
        pass


def test_l4_connect_dut_to_neighbour(dut1):
    dut = dut1
    out = dut.run("C NBR", r"Connected to|Failure|Busy", 30)
    assert re.search(r"Connected to", out), out
    out = dut.cmd("P", 2)
    assert "Probe C" in out, f"commands did not reach the neighbour:\n{out}"
    bye(dut)


def test_l4_connect_neighbour_to_dut(nbr1):
    nbr = nbr1
    out = nbr.run("C DUT", r"Connected to|Failure|Busy", 30)
    assert re.search(r"Connected to", out), out
    out = nbr.cmd("P", 2)
    assert "Probe A" in out, f"commands did not reach the DUT:\n{out}"
    bye(nbr)


def test_l4_connect_neighbour_to_dut_bbs(nbr1):
    nbr = nbr1
    """The DUT's BBS reached over NET/ROM by its alias, as a remote user or a
    forwarding partner would."""
    out = nbr.run("C DUTPMS", r"Connected to|Failure|Busy", 30)
    assert re.search(r"Connected to", out), out
    out += nbr.drain(2.5, 10)
    assert re.search(r"Welcome to", out, re.I) and re.search(r"\[\d+\][^\n]*>", out), out
    bye(nbr)


def test_l4_connect_neighbour_to_dut_app_service(nbr1):
    nbr = nbr1
    """NetRomX service 2 (PMS) on the DUT: C DUT 2 (MAN SERVICES)."""
    out = nbr.run("C DUT 2", r"Connected to|Failure|Busy|Invalid", 30)
    out += nbr.drain(2.5, 10)
    assert re.search(r"Welcome to", out, re.I), out
    bye(nbr)
