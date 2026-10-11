"""Route withdrawal and recovery, driven by dropping frames in the relay.

[INP3]: "Negative information is propagated with higher priority than positive
information. The propagation has to occur immediately after arrival." and
"Interlink Failure: On a AX.25 link failure, all routes to and from this
neighbor are dropped."

These tests run in file order and share the link state: the third-party link
(LinBPQ <-> LinBPQ2) goes down and comes back first, then the XRouter link.
"""

import time

import pytest

from conftest import BPQ2_ALIAS, BPQ2_CALL, BPQ_CALL, LINK, LINK2, XR_CALL, relay_ctl
from parse import bpq_node_routes, bpq_routes, xr_routes
from wire import lines, wait_for

HORIZON_TT = 60000
NEGATIVE_BOUND = 60       # seconds from the drop to the negative RIF
TABLE_BOUND = 20          # seconds from a RIF to the routing table showing it
RECOVERY_BOUND = 120      # seconds from restoring a link to routes being back

state: dict = {}


@pytest.fixture(scope="module", autouse=True)
def _restore_links_after(stack):
    yield
    for link in (LINK, LINK2):
        try:
            relay_ctl(f"/links/{link}?drop=0")
        except OSError:
            pass


def _drop(link: str) -> float:
    relay_ctl(f"/links/{link}?drop=1")
    return time.time()


def _restore(link: str) -> float:
    relay_ctl(f"/links/{link}?drop=0")
    return time.time()


def _xr_node_plus(xr) -> dict[str, dict]:
    """XRouter `N +`: alias:call -> qual, obs, port, via, sntt (target time, s), hops, obs2."""
    out = {}
    for ln in xr.cmd("N +", 1.5).splitlines():
        p = ln.split()
        if len(p) == 8 and ":" in p[0]:
            try:
                out[p[0].split(":")[1]] = {"qual": int(p[1]), "via": p[4], "tt": float(p[5]),
                                           "hops": int(p[6]), "obs2": int(p[7]), "line": ln}
            except ValueError:
                pass
    return out


def _xr_time_route_ok(entry: dict | None) -> bool:
    return bool(entry) and entry["tt"] < 600 and 0 < entry["hops"] < 30 and entry["obs2"] > 0


# ---------------------------------------------------------------- third party link


def test_bpq_sends_negative_info_when_third_party_lost(wire, converged):
    state["t_drop2"] = t0 = _drop(LINK2)

    def negative():
        return [r for rip, r in wire.rips(LINK, "linbpq", since=t0)
                if rip["call"] == BPQ2_CALL and rip["tt"] >= HORIZON_TT]

    got = wait_for(negative, NEGATIVE_BOUND, 1)
    assert got, (f"LinBPQ did not tell XRouter that {BPQ2_CALL} is gone within {NEGATIVE_BOUND} s of "
                 f"the LinBPQ2 link dropping.\nRIFs to XRouter since:\n{lines(wire.rifs(LINK, 'linbpq', since=t0))}")
    state["t_neg2"] = got[0]["t"]


def test_xrouter_stops_time_routing_lost_third_party(xr, wire):
    if "t_neg2" not in state:
        pytest.skip("no negative RIF to react to (see the previous test)")
    got = wait_for(lambda: not _xr_time_route_ok(_xr_node_plus(xr).get(BPQ2_CALL)), TABLE_BOUND, 2)
    assert got, (f"XRouter still holds a usable trip-time route to {BPQ2_CALL} {TABLE_BOUND} s after "
                 f"LinBPQ withdrew it:\n{xr.cmd('N +')}\n{xr.cmd('N ' + BPQ2_ALIAS)}")
    # And XRouter must not re-advertise it to anyone as reachable.
    bad = [r for rip, r in wire.rips(LINK, "xrouter", since=state["t_neg2"])
           if rip["call"] == BPQ2_CALL and rip["tt"] < HORIZON_TT]
    assert not bad, f"XRouter advertised {BPQ2_CALL} as reachable after its withdrawal:\n{lines(bad)}"


def test_third_party_returns_when_link_restored(xr, wire):
    t0 = _restore(LINK2)

    def back():
        rips = [r for rip, r in wire.rips(LINK, "linbpq", since=t0)
                if rip["call"] == BPQ2_CALL and rip["tt"] < HORIZON_TT]
        return rips and _xr_time_route_ok(_xr_node_plus(xr).get(BPQ2_CALL))

    got = wait_for(back, RECOVERY_BOUND, 3)
    assert got, (f"{BPQ2_CALL} did not come back at XRouter by INP3 within {RECOVERY_BOUND} s of restoring the "
                 f"LinBPQ2 link.\nLinBPQ RIFs to XRouter since:\n{lines(wire.rifs(LINK, 'linbpq', since=t0))}\n"
                 f"{xr.cmd('N +')}")
    entry = _xr_node_plus(xr)[BPQ2_CALL]
    assert entry["hops"] == 2 and entry["via"] == BPQ_CALL, f"unexpected route after recovery: {entry['line']}"


