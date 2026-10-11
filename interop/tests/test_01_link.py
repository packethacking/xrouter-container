"""Both nodes boot and the AXUDP link between them carries traffic both ways."""

from conftest import BPQ_CALL, LINK, XR_CALL
from wire import lines, wait_for


def test_axudp_link_carries_frames_both_ways(wire):
    def both():
        a = wire.frames(link=LINK, frm="xrouter")
        b = wire.frames(link=LINK, frm="linbpq")
        return (a, b) if a and b else None

    got = wait_for(both, 60)
    assert got, ("expected AXUDP frames in both directions within 60 s.\n"
                 f"xrouter->linbpq:\n{lines(wire.frames(link=LINK, frm='xrouter'))}\n"
                 f"linbpq->xrouter:\n{lines(wire.frames(link=LINK, frm='linbpq'))}")
    bad = [r for r in wire.frames(link=LINK) if r["frame"].get("fcs") != "ok"]
    assert not bad, f"frames without a valid AX.25 FCS (AXUDP carries one):\n{lines(bad)}"


def test_ax25_interlink_comes_up(wire):
    """XRouter keeps permanent links to neighbours (MAN PERMLINKS) and BPQ opens
    links to INP3 routes, so one of them must get a SABM answered by a UA."""
    def ua():
        return [r for r in wire.frames(link=LINK)
                if r["frame"].get("ctl", {}).get("type") == "UA"
                and {r["frame"]["src"], r["frame"]["dst"]} == {XR_CALL, BPQ_CALL}]

    got = wait_for(ua, 60)
    sabms = [r for r in wire.frames(link=LINK) if r["frame"].get("ctl", {}).get("type") in ("SABM", "SABME", "DM", "DISC", "XID")]
    assert got, f"no UA between {XR_CALL} and {BPQ_CALL} within 60 s. Link set-up frames:\n{lines(sabms)}"
