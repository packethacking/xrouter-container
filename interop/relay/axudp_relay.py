#!/usr/bin/env python3
"""AXUDP relay and wire logger for the NET/ROM + INP3 interop suite.

Each link joins two nodes, A and B. Node A is configured with the relay's
port `a_port` as its AXUDP peer, node B with `b_port`. A datagram that A
sends to `a_port` leaves the relay from `b_port` towards B, and the other
way round, so each node sees one fixed peer address. Datagrams are
forwarded byte for byte; the relay never edits a frame.

Every datagram is also decoded (AX.25 header, and NET/ROM content for
PID 0xCF) and written as one JSON object per line to the log file. That
log is the wire evidence for the tests and for bug reports.

A small HTTP control server lets tests drop or delay frames on a link:

    GET  /links                     current link state
    POST /links/<name>?drop=1       drop everything on that link
    POST /links/<name>?drop=0       stop dropping
    POST /links/<name>?delay_ms=N   delay every datagram by N ms
    POST /mark?text=...             write a marker line into the log

Configuration is JSON, passed with --config:

    {"links": [{"name": "xr-bpq",
                "a": {"name": "xrouter", "host": "172.28.77.11", "port": 10093},
                "b": {"name": "linbpq",  "host": "172.28.77.12", "port": 10093},
                "a_port": 20001, "b_port": 20002}]}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.parse
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Decoding
# --------------------------------------------------------------------------

L4_OPCODES = {
    0: "PROTEXT",
    1: "CONREQ",
    2: "CONACK",
    3: "DISCREQ",
    4: "DISCACK",
    5: "INFO",
    6: "INFOACK",
    7: "RSET",
}


def fcs16(data: bytes) -> int:
    """CRC-16/X.25 as used by AX.25 (init 0xFFFF, reflected, final xor)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def decode_call(raw: bytes) -> str:
    """Seven-byte AX.25 address field to 'CALL-SSID' text."""
    call = "".join(chr(b >> 1) for b in raw[:6]).strip()
    ssid = (raw[6] >> 1) & 0x0F
    return f"{call}-{ssid}" if ssid else call


def valid_call(raw: bytes) -> bool:
    if len(raw) < 7:
        return False
    for b in raw[:6]:
        c = chr(b >> 1)
        if b & 1 or not (c.isalnum() or c == " "):
            return False
    return True


def decode_control(ctl: int) -> dict:
    pf = bool(ctl & 0x10)
    if ctl & 1 == 0:
        return {"type": "I", "ns": (ctl >> 1) & 7, "nr": (ctl >> 5) & 7, "pf": pf}
    if ctl & 3 == 1:
        kind = {0: "RR", 1: "RNR", 2: "REJ", 3: "SREJ"}[(ctl >> 2) & 3]
        return {"type": kind, "nr": (ctl >> 5) & 7, "pf": pf}
    kind = {
        0x03: "UI", 0x0F: "DM", 0x2F: "SABM", 0x43: "DISC", 0x63: "UA",
        0x6F: "SABME", 0x87: "FRMR", 0xAF: "XID", 0xE3: "TEST",
    }.get(ctl & ~0x10, f"U?{ctl:02x}")
    return {"type": kind, "pf": pf}


def decode_nodes(info: bytes) -> dict:
    """NET/ROM NODES broadcast (UI to NODES, PID 0xCF, first byte 0xFF)."""
    out = {"kind": "NODES", "sender_alias": info[1:7].decode("ascii", "replace").strip()}
    entries = []
    body = info[7:]
    while len(body) >= 21:
        e = body[:21]
        body = body[21:]
        entries.append({
            "call": decode_call(e[0:7]),
            "alias": e[7:13].decode("ascii", "replace").strip(),
            "via": decode_call(e[13:20]),
            "quality": e[20],
        })
    out["entries"] = entries
    if body:
        out["trailing_hex"] = body.hex()
    return out


