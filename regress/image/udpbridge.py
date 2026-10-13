#!/usr/bin/env python3
"""Relay one AXUDP port of XRouter between localhost and the outside.

    udpbridge.py <xr_port> <local_port> <outside_bind_port> <probe_host> <probe_port>

XRouter's port is IPLINK=127.0.0.1, UDPREMOTE=<local_port>, so it uses the
Linux stack even when a TUN port would otherwise put AXUDP on XRouter's
own. Datagrams XRouter sends to 127.0.0.1:<local_port> go to the probe;
datagrams arriving on <outside_bind_port> go to XRouter from <local_port>,
so they come from the address and port XRouter expects.
"""
import select
import socket
import sys

xr_port, local_port, outside_port, probe_host, probe_port = sys.argv[1:6]
inner = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
inner.bind(("127.0.0.1", int(local_port)))
outer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
outer.bind(("0.0.0.0", int(outside_port)))
probe = (probe_host, int(probe_port))
xr = ("127.0.0.1", int(xr_port))
while True:
    ready, _, _ = select.select([inner, outer], [], [])
    for s in ready:
        data, _ = s.recvfrom(65535)
        if s is inner:
            outer.sendto(data, probe)
        else:
            inner.sendto(data, xr)
