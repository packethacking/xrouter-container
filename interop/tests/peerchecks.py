"""Checks shared by the XNet, TNN and second-XRouter tests.

Each check takes a Peer and asserts with the wire or console evidence in the
message. The test files call them from explicitly named tests, so a reader
(and known-issues.toml) can see which peer a result is about.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from conftest import BPQ2_CALL, BPQ_APP_CALL, BPQ_CALL, LINK, XR_APP_CALL, XR_CALL
from parse import bpq_node_routes, xr_node_plus, xr_routes
from peerwire import (HORIZON_TT, link_setup, nodes_from, reflections, relay_problems,
                      rip_problems, show, ua_between, unreflected)
from wire import lines, wait_for


@dataclass
class Peer:
    name: str        # compose service and relay end name, e.g. "xnet"
    label: str       # for messages, e.g. "XNet"
    link: str        # relay link to XRouter
    call: str
    alias: str
    extra: tuple = ()   # other calls the peer advertises (applications)

    @property
    def own(self) -> set[str]:
        return {self.call, *self.extra}


BEHIND_BPQ = (BPQ_CALL, BPQ_APP_CALL, BPQ2_CALL)


def link_up(wire, p: Peer, timeout: float = 30) -> None:
    got = wait_for(lambda: ua_between(wire, p.link, XR_CALL, p.call), timeout)
    assert got, f"no UA between {XR_CALL} and {p.call} ({p.label}). Link set-up frames:\n{show(link_setup(wire, p.link))}"


def peer_sends_nodes(wire, p: Peer, timeout: float = 90) -> None:
    got = wait_for(lambda: nodes_from(wire, p.link, p.name, p.call, with_entries=True), timeout, 3)
    assert got, (f"no NODES broadcast with entries from {p.label} ({p.call}).\nUI frames from it:\n"
                 f"{show([r for r in wire.frames(link=p.link, frm=p.name) if r['frame'].get('ctl', {}).get('type') == 'UI'])}")


def xrouter_sends_nodes(wire, p: Peer, timeout: float = 90) -> None:
    got = wait_for(lambda: nodes_from(wire, p.link, "xrouter", XR_CALL, with_entries=True), timeout, 3)
    assert got, f"XRouter sent no NODES broadcast with entries to {p.label}.\n{show(wire.frames(link=p.link, frm='xrouter', kind='NODES'))}"


def l3rtt_probes_and_reflections(wire, p: Peer, prober: str) -> None:
    """[INP3]: any INP node sends $N; the neighbour reflects every RTT frame immediately."""
    prober_call = XR_CALL if prober == "xrouter" else p.call
    reflector = p.name if prober == "xrouter" else "xrouter"
    pairs = reflections(wire, p.link, prober, prober_call, reflector)
    assert pairs, f"no L3RTT probe from {prober} on the {p.label} link.\n{show(wire.frames(link=p.link, kind='L3RTT'))}"
    flags = pairs[-1][0]["frame"]["netrom"]["l3rtt"].get("flags", [])
    assert "$N" in flags, f"{prober}'s L3RTT lacks $N:\n{lines([pairs[-1][0]])}"
    missing = unreflected(pairs, wire)
    assert not missing, f"{reflector} did not reflect these L3RTT probes:\n{lines(missing)}"
    # Probes around a host stall are left out: the delay is the test machine's.
    slow = [(q, r) for q, r in pairs if r and r["t"] - q["t"] > 2.0 and not wire.near_stall(q["t"])]
    assert not slow, (f"{reflector} took over 2 s to reflect:\n" +
                      "\n".join(f"  probe {q['t']:.3f} reflected {r['t']:.3f}" for q, r in slow))


def l3rtt_fields_fit(wire, p: Peer, frm: str) -> None:
    """MAN L3RTT: timestamp, srtt, rtt and packet id are 10 character
    decimal fields; a 64-bit build overflowing them breaks other parsers."""
    origin = XR_CALL if frm == "xrouter" else p.call
    bad = []
    for r in wire.l3rtt(p.link, frm, origin=origin):
        f = r["frame"]["netrom"]["l3rtt"]
        for k in ("ts", "srtt", "rtt", "id"):
            v = f.get(k, "")
            if not v.isdigit() or len(v) > 10:
                bad.append(r)
                break
    assert wire.l3rtt(p.link, frm, origin=origin), f"no L3RTT from {frm} to check"
    assert not bad, f"L3RTT number fields not 1 to 10 digits:\n{lines(bad)}"


def rif_sent(wire, p: Peer, frm: str) -> None:
    rifs = wire.rifs(p.link, frm)
    assert rifs, f"{frm} never sent a RIF on the {p.label} link. L3RTT for context:\n{show(wire.frames(link=p.link, kind='L3RTT'))}"


def rif_fields_in_range(wire, p: Peer, frm: str) -> None:
    """[INP3] figure 1: hop counter 1..255, transport time 1..60000."""
    assert wire.rifs(p.link, frm), f"no RIF from {frm} to check"
    problems = rip_problems(wire, p.link, frm)
    assert not problems, (f"{frm} RIPs on the {p.label} link outside [INP3] figure 1:\n  " + "\n  ".join(problems) +
                          f"\n{show(wire.rifs(p.link, frm))}")


def own_rip_hop_one(wire, p: Peer, frm: str) -> None:
    """[INP3]: 'For the own node, a RIP is created and sent after the interlink
    has been established. The hop-counter has to be 1.'"""
    own = XR_CALL if frm == "xrouter" else p.call
    rips = [(rip, r) for rip, r in wire.rips(p.link, frm) if rip["call"] == own]
    assert rips, f"{frm} never sent a RIP for its own node {own} on the {p.label} link:\n{show(wire.rifs(p.link, frm))}"
    bad = [r for rip, r in rips if rip["hops"] != 1]
    assert not bad, f"own-node RIP with hop count other than 1:\n{lines(bad)}"


