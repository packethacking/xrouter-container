"""NET/ROM layer 4 circuits across the interlink, in both directions."""

import time

from conftest import BPQ2_ALIAS, BPQ_ALIAS, BPQ_CALL, LINK, XR_ALIAS, XR_CALL
from wire import lines


def _l4(wire, since, src, dst, op):
    return [r for r in wire.frames(link=LINK, since=since, kind="L3")
            if r["frame"]["netrom"]["l3src"] == src and r["frame"]["netrom"]["l3dst"] == dst
            and r["frame"]["netrom"]["l4"]["op"] == op]


def test_l4_connect_xrouter_to_bpq(xr, wire, converged):
    t0 = time.time()
    out = xr.cmd(f"C {BPQ_ALIAS}", 3)
    if "Connected to" not in out:
        out += xr.drain(1.0, 15)
    assert f"Connected to {BPQ_CALL}" in out, f"XRouter could not connect to {BPQ_ALIAS}:\n{out}\nL4 on the wire:\n{lines(wire.frames(link=LINK, since=t0, kind='L3'))}"
    out = xr.cmd("V", 2)
    assert "Version 6." in out, f"no reply from LinBPQ's V command through the circuit:\n{out}"
    assert _l4(wire, t0, XR_CALL, BPQ_CALL, "CONREQ"), "no CONREQ from XRouter on the wire"
    assert _l4(wire, t0, BPQ_CALL, XR_CALL, "CONACK"), "no CONACK from LinBPQ on the wire"
    assert _l4(wire, t0, BPQ_CALL, XR_CALL, "INFO"), "no L4 INFO from LinBPQ on the wire"


def test_l4_connect_bpq_to_xrouter(bpq, wire, converged):
    t0 = time.time()
    out = bpq.cmd(f"C {XR_ALIAS}", 3)
    if "Connected to" not in out:
        out += bpq.drain(1.0, 15)
    assert f"Connected to {XR_ALIAS}:{XR_CALL}" in out, f"LinBPQ could not connect to {XR_ALIAS}:\n{out}\nL4 on the wire:\n{lines(wire.frames(link=LINK, since=t0, kind='L3'))}"
    out = bpq.cmd("V", 2)
    assert "XRouter" in out or "XrLin" in out or "Xrouter" in out, f"no reply from XRouter's V command through the circuit:\n{out}"
    assert _l4(wire, t0, BPQ_CALL, XR_CALL, "CONREQ"), "no CONREQ from LinBPQ on the wire"
    assert _l4(wire, t0, XR_CALL, BPQ_CALL, "CONACK"), "no CONACK from XRouter on the wire"
    assert _l4(wire, t0, XR_CALL, BPQ_CALL, "INFO"), "no L4 INFO from XRouter on the wire"


def test_l4_connect_xrouter_to_third_party(xr, wire, converged):
    """Two hops: XRouter -> LinBPQ -> LinBPQ2, routed on what XRouter learned by INP3."""
    t0 = time.time()
    out = xr.cmd(f"C {BPQ2_ALIAS}", 3)
    if "Connected to" not in out:
        out += xr.drain(1.0, 20)
    assert "Connected to PN0BQB" in out, f"XRouter could not connect to {BPQ2_ALIAS}:\n{out}\nL4 on the wire:\n{lines(wire.frames(link=LINK, since=t0, kind='L3'))}"
    out = xr.cmd("V", 2)
    assert "Version 6." in out, f"no reply from LinBPQ2 through the circuit:\n{out}"


def test_l4_connect_bpq2_to_xrouter(bpq2, converged):
    out = bpq2.cmd(f"C {XR_ALIAS}", 3)
    if "Connected to" not in out:
        out += bpq2.drain(1.0, 20)
    assert f"Connected to {XR_ALIAS}:{XR_CALL}" in out, f"LinBPQ2 could not connect to {XR_ALIAS} through LinBPQ:\n{out}"
    out = bpq2.cmd("V", 2)
    assert "XrLin" in out or "XRouter" in out, f"no reply from XRouter through the circuit:\n{out}"