# ---------------------------------------------------------------- the XRouter link


def test_xrouter_withdraws_routes_when_link_lost(xr, wire):
    state["t_drop"] = t0 = _drop(LINK)

    def gone():
        r = xr_routes(xr.cmd("R")).get(BPQ_CALL)
        nodes = _xr_node_plus(xr)
        usable = [c for c in (BPQ_CALL, BPQ2_CALL) if _xr_time_route_ok(nodes.get(c))]
        return (r is None or r["state"] != ">") and not usable

    got = wait_for(gone, 60, 2)
    state["t_xr_gone"] = time.time()
    assert got, (f"60 s after the link to LinBPQ went silent XRouter still shows it in use or still "
                 f"time-routes through it:\n{xr.cmd('R')}\n{xr.cmd('N +')}")


def test_bpq_withdraws_routes_when_link_lost(bpq):
    if "t_drop" not in state:
        pytest.skip("link was not dropped")

    def gone():
        r = bpq_routes(bpq.cmd("R")).get(XR_CALL)
        inp3 = [x for x in bpq_node_routes(bpq.cmd(f"N {XR_CALL}"))["inp3"] if x["tt"] < 600]
        return (r is None or not r["active"]) and not inp3

    left = max(5, 60 - (time.time() - state["t_drop"]))
    got = wait_for(gone, left, 2)
    assert got, (f"60 s after the link to XRouter went silent LinBPQ still shows it active or keeps an INP3 "
                 f"route to it:\n{bpq.cmd('R V')}\n{bpq.cmd('N ' + XR_CALL)}")


def test_bpq_tells_bpq2_that_xrouter_is_gone(wire):
    if "t_drop" not in state:
        pytest.skip("link was not dropped")
    t0 = state["t_drop"]

    def negative():
        return [r for rip, r in wire.rips(LINK2, "linbpq", since=t0)
                if rip["call"] == XR_CALL and rip["tt"] >= HORIZON_TT]

    left = max(5, NEGATIVE_BOUND - (time.time() - t0))
    got = wait_for(negative, left, 1)
    assert got, (f"LinBPQ did not send LinBPQ2 negative information for {XR_CALL} within {NEGATIVE_BOUND} s.\n"
                 f"RIFs to LinBPQ2 since the drop:\n{lines(wire.rifs(LINK2, 'linbpq', since=t0))}")


def test_routes_recover_when_link_restored(xr, bpq, wire):
    # Keep the outage short: both nodes back off their reconnect attempts.
    state["t_restore"] = t0 = _restore(LINK)

    def back():
        r = xr_routes(xr.cmd("R")).get(BPQ_CALL)
        nodes = _xr_node_plus(xr)
        b = [x for x in bpq_node_routes(bpq.cmd(f"N {XR_CALL}"))["inp3"] if x["tt"] < 600 and x["hops"] == 1]
        return (r and r["state"] == ">" and _xr_time_route_ok(nodes.get(BPQ_CALL))
                and _xr_time_route_ok(nodes.get(BPQ2_CALL)) and b)

    got = wait_for(back, RECOVERY_BOUND, 3)
    assert got, (f"routes did not recover within {RECOVERY_BOUND} s of restoring the link.\n"
                 f"{xr.cmd('R')}\n{xr.cmd('N +')}\n{bpq.cmd('R V')}\n{bpq.cmd('N ' + XR_CALL)}\n"
                 f"Link set-up since restore:\n"
                 f"{lines([r for r in wire.frames(link=LINK, since=t0) if r['frame'].get('ctl', {}).get('type') in ('SABM', 'UA', 'DM', 'DISC')])}")


def test_xrouter_resends_own_rif_after_link_restored(wire):
    """[INP3]: 'For the own node, a RIP is created and sent after the interlink has been established.'"""
    if "t_restore" not in state:
        pytest.skip("link was not restored")
    t0 = state["t_restore"]
    got = wait_for(lambda: [r for rip, r in wire.rips(LINK, "xrouter", since=t0)
                            if rip["call"] == XR_CALL and rip["hops"] == 1], 60, 2)
    assert got, (f"XRouter sent no RIP for its own node after the link came back.\n"
                 f"Frames from XRouter since restore:\n{lines(wire.frames(link=LINK, frm='xrouter', since=t0), 25)}")