def one_rip_per_destination(wire, p: Peer) -> None:
    dups = []
    for frm in ("xrouter", p.name):
        for r in wire.rifs(p.link, frm):
            calls = [rip["call"] for rip in r["frame"]["netrom"]["rips"]]
            if len(calls) != len(set(calls)):
                dups.append(r)
    assert not dups, f"a RIF listing the same destination more than once:\n{lines(dups)}"


def poisoned_reverse(wire, p: Peer) -> None:
    """[INP3] 'A backward information is never returned to the neighbor'."""
    bad = [r for rip, r in wire.rips(p.link, "xrouter") if rip["call"] in p.own and rip["tt"] < HORIZON_TT]
    bad += [r for rip, r in wire.rips(p.link, p.name)
            if rip["call"] in {XR_CALL, XR_APP_CALL, *BEHIND_BPQ} and rip["tt"] < HORIZON_TT]
    assert not bad, f"positive route returned to the neighbour it came from:\n{lines(bad)}"


def xrouter_marks_inp3(xr, p: Peer) -> None:
    """MAN ROUTES: R T flags 2 = INP3 compatible, 4 = responds to L3RTT."""
    def look():
        r = xr_routes(xr.cmd("R T")).get(p.call)
        return r if r and r.get("flags", 0) & 6 == 6 else None
    assert wait_for(look, 30), f"XRouter does not flag {p.call} ({p.label}) as INP3 + L3RTT (flags & 6):\n{xr.cmd('R T')}"


def xrouter_learns_peer(xr, p: Peer) -> None:
    def look():
        nodes = xr_node_plus(xr.cmd("N +", 1.5))
        e = nodes.get(p.call)
        return nodes if e and e["via"] == p.call and e["hops"] == 1 and e["obs2"] > 0 and e["tt"] < 600 else None
    got = wait_for(look, 60, 5)
    assert got, f"XRouter has no live INP3 route to {p.call} at hop 1:\n{xr.cmd('N +')}\n{xr.cmd('N ' + p.alias)}"


def relays_bpq_routes_to_peer(wire, p: Peer, hop_mask: int = 0xFF) -> None:
    wait_for(lambda: all(relay_problems(wire, LINK, "linbpq", p.link, "xrouter", [c], hop_mask)[0] == []
                         for c in BEHIND_BPQ), 45, 3)
    problems, evidence = relay_problems(wire, LINK, "linbpq", p.link, "xrouter", BEHIND_BPQ, hop_mask)
    assert not problems, "\n".join(problems) + f"\nEvidence:\n{show(evidence, 20)}\nXRouter RIFs to {p.label}:\n{show(wire.rifs(p.link, 'xrouter'))}"


