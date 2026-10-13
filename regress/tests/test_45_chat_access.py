"""The chat server, and telnet login rules.

Chat: the CHAT command from the node, and an AX.25 connect to CHATCALL
(PN0DUT-8). Two users in the same channel see each other's text.

Access: ACCESS.SYS lets any valid callsign in on telnet without a password
(flag 1); an invalid callsign is refused.
"""

from __future__ import annotations

import os
import re
import socket
import time

import pytest

from ax25 import L2Session
from conftest import DUT_TELNET, HOST, OUT, Log
from xrconsole import XRConsole


def console(call: str, name: str) -> XRConsole:
    return XRConsole(HOST, DUT_TELNET, call, name=name, log=Log(os.path.join(OUT, "consoles.txt")))


def test_chat_command_enters_chat(stack):
    c = console("PN0CHA", "chat-a")
    try:
        out = c.cmd("CHAT", 2.5)
        assert re.search(r"Welcome to the chat server", out, re.I), out
        c.cmd("/N Alice", 2)
        c.cmd("/JOIN 1", 2)
        out = c.cmd("/WHO", 2)
        assert "PN0CHA" in out.upper(), out
        out = c.cmd("/BYE", 2)
    finally:
        c.close()


def test_chat_two_users_see_each_other(stack, probe_a):
    a = console("PN0CHB", "chat-b")
    s = L2Session(probe_a, "PN0CHC", "PN0DUT-8")
    try:
        a.cmd("CHAT", 2.5)
        a.cmd("/N Bob", 2)
        a.cmd("/JOIN 1", 2)
        assert s.connect(), "no UA from CHATCALL PN0DUT-8"
        s.read(2.5, 10)
        s.line("/N Carol")
        s.read(2, 5)
        s.line("/JOIN 1")
        s.read(2, 5)
        a.drain(1, 3)
        s.line("hello from rf chat user")
        out = a.drain(3, 10)
        assert "hello from rf chat user" in out, f"telnet chat user did not see the RF user's text:\n{out}"
        a.send("hello from telnet chat user")
        out = s.read(3, 10)
        assert "hello from telnet chat user" in out, f"RF chat user did not see the telnet user's text:\n{out}"
    finally:
        s.line("/BYE")
        time.sleep(1)
        s.disconnect()
        a.close()


def test_telnet_valid_callsign_logs_in(stack):
    c = console("PN0ACC", "access")
    try:
        out = c.cmd("U", 1.5)
        assert re.search(r"pn0acc", out, re.I), out
    finally:
        c.close()


def test_telnet_invalid_callsign_refused(stack):
    s = socket.create_connection((HOST, DUT_TELNET), timeout=10)
    s.settimeout(1)
    buf = b""
    end = time.time() + 10
    while time.time() < end and b":" not in buf:
        try:
            buf += s.recv(1024)
        except socket.timeout:
            pass
    s.sendall(b"NOTACALL123\r")
    out = b""
    end = time.time() + 8
    while time.time() < end:
        try:
            d = s.recv(1024)
            if not d:
                break
            out += d
        except socket.timeout:
            continue
    s.close()
    text = out.decode("latin-1")
    assert not re.search(r"\}\s*$", text) or re.search(r"invalid|callsign", text, re.I), \
        f"an invalid callsign got a node prompt:\n{text}"


def test_telnet_ctext_sent(stack):
    """CTFLAGS 9 includes telnet callers: the CTEXT follows the login."""
    s = socket.create_connection((HOST, DUT_TELNET), timeout=10)
    s.settimeout(1)
    buf = b""
    end = time.time() + 10
    while time.time() < end and b":" not in buf:
        try:
            buf += s.recv(1024)
        except socket.timeout:
            pass
    s.sendall(b"PN0CTX\r")
    out = b""
    end = time.time() + 5
    while time.time() < end:
        try:
            out += s.recv(1024)
        except socket.timeout:
            continue
    s.close()
    assert b"PN0DUT regress test node" in out, out
