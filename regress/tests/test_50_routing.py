"""NET/ROM route choice between a direct neighbour and an INP3 path
(groups.io 4400, Danny PA2SNK on 505o: "the inp3 route via pe1oez is chosen
above a direct rf link with quality 192 and 1 hop. With 505c this was not an
issue"; 4401: "i cant get a connection to joure anymore").

PN0TS (alias JOURE) is a plain NET/ROM node heard directly on DUT port 1
(QUALITY=192), played by a fake node on probe A that does not speak INP3.
The same station is also a neighbour of the other XRouter, PN0NB, and talks
INP3 to it (fake node on probe C), so PN0NB tells the DUT about PN0TS by
INP3 as well. The DUT then has two routes to PN0TS: direct on port 1, one
hop, quality 192, or via PN0NB on port 3, two hops by INP3. 505c uses the
direct one.
"""

from __future__ import annotations

import re
import time

import pytest

from conftest import DUT_CALL, NBR_CALL
from fakenode import FakeNode

TS, TS_ALIAS = "PN0TS", "JOURE"


@pytest.fixture(scope="module")
def two_paths(probe_a, probe_c, nbr):
    direct = FakeNode(probe_a, TS, TS_ALIAS, DUT_CALL, inp3=False, nodes_every=20)
    via_nbr = FakeNode(probe_c, TS, TS_ALIAS, NBR_CALL, inp3=True, nodes_every=20, rif_every=30)
    yield direct, via_nbr
    direct.stop()
    via_nbr.stop()


def routes_to(dut, call: str) -> list[dict]:
    """Rows of the 'Routes to:' table of `N <call>`: port, via, markers."""
    out = dut.cmd(f"N {call}", 1.5)
    rows = []
    for line in out.splitlines():
        # "> 192  5   1 PN0TS        0.09  1   5   N <"
        m = re.match(r"^\s*(>?)\s*(\d+)\s+(\d+)\s+(\d+)\s+([A-Z0-9]+(?:-\d+)?)\s+([\d.]+)\s+(\d+)"
                     r"\s+(\d+)\s+([YN])?\s*(<)?\s*$", line)
        if m:
            rows.append({"line": line, "active": m.group(1) == ">", "preferred": bool(m.group(10)),
                         "qty": int(m.group(2)), "port": int(m.group(4)), "via": m.group(5),
                         "stt": float(m.group(6)), "hops": int(m.group(7))})
    return rows, out


def wait_both_routes(dut, timeout=240):
    """Until the DUT has the direct route and an INP3 route (hops >= 2, a
    trip time below the 600 s horizon) via the neighbour."""
    end = time.time() + timeout
    rows, out = [], ""
    while time.time() < end:
        rows, out = routes_to(dut, TS)
        direct = [r for r in rows if r["via"] == TS]
        inp3 = [r for r in rows if r["via"] == NBR_CALL and r["hops"] >= 2 and r["stt"] < 600]
        if direct and inp3:
            return rows, out
        time.sleep(10)
    return rows, out


def test_nbr_learns_ts_by_inp3(two_paths, nbr):
    end = time.time() + 180
    out = ""
    while time.time() < end:
        rows, out = routes_to(nbr, TS)
        if any(r["via"] == TS and r["stt"] < 600 for r in rows):
            return
        time.sleep(10)
    pytest.fail(f"neighbour never got a trip time for {TS} by INP3:\n{out}")


def test_dut_knows_both_paths(two_paths, dut):
    rows, out = wait_both_routes(dut)
    assert any(r["via"] == TS for r in rows) and \
        any(r["via"] == NBR_CALL and r["hops"] >= 2 and r["stt"] < 600 for r in rows), \
        f"DUT does not have both the direct route and an INP3 route via {NBR_CALL} to {TS}:\n{out}"


def test_dut_prefers_direct_route(two_paths, dut):
    rows, out = wait_both_routes(dut)
    best = [r for r in rows if r["preferred"]] or [r for r in rows if r["active"]]
    assert best, f"no preferred or active route marked:\n{out}"
    assert best[0]["via"] == TS and best[0]["port"] == 1, \
        f"DUT prefers the route via {best[0]['via']} on port {best[0]['port']}, not the direct one:\n{out}"


def test_dut_connects_to_direct_neighbour_directly(two_paths, dut):
    """C JOURE: the NET/ROM connect request goes straight to PN0TS on port 1,
    not round through PN0NB."""
    direct, via_nbr = two_paths
    wait_both_routes(dut)
    a0, c0 = len(direct.l3_frames), len(via_nbr.l3_frames)
    dut.send(f"C {TS_ALIAS}")
    time.sleep(8)
    dut.send("")
    dut.drain(1, 3)
    to_ts = lambda frames: [f for f in frames if "".join(chr(b >> 1) for b in f[7:13]).strip() == TS]  # noqa: E731
    got_direct = to_ts(direct.l3_frames[a0:])
    got_via = to_ts(via_nbr.l3_frames[c0:])
    assert got_direct and not got_via, \
        f"connect to {TS_ALIAS}: {len(got_direct)} L3 frames direct on port 1, {len(got_via)} via PN0NB"
