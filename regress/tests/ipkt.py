"""Just enough IPv4 / ICMP / ARP (AX.25 flavour) to talk to XRouter's stack."""

from __future__ import annotations

import socket
import struct

PID_IP, PID_ARP = 0xCC, 0xCD


def csum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\0"
    s = sum(struct.unpack(f"!{len(data) // 2}H", data))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return ~s & 0xFFFF


def ipv4(src: str, dst: str, proto: int, payload: bytes, ttl: int = 64, ident: int = 0x1234) -> bytes:
    hdr = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(payload), ident, 0, ttl, proto, 0,
                      socket.inet_aton(src), socket.inet_aton(dst))
    hdr = hdr[:10] + struct.pack("!H", csum(hdr)) + hdr[12:]
    return hdr + payload


def icmp_echo(ident: int, seq: int, data: bytes = b"regress", reply: bool = False) -> bytes:
    body = struct.pack("!BBHHH", 0 if reply else 8, 0, 0, ident, seq) + data
    return body[:2] + struct.pack("!H", csum(body)) + body[4:]


def parse_ip(pkt: bytes) -> dict | None:
    if len(pkt) < 20 or pkt[0] >> 4 != 4:
        return None
    ihl = (pkt[0] & 0x0F) * 4
    d = {"src": socket.inet_ntoa(pkt[12:16]), "dst": socket.inet_ntoa(pkt[16:20]),
         "proto": pkt[9], "ttl": pkt[8], "payload": pkt[ihl:]}
    if d["proto"] == 1 and len(d["payload"]) >= 8:
        t, c, _, ident, seq = struct.unpack("!BBHHH", d["payload"][:8])
        d.update(icmp_type=t, icmp_code=c, icmp_id=ident, icmp_seq=seq)
    return d


def ax25_call_bytes(call: str) -> bytes:
    base, _, ssid = call.upper().partition("-")
    return bytes((ord(c) << 1) for c in base.ljust(6)[:6]) + bytes([0x60 | (int(ssid or 0) << 1)])


def arp_ax25(op: int, sha: str, spa: str, tha: str, tpa: str) -> bytes:
    """ARP over AX.25 (hardware type 3, protocol 0xCC per RFC 1201 practice)."""
    return (struct.pack("!HHBBH", 3, 0xCC, 7, 4, op) + ax25_call_bytes(sha) + socket.inet_aton(spa)
            + ax25_call_bytes(tha) + socket.inet_aton(tpa))
