"""XRouter against a second XRouter of another version (PN0XP, XRPEER).

The peer links only to the XRouter under test, so it learns LinBPQ and its
neighbours through that XRouter by INP3, and LinBPQ learns the peer the same
way. Both ends advertise `$V4` in L3RTT (MAN L3RTT: "INP version number (v4
and above)"), and between two V4 XRouters the hop count in a RIP carries
0x80 for some routes (see FINDINGS, XRouter to XRouter hop flag); the peer
decodes those as the plain hop count, so the relay check masks that bit.
"""


from conftest import (BPQ2_CALL, BPQ_APP_CALL, BPQ_CALL, LINK, LINK_XRPEER, XR_APP_CALL, XR_CALL,
                      XRPEER_APP_ALIAS, XRPEER_APP_CALL, XRPEER_CALL, needs_peer)
from parse import bpq_node_routes, xr_node_plus, xr_routes
from peerwire import (HORIZON_TT, link_setup, nodes_from, reflections, relay_problems, rip_problems,
                      show, ua_between, unreflected)
from wire import lines, wait_for

pytestmark = needs_peer("xrpeer")
PEER = "xrpeer"


def test_xrpeer_link_up(wire, peers_converged):
    got = wait_for(lambda: ua_between(wire, LINK_XRPEER, XR_CALL, XRPEER_CALL), 30)
    assert got, f"no UA between {XR_CALL} and {XRPEER_CALL}. Link set-up frames:\n{show(link_setup(wire, LINK_XRPEER))}"


def test_xrpeer_sends_nodes(wire, peers_converged):
    got = wait_for(lambda: nodes_from(wire, LINK_XRPEER, PEER, XRPEER_CALL), 90, 3)
    assert got, f"no NODES broadcast from the peer XRouter.\nUI frames from it:\n{show(wire.frames(link=LINK_XRPEER, frm=PEER))}"


def test_xrouter_sends_nodes_to_xrpeer(wire, peers_converged):
    got = wait_for(lambda: nodes_from(wire, LINK_XRPEER, "xrouter", XR_CALL, with_entries=True), 90, 3)
    assert got, ("XRouter never sent a NODES broadcast on its port to the peer XRouter (NODESINTERVAL=1). "
                 f"NODES it sent anywhere:\n{show([r for r in wire.frames(frm='xrouter', kind='NODES')])}")


def test_xrpeer_l3rtt_both_ways(wire, peers_converged):
    problems = []
    for prober, call, reflector in (("xrouter", XR_CALL, PEER), (PEER, XRPEER_CALL, "xrouter")):
        pairs = reflections(wire, LINK_XRPEER, prober, call, reflector)
        if not pairs:
            problems.append(f"no L3RTT probe from {prober}")
            continue
        if "$N" not in pairs[-1][0]["frame"]["netrom"]["l3rtt"].get("flags", []):
            problems.append(f"{prober} L3RTT lacks $N: {lines(pairs[-1][:1])}")
        missing = unreflected(pairs, wire)
        if missing:
            problems.append(f"{reflector} did not reflect:\n{lines(missing)}")
    assert not problems, "\n".join(problems) + f"\nL3RTT on the link:\n{show(wire.frames(link=LINK_XRPEER, kind='L3RTT'))}"


def test_xrpeer_rif_both_ways(wire, peers_converged):
    assert wire.rifs(LINK_XRPEER, "xrouter"), "XRouter never sent a RIF to the peer XRouter"
    assert wire.rifs(LINK_XRPEER, PEER), "the peer XRouter never sent a RIF to XRouter"


def test_xrouter_rif_to_xrpeer_fields_in_spec_range(wire, peers_converged):
    assert wire.rifs(LINK_XRPEER, "xrouter"), "no RIF to check"
    problems = rip_problems(wire, LINK_XRPEER, "xrouter")
    assert not problems, "XRouter RIPs to the peer outside [INP3] figure 1:\n  " + "\n  ".join(problems) + \
        f"\n{show(wire.rifs(LINK_XRPEER, 'xrouter'))}"


def test_xrpeer_rif_fields_in_spec_range(wire, peers_converged):
    assert wire.rifs(LINK_XRPEER, PEER), "no RIF to check"
    problems = rip_problems(wire, LINK_XRPEER, PEER)
    assert not problems, "peer XRouter RIPs outside [INP3] figure 1:\n  " + "\n  ".join(problems) + \
        f"\n{show(wire.rifs(LINK_XRPEER, PEER))}"


def test_xrouter_marks_xrpeer_as_inp3(xr, peers_converged):
    def look():
        r = xr_routes(xr.cmd("R T")).get(XRPEER_CALL)
        return r if r and r.get("flags", 0) & 6 == 6 else None
    assert wait_for(look, 30), f"XRouter does not flag {XRPEER_CALL} as INP3 + L3RTT:\n{xr.cmd('R T')}"


def test_xrpeer_marks_xrouter_as_inp3(xrp, peers_converged):
    def look():
        r = xr_routes(xrp.cmd("R T")).get(XR_CALL)
        return r if r and r.get("flags", 0) & 6 == 6 else None
    assert wait_for(look, 30), f"the peer XRouter does not flag {XR_CALL} as INP3 + L3RTT:\n{xrp.cmd('R T')}"


