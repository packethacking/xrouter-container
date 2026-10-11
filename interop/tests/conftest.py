"""Bring the interop stack up once per test session and tear it down after.

Environment:
    XROUTER_TAG   XRouter image tag (default latest)
    LINBPQ_TAG    LinBPQ image tag (default latest)
    XRI_OUT       where the relay log and node logs go (default interop/out)
    XRI_KEEP=1    leave the stack running after the tests, for poking at
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from consoles import BpqConsole, XRouterConsole  # noqa: E402
from wire import Wire, wait_for  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
INTEROP = os.path.dirname(HERE)
OUT = os.path.abspath(os.environ.get("XRI_OUT", os.path.join(INTEROP, "out")))

HOST = "127.0.0.1"
XR_TELNET = int(os.environ.get("XRI_XR_TELNET", "17023"))
BPQ_TELNET = int(os.environ.get("XRI_BPQ_TELNET", "17010"))
BPQ2_TELNET = int(os.environ.get("XRI_BPQ2_TELNET", "17011"))
BPQ3_TELNET = int(os.environ.get("XRI_BPQ3_TELNET", "17012"))
RELAY_CTL = int(os.environ.get("XRI_RELAY_PORT", "17080"))

# Names used throughout the tests.
XR_CALL, XR_ALIAS = "PN0XR", "XRNODE"
BPQ_CALL, BPQ_ALIAS = "PN0BQ", "BPQNOD"
BPQ_APP_CALL, BPQ_APP_ALIAS = "PN0BQ-1", "BQAPP"
BPQ2_CALL, BPQ2_ALIAS = "PN0BQB", "BPQB"
BPQ3_CALL, BPQ3_ALIAS = "PN0BQC", "BPQC"
LINK = "xr-bpq"          # relay link between XRouter and LinBPQ
LINK2 = "bpq-bpq2"       # relay link between LinBPQ and LinBPQ2
LINK3 = "xr-bpq3"        # relay link between XRouter and LinBPQ3

SERVICES = ["relay", "xrouter", "linbpq", "linbpq2", "linbpq3"]


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.setdefault("XRI_UID", str(os.getuid()))
    env.setdefault("XRI_GID", str(os.getgid()))
    env["XRI_OUT"] = OUT
    return subprocess.run(["docker", "compose", "-f", os.path.join(INTEROP, "docker-compose.yml"), *args],
                          env=env, check=check, capture_output=True, text=True)


def relay_ctl(path: str) -> str:
    req = urllib.request.Request(f"http://{HOST}:{RELAY_CTL}{path}", method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read().decode()


def mark(text: str) -> None:
    """Write a marker into the relay log so a reader can find each test's frames."""
    try:
        relay_ctl("/mark?text=" + urllib.request.quote(text))
    except OSError:
        pass


def _port_open(port: int) -> bool:
    import socket
    try:
        with socket.create_connection((HOST, port), timeout=2) as s:
            s.settimeout(2)
            return bool(s.recv(64))
    except OSError:
        return False


def _collect_logs() -> None:
    os.makedirs(OUT, exist_ok=True)
    for svc in SERVICES:
        r = subprocess.run(["docker", "logs", f"xri-{svc}"], capture_output=True, text=True)
        with open(os.path.join(OUT, f"{svc}.log"), "w") as f:
            f.write(r.stdout + r.stderr)
    # XRouter keeps its real logs in /data/LOG; LinBPQ in /data/logs.
    for svc, path in [("xrouter", "/data/LOG"), ("linbpq", "/data/logs"), ("linbpq2", "/data/logs"),
                      ("linbpq3", "/data/logs")]:
        dest = os.path.join(OUT, f"{svc}-files")
        subprocess.run(["docker", "cp", f"xri-{svc}:{path}", dest], capture_output=True)
    for svc, files in [("xrouter", ["XRNODES"]), ("linbpq", ["BPQNODES.dat"]), ("linbpq2", ["BPQNODES.dat"]),
                        ("linbpq3", ["BPQNODES.dat"])]:
        for name in files:
            subprocess.run(["docker", "cp", f"xri-{svc}:/data/{name}", os.path.join(OUT, f"{svc}-{name}")],
                           capture_output=True)


@pytest.fixture(scope="session")
def stack():
    os.makedirs(OUT, exist_ok=True)
    for name in ("relay.jsonl", "relay.txt"):
        p = os.path.join(OUT, name)
        if os.path.exists(p):
            os.remove(p)
    compose("down", "-v", "--remove-orphans", check=False)
    up = compose("up", "-d", check=False)
    if up.returncode != 0:
        pytest.exit(f"docker compose up failed:\n{up.stdout}\n{up.stderr}", returncode=3)
    started = time.time()
    ok = wait_for(lambda: _port_open(XR_TELNET) and _port_open(BPQ_TELNET) and _port_open(BPQ2_TELNET)
                  and _port_open(BPQ3_TELNET), 60)
    if not ok:
        _collect_logs()
        pytest.exit("nodes did not open their telnet ports within 60 s; see the logs in " + OUT, returncode=3)
    info = {"started": started, "out": OUT, "xrouter_tag": os.environ.get("XROUTER_TAG", "latest")}
    yield info
    _collect_logs()
    if os.environ.get("XRI_KEEP") != "1":
        compose("down", "-v", "--remove-orphans", check=False)


@pytest.fixture(scope="session")
def wire(stack) -> Wire:
    return Wire(os.path.join(OUT, "relay.jsonl"))


@pytest.fixture(scope="session")
def converged(stack, wire):
    """Give INP3 a chance to settle: both sides have sent RIF on the XRouter link
    and LinBPQ has told XRouter about LinBPQ2. Never fails by itself: tests that
    depend on a step that did not happen fail with their own evidence."""
    def done():
        return (wire.rifs(LINK, "xrouter") and
                any(rip["call"] == BPQ2_CALL for rip, _ in wire.rips(LINK, "linbpq")) and
                any(rip["call"] == BPQ2_CALL for rip, _ in wire.rips(LINK3, "xrouter")))
    wait_for(done, 120, 3)
    # One more NODES interval so both NODES tables are populated too.
    time.sleep(5)
    return True


@pytest.fixture
def xr(stack):
    with XRouterConsole(HOST, XR_TELNET) as c:
        yield c


@pytest.fixture
def bpq(stack):
    with BpqConsole(HOST, BPQ_TELNET) as c:
        yield c


@pytest.fixture
def bpq2(stack):
    with BpqConsole(HOST, BPQ2_TELNET, name="linbpq2") as c:
        yield c


@pytest.fixture
def bpq3(stack):
    with BpqConsole(HOST, BPQ3_TELNET, name="linbpq3") as c:
        yield c


@pytest.fixture(autouse=True)
def _mark_test(request, stack):
    mark(f"BEGIN {request.node.name}")
    yield
    mark(f"END {request.node.name}")
