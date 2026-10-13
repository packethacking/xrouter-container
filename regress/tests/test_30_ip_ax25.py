"""IP over AX.25 on the main DUT (datagram mode on port 1).

The DUT is 44.128.0.1; the probe's station PN0TS is 44.128.1.2, with a
static ARP entry and route (config/dut/IPROUTE.SYS). These check XRouter's
IP stack on its own, without the TUN interface; test_31_ip_gateway covers
the TUN / AMPRNet gateway case reported on groups.io.
"""

from __future__ import annotations

import time

from ax25 import ui
from conftest import DUT_CALL
from ipkt import PID_ARP, PID_IP, arp_ax25, icmp_echo, ipv4, parse_ip

ME, ME_IP, DUT_IP44 = "PN0TS", "44.128.1.2", "44.128.0.1"


def ip_frames(probe, since, pred):
    out = []
    for f in probe.received(since, lambda f: f.pid == PID_IP and f.src == DUT_CALL):
        p = parse_ip(f.info)
        if p and pred(p):
            out.append(p)
    return out


def wait_ip(probe, since, pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        got = ip_frames(probe, since, pred)
        if got:
            return got[0]
        time.sleep(0.1)
    return None


def test_dut_answers_ping_over_ax25(probe_a):
    t = time.time()
    probe_a.send(ui(DUT_CALL, ME, ipv4(ME_IP, DUT_IP44, 1, icmp_echo(77, 1)), pid=PID_IP))
    r = wait_ip(probe_a, t, lambda p: p.get("icmp_type") == 0 and p.get("icmp_id") == 77)
    assert r is not None, "no ICMP echo reply over AX.25 from the DUT"
    assert r["src"] == DUT_IP44 and r["dst"] == ME_IP, r


def test_dut_pings_station_over_ax25(dut, probe_a):
    """PING from the console goes out as an IP datagram to PN0TS; our reply
    is reported."""
    t = time.time()
    dut.send(f"PING {ME_IP}")
    req = wait_ip(probe_a, t, lambda p: p.get("icmp_type") == 8 and p["dst"] == ME_IP)
    assert req is not None, "PING from the console sent no ICMP echo request on port 1"
    probe_a.send(ui(DUT_CALL, ME, ipv4(ME_IP, req["src"], 1,
                                       icmp_echo(req["icmp_id"], req["icmp_seq"], req["payload"][8:], reply=True)),
                    pid=PID_IP))
    out = dut.expect(r"reply from", 10)
    dut.send("")
    dut.drain(1, 3)
    assert "reply from" in out.lower(), out


def test_dut_answers_arp_request(probe_a):
    t = time.time()
    probe_a.send(ui("QST", ME, arp_ax25(1, ME, ME_IP, "", DUT_IP44), pid=PID_ARP))
    f = probe_a.wait(lambda f: f.pid == PID_ARP and f.src == DUT_CALL, 10, t)
    assert f is not None, "no ARP reply from the DUT"
    assert f.info[6:8] == b"\x00\x02", f.info.hex()


def test_dut_forwards_ip_between_stations_on_same_port(probe_a):
    """A datagram from PN0TS to another 44.128.1.x station is routed back out
    port 1 (route 44.128.1.0/24 * 1 d), ARP permitting: here the target has
    no ARP entry, so XRouter should send an ARP request for it."""
    t = time.time()
    probe_a.send(ui(DUT_CALL, ME, ipv4(ME_IP, "44.128.1.3", 1, icmp_echo(78, 1)), pid=PID_IP))
    f = probe_a.wait(lambda f: f.src == DUT_CALL and f.pid in (PID_ARP, PID_IP)
                     and (f.pid == PID_ARP or (parse_ip(f.info) or {}).get("dst") == "44.128.1.3"), 10, t)
    assert f is not None, "DUT neither forwarded the datagram nor ARPed for 44.128.1.3"
