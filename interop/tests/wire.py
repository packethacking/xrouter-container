"""Read the relay's JSON lines log and answer questions about the wire."""

from __future__ import annotations

import json
import os
import time


class Wire:
    def __init__(self, path: str):
        self.path = path

    def records(self, since: float | None = None) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a line still being written
                if "frame" not in r:
                    continue
                if since is not None and r["t"] < since:
                    continue
                out.append(r)
        return out

    def frames(self, link: str | None = None, frm: str | None = None, since: float | None = None,
               kind: str | None = None, forwarded_only: bool = True) -> list[dict]:
        out = []
        for r in self.records(since):
            if link and r["link"] != link:
                continue
            if frm and r["from"] != frm:
                continue
            if forwarded_only and r.get("action") != "forwarded":
                continue
            if kind and r["frame"].get("netrom", {}).get("kind") != kind:
                continue
            out.append(r)
        return out

    def rifs(self, link: str, frm: str, since: float | None = None) -> list[dict]:
        return self.frames(link=link, frm=frm, since=since, kind="RIF")

    def rips(self, link: str, frm: str, since: float | None = None) -> list[tuple[dict, dict]]:
        """Every RIP sent by `frm` on `link`, paired with the record it came in."""
        out = []
        for r in self.rifs(link, frm, since):
            for rip in r["frame"]["netrom"]["rips"]:
                out.append((rip, r))
        return out

    def l3rtt(self, link: str, frm: str, origin: str | None = None,
              since: float | None = None) -> list[dict]:
        """L3RTT frames sent by `frm`; origin is the L3 source (the prober)."""
        out = []
        for r in self.frames(link=link, frm=frm, since=since, kind="L3RTT"):
            if origin and r["frame"]["netrom"]["l3src"] != origin:
                continue
            out.append(r)
        return out


def line(r: dict) -> str:
    """Short human readable form of one relay record, for assertion messages."""
    f = r.get("frame", {})
    s = f"{r['t']:.3f} {r['from']}->{r['to']} {f.get('src')}>{f.get('dst')} {f.get('ctl', {}).get('type')}"
    nr = f.get("netrom")
    if nr:
        if nr["kind"] == "RIF":
            s += " RIF " + ", ".join(
                f"{p.get('alias', '')}:{p['call']} hops={p['hops']} tt={p['tt']}" for p in nr["rips"])
        elif nr["kind"] == "L3RTT":
            s += f" L3RTT {nr['l3src']} ttl={nr['ttl']} '{nr['l3rtt']['text']}'"
        elif nr["kind"] == "NODES":
            s += " NODES " + ", ".join(f"{e['alias']}:{e['call']} q={e['quality']}" for e in nr["entries"])
        else:
            s += f" {nr['kind']}"
            if nr.get("l4"):
                s += f" {nr['l3src']}>{nr['l3dst']} {nr['l4']['op']}"
    return s


def lines(rs: list[dict], limit: int = 12) -> str:
    if not rs:
        return "  (none)"
    tail = rs[-limit:]
    more = f"  ... {len(rs) - limit} earlier\n" if len(rs) > limit else ""
    return more + "\n".join("  " + line(r) for r in tail)


def wait_for(fn, timeout: float, interval: float = 2.0):
    """Call fn until it returns something truthy or timeout passes; return the last value."""
    deadline = time.time() + timeout
    value = fn()
    while not value and time.time() < deadline:
        time.sleep(interval)
        value = fn()
    return value