def test_xrpeer_learns_network_through_xrouter(xrp, peers_converged):
    """The peer's only neighbour is XRouter: it must time-route to everything
    behind it, one hop further than XRouter is."""
    want = {XR_CALL: 1, XR_APP_CALL: 1, BPQ_CALL: 2, BPQ_APP_CALL: 2, BPQ2_CALL: 3}

    def look():
        nodes = xr_node_plus(xrp.cmd("N +", 1.5))
        ok = all(c in nodes and nodes[c]["via"] == XR_CALL and nodes[c]["hops"] == h and nodes[c]["obs2"] > 0
                 and nodes[c]["tt"] < 600 for c, h in want.items())
        return nodes if ok else None

    got = wait_for(look, 60, 5)
    assert got, f"peer XRouter lacks INP3 routes via {XR_CALL} at hop counts {want}:\n{xrp.cmd('N +')}"


def test_xrouter_learns_xrpeer_by_inp3(xr, peers_converged):
    want = {XRPEER_CALL: 1, XRPEER_APP_CALL: 1}

    def look():
        nodes = xr_node_plus(xr.cmd("N +", 1.5))
        ok = all(c in nodes and nodes[c]["via"] == XRPEER_CALL and nodes[c]["hops"] == h and nodes[c]["obs2"] > 0
                 for c, h in want.items())
        return nodes if ok else None

    got = wait_for(look, 60, 5)
    assert got, f"XRouter lacks INP3 routes to the peer and its application {want}:\n{xr.cmd('N +')}\n{xr.cmd('N ' + XRPEER_APP_ALIAS)}"


def test_xrouter_relays_bpq_routes_to_xrpeer(wire, peers_converged):
    problems, evidence = relay_problems(wire, LINK, "linbpq", LINK_XRPEER, "xrouter",
                                        (BPQ_CALL, BPQ_APP_CALL, BPQ2_CALL), hop_mask=0x7F)
    assert not problems, "\n".join(problems) + f"\nEvidence:\n{show(evidence, 20)}"


def test_xrouter_relays_xrpeer_routes_to_bpq(wire, peers_converged):
    """XRouter talks to LinBPQ without $V4, so the hop counts must be plain."""
    problems, evidence = relay_problems(wire, LINK_XRPEER, PEER, LINK, "xrouter", (XRPEER_CALL, XRPEER_APP_CALL))
    assert not problems, "\n".join(problems) + f"\nEvidence:\n{show(evidence, 20)}"


def test_xrpeer_reaches_bpq2_through_xrouter(bpq2, peers_converged):
    """Two INP3 hops away from the peer: XRPEER -> XRouter -> LinBPQ -> LinBPQ2."""
    def look():
        routes = bpq_node_routes(bpq2.cmd(f"N {XRPEER_CALL}"))["inp3"]
        return routes if any(x["hops"] == 3 and x["tt"] < 600 for x in routes) else None
    got = wait_for(look, 60, 5)
    assert got, f"LinBPQ2 has no INP3 route at hop 3 to {XRPEER_CALL}:\n{bpq2.cmd('N ' + XRPEER_CALL)}"


def test_no_positive_route_advertised_back_to_xrpeer(wire, peers_converged):
    """[INP3] poisoned reverse: what XRouter learned from the peer goes back
    to it only with the horizon trip time."""
    behind = {XRPEER_CALL, XRPEER_APP_CALL}
    bad = [r for rip, r in wire.rips(LINK_XRPEER, "xrouter") if rip["call"] in behind and rip["tt"] < HORIZON_TT]
    bad += [r for rip, r in wire.rips(LINK_XRPEER, PEER) if rip["call"] in {XR_CALL, XR_APP_CALL, BPQ_CALL}
            and rip["tt"] < HORIZON_TT]
    assert not bad, f"positive route returned to the neighbour it came from:\n{lines(bad)}"


def test_l4_connect_xrouter_to_xrpeer(xr, peers_converged):
    out = xr.ask("C XRPEER", r"Connected to|Failure|Busy|not known|Unknown", 45)
    assert f"Connected to {XRPEER_CALL}" in out or "XRPEER:PN0XP" in out, f"XRouter could not connect to XRPEER:\n{out}"


def test_l4_connect_xrpeer_to_bpq2_through_xrouter(xrp, peers_converged):
    """Three hops with the XRouter under test in the middle."""
    out = xrp.ask("C BPQB", r"Connected to|Failure|Busy|not known|Unknown", 60)
    assert "Connected to" in out and "PN0BQB" in out, f"the peer XRouter could not reach BPQB through XRouter:\n{out}"
    out = xrp.ask("V", r"Version 6\.")
    assert "Version 6." in out, f"no reply from LinBPQ2 through the circuit:\n{out}"


def test_l4_connect_bpq_to_xrpeer(bpq, peers_converged):
    out = bpq.ask("C XRPEER", r"Connected to|Failure|Busy|not known|Unknown", 45)
    assert "Connected to XRPEER:PN0XP" in out, f"LinBPQ could not connect to XRPEER through XRouter:\n{out}"
    out = bpq.ask("V", r"XrLin|XRouter")
    assert "XRouter" in out or "XrLin" in out, f"no reply from the peer XRouter through the circuit:\n{out}"


def test_xrouter_passes_xrpeer_alias_to_bpq3(wire, peers_converged):
    from peerchecks import Peer, peer_alias_reaches_bpq3
    peer_alias_reaches_bpq3(wire, Peer(PEER, "the peer XRouter", LINK_XRPEER, XRPEER_CALL, "XRPEER"))
