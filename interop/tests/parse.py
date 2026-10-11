"""Parse the ROUTES / NODES console output of XRouter and LinBPQ."""

from __future__ import annotations

import re


def xr_routes(text: str) -> dict[str, dict]:
    """XRouter `R` or `R T` output.

    `>  1 PN0BQ     200   3  N   0    0.74  550   5000   15   9000`
    The first column is '>' (in use), '~' (opening/closing), 'x' (failed) or blank.
    """
    out = {}
    for ln in text.splitlines():
        m = re.match(r"^([>~x ])\s*(\d+)\s+([A-Z0-9]+(?:-\d+)?)\s+(\d+)\s+(\d+)!?\s*(.*)$", ln)
        if not m:
            continue
        state, port, call, qual, nodes, rest = m.groups()
        r = {"state": state.strip(), "port": int(port), "qual": int(qual), "nodes": int(nodes),
             "rest": rest.split(), "line": ln}
        # R T columns after RF: Tdr Sntt Flg Maxtt Maxhops TheirMaxtt
        rest_cols = r["rest"]
        if rest_cols and rest_cols[0] in ("N", "Y"):
            rest_cols = rest_cols[1:]
        if len(rest_cols) >= 3:
            try:
                r["tdr"] = int(rest_cols[0])
                r["sntt"] = float(rest_cols[1])
                r["flags"] = int(rest_cols[2])
            except ValueError:
                pass
        out[call] = r
    return out


def xr_node_routes(text: str) -> list[dict]:
    """Route lines from XRouter `N <call>`.

    `> 156  5   1 PN0BQ        0.77  2   5   N <  11/10 08:50`
    Columns: active, Qty, Obs, Pt, Via, [Stt Hop Obs2], RF, preferred.
    """
    out = []
    in_routes = False
    for ln in text.splitlines():
        if ln.strip().startswith("Routes to:"):
            in_routes = True
            continue
        if not in_routes or not ln.strip() or ln.strip().startswith("Qty"):
            continue
        m = re.match(r"^([> ])\s*(\d+)\s+(\d+)\s+(\d+)\s+([A-Z0-9]+(?:-\d+)?)\s*(.*)$", ln)
        if not m:
            continue
        active, qty, obs, port, via, rest = m.groups()
        r = {"active": active == ">", "qty": int(qty), "obs": int(obs), "port": int(port),
             "via": via, "line": ln}
        m2 = re.match(r"^([\d.]+)\s+(\d+)\s+(\d+)\s", rest + " ")
        if m2:
            r["stt"] = float(m2.group(1))
            r["hops"] = int(m2.group(2))
            r["obs2"] = int(m2.group(3))
        out.append(r)
    return out


def xr_node_list(text: str) -> set[str]:
    """`ALIAS:CALL` pairs from XRouter `N`."""
    return set(re.findall(r"\b([A-Z0-9#]+:[A-Z0-9]+(?:-\d+)?)\b", text))


def bpq_routes(text: str) -> dict[str, dict]:
    """LinBPQ `R` / `R V`: `> 2 PN0XR     200 1!` (verbose adds srtt fields for INP3 routes)."""
    out = {}
    for ln in text.splitlines():
        m = re.match(r"^([> ])\s*(\d+)\s+([A-Z0-9]+(?:-\d+)?)\s+(\d+)\s+(\d+)(!*)\s*(.*)$", ln)
        if not m:
            continue
        active, port, call, qual, nodes, locked, rest = m.groups()
        r = {"active": active == ">", "port": int(port), "qual": int(qual), "nodes": int(nodes),
             "locked": bool(locked), "line": ln}
        m2 = re.search(r"([\d.]+)s\s+([\d.]+)s\s+([0-9A-F]+)", rest)
        if m2:
            r["inp3"] = True
            r["srtt"] = float(m2.group(1))
            r["neighbour_srtt"] = float(m2.group(2))
            r["status"] = int(m2.group(3), 16)
        else:
            r["inp3"] = False
        out[call] = r
    return out


def bpq_node_routes(text: str) -> dict[str, list[dict]]:
    """LinBPQ `N <call>`: NET/ROM lines `> 200 6 2 PN0XR` and INP3 lines `> 1 0.01s 2 PN0XR 08:50`."""
    netrom, inp3 = [], []
    for ln in text.splitlines():
        m = re.match(r"^([> ])\s*(\d+)\s+([\d.]+)s\s+(\d+)\s+([A-Z0-9]+(?:-\d+)?)\s+\d\d:\d\d", ln)
        if m:
            inp3.append({"active": m.group(1) == ">", "hops": int(m.group(2)), "tt": float(m.group(3)),
                         "port": int(m.group(4)), "via": m.group(5), "line": ln})
            continue
        m = re.match(r"^([> ])\s*(\d+)\s+(\d+)\s+(\d+)\s+([A-Z0-9]+(?:-\d+)?)\s*$", ln)
        if m:
            netrom.append({"active": m.group(1) == ">", "qual": int(m.group(2)), "obs": int(m.group(3)),
                           "port": int(m.group(4)), "via": m.group(5), "line": ln})
    return {"netrom": netrom, "inp3": inp3}


def bpq_node_list(text: str) -> set[str]:
    return set(re.findall(r"\b([A-Z0-9#]+:[A-Z0-9]+(?:-\d+)?)\b", text))