def decode_rif(info: bytes) -> dict:
    """INP3 Routing Information Frame: 0xFF then RIPs.

    RIP = call(7) hops(1) tripTime(2, big endian, 10 ms units) options, where
    options are (len, type, data[len-2]) records ended by a zero length byte.
    """
    out = {"kind": "RIF", "rips": []}
    p = 1
    while p < len(info):
        if len(info) - p < 10 or not valid_call(info[p:p + 7]):
            out["error"] = f"bad RIP at offset {p}"
            out["rest_hex"] = info[p:].hex()
            break
        rip = {
            "call": decode_call(info[p:p + 7]),
            "hops": info[p + 7],
            "tt": (info[p + 8] << 8) | info[p + 9],
        }
        p += 10
        opts = []
        while p < len(info) and info[p] != 0:
            ln = info[p]
            if ln < 2 or p + ln > len(info):
                out["error"] = f"bad option length {ln} at offset {p}"
                break
            typ = info[p + 1]
            data = info[p + 2:p + ln]
            if typ == 0:
                rip["alias"] = data.decode("ascii", "replace")
            elif typ == 1 and len(data) >= 4:
                rip["ip"] = ".".join(str(b) for b in data[:4])
            opts.append({"type": typ, "hex": data.hex()})
            p += ln
        if "error" in out:
            out["rips"].append(rip)
            break
        p += 1  # zero terminator of this RIP
        if opts:
            rip["options"] = opts
        out["rips"].append(rip)
    return out


def decode_l3rtt_text(text: str) -> dict:
    """Pull the useful fields out of an L3RTT payload (MAN L3RTT)."""
    out: dict = {"text": text}
    words = text.split()
    if words and words[0] == "L3RTT:":
        names = ["ts", "srtt", "rtt", "id", "alias", "inp_id", "sw"]
        for n, w in zip(names, words[1:8]):
            out[n] = w
        out["flags"] = [w for w in words[1:] if w.startswith("$")]
    return out


def decode_netrom(info: bytes, dest: str, ctl: dict) -> dict:
    if not info:
        return {"kind": "EMPTY"}
    if info[0] == 0xFF:
        if ctl.get("type") == "UI" and dest == "NODES":
            return decode_nodes(info)
        return decode_rif(info)
    if info[0] == 0xFE and ctl.get("type") == "UI" and dest == "NODES":
        # A NODES poll: "please send me your NODES now", alias follows.
        return {"kind": "NODES_POLL", "sender_alias": info[1:7].decode("ascii", "replace").strip()}
    if len(info) < 20 or not valid_call(info[0:7]) or not valid_call(info[7:14]):
        return {"kind": "UNKNOWN", "hex": info.hex()}
    src = decode_call(info[0:7])
    dst = decode_call(info[7:14])
    ttl = info[14]
    ci, cid, txno, rxno, op = info[15], info[16], info[17], info[18], info[19]
    payload = info[20:]
    out = {
        "kind": "L3",
        "l3src": src,
        "l3dst": dst,
        "ttl": ttl,
        "l4": {
            "op": L4_OPCODES.get(op & 0x0F, f"OP{op & 0x0F}"),
            "choke": bool(op & 0x80),
            "nak": bool(op & 0x40),
            "more": bool(op & 0x20),
            "ci": ci, "cid": cid, "txno": txno, "rxno": rxno,
        },
    }
    if dst == "L3RTT":
        out["kind"] = "L3RTT"
        out["l3rtt"] = decode_l3rtt_text(payload.decode("ascii", "replace").rstrip("\r\x00 "))
    elif payload:
        out["payload_len"] = len(payload)
        out["payload_text"] = payload[:120].decode("ascii", "replace")
    return out


