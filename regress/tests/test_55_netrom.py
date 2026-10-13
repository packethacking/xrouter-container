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
    """A NODES broadcast heard on port 2 puts the sender and its entries in N."""
    info = nodes_broadcast("BBSNOD", [("PN0FAR", "FARNOD", "PN0BX", 200)])
    for _ in range(2):
        probe_b.send(ui("NODES", "PN0BX", info, pid=0xCF))
        time.sleep(1)
    out = dut.cmd("N", 1.5)
    assert "BBSNOD:PN0BX" in out, out
    assert "FARNOD:PN0FAR" in out, out


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


def test_l4_connect_dut_to_neighbour(dut):
    out = dut.run("C NBR", r"Connected to|Failure|Busy", 30)
    assert re.search(r"Connected to", out), out
    out = dut.cmd("P", 2)
    assert "Probe C" in out, f"commands did not reach the neighbour:\n{out}"
    dut.cmd("B", 2)
    out = dut.drain(1.5, 5)


def test_l4_connect_neighbour_to_dut(nbr):
    out = nbr.run("C DUT", r"Connected to|Failure|Busy", 30)
    assert re.search(r"Connected to", out), out
    out = nbr.cmd("P", 2)
    assert "Probe A" in out, f"commands did not reach the DUT:\n{out}"
    nbr.cmd("B", 2)
    nbr.drain(1.5, 5)


def test_l4_connect_neighbour_to_dut_bbs(nbr):
    """The DUT's BBS reached over NET/ROM by its alias, as a remote user or a
    forwarding partner would."""
    out = nbr.run("C DUTPMS", r"Connected to|Failure|Busy", 30)
    assert re.search(r"Connected to", out), out
    out += nbr.drain(2.5, 10)
    assert re.search(r"Welcome to", out, re.I) and re.search(r"\[\d+\][^\n]*>", out), out
    nbr.cmd("B", 2)
    nbr.drain(1.5, 5)


def test_l4_connect_neighbour_to_dut_app_service(nbr):
    """NetRomX service 2 (PMS) on the DUT: C DUT 2 (MAN SERVICES)."""
    out = nbr.run("C DUT 2", r"Connected to|Failure|Busy|Invalid", 30)
    out += nbr.drain(2.5, 10)
    assert re.search(r"Welcome to", out, re.I), out
    nbr.cmd("B", 2)
    nbr.drain(1.5, 5)