def xr_node_plus(text: str) -> dict[str, dict]:
    """XRouter `N +`: call -> qual, via, tt (trip time, s), hops, obs2 (INP3 obsolescence)."""
    out = {}
    for ln in text.splitlines():
        p = ln.split()
        if len(p) == 8 and ":" in p[0]:
            try:
                out[p[0].split(":")[1]] = {"alias": p[0].split(":")[0], "qual": int(p[1]), "port": int(p[3]),
                                           "via": p[4], "tt": float(p[5]), "hops": int(p[6]),
                                           "obs2": int(p[7]), "line": ln}
            except ValueError:
                pass
    return out


# ---------------------------------------------------------------- XNet

def xnet_nodes(text: str) -> dict[str, str]:
    """XNet `n`: call -> alias (`#tmp` when XNet learned no alias)."""
    return {c: a for a, c in re.findall(r"([A-Za-z0-9#]+):([A-Z0-9]+(?:-\d+)?)", text)}


def xnet_node_times(text: str) -> dict[str, float]:
    """XNet `n +`: call -> trip time in seconds."""
    return {c: float(t) for _, c, t in re.findall(r"([A-Za-z0-9#]+):([A-Z0-9]+(?:-\d+)?)\s+([\d.]+)", text)}


def xnet_route(text: str) -> list[dict]:
    """XNet `n <alias>`: `> PN0BQB    PN0XR     255/6   0.05s  4 hops`.
    XNet counts a direct neighbour as 2 hops, one more than INP3 does."""
    out = []
    for m in re.finditer(r"^([> ])\s*([A-Z0-9]+(?:-\d+)?)\s+([A-Z0-9]+(?:-\d+)?)\s+(\d+)/(\d+)\s+([\d.]+)s\s+(\d+) hops",
                         text, re.M):
        out.append({"active": m.group(1) == ">", "call": m.group(2), "via": m.group(3), "qual": int(m.group(4)),
                    "obs": int(m.group(5)), "tt": float(m.group(6)), "hops": int(m.group(7)), "line": m.group(0)})
    return out


def xnet_links(text: str) -> dict[str, dict]:
    """XNet `l`: ` 1:PN0XR        9 I   0 ...` -> call -> port, link type letter."""
    out = {}
    for m in re.finditer(r"^\s*(\d+):([A-Z0-9]+(?:-\d+)?)\s+\d+\s+([A-Z])\b", text, re.M):
        out[m.group(2)] = {"port": int(m.group(1)), "type": m.group(3), "line": m.group(0)}
    return out


# ---------------------------------------------------------------- TheNetNode

def tnn_nodes(text: str) -> dict[str, str]:
    """TNN `NODES`: call -> alias. TNN prints a call in lower case when the
    node carries INP3 options, and an empty alias as `:CALL`."""
    return {c.upper(): a for a, c in re.findall(r"(?<![\w:])([A-Z0-9#]*):([A-Za-z0-9]+(?:-\d+)?)", text)}


def tnn_routes(text: str) -> dict[str, dict]:
    """TNN `ROUTES`: `PN0XR       0    I   0   10/10      440/130       50000 conn.`"""
    out = {}
    for m in re.finditer(r"^([A-Z0-9]+)\s+(\d+)\s+([A-Z])\s+(\d+)\s+(\d+)/(\d+)\s+(\d+)/(\d+)\s+(\d+)\s+(\S+)",
                         text, re.M):
        out[m.group(1)] = {"ssid": int(m.group(2)), "type": m.group(3), "port": int(m.group(4)),
                           "srtt_ms": int(m.group(7)), "maxt_ms": int(m.group(9)), "state": m.group(10),
                           "line": m.group(0)}
    return out


def tnn_node_routes(text: str) -> list[dict]:
    """TNN `NODES <alias>`: `>    450     40      0   4   DG   0     410  0 PN0XR`.
    T is the total trip time in ms, LT the hop count (TNN counts a direct
    neighbour as 2, one more than INP3 does), Route the neighbour."""
    out = []
    for m in re.finditer(r"^([> ])\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([A-Z]+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([A-Z0-9]+(?:-\d+)?)",
                         text, re.M):
        out.append({"active": m.group(1) == ">", "tt_ms": int(m.group(2)), "rxt": int(m.group(3)),
                    "hops": int(m.group(5)), "mode": m.group(6), "via": m.group(10), "line": m.group(0)})
    return out


# ---------------------------------------------------------------- TheNet X1J

def thenet_nodes(text: str) -> dict[str, str]:
    return {c: a for a, c in re.findall(r"([A-Z0-9#]+):([A-Z0-9]+(?:-\d+)?)", text.split("}", 1)[-1])}


def thenet_routes(text: str) -> dict[str, dict]:
    """TheNet `ROUTES`: `  0 XRNODE:PN0XR 192 10` (port, neighbour, quality, node count)."""
    out = {}
    for m in re.finditer(r"^\s*(\d+)\s+(?:([A-Z0-9#]+):)?([A-Z0-9]+(?:-\d+)?)\s+(\d+)\s+(\d+)", text, re.M):
        out[m.group(3)] = {"port": int(m.group(1)), "qual": int(m.group(4)), "nodes": int(m.group(5)),
                           "line": m.group(0)}
    return out