def decode_frame(data: bytes) -> dict:
    out: dict = {"len": len(data)}
    if len(data) >= 2 and fcs16(data[:-2]) == (data[-2] | (data[-1] << 8)):
        out["fcs"] = "ok"
        frame = data[:-2]
    else:
        out["fcs"] = "absent_or_bad"
        frame = data
    if len(frame) < 15:
        out["error"] = "too short"
        out["hex"] = data.hex()
        return out
    addrs = []
    p = 0
    while p + 7 <= len(frame):
        addrs.append(frame[p:p + 7])
        p += 7
        if frame[p - 1] & 1:
            break
    if len(addrs) < 2 or p >= len(frame):
        out["error"] = "bad address field"
        out["hex"] = data.hex()
        return out
    out["dst"] = decode_call(addrs[0])
    out["src"] = decode_call(addrs[1])
    out["cmd"] = bool(addrs[0][6] & 0x80) and not bool(addrs[1][6] & 0x80)
    if len(addrs) > 2:
        out["digis"] = [decode_call(a) for a in addrs[2:]]
    ctl = decode_control(frame[p])
    p += 1
    out["ctl"] = ctl
    if ctl["type"] in ("I", "UI"):
        if p < len(frame):
            pid = frame[p]
            p += 1
            out["pid"] = f"{pid:02X}"
            info = frame[p:]
            if pid == 0xCF:
                out["netrom"] = decode_netrom(info, out["dst"], ctl)
            elif info:
                out["info_len"] = len(info)
                out["info_text"] = info[:80].decode("ascii", "replace")
    elif ctl["type"] in ("FRMR", "XID", "TEST") and p < len(frame):
        out["info_hex"] = frame[p:].hex()
    return out


def summarise(rec: dict) -> str:
    """One readable line per frame for the plain text log."""
    f = rec.get("frame", {})
    s = f"{rec['t']:.3f} {rec['link']} {rec['from']}->{rec['to']} "
    s += f"{f.get('src', '?')}>{f.get('dst', '?')} {f.get('ctl', {}).get('type', '?')}"
    nr = f.get("netrom")
    if nr:
        k = nr["kind"]
        if k == "NODES":
            s += f" NODES from {nr['sender_alias']}: " + ", ".join(
                f"{e['alias']}:{e['call']} via {e['via']} q{e['quality']}" for e in nr["entries"])
        elif k == "RIF":
            s += " RIF: " + ", ".join(
                f"{r.get('alias', '')}:{r['call']} h{r['hops']} tt{r['tt']}" for r in nr["rips"])
            if "error" in nr:
                s += f" [{nr['error']}]"
        elif k == "L3RTT":
            s += f" L3RTT {nr['l3src']}>{nr['l3dst']} ttl{nr['ttl']}: {nr['l3rtt']['text']}"
        elif k == "L3":
            s += f" L3 {nr['l3src']}>{nr['l3dst']} {nr['l4']['op']}"
            if "payload_text" in nr:
                s += f" {nr['payload_text']!r}"
        else:
            s += f" {k}"
    return s


# --------------------------------------------------------------------------
# Relay
# --------------------------------------------------------------------------


@dataclass
class Link:
    name: str
    a: dict
    b: dict
    a_port: int
    b_port: int
    drop: bool = False
    delay_ms: int = 0
    counts: dict = field(default_factory=lambda: {"forwarded": 0, "dropped": 0})
    a_transport: asyncio.DatagramTransport | None = None
    b_transport: asyncio.DatagramTransport | None = None


class Logger:
    def __init__(self, path: str, text_path: str | None):
        self.f = open(path, "a", buffering=1)
        self.t = open(text_path, "a", buffering=1) if text_path else None

    def write(self, rec: dict) -> None:
        self.f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        if self.t:
            if "frame" in rec:
                self.t.write(summarise(rec) + "\n")
            else:
                self.t.write(f"{rec['t']:.3f} {rec.get('event', '')} {rec.get('text', '')}\n")


class Side(asyncio.DatagramProtocol):
    def __init__(self, relay: "Relay", link: Link, side: str):
        self.relay, self.link, self.side = relay, link, side

    def datagram_received(self, data: bytes, addr) -> None:
        self.relay.on_datagram(self.link, self.side, data, addr)


