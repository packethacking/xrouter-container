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
