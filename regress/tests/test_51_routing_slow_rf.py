"""Route choice when the direct neighbour is on a slow link (groups.io 4400).

The same two-path set-up as test_50_routing, but the direct neighbour on
DUT port 1 answers 0.8 s late, as a 1200 bit/s radio link would, while the
path through PN0NB is fast. Danny's direct link to JOURE is RF and his INP3
path via PE1OEZ is probably over the internet, so an INP3 trip-time
comparison would favour the longer path. These tests record which route
the DUT uses in two cases: the direct neighbour speaks INP3 or it does not.
505c keeps the direct, higher-quality route in both.
"""

from __future__ import annotations

import time

import pytest

from conftest import DUT_CALL, NBR_CALL
from fakenode import FakeNode
from test_50_routing import routes_to

CASES = [
    # (call, alias, the direct neighbour speaks INP3)
    ("PN0TU", "SLOWA", False),
    ("PN0TV", "SLOWB", True),
]


@pytest.fixture(scope="module", params=CASES, ids=["direct-netrom", "direct-inp3"])
def slow_paths(request, probe_a, probe_c, nbr):
    call, alias, direct_inp3 = request.param
    direct = FakeNode(probe_a, call, alias, DUT_CALL, inp3=direct_inp3, nodes_every=20, rif_every=30, delay=0.8)
    via_nbr = FakeNode(probe_c, call, alias, NBR_CALL, inp3=True, nodes_every=20, rif_every=30)
    yield call, alias, direct, via_nbr
    direct.stop()
    via_nbr.stop()


def wait_routes(dut, call, timeout=240):
    end = time.time() + timeout
    rows, out = [], ""
    while time.time() < end:
        rows, out = routes_to(dut, call)
        if any(r["via"] == call for r in rows) and any(
                r["via"] == NBR_CALL and r["hops"] >= 2 and r["stt"] < 600 for r in rows):
            time.sleep(20)          # let trip times settle
            return routes_to(dut, call)
        time.sleep(10)
    return rows, out


def test_slow_direct_route_preferred(slow_paths, dut):
    call, alias, _, _ = slow_paths
    rows, out = wait_routes(dut, call)
    assert any(r["via"] == NBR_CALL for r in rows), f"never got the INP3 route via {NBR_CALL}:\n{out}"
    best = [r for r in rows if r["preferred"]] or [r for r in rows if r["active"]]
    assert best and best[0]["via"] == call and best[0]["port"] == 1, \
        f"DUT does not use the direct route to {call}:\n{out}"


def test_slow_direct_connect_goes_direct(slow_paths, dut):
    call, alias, direct, via_nbr = slow_paths
    wait_routes(dut, call)
    a0, c0 = len(direct.l3_frames), len(via_nbr.l3_frames)
    dut.send(f"C {alias}")
    time.sleep(10)
    dut.send("")
    dut.drain(1, 3)
    to = lambda frames: [f for f in frames if "".join(chr(b >> 1) for b in f[7:13]).strip() == call]  # noqa: E731
    got_direct, got_via = to(direct.l3_frames[a0:]), to(via_nbr.l3_frames[c0:])
    assert got_direct and not got_via, \
        f"connect to {alias}: {len(got_direct)} L3 frames direct on port 1, {len(got_via)} via {NBR_CALL}"
