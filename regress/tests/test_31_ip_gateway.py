"""XRouter as an AMPRNet gateway through a TUN interface (groups.io 4386-4397,
Jean VE2PKT: on 505o "cannot ping any 44 station ... no 44 traffic going out
using version o"; AXUDP and AXTCP are fine; 505c works).

The node is xrr-ip (config/ip). Linux on the far side of tun99 plays the
rest of the network: a tcpdump on tun99 shows what XRouter routes into the
tunnel, and Linux's own ping and a raw socket play the hosts beyond it.
Each route form in IPROUTE.SYS has its own destination range.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time

import pytest

from ax25 import Frame, ui
from conftest import dexec
from ipkt import PID_IP, icmp_echo, ipv4, parse_ip

NODE = "xrr-ip"
NODE_CALL, NODE_IP = "PN0IP", "44.130.0.1"
TT_CALL, TT_IP = "PN0TT", "44.130.1.2"
AXIP_PEER = "44.130.2.2"


class Tcpdump:
    """tcpdump on tun99 inside the node, in the background, for a window."""

    def __init__(self, expr: str = "", seconds: float = 12):
        self.out = ""
        self.t = threading.Thread(target=self._run, args=(expr, seconds), daemon=True)
        self.t.start()
        time.sleep(1.5)   # let it attach before the test makes traffic

    def _run(self, expr, seconds):
        r = subprocess.run(["docker", "exec", NODE, "timeout", str(seconds), "tcpdump", "-l", "-n", "-i", "tun99",
                            *expr.split()], capture_output=True, text=True)
        self.out = r.stdout

    def result(self) -> str:
        self.t.join()
        return self.out


def console_ping(con, target: str, wait: float = 6) -> str:
    con.send(f"PING {target}")
    time.sleep(wait)
    con.send("")
    return con.drain(1, 3)


def test_tun_is_up(ipgw):
    r = dexec(NODE, "ip addr show tun99")
    assert "UP" in r.stdout and "192.168.99.98" in r.stdout, r.stdout + r.stderr


def test_linux_pings_xrouter_tun_address(ipgw):
    r = dexec(NODE, "ping -c 2 -W 2 192.168.99.99")
    assert " 0% packet loss" in r.stdout, r.stdout


def test_linux_pings_xrouter_main_44_address(ipgw):
    r = dexec(NODE, f"ping -c 2 -W 2 {NODE_IP}")
    assert " 0% packet loss" in r.stdout, r.stdout


def test_xrouter_pings_linux_end_of_tunnel(ipcon):
    out = console_ping(ipcon, "192.168.99.98", 3)
    assert re.search(r"reply from 192\.168\.99\.98", out, re.I), out


def test_xrouter_pings_44net_via_gateway_route(ipcon):
    """`ip route add 44.0.0.0/8 192.168.99.98 1 d`: Jean's case."""
    dump = Tcpdump("icmp")
    console_ping(ipcon, "44.1.2.3", 4)
    out = dump.result()
    assert re.search(r"> 44\.1\.2\.3: ICMP echo request", out), f"no echo request to 44.1.2.3 on tun99:\n{out}"


def test_xrouter_pings_44_partner_and_gets_reply(ipcon):
    """44.130.2.2 is a Linux address beyond the tunnel; Linux answers."""
    out = console_ping(ipcon, AXIP_PEER, 3)
    assert re.search(rf"reply from {re.escape(AXIP_PEER)}", out, re.I), out


def test_xrouter_routes_into_tunnel_without_gateway(ipcon):
    dump = Tcpdump("icmp")
    console_ping(ipcon, "10.77.1.1", 4)
    out = dump.result()
    assert "> 10.77.1.1: ICMP echo request" in out, f"no echo request to 10.77.1.1 on tun99:\n{out}"


def test_xrouter_default_route_into_tunnel(ipcon):
    dump = Tcpdump("icmp")
    console_ping(ipcon, "198.51.100.7", 4)
    out = dump.result()
    assert "> 198.51.100.7: ICMP echo request" in out, f"no echo request to 198.51.100.7 on tun99:\n{out}"


def test_ax25_user_reaches_44net_through_tunnel(ipgw):
    """An AX.25 station on port 2 pings a 44-net host beyond the tunnel:
    XRouter forwards the datagram into tun99 and the reply back to the user."""
    probe = ipgw["probe"]
    dump = Tcpdump("icmp")
    t = time.time()
    probe.send(ui(NODE_CALL, TT_CALL, ipv4(TT_IP, AXIP_PEER, 1, icmp_echo(91, 1)), pid=PID_IP))
    out = dump.result()
    assert re.search(rf"{TT_IP} > {AXIP_PEER}: ICMP echo request", out), \
        f"datagram from the AX.25 user was not forwarded into the tunnel:\n{out}"
    reply = probe.wait(lambda f: f.pid == PID_IP and (parse_ip(f.info) or {}).get("icmp_type") == 0, 8, t)
    assert reply is not None, "the reply from 44-net did not come back to the AX.25 user"


def test_linux_reaches_ax25_user_through_xrouter(ipgw):
    """Linux pings the AX.25 station: XRouter routes it from the tunnel to port 2."""
    probe = ipgw["probe"]
    t = time.time()
    dexec(NODE, f"ping -c 1 -W 3 {TT_IP}")
    f = probe.wait(lambda f: f.pid == PID_IP and (parse_ip(f.info) or {}).get("dst") == TT_IP, 6, t)
    assert f is not None, "datagram from Linux to the AX.25 user was not routed onto port 2"


def test_axip_frames_go_out_through_tunnel(ipcon):
    """A connect on the AXIP port sends SABMs as IP protocol 93 to the partner."""
    dump = Tcpdump("ip proto 93", 10)
    ipcon.cmd("C 3 PN0AX", 4)
    out = dump.result()
    ipcon.send("")
    ipcon.drain(1, 3)
    assert re.search(rf"> {re.escape(AXIP_PEER)}: +ip-proto-93", out), f"no AXIP to {AXIP_PEER} on tun99:\n{out}"


def test_axip_frame_from_partner_is_answered(ipgw):
    """A SABM arriving by AXIP from the 44-net partner gets a UA back by AXIP."""
    f = Frame(dst=NODE_CALL, src="PN0AX", ctl=0x2F | 0x10, pid=None)
    dump = Tcpdump("ip proto 93", 10)
    dexec(NODE, f"python3 /usr/local/bin/axip_send.py {AXIP_PEER} {NODE_IP} {f.encode().hex()}", check=True)
    out = dump.result()
    replies = [l for l in out.splitlines() if re.search(rf"> {re.escape(AXIP_PEER)}: +ip-proto-93", l)]
    assert replies, f"no AXIP reply to {AXIP_PEER} after its SABM:\n{out}"


def test_kernel_mode_route_uses_linux_stack(ipcon):
    """`ip route add 10.78.0.0/16 * 0 k`: handed to Linux, so it leaves on eth0
    (not tun99)."""
    r = []
    th = threading.Thread(target=lambda: r.append(subprocess.run(
        ["docker", "exec", NODE, "timeout", "8", "tcpdump", "-l", "-n", "-i", "any", "icmp and host 10.78.1.1"],
        capture_output=True, text=True).stdout), daemon=True)
    th.start()
    time.sleep(1.5)
    console_ping(ipcon, "10.78.1.1", 4)
    th.join()
    assert "10.78.1.1: ICMP echo request" in r[0], f"no echo request to 10.78.1.1 anywhere:\n{r[0]}"
