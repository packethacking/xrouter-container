"""XRouter as an INP3 transit node.

LinBPQ3 (PN0BQC) links only to XRouter, so everything it knows about LinBPQ and
LinBPQ2 must come through XRouter's INP3 relaying, and LinBPQ only hears of
LinBPQ3 through XRouter. This is the part of XRouter's INP3 that re-advertises
other nodes' routes, rather than just its own.

[INP3]: "Each propagation of a route implicates the increase of the route time
by one granularity step (10ms). The hop-counter is increased by one."
"""

from conftest import BPQ2_CALL, BPQ3_CALL, BPQ_APP_CALL, BPQ_CALL, LINK, LINK3, XR_CALL
from parse import bpq_node_routes
from wire import lines, wait_for

HORIZON_TT = 60000


def _latest_positive(wire, link, frm, call, since=None):
    rips = [(rip, r) for rip, r in wire.rips(link, frm, since=since) if rip["call"] == call and rip["tt"] < HORIZON_TT]
    return rips[-1] if rips else (None, None)


def test_xrouter_relays_bpq_routes_to_bpq3(wire, converged):
    """What LinBPQ advertised to XRouter must reach LinBPQ3 one hop further and no quicker."""
    def ready():
        return all(_latest_positive(wire, LINK3, "xrouter", c)[0] for c in (BPQ_CALL, BPQ_APP_CALL, BPQ2_CALL))

    wait_for(ready, 45, 3)
    problems, evidence = [], []
    for call in (BPQ_CALL, BPQ_APP_CALL, BPQ2_CALL):
        got, grec = _latest_positive(wire, LINK, "linbpq", call)
        sent, srec = _latest_positive(wire, LINK3, "xrouter", call)
        evidence += [x for x in (grec, srec) if x]
        if got is None:
            problems.append(f"LinBPQ never advertised {call} to XRouter")
            continue
        if sent is None:
            problems.append(f"XRouter never advertised {call} to LinBPQ3 (it learned it at hops={got['hops']} tt={got['tt']})")
            continue
        if sent["hops"] != got["hops"] + 1:
            problems.append(f"{call}: XRouter received hops={got['hops']}, sent hops={sent['hops']} (expected {got['hops'] + 1})")
        if sent["tt"] <= got["tt"]:
            problems.append(f"{call}: XRouter received tt={got['tt']}, sent tt={sent['tt']} (must be larger)")
    assert not problems, "\n".join(problems) + f"\nEvidence:\n{lines(evidence, 20)}\nAll XRouter RIFs to LinBPQ3:\n{lines(wire.rifs(LINK3, 'xrouter'))}"


def test_xrouter_relays_bpq3_to_bpq(wire, converged):
    def ready():
        return _latest_positive(wire, LINK, "xrouter", BPQ3_CALL)[0]

    wait_for(ready, 45, 3)
    got, grec = _latest_positive(wire, LINK3, "linbpq3", BPQ3_CALL)
    sent, srec = _latest_positive(wire, LINK, "xrouter", BPQ3_CALL)
    assert got, f"LinBPQ3 never advertised itself to XRouter:\n{lines(wire.rifs(LINK3, 'linbpq3'))}"
    assert sent, (f"XRouter never advertised {BPQ3_CALL} to LinBPQ.\nLinBPQ3 to XRouter:\n{lines([grec])}\n"
                  f"XRouter RIFs to LinBPQ:\n{lines(wire.rifs(LINK, 'xrouter'))}")
    assert sent["hops"] == got["hops"] + 1 and sent["tt"] > got["tt"], \
        f"XRouter relayed {BPQ3_CALL} with odd metrics:\n{lines([grec, srec])}"


def test_alias_travels_with_relayed_route(wire, converged):
    """[INP3]: optional fields are propagated with the first positive information.
    LinBPQ sends aliases; XRouter should pass them on to LinBPQ3."""
    missing = []
    for call in (BPQ_CALL, BPQ2_CALL):
        sent = [rip for rip, _ in wire.rips(LINK3, "xrouter") if rip["call"] == call and rip["tt"] < HORIZON_TT]
        if sent and not any(rip.get("alias") for rip in sent):
            missing.append(call)
    assert not missing, f"XRouter relayed {missing} to LinBPQ3 without an alias in any RIP:\n{lines(wire.rifs(LINK3, 'xrouter'))}"


def test_bpq3_learns_whole_network_through_xrouter(bpq3, converged):
    want = {XR_CALL: 1, BPQ_CALL: 2, BPQ2_CALL: 3}

    def look():
        out = {}
        for call, hops in want.items():
            routes = bpq_node_routes(bpq3.cmd(f"N {call}"))["inp3"]
            if not any(x["via"] == XR_CALL and x["hops"] == hops and x["tt"] < 600 for x in routes):
                return None
            out[call] = routes
        return out

    got = wait_for(look, 60, 5)
    assert got, ("LinBPQ3 lacks INP3 routes via XRouter at the expected hop counts "
                 f"{want}:\n" + "\n".join(bpq3.cmd(f"N {c}") for c in want) + "\n" + bpq3.cmd("N"))


def test_l4_connect_bpq3_to_bpq2_through_xrouter(bpq3, converged):
    """Three hops, with XRouter in the middle of the path."""
    out = bpq3.ask("C BPQB", r"Connected to|Failure|Busy|not known|Unknown", 45)
    assert "Connected to BPQB:PN0BQB" in out, f"LinBPQ3 could not reach BPQB through XRouter and LinBPQ:\n{out}"
    out = bpq3.ask("V", r"Version 6\.")
    assert "Version 6." in out, f"no reply from LinBPQ2 through the circuit:\n{out}"
