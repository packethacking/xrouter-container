"""XRouter and XNet 1.38 (DL1GJI): NET/ROM and INP3 over AXUDP.

XNet (PN0XN, XNET) links only to XRouter, so LinBPQ hears of it only through
XRouter and XNet hears of LinBPQ only through XRouter. XNet opens the link
only after it hears a NODES broadcast from XRouter, then switches the link
to INP3 by itself once L3RTT is answered (there is no INP3 setting).

XNet counts a direct neighbour as 2 hops in its own tables (one more than
INP3's hop counter); the console checks allow for that.
"""

import re

from conftest import (BPQ2_ALIAS, BPQ2_CALL, BPQ_CALL, LINK_XNET, XNET_ALIAS, XNET_CALL, XR_ALIAS, XR_APP_CALL,
                      XR_CALL, needs_peer)
from parse import xnet_links, xnet_nodes, xnet_route
from peerchecks import Peer
import peerchecks as pc
from wire import wait_for

pytestmark = needs_peer("xnet")
P = Peer("xnet", "XNet", LINK_XNET, XNET_CALL, XNET_ALIAS)


def test_xnet_link_up(wire, peers_converged):
    pc.link_up(wire, P)


def test_xnet_sends_nodes(wire, peers_converged):
    pc.peer_sends_nodes(wire, P, 120)


def test_xrouter_sends_nodes_to_xnet(wire, peers_converged):
    """Sent by the CRONTAB work-around (see config/xrouter/CRONTAB.SYS)."""
    pc.xrouter_sends_nodes(wire, P)


def test_xnet_l3rtt_probes_reflected_by_xrouter(wire, peers_converged):
    pc.l3rtt_probes_and_reflections(wire, P, "xnet")


def test_xrouter_l3rtt_probes_reflected_by_xnet(wire, peers_converged):
    pc.l3rtt_probes_and_reflections(wire, P, "xrouter")


def test_xnet_l3rtt_fields_fit(wire, peers_converged):
    pc.l3rtt_fields_fit(wire, P, "xnet")


def test_xnet_sends_rif(wire, peers_converged):
    pc.rif_sent(wire, P, "xnet")


def test_xrouter_sends_rif_to_xnet(wire, peers_converged):
    pc.rif_sent(wire, P, "xrouter")


def test_xnet_rif_fields_in_spec_range(wire, peers_converged):
    pc.rif_fields_in_range(wire, P, "xnet")


def test_xrouter_rif_to_xnet_fields_in_spec_range(wire, peers_converged):
    pc.rif_fields_in_range(wire, P, "xrouter")


def test_xnet_own_node_rip_has_hop_count_one(wire, peers_converged):
    pc.own_rip_hop_one(wire, P, "xnet")


def test_xnet_link_one_rip_per_destination(wire, peers_converged):
    pc.one_rip_per_destination(wire, P)


def test_xnet_link_no_positive_route_advertised_back(wire, peers_converged):
    pc.poisoned_reverse(wire, P)


def test_xrouter_marks_xnet_as_inp3(xr, peers_converged):
    pc.xrouter_marks_inp3(xr, P)


def test_xnet_marks_xrouter_as_inp3(xnet, peers_converged):
    """XNet's `l` shows the link type; `I` is an INP3 link."""
    def look():
        e = xnet_links(xnet.cmd("l")).get(XR_CALL)
        return e if e and e["type"] == "I" else None
    got = wait_for(look, 30, 3)
    assert got, f"XNet does not list {XR_CALL} as an INP3 (I) link:\n{xnet.cmd('l')}"


def test_xrouter_learns_xnet_by_inp3(xr, peers_converged):
    pc.xrouter_learns_peer(xr, P)