class Relay:
    def __init__(self, links: list[Link], log: Logger):
        self.links = {l.name: l for l in links}
        self.log = log

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        for l in self.links.values():
            l.a_transport, _ = await loop.create_datagram_endpoint(
                lambda l=l: Side(self, l, "a"), local_addr=("0.0.0.0", l.a_port))
            l.b_transport, _ = await loop.create_datagram_endpoint(
                lambda l=l: Side(self, l, "b"), local_addr=("0.0.0.0", l.b_port))
        self.log.write({"t": time.time(), "event": "start",
                        "text": json.dumps({n: [l.a, l.b] for n, l in self.links.items()})})

    def on_datagram(self, link: Link, side: str, data: bytes, addr) -> None:
        if side == "a":
            src, dst, out = link.a, link.b, link.b_transport
        else:
            src, dst, out = link.b, link.a, link.a_transport
        rec = {
            "t": round(time.time(), 3),
            "link": link.name,
            "from": src["name"],
            "to": dst["name"],
            "from_addr": f"{addr[0]}:{addr[1]}",
        }
        if addr[0] != src["host"]:
            rec["warning"] = f"unexpected source, expected {src['host']}"
        try:
            rec["frame"] = decode_frame(data)
        except Exception as e:  # never let a decode bug stop forwarding
            rec["frame"] = {"error": f"decoder crashed: {e!r}", "hex": data.hex()}
        rec["raw"] = data.hex()
        if link.drop:
            rec["action"] = "dropped"
            link.counts["dropped"] += 1
            self.log.write(rec)
            return
        rec["action"] = "forwarded"
        link.counts["forwarded"] += 1
        self.log.write(rec)
        target = (dst["host"], dst["port"])
        if link.delay_ms > 0:
            asyncio.get_running_loop().call_later(link.delay_ms / 1000, out.sendto, data, target)
        else:
            out.sendto(data, target)

    def state(self) -> dict:
        return {n: {"drop": l.drop, "delay_ms": l.delay_ms, **l.counts}
                for n, l in self.links.items()}

    async def handle_http(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = (await reader.readline()).decode("latin-1").strip()
            while (await reader.readline()) not in (b"\r\n", b"\n", b""):
                pass
            method, target, _ = line.split(" ", 2)
            url = urllib.parse.urlsplit(target)
            q = dict(urllib.parse.parse_qsl(url.query))
            parts = [p for p in url.path.split("/") if p]
            status, body = 200, None
            if parts == ["links"]:
                body = self.state()
            elif len(parts) == 2 and parts[0] == "links" and method == "POST":
                l = self.links.get(parts[1])
                if l is None:
                    status, body = 404, {"error": "no such link"}
                else:
                    if "drop" in q:
                        l.drop = q["drop"] not in ("0", "false", "")
                    if "delay_ms" in q:
                        l.delay_ms = int(q["delay_ms"])
                    self.log.write({"t": round(time.time(), 3), "event": "control",
                                    "text": f"{l.name} drop={l.drop} delay_ms={l.delay_ms}"})
                    body = self.state()
            elif parts == ["mark"] and method == "POST":
                self.log.write({"t": round(time.time(), 3), "event": "mark", "text": q.get("text", "")})
                body = {"ok": True}
            else:
                status, body = 404, {"error": "unknown path"}
            payload = json.dumps(body).encode()
            writer.write(f"HTTP/1.0 {status} X\r\nContent-Type: application/json\r\n"
                         f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)
            await writer.drain()
        except Exception as e:
            writer.write(f"HTTP/1.0 500 X\r\n\r\n{e!r}".encode())
        finally:
            writer.close()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--log", required=True, help="JSON lines output file")
    ap.add_argument("--text-log", help="optional one-line-per-frame text log")
    ap.add_argument("--control-port", type=int, default=8080)
    args = ap.parse_args()
    with open(args.config) as f:
        cfg = json.load(f)
    links = [Link(name=l["name"], a=l["a"], b=l["b"], a_port=l["a_port"], b_port=l["b_port"])
             for l in cfg["links"]]
    relay = Relay(links, Logger(args.log, args.text_log))
    await relay.start()
    server = await asyncio.start_server(relay.handle_http, "0.0.0.0", args.control_port)
    print(f"relay up: {len(links)} links, control on :{args.control_port}", flush=True)

    async def heartbeat() -> None:
        # Proves the relay itself was alive during any quiet spell in the log.
        while True:
            await asyncio.sleep(30)
            relay.log.write({"t": round(time.time(), 3), "event": "stats", "text": json.dumps(relay.state())})

    hb = asyncio.create_task(heartbeat())
    async with server:
        await server.serve_forever()
    hb.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
