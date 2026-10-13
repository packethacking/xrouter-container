"""A minimal NET/ROM node behind a Probe, to stand in for a neighbour.

It broadcasts NODES (UI to NODES, PID 0xCF) on a timer, accepts the L2
link XRouter opens to it, and optionally speaks enough INP3 to be taken for
an INP3 neighbour: it reflects L3RTT frames and sends a RIF with its own
node (and any extra destinations) after the link comes up and on a timer.
"""

from __future__ import annotations

import threading
import time

from ax25 import L2Session, Probe, enc_call, ui

PID_NETROM = 0xCF


def nodes_broadcast(alias: str, entries=()) -> bytes:
    """entries: (call, alias, best_neighbour, quality)."""
    out = b"\xff" + alias.upper().ljust(6).encode()[:6]
    for call, al, via, q in entries:
        out += _call7(call) + al.upper().ljust(6).encode()[:6] + _call7(via) + bytes([q])
    return out


def _call7(call: str) -> bytes:
    raw = enc_call(call)
    return raw[:6] + bytes([raw[6] & 0x1E | 0x60])


def rif(rips) -> bytes:
    """rips: (call, hops, tt, alias or None)."""
    out = b"\xff"
    for call, hops, tt, alias in rips:
        out += _call7(call) + bytes([hops]) + tt.to_bytes(2, "big")
        if alias:
            a = alias.upper().encode()
            out += bytes([len(a) + 2, 0]) + a
        out += b"\x00"
    return out


class FakeNode:
    def __init__(self, probe: Probe, call: str, alias: str, neighbour: str, inp3: bool = False,
                 nodes_entries=(), rif_extra=(), nodes_every: float = 30.0, rif_every: float = 60.0,
                 delay: float = 0.0):
        self.probe, self.call, self.alias, self.neighbour = probe, call.upper(), alias.upper(), neighbour.upper()
        self.inp3 = inp3
        # XRouter ignores a NODES broadcast with no entries, so always list
        # something: a BBS at SSID 7 of our own call by default.
        self.nodes_entries = list(nodes_entries) or [(f"{self.call}-7", self.alias[:5] + "B", self.call, 200)]
        self.rif_extra = list(rif_extra)
        self.nodes_every, self.rif_every = nodes_every, rif_every
        self.session = L2Session(probe, self.call, self.neighbour, delay=delay)
        self.session.state = "listening"
        self.l3rtt_reflected = 0
        self.rifs_sent = 0
        self.l3_frames: list[bytes] = []
        self._stop = False
        orig = self.session._incoming

        def incoming(f):
            if f.type == "I" and f.pid == PID_NETROM:
                self._netrom(f.info)
            orig(f)
        self.session._incoming = incoming
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"fakenode-{call}")
        self.thread.start()

    def _netrom(self, info: bytes) -> None:
        if len(info) >= 20 and info[0] != 0xFF:
            dst = "".join(chr(b >> 1) for b in info[7:13]).strip()
            src = "".join(chr(b >> 1) for b in info[0:6]).strip()
            if dst == "L3RTT" and src == self.call:
                return          # our own probe coming back
            if dst == "L3RTT" and self.inp3:
                # Reflect it, TTL one less, as LinBPQ and XRouter do.
                back = info[:14] + bytes([max(info[14] - 1, 0)]) + info[15:]
                threading.Thread(target=self._send_i, args=(back,), daemon=True).start()
                self.l3rtt_reflected += 1
                return
            self.l3_frames.append(info)

    def _send_i(self, info: bytes) -> None:
        s = self.session
        if s.state != "connected":
            return
        ns = s.vs
        s.vs = (s.vs + 1) & 7
        ctl = (ns << 1) | (s.vr << 5)
        from ax25 import Frame
        self.session._tx(Frame(dst=self.neighbour, src=self.call, ctl=ctl, pid=PID_NETROM, info=info))

    def send_l3rtt(self) -> None:
        """Our own L3RTT probe, as LinBPQ sends it: NET/ROM L3 to L3RTT with
        the INP3 flag $N, which the neighbour reflects."""
        text = (f"L3RTT: {int(time.time() * 100) % 1000000:10d} {0:10d} {0:10d} {1:10d} "
                f"{self.alias:<6} LEVEL3_V2.1 FAKE001 $M9000 $N $H4\r").encode()
        hdr = _call7(self.call) + _call7("L3RTT") + bytes([2]) + bytes([0, 0, 0, 0, 5])
        self._send_i(hdr + text)

    def send_rif(self) -> None:
        self._send_i(rif([(self.call, 1, 1, self.alias)] + self.rif_extra))
        self.rifs_sent += 1

    def broadcast(self) -> None:
        self.session._tx(ui("NODES", self.call, nodes_broadcast(self.alias, self.nodes_entries), pid=PID_NETROM))

    def _run(self) -> None:
        next_nodes = 0.0
        next_rif = 0.0
        was_connected = False
        while not self._stop:
            now = time.time()
            if now >= next_nodes:
                self.broadcast()
                next_nodes = now + self.nodes_every
            connected = self.session.state == "connected"
            if self.inp3 and connected and (not was_connected or now >= next_rif):
                time.sleep(1)
                self.send_l3rtt()
                time.sleep(1)
                self.send_rif()
                next_rif = now + self.rif_every
            was_connected = connected
            time.sleep(0.5)

    def stop(self) -> None:
        self._stop = True
        self.session.abort()