def test_xnet_learns_network_through_xrouter(xnet, peers_converged):
    """XNet must route XRouter, its application and LinBPQ's nodes via XRouter
    with the hop counts INP3 gives (plus XNet's one extra)."""
    want = {XR_CALL: 1, XR_APP_CALL: 1, BPQ_CALL: 2, BPQ2_CALL: 3}

    def look():
        out = {}
        for call, hops in want.items():
            routes = [r for r in xnet_route(xnet.cmd(f"n {call}", 2.5)) if r["call"] == call and r["via"] == XR_CALL]
            if not routes or routes[0]["hops"] != hops + 1:
                return None
            out[call] = routes[0]
        return out

    got = wait_for(look, 60, 5)
    assert got, (f"XNet lacks routes via {XR_CALL} with INP3 hop counts {want}:\n{xnet.cmd('n')}\n" +
                 "\n".join(xnet.cmd(f"n {c}", 2.5) for c in want))


def test_xnet_knows_aliases_of_relayed_nodes(xnet, peers_converged):
    """XNet labels a node it learned without an alias `#tmp`. It hears
    aliases from XRouter's RIFs (the alias option) and NODES."""
    want = {XR_CALL: XR_ALIAS, XR_APP_CALL: "XRAPP", BPQ_CALL: "BPQNOD", BPQ2_CALL: BPQ2_ALIAS}
    nodes = xnet_nodes(xnet.cmd("n"))
    wrong = {c: nodes.get(c) for c, a in want.items() if nodes.get(c) != a}
    assert not wrong, f"XNet has the wrong alias (or none) for {wrong}:\n{xnet.cmd('n')}"


def test_xrouter_relays_bpq_routes_to_xnet(wire, peers_converged):
    pc.relays_bpq_routes_to_peer(wire, P)


def test_xrouter_relays_xnet_to_bpq(wire, peers_converged):
    pc.relays_peer_routes_to_bpq(wire, P)


def test_alias_travels_with_route_relayed_to_xnet(wire, peers_converged):
    pc.alias_travels_to_peer(wire, P)


def test_xnet_reaches_bpq2_through_xrouter(bpq2, peers_converged):
    pc.peer_route_reaches_bpq2(bpq2, P)


def test_l4_connect_xrouter_to_xnet(xr, peers_converged):
    out = xr.ask(f"C {XNET_ALIAS}", r"Connected to|Failure|Busy|not known|Unknown", 45)
    assert f"Connected to {XNET_CALL}" in out, f"XRouter could not connect to {XNET_ALIAS}:\n{out}"
    more = xr.drain(2, 10)
    assert "(X)NET" in out + more, f"no XNet greeting through the circuit:\n{out}{more}"


def test_l4_connect_xnet_to_xrouter(xnet, peers_converged):
    out = xnet.ask(f"C {XR_ALIAS}", r"connected to|failure|busy|not found|no route", 45)
    assert re.search(rf"connected to {XR_CALL}", out, re.I), f"XNet could not connect to {XR_ALIAS}:\n{out}"
    more = xnet.ask("V", r"XrLin|XRouter", 20)
    assert "XRouter" in more or "XrLin" in more, f"no reply from XRouter's V command through the circuit:\n{more}"


def test_l4_connect_xnet_to_bpq2_through_xrouter(xnet, peers_converged):
    # By callsign: whether XNet knows the alias is test_xnet_knows_aliases_of_relayed_nodes.
    out = xnet.ask(f"C {BPQ2_CALL}", r"connected to|failure|busy|not found|no route|unknown", 60)
    assert "connected to" in out.lower() and BPQ2_CALL in out.upper(), f"XNet could not reach {BPQ2_CALL}:\n{out}"
    out = xnet.ask("V", r"Version 6\.", 20)
    assert "Version 6." in out, f"no reply from LinBPQ2 through the circuit:\n{out}"


def test_l4_connect_bpq_to_xnet(bpq, peers_converged):
    pc.l4_from_bpq(bpq, P, "(X)NET")


def test_xrouter_passes_xnet_alias_to_bpq3(wire, peers_converged):
    pc.peer_alias_reaches_bpq3(wire, P)
