"""PMS / BBS (groups.io 4400: on 505o "after asking for the msg nr ... the bbs
disconnects" and "the connect text/bbs prompt has changed: only a header and
prompt are shown").

The DUT runs its mailbox as a full BBS (PMSTYPE=4, as on a node that offers a
BBS like PA2SNK's) with PMSCALL PN0DUT-2 / PMSALIAS DUTPMS. The tests use it
from the telnet console (`BBS`, `PMS`) and as a radio user would, with an
AX.25 connect to PN0DUT-2 from probe A. Message numbers are not assumed:
each test sends its own message and finds its number in the list.
"""

from __future__ import annotations

import os
import re
import time

import pytest

from ax25 import L2Session
from conftest import OUT

PMSCALL = "PN0DUT-2"
PROMPT = r"\]?\s*[A-Z?,$]*\s*>\s*$"


def save(name: str, text: str) -> None:
    os.makedirs(os.path.join(OUT, "pms"), exist_ok=True)
    with open(os.path.join(OUT, "pms", name + ".txt"), "w") as f:
        f.write(text)


def check_greeting(text: str) -> None:
    """505c's greeting: the [XR-...] SID, 'Welcome to <call>'s PMS', the new
    message count, then the prompt with the command letters."""
    assert re.search(r"\[XR-", text), f"no SID in greeting:\n{text}"
    assert re.search(r"Welcome to", text, re.I), f"no welcome line in greeting:\n{text}"
    assert re.search(r"You have \d+ new messages?", text, re.I), f"no new-messages line:\n{text}"
    assert re.search(r"\[\d+\][^\n]*>", text), f"no [n] ... > prompt:\n{text}"


def send_message(write, read, to: str, subject: str, body: str) -> int:
    """Send a personal message; return its number from '*** Message n saved'."""
    write(f"SP {to}")
    out = read()
    assert re.search(r"subject", out, re.I), f"SP gave no subject prompt:\n{out}"
    write(subject)
    out = read()
    assert re.search(r"Enter message", out, re.I), f"no message prompt after subject:\n{out}"
    write(body)
    write("/EX")
    out = read()
    m = re.search(r"Message (\d+) saved", out)
    assert m, f"no 'Message n saved' after /EX:\n{out}"
    return int(m.group(1))


# ---------------------------------------------------------------- telnet

@pytest.fixture(scope="module")
def bbs_telnet(stack):
    from conftest import DUT_TELNET, HOST, Log
    from xrconsole import XRConsole
    c = XRConsole(HOST, DUT_TELNET, "PN0USR", name="pms-telnet", log=Log(os.path.join(OUT, "consoles.txt")))
    greeting = c.cmd("BBS", 2.5)
    save("telnet-greeting", greeting)
    yield c, greeting
    c.close()


def test_bbs_command_greeting(bbs_telnet):
    c, greeting = bbs_telnet
    check_greeting(greeting)


def test_pms_command_greeting(stack):
    from conftest import DUT_TELNET, HOST
    from xrconsole import XRConsole
    c = XRConsole(HOST, DUT_TELNET, "PN0USS", name="pms-cmd")
    try:
        g = c.cmd("PMS", 2.5)
        save("telnet-pms-greeting", g)
        check_greeting(g)
    finally:
        c.close()


def test_telnet_send_list_read_kill(bbs_telnet):
    c, _ = bbs_telnet
    w = lambda s: c.send(s)  # noqa: E731
    r = lambda: c.drain(1.5, 10)  # noqa: E731
    n = send_message(w, r, "PN0DUT", "regress telnet subject", "telnet body line one")
    out = c.cmd("L", 1.5)
    assert re.search(rf"^\s*{n}\s.*regress telnet subject", out, re.M), f"message {n} not in L:\n{out}"
    out = c.cmd(f"R {n}", 2)
    save("telnet-read", out)
    assert "telnet body line one" in out, f"R {n} did not show the body:\n{out}"
    out = c.cmd(str(n), 2)
    assert "telnet body line one" in out, f"reading by bare number {n} did not show the body:\n{out}"
    out = c.cmd(f"K {n}", 1.5)
    assert re.search(rf"{n}.*deleted", out, re.I), f"K {n}:\n{out}"


