"""INP3 between XRouter and LinBPQ: L3RTT, RIF, route flags and propagation.

Spec references are to "A New Routing Specification for Packet Radio
Datagram Networks" (Gal, DB7KG), the INP3 spec, abbreviated [INP3], and to
XRouter's own manual pages (MAN INP3, MAN L3RTT, MAN ROUTES).
"""

from conftest import (BPQ2_ALIAS, BPQ2_CALL, BPQ_APP_ALIAS, BPQ_APP_CALL, BPQ_CALL, LINK, LINK2,
                      XR_CALL)
from parse import bpq_node_routes, bpq_routes, xr_node_routes, xr_routes
from wire import lines, wait_for

XR_APP_CALL, XR_APP_ALIAS = "PN0XR-1", "XRAPP"
HORIZON_TT = 60000

# Every node the far side can only reach through this neighbour.
BEHIND_BPQ = {BPQ_CALL, BPQ_APP_CALL, BPQ2_CALL}
BEHIND_XR = {XR_CALL, XR_APP_CALL}


# ---------------------------------------------------------------- L3RTT


def test_xrouter_sends_l3rtt_probes(wire, converged):
    probes = wire.l3rtt(LINK, "xrouter", origin=XR_CALL)
    assert probes, f"no L3RTT probe from XRouter ({XR_CALL}).\nL3RTT seen:\n{lines(wire.frames(link=LINK, kind='L3RTT'))}"
    flags = probes[-1]["frame"]["netrom"]["l3rtt"].get("flags", [])
    assert "$N" in flags, f"[INP3] any INP node must send $N in L3RTT; XRouter sent:\n{lines(probes[-1:])}"


def test_bpq_sends_l3rtt_probes(wire, converged):
    probes = wire.l3rtt(LINK, "linbpq", origin=BPQ_CALL)
    assert probes, f"no L3RTT probe from LinBPQ ({BPQ_CALL}).\nL3RTT seen:\n{lines(wire.frames(link=LINK, kind='L3RTT'))}"
    flags = probes[-1]["frame"]["netrom"]["l3rtt"].get("flags", [])
    assert "$N" in flags, f"[INP3] any INP node must send $N in L3RTT; LinBPQ sent:\n{lines(probes[-1:])}"


def _reflections(wire, prober: str, prober_call: str, reflector: str):
    """Pair each probe with its reflection (same text, coming back)."""
    probes = wire.l3rtt(LINK, prober, origin=prober_call)
    back = {r["frame"]["netrom"]["l3rtt"]["text"]: r for r in wire.l3rtt(LINK, reflector, origin=prober_call)}
    return [(p, back.get(p["frame"]["netrom"]["l3rtt"]["text"])) for p in probes]


def test_bpq_reflects_xrouter_l3rtt(wire, converged):
    pairs = _reflections(wire, "xrouter", XR_CALL, "linbpq")
    assert pairs, "no XRouter L3RTT probes to check"
    missing = [p for p, r in pairs if r is None]
    # The newest probe may still be in flight.
    if missing and missing[-1] is pairs[-1][0]:
        missing = missing[:-1]
    # Probes sent around a host stall prove nothing about either node.
    missing = [p for p in missing if not wire.near_stall(p["t"])]
    assert not missing, f"[INP3] the neighbour reflects every RTT frame; LinBPQ did not reflect:\n{lines(missing)}"


def test_xrouter_reflects_bpq_l3rtt(wire, converged):
    pairs = _reflections(wire, "linbpq", BPQ_CALL, "xrouter")
    assert pairs, "no LinBPQ L3RTT probes to check"
    missing = [p for p, r in pairs if r is None]
    if missing and missing[-1] is pairs[-1][0]:
        missing = missing[:-1]
    missing = [p for p in missing if not wire.near_stall(p["t"])]
    assert not missing, f"[INP3] the neighbour reflects every RTT frame; XRouter did not reflect:\n{lines(missing)}"
    slow = [(p, r) for p, r in pairs if r and r["t"] - p["t"] > 2.0 and not wire.near_stall(p["t"])]
    assert not slow, ("[INP3] 'The neighbor will reflect a received RTT frame immediately'; "
                      "XRouter took over 2 s:\n" +
                      "\n".join(f"  probe {p['t']:.3f} reflected {r['t']:.3f} (+{r['t'] - p['t']:.2f} s)" for p, r in slow))


# ---------------------------------------------------------------- RIF


def test_xrouter_sends_rif(wire, converged):
    rifs = wire.rifs(LINK, "xrouter")
    assert rifs, ("XRouter never sent a RIF to LinBPQ. L3RTT exchange for context:\n"
                  f"{lines(wire.frames(link=LINK, kind='L3RTT'))}")


def test_bpq_sends_rif(wire, converged):
    rifs = wire.rifs(LINK, "linbpq")
    assert rifs, ("LinBPQ never sent a RIF to XRouter. L3RTT exchange for context:\n"
                  f"{lines(wire.frames(link=LINK, kind='L3RTT'))}")


