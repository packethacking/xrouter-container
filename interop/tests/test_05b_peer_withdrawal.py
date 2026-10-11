"""Withdrawal and recovery on the links to the other implementations.

All the peer links (XNet, TNN, the second XRouter and the TheNet KISS tap)
are dropped in the relay at once, to keep the run short; each link's
evidence is separate. XRouter must notice each loss, stop routing to that
peer, and tell LinBPQ (to which it advertised every peer by INP3) at once;
when the links come back, everything must return.

[INP3]: "Interlink Failure: On a AX.25 link failure, all routes to and from
this neighbor are dropped" and negative information "has to occur
immediately after arrival".
"""

from __future__ import annotations

import time

import pytest

from conftest import (LINK, LINK_THENET, LINK_TNN, LINK_XNET, LINK_XRPEER, PEERS, THENET_CALL, TNN_CALL,
                      XNET_CALL, XR_CALL, XRPEER_CALL, needs_peer, relay_ctl)
from parse import xr_node_plus, xr_routes, xr_node_routes
from wire import lines, wait_for

HORIZON_TT = 60000
LOSS_BOUND = 90          # s from the drop to XRouter's tables showing the loss (AXUDP links)
THENET_LOSS_BOUND = 180  # TheNet's port runs radio timers: FRACK 8 s, 10 retries
RECOVERY_BOUND = 120

LINKS = {"xnet": (LINK_XNET, XNET_CALL), "tnn": (LINK_TNN, TNN_CALL), "xrpeer": (LINK_XRPEER, XRPEER_CALL),
         "thenet": (LINK_THENET, THENET_CALL)}
state: dict = {}


@pytest.fixture(scope="module", autouse=True)
def _restore_after(stack):
    yield
    for peer, (link, _) in LINKS.items():
        if peer in PEERS:
            try:
                relay_ctl(f"/links/{link}?drop=0")
            except OSError:
                pass


def _dropped():
    if "t_drop" not in state:
        pytest.skip("peer links were not dropped (see test_drop_peer_links)")
    return state["t_drop"]


def _usable(entry: dict | None) -> bool:
    return bool(entry) and entry["tt"] < 600 and 0 < entry["hops"] < 30 and entry["obs2"] > 0


def test_drop_peer_links(peers_converged):
    if not [p for p in LINKS if p in PEERS]:
        pytest.skip("no peers running")
    for peer, (link, _) in LINKS.items():
        if peer in PEERS:
            relay_ctl(f"/links/{link}?drop=1")
    state["t_drop"] = time.time()


def _xrouter_loses(xr, call: str, bound: float, inp3: bool = True):
    t0 = _dropped()

    def gone():
        r = xr_routes(xr.cmd("R")).get(call)
        if r is not None and r["state"] == ">":
            return False
        return not inp3 or not _usable(xr_node_plus(xr.cmd("N +", 1.5)).get(call))

    got = wait_for(gone, max(5, bound - (time.time() - t0)), 3)
    if got:
        state[f"gone_{call}"] = time.time()
    assert got, (f"{bound} s after the link to {call} went silent XRouter still uses it:\n{xr.cmd('R')}\n"
                 f"{xr.cmd('N +')}")


def _tells_bpq_gone(wire, call: str, bound: float):
    t0 = _dropped()

    def negative():
        return [r for rip, r in wire.rips(LINK, "xrouter", since=t0) if rip["call"] == call and rip["tt"] >= HORIZON_TT]

    got = wait_for(negative, max(5, bound - (time.time() - t0)), 1)
    noticed = state.get(f"gone_{call}")
    note = f"XRouter's own table showed the loss {noticed - t0:.0f} s after the drop" if noticed else \
        "XRouter's own table never showed the loss"
    assert got, (f"XRouter did not tell LinBPQ that {call} is unreachable within {bound} s of the link going "
                 f"silent ({note}).\nXRouter RIFs to LinBPQ since the drop:\n{lines(wire.rifs(LINK, 'xrouter', since=t0))}")
    if noticed:
        delay = got[0]["t"] - noticed
        assert delay <= 10 + 3, (f"XRouter noticed the loss of {call} at {noticed:.0f} but told LinBPQ only "
                                 f"{delay:.0f} s later (limit 10 s, plus our 3 s polling):\n{lines(got[:1])}")


@needs_peer("xnet")
def test_xrouter_withdraws_xnet_when_link_lost(xr):
    _xrouter_loses(xr, XNET_CALL, LOSS_BOUND)


@needs_peer("xnet")
def test_xrouter_tells_bpq_that_xnet_is_gone(wire):
    _tells_bpq_gone(wire, XNET_CALL, LOSS_BOUND + 15)


@needs_peer("tnn")
def test_xrouter_withdraws_tnn_when_link_lost(xr):
    _xrouter_loses(xr, TNN_CALL, LOSS_BOUND)


@needs_peer("tnn")
def test_xrouter_tells_bpq_that_tnn_is_gone(wire):
    _tells_bpq_gone(wire, TNN_CALL, LOSS_BOUND + 15)


