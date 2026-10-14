"""XRouter and TheNet X1J (on the tnc2-emu TNC-2 emulator): plain NET/ROM.

TheNet (PN0TH, THENET) predates INP3, so this is NET/ROM only: NODES both
ways, routes, layer 4 circuits both ways, and that XRouter's INP3 does no
harm (it must not treat TheNet as INP3, must not send it RIFs, and TheNet must
keep XRouter as a working neighbour despite the L3RTT probes it cannot
reflect). The link is TCP KISS at a simulated 1200 bit/s, through the relay's
KISS tap, so frames are logged like the AXUDP links but carry no FCS.
"""

import re

from conftest import (BPQ2_ALIAS, BPQ_ALIAS, BPQ_CALL, LINK_THENET, THENET_ALIAS, THENET_CALL, XR_ALIAS,
                      XR_APP_CALL, XR_CALL, needs_peer)
from parse import bpq_node_list, thenet_nodes, thenet_routes, xr_node_list, xr_routes
from peerwire import link_setup, nodes_entries, nodes_from, show, ua_between
from wire import lines, wait_for

pytestmark = needs_peer("thenet")


def test_thenet_kiss_link_carries_frames_both_ways(wire, peers_converged):
    a = wire.frames(link=LINK_THENET, frm="xrouter")
    b = wire.frames(link=LINK_THENET, frm="thenet")
    assert a and b, f"expected frames both ways on the TheNet KISS link.\nxrouter:\n{show(a)}\nthenet:\n{show(b)}"


def test_thenet_sends_nodes(wire, peers_converged):
    got = wait_for(lambda: nodes_from(wire, LINK_THENET, "thenet", THENET_CALL, with_entries=True), 120, 3)
    assert got, f"no NODES broadcast with entries from TheNet:\n{show(wire.frames(link=LINK_THENET, frm='thenet'))}"


def test_xrouter_sends_nodes_to_thenet(wire, peers_converged):
    """Sent by the CRONTAB work-around (see config/xrouter/CRONTAB.SYS)."""
    got = wait_for(lambda: nodes_from(wire, LINK_THENET, "xrouter", XR_CALL, with_entries=True), 90, 3)
    assert got, f"XRouter sent TheNet no NODES broadcast with entries:\n{show(wire.frames(link=LINK_THENET, frm='xrouter'))}"


def test_xrouter_nodes_to_thenet_carry_bpq_side(wire, peers_converged):
    """XRouter's NODES on the TheNet port must list what it learned by INP3 from
    LinBPQ, since that is the only way TheNet can learn it."""
    want = {BPQ_CALL, "PN0BQB", "PN0BQ-1"}
    got = wait_for(lambda: want <= nodes_entries(wire, LINK_THENET, "xrouter"), 60, 3)
    assert got, (f"XRouter's NODES to TheNet never listed {sorted(want - nodes_entries(wire, LINK_THENET, 'xrouter'))}:\n"
                 f"{show(wire.frames(link=LINK_THENET, frm='xrouter', kind='NODES'))}")


def test_xrouter_lists_thenet_as_neighbour(xr, peers_converged):
    text = wait_for(lambda: (t := xr.cmd("R")) and THENET_CALL in xr_routes(t) and t, 30)
    assert text, f"XRouter ROUTES does not list {THENET_CALL}:\n{xr.cmd('R')}"


def test_xrouter_lists_thenet_node(xr, peers_converged):
    text = wait_for(lambda: (t := xr.cmd("N")) and f"{THENET_ALIAS}:{THENET_CALL}" in xr_node_list(t) and t, 30)
    assert text, f"XRouter NODES does not list {THENET_ALIAS}:{THENET_CALL}:\n{xr.cmd('N')}"


def test_thenet_lists_xrouter_as_neighbour(thenet, peers_converged):
    got = wait_for(lambda: XR_CALL in thenet_routes(thenet.cmd("ROUTES")), 30, 3)
    assert got, f"TheNet ROUTES does not list {XR_CALL}:\n{thenet.cmd('ROUTES')}"


def test_thenet_learns_network_through_xrouter(thenet, peers_converged):
    want = {XR_CALL: XR_ALIAS, XR_APP_CALL: "XRAPP", BPQ_CALL: BPQ_ALIAS, "PN0BQB": BPQ2_ALIAS}
    def look():
        nodes = thenet_nodes(thenet.cmd("NODES"))
        return nodes if all(nodes.get(c) == a for c, a in want.items()) else None
    got = wait_for(look, 60, 5)
    assert got, f"TheNet NODES lacks {want}:\n{thenet.cmd('NODES')}"


def test_bpq_learns_thenet_through_xrouter(bpq, peers_converged):
    text = wait_for(lambda: (t := bpq.cmd("N")) and f"{THENET_ALIAS}:{THENET_CALL}" in bpq_node_list(t) and t, 60, 5)
    assert text, f"LinBPQ NODES does not list {THENET_ALIAS}:{THENET_CALL}:\n{bpq.cmd('N')}"


