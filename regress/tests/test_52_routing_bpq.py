"""Route choice with LinBPQ as the INP3 neighbour (groups.io 4400; #15).

As test_50_routing, but the neighbour on DUT port 3 is LinBPQ (PN0BP), not
another XRouter: 505o's INP3 rewrite was for BPQ compatibility, and the
neighbour in PA2SNK's report (PE1OEZ) may run BPQ. For this module the
neighbour XRouter is stopped and LinBPQ takes its address; it is restored
afterwards.

PN0TX (alias JOUREX) is heard directly on DUT port 1 (quality 192, plain
NET/ROM, a slow link) and is an INP3 neighbour of LinBPQ, which passes it
on to the DUT by INP3.
"""

from __future__ import annotations

import os
import re
import time

import pytest

from conftest import DUT_CALL, NBR_IP, NET, REGRESS, sh
from fakenode import FakeNode
from test_50_routing import routes_to

BPQ_CALL = "PN0BP"
TX, TX_ALIAS = "PN0TX", "JOUREX"


@pytest.fixture(scope="module")
def bpq_paths(stack, probe_a, probe_c):
    sh("docker", "stop", "xrr-nbr", check=False)
    sh("docker", "rm", "-f", "xrr-bpq", check=False)
    cfg = os.path.join(REGRESS, "config", "bpq", "bpq32.cfg")
    sh("docker", "pull", "-q", "m0lte/linbpq:latest", check=False)
    sh("docker", "run", "-d", "--name", "xrr-bpq", "--network", NET, "--ip", NBR_IP,
       "-v", f"{cfg}:/data/bpq32.cfg:ro", "m0lte/linbpq:latest")
    direct = FakeNode(probe_a, TX, TX_ALIAS, DUT_CALL, inp3=False, nodes_every=20, delay=0.8)
    via_bpq = FakeNode(probe_c, TX, TX_ALIAS, BPQ_CALL, inp3=True, nodes_every=20, rif_every=30)
    yield direct, via_bpq
    direct.stop()
    via_bpq.stop()
    sh("docker", "rm", "-f", "xrr-bpq", check=False)
    sh("docker", "start", "xrr-nbr", check=False)


def wait_routes(dut, timeout=300):
    end = time.time() + timeout
    rows, out = [], ""
    while time.time() < end:
        rows, out = routes_to(dut, TX)
        if any(r["via"] == TX for r in rows) and any(
                r["via"] == BPQ_CALL and r["hops"] >= 2 and r["stt"] < 600 for r in rows):
            time.sleep(20)
            return routes_to(dut, TX)
        time.sleep(10)
    return rows, out


def test_dut_learns_tx_via_bpq(bpq_paths, dut):
    rows, out = wait_routes(dut)
    assert any(r["via"] == BPQ_CALL and r["hops"] >= 2 and r["stt"] < 600 for r in rows), \
        f"no INP3 route to {TX} via LinBPQ:\n{out}"


def test_dut_prefers_direct_over_bpq_inp3(bpq_paths, dut):
    rows, out = wait_routes(dut)
    best = [r for r in rows if r["preferred"]] or [r for r in rows if r["active"]]
    assert best and best[0]["via"] == TX and best[0]["port"] == 1, \
        f"DUT does not use the direct route to {TX}:\n{out}"


def test_dut_connect_goes_direct_not_via_bpq(bpq_paths, dut):
    direct, via_bpq = bpq_paths
    wait_routes(dut)
    a0, c0 = len(direct.l3_frames), len(via_bpq.l3_frames)
    dut.send(f"C {TX_ALIAS}")
    time.sleep(10)
    dut.send("")
    dut.drain(1, 3)
    to = lambda frames: [f for f in frames if "".join(chr(b >> 1) for b in f[7:13]).strip() == TX]  # noqa: E731
    got_direct, got_via = to(direct.l3_frames[a0:]), to(via_bpq.l3_frames[c0:])
    assert got_direct and not got_via, \
        f"connect to {TX_ALIAS}: {len(got_direct)} L3 frames direct on port 1, {len(got_via)} via LinBPQ"


def connect_path(dut, direct, via_bpq, wait=12):
    """Where a C JOUREX goes: ('direct', n) / ('bpq', n) by L3 frames seen."""
    a0, c0 = len(direct.l3_frames), len(via_bpq.l3_frames)
    dut.send(f"C {TX_ALIAS}")
    time.sleep(wait)
    dut.send("")
    dut.drain(1, 3)
    to = lambda frames: [f for f in frames if "".join(chr(b >> 1) for b in f[7:13]).strip() == TX]  # noqa: E731
    return len(to(direct.l3_frames[a0:])), len(to(via_bpq.l3_frames[c0:]))


def test_direct_link_failure_and_recovery(bpq_paths, dut, probe_a):
    """The direct link dies (the station stops answering): connects fall back
    to the INP3 path via LinBPQ. When the station is back, the DUT returns
    to the direct route (PA2SNK 4401: "i cant get a connection to joure
    anymore")."""
    direct, via_bpq = bpq_paths
    wait_routes(dut)
    direct.stop()
    # Silence: no UA, no RR. Wait for the DUT to give up on the link.
    end = time.time() + 120
    rows, out = [], ""
    while time.time() < end:
        n_direct, n_via = connect_path(dut, direct, via_bpq, 8)
        if n_via:
            break
    rows, out = routes_to(dut, TX)
    assert n_via, f"with the direct link dead, connects did not fall back to LinBPQ:\n{out}"
    # The station comes back.
    back = FakeNode(probe_a, TX, TX_ALIAS, DUT_CALL, inp3=False, nodes_every=20, delay=0.8)
    try:
        end = time.time() + 240
        while time.time() < end:
            rows, out = routes_to(dut, TX)
            best = [r for r in rows if r["preferred"]] or [r for r in rows if r["active"]]
            if best and best[0]["via"] == TX:
                break
            time.sleep(15)
        assert best and best[0]["via"] == TX, f"DUT did not return to the direct route after recovery:\n{out}"
        n_direct, n_via = connect_path(dut, back, via_bpq)
        assert n_direct and not n_via, f"after recovery: {n_direct} L3 frames direct, {n_via} via LinBPQ\n{out}"
    finally:
        back.stop()
