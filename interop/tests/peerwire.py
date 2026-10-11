"""Wire checks shared by the tests for the other implementations (XNet, TNN,
TheNet, a second XRouter). Each takes the relay link name and the two ends'
names as the relay logs them ("xrouter" and the peer's service name)."""

from __future__ import annotations

from wire import Wire, lines

HORIZON_TT = 60000


def ua_between(wire: Wire, link: str, call_a: str, call_b: str) -> list[dict]:
    return [r for r in wire.frames(link=link)
            if r["frame"].get("ctl", {}).get("type") == "UA"
            and {r["frame"]["src"], r["frame"]["dst"]} == {call_a, call_b}]


def link_setup(wire: Wire, link: str) -> list[dict]:
    return [r for r in wire.frames(link=link)
            if r["frame"].get("ctl", {}).get("type") in ("SABM", "SABME", "UA", "DM", "DISC", "FRMR")]


def nodes_from(wire: Wire, link: str, frm: str, call: str, with_entries: bool = False) -> list[dict]:
    out = [r for r in wire.frames(link=link, frm=frm, kind="NODES")
           if r["frame"]["src"] == call and r["frame"]["dst"] == "NODES"]
    if with_entries:
        out = [r for r in out if r["frame"]["netrom"]["entries"]]
    return out


def nodes_entries(wire: Wire, link: str, frm: str) -> set[str]:
    """Every callsign the sender has listed in a NODES broadcast on the link."""
    return {e["call"] for r in wire.frames(link=link, frm=frm, kind="NODES") for e in r["frame"]["netrom"]["entries"]}


def reflections(wire: Wire, link: str, prober: str, prober_call: str, reflector: str):
    """Pair each L3RTT probe with its reflection (same text, coming back)."""
    probes = wire.l3rtt(link, prober, origin=prober_call)
    back = {r["frame"]["netrom"]["l3rtt"]["text"]: r for r in wire.l3rtt(link, reflector, origin=prober_call)}
    return [(p, back.get(p["frame"]["netrom"]["l3rtt"]["text"])) for p in probes]


def unreflected(pairs, wire: Wire | None = None) -> list[dict]:
    """Probes with no reflection, leaving out the newest (it may still be in
    flight) and any sent around a host stall (see Wire.near_stall)."""
    missing = [p for p, r in pairs if r is None]
    if missing and pairs and missing[-1] is pairs[-1][0]:
        missing = missing[:-1]
    if wire is not None:
        missing = [p for p in missing if not wire.near_stall(p["t"])]
    return missing


def rip_problems(wire: Wire, link: str, frm: str, max_hops: int = 255) -> list[str]:
    """[INP3] figure 1: hop counter 1..255, transport time 1..60000 (10 ms units)."""
    problems = []
    for r in wire.rifs(link, frm):
        nr = r["frame"]["netrom"]
        if "error" in nr:
            problems.append(f"undecodable RIF ({nr['error']}): {r['raw']}")
        for rip in nr["rips"]:
            if not 1 <= rip["hops"] <= max_hops:
                problems.append(f"{rip['call']} hops={rip['hops']} (allowed 1..{max_hops})")
            if not 1 <= rip["tt"] <= HORIZON_TT:
                problems.append(f"{rip['call']} tt={rip['tt']} (spec: 1..60000)")
    return sorted(set(problems))


def latest_positive(wire: Wire, link: str, frm: str, call: str, since: float | None = None):
    rips = [(rip, r) for rip, r in wire.rips(link, frm, since=since) if rip["call"] == call and rip["tt"] < HORIZON_TT]
    return rips[-1] if rips else (None, None)


def relay_problems(wire: Wire, in_link: str, in_from: str, out_link: str, out_from: str, calls,
                   hop_mask: int = 0xFF) -> tuple[list[str], list[dict]]:
    """XRouter learned each call on in_link and must pass it on along out_link
    one hop further and no quicker ([INP3]: "Each propagation of a route
    implicates the increase of the route time by one granularity step (10ms).
    The hop-counter is increased by one.")."""
    problems, evidence = [], []
    for call in calls:
        got, grec = latest_positive(wire, in_link, in_from, call)
        sent, srec = latest_positive(wire, out_link, out_from, call)
        evidence += [x for x in (grec, srec) if x]
        if got is None:
            problems.append(f"{in_from} never advertised {call} to XRouter on {in_link}")
            continue
        if sent is None:
            problems.append(f"XRouter never advertised {call} on {out_link} (it learned it at hops={got['hops']} tt={got['tt']})")
            continue
        if (sent["hops"] & hop_mask) != (got["hops"] & hop_mask) + 1:
            problems.append(f"{call}: XRouter received hops={got['hops']}, sent hops={sent['hops']} (expected {(got['hops'] & hop_mask) + 1})")
        if sent["tt"] <= got["tt"]:
            problems.append(f"{call}: XRouter received tt={got['tt']}, sent tt={sent['tt']} (must be larger)")
    return problems, evidence


def show(rs, limit: int = 12) -> str:
    return lines(rs, limit)


def check_refresh(wire: Wire, link: str, frm: str, own: str, interval: float) -> None:
    """Assert `frm` re-sends its own node by RIF on `link` within 1.5 intervals
    of the first one, on a schedule. An own-node RIF within a minute of the link
    being (re)established is the [INP3] "after the interlink has been
    established" one, not a refresh, so those are left out. The failure
    message lists every later re-send, so the real period can be read off."""
    import time

    def own_rifs():
        return [r for rip, r in wire.rips(link, frm) if rip["call"] == own and rip["tt"] < HORIZON_TT]

    first = own_rifs()
    assert first, f"{frm} never sent its own node {own} by RIF on {link}:\n{lines(wire.rifs(link, frm))}"
    t1 = first[0]["t"]
    end = t1 + 1.5 * interval
    if end > time.time():
        time.sleep(end - time.time())
    ups = [r["t"] for r in wire.frames(link=link) if r["frame"].get("ctl", {}).get("type") == "UA"]
    scheduled = [r for r in own_rifs() if r["t"] > t1 + 5 and not any(0 <= r["t"] - u <= 60 for u in ups)]
    in_window = [r for r in scheduled if r["t"] <= end]
    later = ", ".join(f"+{r['t'] - t1:.0f} s" for r in scheduled) or "none"
    assert in_window, (
        f"{frm} sent its own node {own} by RIF on {link} at {t1:.3f} and did not re-send it within "
        f"{1.5 * interval:.0f} s (configured interval {interval:.0f} s). Re-sends not explained by the link "
        f"being (re)established, up to now ({time.time() - t1:.0f} s): {later}. Link set-ups: "
        f"{len([u for u in ups if u > t1])}.\nAll {frm} RIFs on {link}:\n{lines(wire.rifs(link, frm))}")
