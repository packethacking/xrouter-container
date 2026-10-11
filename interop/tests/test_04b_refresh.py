"""Scheduled INP3 refresh.

Both configs ask for regular full INP3 updates: XRouter INPBCINTERVAL=120
("Secs between scheduled INP3 unicasts", MAN XROUTER.CFG) and LinBPQ
RIFINTERVAL=60. LinBPQ relies on them: it times out INP3 routes from a
non-BPQ neighbour that are not refreshed (BPQINP3.c DecayINP3Routes, with
`timeoutRoutes` set for "XR or others" and INP3NodeTimeout of 3 hours), so a
neighbour that never refreshes loses its routes at LinBPQ after 3 hours.

These run before the withdrawal tests so no link reset muddies the window.
"""

import time

from conftest import BPQ_CALL, LINK, LINK3, XR_CALL
from wire import lines

XR_INTERVAL = 120
BPQ_INTERVAL = 60


def _own_rifs(wire, link, frm, own):
    return [r for rip, r in wire.rips(link, frm) if rip["call"] == own and rip["tt"] < 60000]


def _wait_window(first_t: float, interval: int) -> None:
    """Make sure at least 1.5 intervals have passed since the first RIF."""
    need = first_t + 1.5 * interval - time.time()
    if need > 0:
        time.sleep(need)


def _resets(wire, link, since):
    return [r for r in wire.frames(link=link, since=since)
            if r["frame"].get("ctl", {}).get("type") in ("SABM", "DISC", "DM")]


def test_xrouter_refreshes_rif_on_schedule(wire, converged):
    first = _own_rifs(wire, LINK, "xrouter", XR_CALL)
    assert first, f"XRouter never sent a RIF with its own node:\n{lines(wire.rifs(LINK, 'xrouter'))}"
    t1 = first[0]["t"]
    _wait_window(t1, XR_INTERVAL)
    resets = _resets(wire, LINK, t1)
    later = [r for r in _own_rifs(wire, LINK, "xrouter", XR_CALL) if r["t"] > t1 + 5]
    assert later, (
        f"XRouter sent its own node to LinBPQ by RIF once at {t1:.3f} and not again in the next "
        f"{time.time() - t1:.0f} s, although INPBCINTERVAL={XR_INTERVAL}. "
        f"Link resets in that time: {len(resets)}.\nAll XRouter RIFs to LinBPQ:\n{lines(wire.rifs(LINK, 'xrouter'))}\n"
        f"All XRouter RIFs to LinBPQ3:\n{lines(wire.rifs(LINK3, 'xrouter'))}")


def test_bpq_refreshes_rif_on_schedule(wire, converged):
    first = _own_rifs(wire, LINK, "linbpq", BPQ_CALL)
    assert first, f"LinBPQ never sent a RIF with its own node:\n{lines(wire.rifs(LINK, 'linbpq'))}"
    t1 = first[0]["t"]
    _wait_window(t1, BPQ_INTERVAL)
    later = [r for r in _own_rifs(wire, LINK, "linbpq", BPQ_CALL) if r["t"] > t1 + 5]
    assert later, (f"LinBPQ sent its own node by RIF once at {t1:.3f} and not again, although RIFINTERVAL={BPQ_INTERVAL}."
                   f"\nAll LinBPQ RIFs to XRouter:\n{lines(wire.rifs(LINK, 'linbpq'))}")