def _check_rips(wire, frm: str):
    problems = []
    for r in wire.rifs(LINK, frm):
        nr = r["frame"]["netrom"]
        if "error" in nr:
            problems.append(f"undecodable RIF ({nr['error']}): {r['raw']}")
        for rip in nr["rips"]:
            if not 1 <= rip["hops"] <= 255:
                problems.append(f"{rip['call']} hops={rip['hops']} (spec: 1..255)")
            if not 1 <= rip["tt"] <= HORIZON_TT:
                problems.append(f"{rip['call']} tt={rip['tt']} (spec: 1..60000)")
    return problems


def test_xrouter_rif_fields_in_spec_range(wire, converged):
    """[INP3] fig. 1: hop counter 1..255, transport time 1..60000 (10 ms units)."""
    problems = _check_rips(wire, "xrouter")
    assert wire.rifs(LINK, "xrouter"), "no XRouter RIF to check"
    assert not problems, ("XRouter RIPs outside the ranges in [INP3] figure 1:\n  " +
                          "\n  ".join(sorted(set(problems))) + f"\nRIFs:\n{lines(wire.rifs(LINK, 'xrouter'))}")


def test_bpq_rif_fields_in_spec_range(wire, converged):
    """[INP3] fig. 1: hop counter 1..255, transport time 1..60000 (10 ms units)."""
    problems = _check_rips(wire, "linbpq")
    assert wire.rifs(LINK, "linbpq"), "no LinBPQ RIF to check"
    assert not problems, ("LinBPQ RIPs outside the ranges in [INP3] figure 1:\n  " +
                          "\n  ".join(sorted(set(problems))) + f"\nRIFs:\n{lines(wire.rifs(LINK, 'linbpq'))}")


def test_own_node_rip_has_hop_count_one(wire, converged):
    """[INP3]: 'For the own node, a RIP is created and sent after the interlink
    has been established. The hop-counter has to be 1.'"""
    bad = []
    for frm, own in (("xrouter", XR_CALL), ("linbpq", BPQ_CALL)):
        own_rips = [(rip, r) for rip, r in wire.rips(LINK, frm) if rip["call"] == own]
        assert own_rips, f"{frm} never sent a RIP for its own node {own}:\n{lines(wire.rifs(LINK, frm))}"
        bad += [r for rip, r in own_rips if rip["hops"] != 1]
    assert not bad, f"own-node RIP with hop count other than 1:\n{lines(bad)}"


def test_rif_has_one_rip_per_destination(wire, converged):
    dups = []
    for frm in ("xrouter", "linbpq"):
        for r in wire.rifs(LINK, frm):
            calls = [rip["call"] for rip in r["frame"]["netrom"]["rips"]]
            if len(calls) != len(set(calls)):
                dups.append(r)
    assert not dups, f"a RIF listing the same destination more than once:\n{lines(dups)}"


def test_no_positive_route_advertised_back_to_its_neighbour(wire, converged):
    """[INP3] 'A backward information is never returned to the neighbor': it may
    be poisoned (tt=60000) or replaced by an alternate route, and there is no
    alternate here, so anything advertised back must carry the horizon."""
    bad = [r for rip, r in wire.rips(LINK, "xrouter") if rip["call"] in BEHIND_BPQ and rip["tt"] < HORIZON_TT]
    bad += [r for rip, r in wire.rips(LINK, "linbpq") if rip["call"] in BEHIND_XR and rip["tt"] < HORIZON_TT]
    assert not bad, f"positive route returned to the neighbour it was learned from:\n{lines(bad)}"


# ---------------------------------------------------------------- routes marked INP3


def test_xrouter_marks_bpq_route_as_inp3(xr, converged):
    """MAN ROUTES: R T flags 2 = neighbour is INP3 compatible, 4 = responds to L3RTT."""
    def look():
        r = xr_routes(xr.cmd("R T")).get(BPQ_CALL)
        return r if r and "flags" in r and r["flags"] & 6 == 6 else None

    got = wait_for(look, 30)
    assert got, f"XRouter does not flag {BPQ_CALL} as INP3 + L3RTT (flags & 6):\n{xr.cmd('R T')}\n{xr.cmd('R 1 ' + BPQ_CALL)}"


def test_bpq_marks_xrouter_route_as_inp3(bpq, converged):
    """BPQ prints SRTT columns in R V only for INP3 neighbours, and N <call> lists
    INP3 routes as `hops time port via hh:mm`."""
    r = bpq_routes(bpq.cmd("R V")).get(XR_CALL)
    assert r and r["inp3"], f"LinBPQ does not show {XR_CALL} as an INP3 neighbour:\n{bpq.cmd('R V')}"
    routes = bpq_node_routes(bpq.cmd(f"N {XR_CALL}"))
    assert any(x["via"] == XR_CALL and x["hops"] == 1 for x in routes["inp3"]), \
        f"LinBPQ has no INP3 (time) route to {XR_CALL} at hop 1:\n{bpq.cmd('N ' + XR_CALL)}"


