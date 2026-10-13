#!/usr/bin/env python3
"""Give XRouter a serial port that tests can reach over TCP.

    ptybridge.py <link> <tcp_port>

Opens a pty pair, links the slave side to <link> (e.g. /dev/ttyDED, the COM
of an ASYNC interface) and relays the master side to one TCP client at a
time on <tcp_port>. The pty outlives client connections, so XRouter keeps
its port while tests come and go.
"""
import os
import select
import socket
import sys
import tty

link, port = sys.argv[1], int(sys.argv[2])
master, slave = os.openpty()
tty.setraw(slave)
name = os.ttyname(slave)
if os.path.lexists(link):
    os.unlink(link)
os.symlink(name, link)
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", port))
srv.listen(1)
client = None
while True:
    fds = [master, srv] + ([client] if client else [])
    ready, _, _ = select.select(fds, [], [])
    if srv in ready:
        if client:
            client.close()
        client, _ = srv.accept()
    if master in ready:
        data = os.read(master, 4096)
        if client:
            try:
                client.sendall(data)
            except OSError:
                client.close()
                client = None
    if client and client in ready:
        data = client.recv(4096)
        if not data:
            client.close()
            client = None
        else:
            os.write(master, data)