def test_xrouter_passes_thenet_alias_to_bpq3(wire, peers_converged):
    """XRouter turns TheNet's NET/ROM route into INP3 for its other
    neighbours; it knows the alias from TheNet's NODES, so the first positive
    RIP should carry it as [INP3] asks."""
    import peerchecks as pc
    pc.peer_alias_reaches_bpq3(wire, pc.Peer("thenet", "TheNet", LINK_THENET, THENET_CALL, THENET_ALIAS),
                               alias_source="nodes")


# ---------------------------------------------------------------- INP3 does no harm


def test_xrouter_does_not_mark_thenet_as_inp3(xr, wire, peers_converged):
    """TheNet never answers L3RTT, so XRouter must not flag it INP3 (2) or as
    answering L3RTT (4) (MAN ROUTES)."""
    r = xr_routes(xr.cmd("R T")).get(THENET_CALL)
    assert r, f"XRouter has no route entry for {THENET_CALL}:\n{xr.cmd('R T')}"
    assert r.get("flags", 0) & 6 == 0, f"XRouter flags TheNet as INP3 or L3RTT capable:\n{xr.cmd('R T')}"


def test_xrouter_sends_no_rif_to_thenet(wire, peers_converged):
    """A RIF is an I frame whose first byte is 0xFF; to TheNet that is not a
    valid NET/ROM layer 3 header."""
    rifs = wire.rifs(LINK_THENET, "xrouter")
    assert not rifs, f"XRouter sent RIFs to TheNet, which has never claimed INP3:\n{lines(rifs)}"


def test_thenet_does_not_reflect_or_route_l3rtt(wire, peers_converged):
    """Evidence only: TheNet has no L3RTT. It must neither answer nor send the
    probes anywhere (it has no route to the node `L3RTT`)."""
    sent = wire.l3rtt(LINK_THENET, "xrouter")
    back = wire.l3rtt(LINK_THENET, "thenet")
    assert not back, f"TheNet sent L3RTT frames back:\n{lines(back)}"
    assert sent is not None


def test_thenet_link_survives_l3rtt_probes(wire, thenet, peers_converged):
    """XRouter's L3RTT probes go to TheNet as NET/ROM frames it cannot
    route. The AX.25 link must stay up (no FRMR, no DM in reply to I frames)
    and TheNet must still list XRouter as its neighbour."""
    bad = [r for r in wire.frames(link=LINK_THENET, frm="thenet")
           if r["frame"].get("ctl", {}).get("type") in ("FRMR",)]
    assert not bad, f"TheNet rejected frames from XRouter:\n{lines(bad)}"
    assert XR_CALL in thenet_routes(thenet.cmd("ROUTES")), f"TheNet lost XRouter as a neighbour:\n{thenet.cmd('ROUTES')}"
    assert ua_between(wire, LINK_THENET, XR_CALL, THENET_CALL), \
        f"no AX.25 link set up between XRouter and TheNet:\n{show(link_setup(wire, LINK_THENET))}"


# ---------------------------------------------------------------- layer 4


def test_l4_connect_xrouter_to_thenet(xr, peers_converged):
    out = xr.ask(f"C {THENET_ALIAS}", r"Connected to|Failure|Busy|not known|Unknown", 90)
    assert re.search(rf"Connected to {THENET_CALL}", out), f"XRouter could not connect to {THENET_ALIAS}:\n{out}"
    out = xr.ask("NODES", re.escape(f"{THENET_ALIAS}:{THENET_CALL}}}"), 60)
    assert f"{THENET_ALIAS}:{THENET_CALL}}}" in out, f"no TheNet prompt through the circuit:\n{out}"


def test_l4_connect_thenet_to_xrouter(thenet, peers_converged):
    out = thenet.cmd(f"C {XR_ALIAS}", 6)
    out += thenet.drain(3, 60)
    assert re.search(r"connected to", out, re.I), f"TheNet could not connect to {XR_ALIAS}:\n{out}"
    out = thenet.cmd("V", 5)
    assert re.search(r"XRouter|Xrouter|XrLin|XrPi", out), f"no reply from XRouter's V command through the circuit:\n{out}"


def test_l4_connect_thenet_to_bpq2_through_xrouter(thenet, peers_converged):
    """Three NET/ROM hops, routed by TheNet on what XRouter broadcast."""
    out = thenet.cmd(f"C {BPQ2_ALIAS}", 8)
    out += thenet.drain(3, 90)
    assert re.search(r"connected to", out, re.I), f"TheNet could not reach {BPQ2_ALIAS} through XRouter:\n{out}"
    out = thenet.cmd("V", 8)
    assert "Version 6." in out, f"no reply from LinBPQ2 through the circuit:\n{out}"


def test_l4_connect_bpq_to_thenet(bpq, peers_converged):
    out = bpq.ask(f"C {THENET_ALIAS}", r"Connected to|Failure|Busy|not known|Unknown", 90)
    assert f"Connected to {THENET_ALIAS}:{THENET_CALL}" in out, f"LinBPQ could not reach TheNet through XRouter:\n{out}"
