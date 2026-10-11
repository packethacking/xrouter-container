"""XRouter and TheNetNode 1.79 (TNN): NET/ROM and INP3 over AXUDP.

TNN (PN0TN, TNN) links only to XRouter, with a link entry of type I (INP3)
for it (peers/tnn/templates/tnn179.tnb). TNN sends no NODES broadcasts to an
INP3 neighbour at all, by design (src/l3misc.c: for a peer of type INP only
RIFs are sent), so XRouter learns TNN by INP3 alone.

TNN adds one to every hop counter it receives (src/l3inp.c, "Hop-Counter
erhoehen"), except for the neighbour itself, so its `LT` column is one more
than INP3's hop count for anything further away; the console checks allow
for that (see FINDINGS).
"""

import re

from conftest import (BPQ2_ALIAS, BPQ2_CALL, BPQ_CALL, LINK_TNN, TNN_ALIAS, TNN_CALL, XR_ALIAS, XR_APP_CALL,
                      XR_CALL, needs_peer)
from parse import tnn_node_routes, tnn_nodes, tnn_routes, xr_node_list
from peerchecks import Peer
import peerchecks as pc
from wire import wait_for

pytestmark = needs_peer("tnn")
P = Peer("tnn", "TNN", LINK_TNN, TNN_CALL, TNN_ALIAS)


def test_tnn_link_up(wire, peers_converged):
    pc.link_up(wire, P)


def test_xrouter_sends_nodes_to_tnn(wire, peers_converged):
    """Sent by the CRONTAB work-around (see config/xrouter/CRONTAB.SYS)."""
    pc.xrouter_sends_nodes(wire, P)


def test_xrouter_lists_tnn_node(xr, peers_converged):
    """TNN sends no NODES to an INP3 neighbour, so this comes from INP3."""
    text = wait_for(lambda: (t := xr.cmd("N")) and f"{TNN_ALIAS}:{TNN_CALL}" in xr_node_list(t) and t, 30)
    assert text, f"XRouter NODES does not list {TNN_ALIAS}:{TNN_CALL}:\n{xr.cmd('N')}"


def test_tnn_l3rtt_probes_reflected_by_xrouter(wire, peers_converged):
    pc.l3rtt_probes_and_reflections(wire, P, "tnn")


def test_xrouter_l3rtt_probes_reflected_by_tnn(wire, peers_converged):
    pc.l3rtt_probes_and_reflections(wire, P, "xrouter")


def test_tnn_l3rtt_fields_fit(wire, peers_converged):
    """The 32-bit build keeps TNN's numbers in range (a 64-bit build does not)."""
    pc.l3rtt_fields_fit(wire, P, "tnn")


def test_tnn_sends_rif(wire, peers_converged):
    pc.rif_sent(wire, P, "tnn")


def test_xrouter_sends_rif_to_tnn(wire, peers_converged):
    pc.rif_sent(wire, P, "xrouter")


def test_tnn_rif_fields_in_spec_range(wire, peers_converged):
    pc.rif_fields_in_range(wire, P, "tnn")


def test_xrouter_rif_to_tnn_fields_in_spec_range(wire, peers_converged):
    pc.rif_fields_in_range(wire, P, "xrouter")


def test_tnn_own_node_rip_has_hop_count_one(wire, peers_converged):
    pc.own_rip_hop_one(wire, P, "tnn")


def test_tnn_link_one_rip_per_destination(wire, peers_converged):
    pc.one_rip_per_destination(wire, P)


def test_tnn_link_no_positive_route_advertised_back(wire, peers_converged):
    pc.poisoned_reverse(wire, P)


def test_xrouter_marks_tnn_as_inp3(xr, peers_converged):
    pc.xrouter_marks_inp3(xr, P)


def test_tnn_marks_xrouter_as_inp3(tnn, peers_converged):
    """TNN `ROUTES`: Typ I is an INP3 neighbour."""
    def look():
        e = tnn_routes(tnn.cmd("ROUTES")).get(XR_CALL)
        return e if e and e["type"] == "I" else None
    got = wait_for(look, 30, 3)
    assert got, f"TNN does not show {XR_CALL} as an INP3 (I) neighbour:\n{tnn.cmd('ROUTES')}"


def test_xrouter_learns_tnn_by_inp3(xr, peers_converged):
    pc.xrouter_learns_peer(xr, P)


