"""Scheduled INP3 refresh on the links to the other implementations.

XRouter is configured with INPBCINTERVAL=120 ("Secs between scheduled INP3
unicasts", MAN XROUTER.CFG), so it should re-send its routes to every INP3
neighbour, not just LinBPQ. The neighbours' own refresh is checked against
the same window: the second XRouter has the same setting; TNN is built with
its full INP3 refresh shortened from one hour to 120 s (peers/tnn); XNet has
no refresh setting at all.

Each check waits until 1.5 intervals have passed since the first RIF on that
link. They run before the withdrawal tests so no link reset muddies it.
"""


from conftest import (LINK_TNN, LINK_XNET, LINK_XRPEER, TNN_CALL, XNET_CALL, XR_CALL, XRPEER_CALL, needs_peer)
from peerwire import check_refresh

INTERVAL = 120
LINKS = {"xnet": (LINK_XNET, XNET_CALL), "tnn": (LINK_TNN, TNN_CALL), "xrpeer": (LINK_XRPEER, XRPEER_CALL)}


def _refreshes(wire, peer: str, frm: str):
    link, peer_call = LINKS[peer]
    check_refresh(wire, link, frm, XR_CALL if frm == "xrouter" else peer_call, INTERVAL)


@needs_peer("xnet")
def test_xrouter_refreshes_rif_to_xnet(wire, peers_converged):
    _refreshes(wire, "xnet", "xrouter")


@needs_peer("tnn")
def test_xrouter_refreshes_rif_to_tnn(wire, peers_converged):
    _refreshes(wire, "tnn", "xrouter")


@needs_peer("xrpeer")
def test_xrouter_refreshes_rif_to_xrpeer(wire, peers_converged):
    _refreshes(wire, "xrpeer", "xrouter")


@needs_peer("xnet")
def test_xnet_refreshes_rif_on_schedule(wire, peers_converged):
    _refreshes(wire, "xnet", "xnet")


@needs_peer("tnn")
def test_tnn_refreshes_rif_on_schedule(wire, peers_converged):
    _refreshes(wire, "tnn", "tnn")


@needs_peer("xrpeer")
def test_xrpeer_refreshes_rif_on_schedule(wire, peers_converged):
    _refreshes(wire, "xrpeer", "xrpeer")