def relays_peer_routes_to_bpq(wire, p: Peer) -> None:
    wait_for(lambda: relay_problems(wire, p.link, p.name, LINK, "xrouter", sorted(p.own))[0] == [], 45, 3)
    problems, evidence = relay_problems(wire, p.link, p.name, LINK, "xrouter", sorted(p.own))
    assert not problems, "\n".join(problems) + f"\nEvidence:\n{show(evidence, 20)}"


def alias_travels_to_peer(wire, p: Peer) -> None:
    """[INP3]: options such as the alias go with the first positive information.
    LinBPQ sends aliases with its routes; XRouter should pass them on."""
    learned = {rip["call"] for rip, _ in wire.rips(LINK, "linbpq") if rip.get("alias")}
    missing, evidence = [], []
    for call in BEHIND_BPQ:
        if call not in learned:
            continue
        sent = [(rip, r) for rip, r in wire.rips(p.link, "xrouter") if rip["call"] == call and rip["tt"] < HORIZON_TT]
        if sent and not sent[0][0].get("alias"):
            missing.append(call)
            evidence.append(sent[0][1])
    assert not missing, (f"XRouter's first positive RIP to {p.label} for {missing} carried no alias, although LinBPQ "
                         f"sent one:\n{lines(evidence)}")


def peer_route_reaches_bpq2(bpq2, p: Peer) -> None:
    """Three INP3 hops from LinBPQ2: LinBPQ2 -> LinBPQ -> XRouter -> peer."""
    def look():
        routes = bpq_node_routes(bpq2.cmd(f"N {p.call}"))["inp3"]
        return routes if any(x["hops"] == 3 and x["tt"] < 600 for x in routes) else None
    got = wait_for(look, 60, 5)
    assert got, f"LinBPQ2 has no INP3 route at hop 3 to {p.label} ({p.call}):\n{bpq2.cmd('N ' + p.call)}"


def l4_from_bpq(bpq, p: Peer, banner: str) -> None:
    out = bpq.ask(f"C {p.alias}", r"Connected to|Failure|Busy|not known|Unknown", 45)
    assert f"Connected to {p.alias}:{p.call}" in out, f"LinBPQ could not connect to {p.alias} through XRouter:\n{out}"
    time.sleep(1)
    more = bpq.drain(2, 10)
    assert banner.lower() in (out + more).lower() or more.strip(), \
        f"no greeting from {p.label} through the circuit:\n{out}{more}"


def first_positive_rips(wire, link: str, frm: str, call: str) -> list[tuple[dict, dict]]:
    """Each RIP that turned `call` positive on the link: the very first one, and
    the first after every negative one."""
    out, positive = [], False
    for rip, r in wire.rips(link, frm):
        if rip["call"] != call:
            continue
        pos = rip["tt"] < HORIZON_TT
        if pos and not positive:
            out.append((rip, r))
        positive = pos
    return out


def peer_alias_reaches_bpq3(wire, p: Peer, alias_source: str = "rif") -> None:
    """[INP3]: optional fields (the alias) are sent "with the first positive
    information". LinBPQ3 hears of the peer only from XRouter, so XRouter's
    first positive RIP for it there must carry the alias the peer gave it."""
    from conftest import LINK3
    got = wait_for(lambda: first_positive_rips(wire, LINK3, "xrouter", p.call), 30, 3)
    assert got, f"XRouter never advertised {p.call} to LinBPQ3:\n{show(wire.rifs(LINK3, 'xrouter'))}"
    rip, rec = got[0]
    if alias_source == "rif":
        given = [r for x, r in wire.rips(p.link, p.name) if x["call"] == p.call and x.get("alias")]
        assert given, f"{p.label} never sent XRouter its alias by RIF"
        source = f"{p.label} sent it in its own RIF:\n{lines(given[:1])}"
    else:
        source = f"XRouter knows it from {p.label}'s NODES broadcasts"
    assert rip.get("alias") == p.alias, (
        f"XRouter's first positive RIP for {p.call} to LinBPQ3 carried no alias {p.alias} ({source}):\n{lines([rec])}")
