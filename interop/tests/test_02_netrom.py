"""Plain NET/ROM: each node lists the other as a neighbour and as a node."""

import time

from conftest import (BPQ_ALIAS, BPQ_CALL, LINK, LINK3, XR_ALIAS, XR_CALL)
from parse import bpq_node_list, bpq_routes, xr_node_list, xr_routes
from wire import lines, wait_for


def test_both_sides_broadcast_nodes(wire, converged):
    """NODESINTERVAL is 1 minute on both; allow a couple of intervals."""
    for frm, call in (("xrouter", XR_CALL), ("linbpq", BPQ_CALL)):
        nodes = wait_for(lambda: [r for r in wire.frames(link=LINK, frm=frm, kind="NODES")
                                  if r["frame"]["src"] == call], 150, 3)
        assert nodes, (f"no NODES broadcast from {frm} ({call}) on the link.\n"
                       f"UI frames seen from {frm}:\n"
                       f"{lines([r for r in wire.frames(link=LINK, frm=frm) if r['frame'].get('ctl', {}).get('type') == 'UI'])}")


def test_xrouter_lists_bpq_as_neighbour(xr, converged):
    text = wait_for(lambda: (t := xr.cmd("R")) and BPQ_CALL in xr_routes(t) and t, 30)
    assert text, f"XRouter ROUTES does not list {BPQ_CALL}:\n{xr.cmd('R')}"


def test_xrouter_lists_bpq_node(xr, converged):
    text = wait_for(lambda: (t := xr.cmd("N")) and f"{BPQ_ALIAS}:{BPQ_CALL}" in xr_node_list(t) and t, 30)
    assert text, f"XRouter NODES does not list {BPQ_ALIAS}:{BPQ_CALL}:\n{xr.cmd('N')}"


def test_bpq_lists_xrouter_as_neighbour(bpq, converged):
    text = wait_for(lambda: (t := bpq.cmd("R")) and XR_CALL in bpq_routes(t) and t, 30)
    assert text, f"LinBPQ ROUTES does not list {XR_CALL}:\n{bpq.cmd('R')}"


def test_bpq_lists_xrouter_node(bpq, converged):
    text = wait_for(lambda: (t := bpq.cmd("N")) and f"{XR_ALIAS}:{XR_CALL}" in bpq_node_list(t) and t, 30)
    assert text, f"LinBPQ NODES does not list {XR_ALIAS}:{XR_CALL}:\n{bpq.cmd('N')}"


def test_xrouter_broadcasts_nodes_to_bpq3(wire, stack, converged):
    """NODESINTERVAL=1 is global, so every port should get a NODES broadcast
    every minute (MAN NODESINT(7): the global value "sets ... the default for
    all PORTs"). Port 2, to LinBPQ3, is deliberately left out of the CRONTAB
    work-around, so this sees XRouter's own scheduler."""
    got = wait_for(lambda: [r for r in wire.frames(link=LINK3, frm="xrouter", kind="NODES")
                            if r["frame"]["src"] == XR_CALL and r["frame"]["dst"] == "NODES"
                            and r["frame"]["netrom"]["entries"]],
                   max(5, stack["started"] + 180 - time.time()), 3)
    port1 = [r for r in wire.frames(link=LINK, frm="xrouter", kind="NODES") if r["frame"]["netrom"]["entries"]]
    assert got, (f"XRouter sent no NODES broadcast on port 2 (LinBPQ3) in {time.time() - stack['started']:.0f} s, "
                 f"while on port 1 (LinBPQ) it sent {len(port1)}:\n{lines(port1, 4)}")