# ---------------------------------------------------------------- AX.25

@pytest.fixture(scope="module")
def bbs_ax25(probe_a):
    s = L2Session(probe_a, "PN0RF", PMSCALL)
    assert s.connect(), f"no UA from {PMSCALL}"
    greeting = s.read(2.5, 15)
    save("ax25-greeting", greeting)
    yield s, greeting
    s.disconnect()


def test_ax25_connect_greeting(bbs_ax25):
    s, greeting = bbs_ax25
    check_greeting(greeting)


def test_ax25_send_and_read_by_number(bbs_ax25):
    """The PA2SNK case: read a message by number over an AX.25 connection.
    The link must stay up and the body arrive."""
    s, _ = bbs_ax25
    n = send_message(s.line, lambda: s.read(1.5, 15), "PN0DUT", "regress rf subject", "rf body line one")
    s.line(f"R {n}")
    out = s.read(2, 15)
    save("ax25-read", out)
    assert s.state == "connected", f"BBS disconnected after R {n}:\n{out}"
    assert "rf body line one" in out, f"R {n} did not show the body:\n{out}"
    s.line(str(n))
    out = s.read(2, 15)
    assert s.state == "connected", f"BBS disconnected after reading {n} by bare number:\n{out}"
    assert "rf body line one" in out, f"bare {n} did not show the body:\n{out}"
    s.line(f"K {n}")
    s.read(1.5, 10)


def test_ax25_list_after_send(bbs_ax25):
    s, _ = bbs_ax25
    n = send_message(s.line, lambda: s.read(1.5, 15), "PN0DUT", "regress rf list", "list body")
    s.line("L")
    out = s.read(2, 15)
    assert s.state == "connected", f"BBS disconnected after L:\n{out}"
    assert re.search(rf"^\s*{n}\s.*regress rf list", out, re.M), f"message {n} not in L:\n{out}"
    s.line(f"K {n}")
    s.read(1.5, 10)


def test_ax25_bye_disconnects(probe_a):
    s = L2Session(probe_a, "PN0RG", PMSCALL)
    assert s.connect()
    s.read(2, 10)
    s.line("B")
    end = time.time() + 15
    while time.time() < end and s.state == "connected":
        time.sleep(0.2)
    assert s.state == "disconnected", "BBS did not disconnect after B"


# ---------------------------------------------------------------- node via AX.25

def test_ax25_node_call_no_ctext(probe_a):
    """CTFLAGS defaults to 9: no CTEXT for a connect to the node call, but the
    node answers commands."""
    s = L2Session(probe_a, "PN0RI", "PN0DUT")
    assert s.connect(), "no UA from the node call"
    try:
        greeting = s.read(2, 10)
        assert "regress test node" not in greeting, greeting
        s.line("P")
        out = s.read(1.5, 10)
        assert "PN0DUT:DUT}" in out and "Probe A" in out, out
    finally:
        s.disconnect()


def test_ax25_node_ctext_and_prompt(probe_a):
    """Connecting to the node alias gives the CTEXT; a command gets the
    'PN0DUT:DUT}' reply prefix; BBS from there and back."""
    s = L2Session(probe_a, "PN0RH", "DUT")
    assert s.connect(), "no UA from the node alias"
    try:
        greeting = s.read(2, 10)
        save("ax25-node-greeting", greeting)
        assert "PN0DUT regress test node" in greeting, greeting
        s.line("P")
        out = s.read(1.5, 10)
        assert "PN0DUT:DUT}" in out and "Probe A" in out, out
        s.line("BBS")
        out = s.read(2.5, 15)
        save("ax25-node-bbs-greeting", out)
        check_greeting(out)
        s.line("B")
        out = s.read(2, 10)
        assert s.state == "connected", "leaving the BBS entered from the node dropped the link"
    finally:
        s.disconnect()