def test_tnn_learns_network_through_xrouter(tnn, peers_converged):
    """TNN must route XRouter, its application and LinBPQ's nodes via XRouter,
    with the INP3 hop counts (plus TNN's one extra beyond the neighbour)."""
    want = {XR_CALL: (XR_ALIAS, 1), XR_APP_CALL: ("XRAPP", 1), BPQ_CALL: ("BPQNOD", 2), BPQ2_CALL: (BPQ2_ALIAS, 3)}

    def look():
        nodes = tnn_nodes(tnn.cmd("NODES"))
        if any(c not in nodes for c in want):
            return None
        out = {}
        for call, (alias, hops) in want.items():
            routes = [r for r in tnn_node_routes(tnn.cmd(f"NODES {call}", 2.5)) if r["via"] == XR_CALL]
            if not routes or routes[0]["hops"] != (hops if call == XR_CALL else hops + 1):
                return None
            out[call] = routes[0]
        return out

    got = wait_for(look, 60, 5)
    assert got, (f"TNN lacks routes via {XR_CALL} with INP3 hop counts {want}:\n{tnn.cmd('NODES')}\n" +
                 "\n".join(tnn.cmd(f"NODES {c}", 2.5) for c in want))


def test_tnn_knows_aliases_of_relayed_nodes(tnn, peers_converged):
    """TNN only learns aliases from the INP3 alias option, so this shows
    whether XRouter passed them on."""
    want = {XR_CALL: XR_ALIAS, XR_APP_CALL: "XRAPP", BPQ_CALL: "BPQNOD", BPQ2_CALL: BPQ2_ALIAS}
    nodes = tnn_nodes(tnn.cmd("NODES"))
    wrong = {c: nodes.get(c) for c, a in want.items() if nodes.get(c) != a}
    assert not wrong, f"TNN has the wrong alias (or none) for {wrong}:\n{tnn.cmd('NODES')}"


def test_xrouter_relays_bpq_routes_to_tnn(wire, peers_converged):
    pc.relays_bpq_routes_to_peer(wire, P)


def test_xrouter_relays_tnn_to_bpq(wire, peers_converged):
    pc.relays_peer_routes_to_bpq(wire, P)


def test_alias_travels_with_route_relayed_to_tnn(wire, peers_converged):
    pc.alias_travels_to_peer(wire, P)


def test_tnn_reaches_bpq2_through_xrouter(bpq2, peers_converged):
    pc.peer_route_reaches_bpq2(bpq2, P)


def test_l4_connect_xrouter_to_tnn(xr, peers_converged):
    out = xr.ask(f"C {TNN_ALIAS}", r"Connected to|Failure|Busy|not known|Unknown", 45)
    assert f"Connected to {TNN_CALL}" in out, f"XRouter could not connect to {TNN_ALIAS}:\n{out}"
    more = xr.drain(2, 10)
    assert "PN0TN" in out + more, f"no TNN prompt through the circuit:\n{out}{more}"


def test_l4_connect_tnn_to_xrouter(tnn, peers_converged):
    out = tnn.ask(f"C {XR_ALIAS}", r"Connected to|Failure|Busy|not found|unknown", 45)
    assert re.search(rf"Connected to {XR_ALIAS}:{XR_CALL}", out, re.I), f"TNN could not connect to {XR_ALIAS}:\n{out}"
    more = tnn.ask("V", r"XrLin|XRouter", 20)
    assert "XRouter" in more or "XrLin" in more, f"no reply from XRouter's V command through the circuit:\n{more}"


def test_l4_connect_tnn_to_bpq2_through_xrouter(tnn, peers_converged):
    # By callsign: whether TNN knows the alias is test_tnn_knows_aliases_of_relayed_nodes.
    out = tnn.ask(f"C {BPQ2_CALL}", r"Connected to|Failure|Busy|not found|unknown", 60)
    assert re.search(r"Connected to", out, re.I) and BPQ2_CALL in out.upper(), f"TNN could not reach {BPQ2_CALL}:\n{out}"
    out = tnn.ask("V", r"Version 6\.", 20)
    assert "Version 6." in out, f"no reply from LinBPQ2 through the circuit:\n{out}"


def test_l4_connect_bpq_to_tnn(bpq, peers_converged):
    pc.l4_from_bpq(bpq, P, "PN0TN")


def test_xrouter_passes_tnn_alias_to_bpq3(wire, peers_converged):
    pc.peer_alias_reaches_bpq3(wire, P)