@needs_peer("xrpeer")
def test_xrouter_withdraws_xrpeer_when_link_lost(xr):
    _xrouter_loses(xr, XRPEER_CALL, LOSS_BOUND)


@needs_peer("xrpeer")
def test_xrouter_tells_bpq_that_xrpeer_is_gone(wire):
    _tells_bpq_gone(wire, XRPEER_CALL, LOSS_BOUND + 15)


@needs_peer("xrpeer")
def test_xrpeer_withdraws_xrouter_when_link_lost(xrp):
    t0 = _dropped()

    def gone():
        r = xr_routes(xrp.cmd("R")).get(XR_CALL)
        return (r is None or r["state"] != ">") and not _usable(xr_node_plus(xrp.cmd("N +", 1.5)).get(XR_CALL))

    got = wait_for(gone, max(5, LOSS_BOUND - (time.time() - t0)), 3)
    assert got, f"the peer XRouter still uses its link to {XR_CALL}:\n{xrp.cmd('R')}\n{xrp.cmd('N +')}"


@needs_peer("thenet")
def test_xrouter_withdraws_thenet_when_link_lost(xr):
    """NET/ROM only: the neighbour route must stop being in use. XRouter also
    time-routes TheNet (it advertises it by INP3 with a measured time), so the
    time route must go too."""
    _xrouter_loses(xr, THENET_CALL, THENET_LOSS_BOUND)


@needs_peer("thenet")
def test_xrouter_tells_bpq_that_thenet_is_gone(wire):
    """XRouter advertised TheNet to LinBPQ by INP3, so it owes LinBPQ the
    negative information too."""
    advertised = [r for rip, r in wire.rips(LINK, "xrouter") if rip["call"] == THENET_CALL and rip["tt"] < HORIZON_TT]
    if not advertised:
        pytest.skip("XRouter never advertised TheNet to LinBPQ by INP3")
    _tells_bpq_gone(wire, THENET_CALL, THENET_LOSS_BOUND + 15)


# ---------------------------------------------------------------- recovery


def test_restore_peer_links():
    _dropped()
    for peer, (link, _) in LINKS.items():
        if peer in PEERS:
            relay_ctl(f"/links/{link}?drop=0")
    state["t_restore"] = time.time()


def _recovers(xr, wire, call: str, link: str, bound: float = RECOVERY_BOUND, inp3: bool = True):
    if "t_restore" not in state:
        pytest.skip("links were not restored")
    t0 = state["t_restore"]

    def back():
        r = xr_routes(xr.cmd("R")).get(call)
        if not (r and r["state"] == ">"):
            return False
        if not inp3:
            return True
        positive = [rr for rip, rr in wire.rips(LINK, "xrouter", since=t0) if rip["call"] == call and rip["tt"] < HORIZON_TT]
        return _usable(xr_node_plus(xr.cmd("N +", 1.5)).get(call)) and positive

    got = wait_for(back, max(5, bound - (time.time() - t0)), 3)
    setup = [r for r in wire.frames(link=link, since=t0) if r["frame"].get("ctl", {}).get("type") in ("SABM", "UA", "DM", "DISC")]
    peer = next(p for p, (lk, _) in LINKS.items() if lk == link)
    heard = wire.frames(link=link, frm=peer)
    last = f"{peer} last sent anything at {heard[-1]['t']:.3f}" if heard else f"{peer} never sent anything"
    silent = "" if [r for r in heard if r["t"] >= t0] else f" {peer} has sent nothing since the restore ({last})."
    assert got, (f"{call} did not come back within {bound} s of restoring its link (route in use, live time route "
                 f"at XRouter and re-advertised to LinBPQ).{silent}\n{xr.cmd('R')}\n{xr.cmd('N +')}\n"
                 f"Link set-up since restore:\n{lines(setup)}\n"
                 f"XRouter RIFs to LinBPQ since:\n{lines(wire.rifs(LINK, 'xrouter', since=t0))}")


@needs_peer("xnet")
def test_xnet_recovers_when_link_restored(xr, wire):
    _recovers(xr, wire, XNET_CALL, LINK_XNET)


@needs_peer("tnn")
def test_tnn_recovers_when_link_restored(xr, wire):
    _recovers(xr, wire, TNN_CALL, LINK_TNN)


@needs_peer("xrpeer")
def test_xrpeer_recovers_when_link_restored(xr, wire):
    _recovers(xr, wire, XRPEER_CALL, LINK_XRPEER)


@needs_peer("thenet")
def test_thenet_recovers_when_link_restored(xr, wire):
    _recovers(xr, wire, THENET_CALL, LINK_THENET, RECOVERY_BOUND + 60, inp3=False)
    routes = xr_node_routes(xr.cmd("N THENET"))
    assert any(r["active"] for r in routes), f"XRouter has no active route to THENET:\n{xr.cmd('N THENET')}"