# ---------------------------------------------------------------- propagation


def test_xrouter_learns_bpq_application_by_inp3(xr, wire, converged):
    rips = [r for rip, r in wire.rips(LINK, "linbpq") if rip["call"] == BPQ_APP_CALL and rip["tt"] < HORIZON_TT]
    assert rips, f"LinBPQ never advertised {BPQ_APP_CALL} by RIF:\n{lines(wire.rifs(LINK, 'linbpq'))}"
    routes = xr_node_routes(xr.cmd(f"N {BPQ_APP_ALIAS}"))
    via = [x for x in routes if x["via"] == BPQ_CALL]
    assert via and via[0].get("hops") == 1, f"XRouter route to {BPQ_APP_ALIAS} lacks INP3 hop 1 via {BPQ_CALL}:\n{xr.cmd('N ' + BPQ_APP_ALIAS)}"


def test_third_party_node_reaches_xrouter_by_inp3(xr, wire, converged):
    """PN0BQB is only linked to LinBPQ. LinBPQ must advertise it to XRouter in a
    RIF at hop 2 with a positive trip time, and XRouter must route it via PN0BQ."""
    rips = [(rip, r) for rip, r in wire.rips(LINK, "linbpq") if rip["call"] == BPQ2_CALL]
    assert rips, (f"LinBPQ never sent {BPQ2_CALL} to XRouter by RIF. LinBPQ RIFs:\n"
                  f"{lines(wire.rifs(LINK, 'linbpq'))}\nLinBPQ2 link RIFs:\n{lines(wire.frames(link=LINK2, kind='RIF'))}")
    last, rec = rips[-1]
    assert last["hops"] == 2 and 1 <= last["tt"] < HORIZON_TT, f"unexpected RIP for {BPQ2_CALL}:\n{lines([rec])}"
    text = xr.cmd(f"N {BPQ2_ALIAS}")
    routes = xr_node_routes(text)
    via = [x for x in routes if x["via"] == BPQ_CALL]
    assert via, f"XRouter has no route to {BPQ2_ALIAS} via {BPQ_CALL}:\n{text}"
    assert via[0].get("hops") == 2, f"XRouter's hop count to {BPQ2_ALIAS} is not 2:\n{text}"
    assert via[0].get("obs2", 0) > 0, f"XRouter holds no live time-domain (Obs2) info for {BPQ2_ALIAS}:\n{text}"
    # N + lists the trip time to each node: one hop further must not be quicker.
    plus = xr.cmd("N +")
    tt = {}
    for ln in plus.splitlines():
        p = ln.split()
        if len(p) == 8 and ":" in p[0] and p[1].isdigit():
            tt[p[0].split(":")[1]] = float(p[5])
    assert BPQ2_CALL in tt and BPQ_CALL in tt, f"N + lacks trip times:\n{plus}"
    assert tt[BPQ_CALL] <= tt[BPQ2_CALL] < 600, f"implausible trip times (s) {tt}:\n{plus}"


def test_xrouter_nodes_reach_bpq2_through_bpq(bpq2, converged):
    """The reverse direction: XRouter's own node and application go XRouter ->
    LinBPQ -> LinBPQ2 by INP3, arriving at hop 2."""
    def look():
        out = {}
        for call in (XR_CALL, XR_APP_CALL):
            routes = bpq_node_routes(bpq2.cmd(f"N {call}"))["inp3"]
            if not any(x["hops"] == 2 for x in routes):
                return None
            out[call] = routes
        return out

    got = wait_for(look, 60, 5)
    assert got, ("LinBPQ2 has no INP3 route at hop 2 to XRouter's node and application:\n" +
                 bpq2.cmd(f"N {XR_CALL}") + "\n" + bpq2.cmd(f"N {XR_APP_CALL}") + "\n" + bpq2.cmd("N"))


def test_bpq_learns_xrouter_application_by_inp3(bpq, wire, converged):
    rips = [r for rip, r in wire.rips(LINK, "xrouter") if rip["call"] == XR_APP_CALL and rip["tt"] < HORIZON_TT]
    assert rips, f"XRouter never advertised its application {XR_APP_CALL} by RIF:\n{lines(wire.rifs(LINK, 'xrouter'))}"
    routes = bpq_node_routes(bpq.cmd(f"N {XR_APP_CALL}"))["inp3"]
    assert any(x["via"] == XR_CALL and x["hops"] == 1 for x in routes), \
        f"LinBPQ has no INP3 route to {XR_APP_CALL} via {XR_CALL}:\n{bpq.cmd('N ' + XR_APP_CALL)}"
