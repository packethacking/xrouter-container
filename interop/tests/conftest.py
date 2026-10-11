"""Bring the interop stack up once per test session and tear it down after.

Environment:
    XROUTER_TAG   XRouter image tag (default latest)
    LINBPQ_TAG    LinBPQ image tag (default latest)
    XROUTER_PEER_TAG  the second XRouter's tag (default: the newest version in
                  versions.json older than the one under test)
    XRI_PEERS     which other implementations to start, comma separated, from
                  xnet, tnn, thenet, xrpeer (default all; "none" for none).
                  Tests for a peer that is not started are skipped.
    XRI_OUT       where the relay log and node logs go (default interop/out)
    XRI_KEEP=1    leave the stack running after the tests, for poking at
    XRI_REUSE=1   run against a stack that is already up (no up, no down),
                  for working on the tests themselves
    XRI_BUILD=1   rebuild the locally built peer images (XNet, TNN) first
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import tomllib
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from consoles import BpqConsole, TheNetConsole, TnnConsole, XNetConsole, XRouterConsole  # noqa: E402
from wire import Wire, wait_for  # noqa: E402
from xrversions import version_key as _version_key, xrouter_peer_version, xrouter_version  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
INTEROP = os.path.dirname(HERE)
OUT = os.path.abspath(os.environ.get("XRI_OUT", os.path.join(INTEROP, "out")))

HOST = "127.0.0.1"
XR_TELNET = int(os.environ.get("XRI_XR_TELNET", "17023"))
BPQ_TELNET = int(os.environ.get("XRI_BPQ_TELNET", "17010"))
BPQ2_TELNET = int(os.environ.get("XRI_BPQ2_TELNET", "17011"))
BPQ3_TELNET = int(os.environ.get("XRI_BPQ3_TELNET", "17012"))
RELAY_CTL = int(os.environ.get("XRI_RELAY_PORT", "17080"))
THENET_CONSOLE = int(os.environ.get("XRI_THENET_CONSOLE", "17013"))
TNN_TELNET = int(os.environ.get("XRI_TNN_TELNET", "17014"))
XNET_CONSOLE = int(os.environ.get("XRI_XNET_CONSOLE", "17015"))
XRPEER_TELNET = int(os.environ.get("XRI_XRPEER_TELNET", "17024"))

# Names used throughout the tests.
XR_CALL, XR_ALIAS = "PN0XR", "XRNODE"
BPQ_CALL, BPQ_ALIAS = "PN0BQ", "BPQNOD"
BPQ_APP_CALL, BPQ_APP_ALIAS = "PN0BQ-1", "BQAPP"
BPQ2_CALL, BPQ2_ALIAS = "PN0BQB", "BPQB"
BPQ3_CALL, BPQ3_ALIAS = "PN0BQC", "BPQC"
LINK = "xr-bpq"          # relay link between XRouter and LinBPQ
LINK2 = "bpq-bpq2"       # relay link between LinBPQ and LinBPQ2
LINK3 = "xr-bpq3"        # relay link between XRouter and LinBPQ3

# The other implementations, each on its own link to XRouter.
XNET_CALL, XNET_ALIAS = "PN0XN", "XNET"
TNN_CALL, TNN_ALIAS = "PN0TN", "TNN"
THENET_CALL, THENET_ALIAS = "PN0TH", "THENET"
XRPEER_CALL, XRPEER_ALIAS = "PN0XP", "XRPEER"
XRPEER_APP_CALL, XRPEER_APP_ALIAS = "PN0XP-1", "XPAPP"
XR_APP_CALL, XR_APP_ALIAS = "PN0XR-1", "XRAPP"
LINK_XNET = "xr-xnet"
LINK_TNN = "xr-tnn"
LINK_THENET = "xr-thenet"   # a KISS over TCP tap, not AXUDP
LINK_XRPEER = "xr-xrpeer"

ALL_PEERS = ("xnet", "tnn", "thenet", "xrpeer")
CORE_SERVICES = ["relay", "xrouter", "linbpq", "linbpq2", "linbpq3"]


def enabled_peers() -> list[str]:
    raw = os.environ.get("XRI_PEERS", ",".join(ALL_PEERS)).strip().lower()
    if raw in ("", "none"):
        return []
    peers = [p.strip() for p in raw.split(",") if p.strip()]
    bad = [p for p in peers if p not in ALL_PEERS]
    if bad:
        raise pytest.UsageError(f"XRI_PEERS names unknown peers {bad}; known: {', '.join(ALL_PEERS)}")
    return [p for p in ALL_PEERS if p in peers]


PEERS = enabled_peers()
SERVICES = CORE_SERVICES + PEERS


def needs_peer(peer: str):
    """Skip marker for tests that need one of the optional peers."""
    return pytest.mark.skipif(peer not in PEERS, reason=f"peer {peer} not started (XRI_PEERS)")


def known_issues(version: str, peer_version: str | None = None) -> dict[str, dict]:
    """Map test name -> the known issue that affects it in this version.

    An issue with `applies_to = "peer"` is a bug in the second XRouter rather
    than the one under test, so its range is matched against the peer's version.
    `applies_to = "xnet"`, "tnn", "thenet" or "linbpq" marks a bug in that
    implementation, which applies whatever the XRouter version.
    """
    with open(os.path.join(INTEROP, "known-issues.toml"), "rb") as f:
        issues = tomllib.load(f)["issue"]
    affected = {}
    for issue in issues:
        which = issue.get("applies_to", "tested")
        if which in ("xnet", "tnn", "thenet", "linbpq"):
            # A bug in one of the other implementations. Their versions are
            # pinned, so it applies to every XRouter version.
            for test in issue["tests"]:
                affected.setdefault(test, issue)
            continue
        ver = peer_version if which == "peer" else version
        if ver is None:
            continue
        v = _version_key(ver)
        lo = _version_key(issue["from"]) if "from" in issue else None
        if (lo is None or v >= lo) and v <= _version_key(issue["until"]):
            for test in issue["tests"]:
                affected.setdefault(test, issue)
    return affected


def all_known_issue_tests() -> set[str]:
    with open(os.path.join(INTEROP, "known-issues.toml"), "rb") as f:
        return {t for issue in tomllib.load(f)["issue"] for t in issue["tests"]}


def pytest_collection_modifyitems(config, items):
    version = xrouter_version()
    peer_version = xrouter_peer_version()
    affected = known_issues(version, peer_version)
    # Check names against the whole suite, not just what -k selected.
    names = set()
    for item in items:
        names.add(item.originalname or item.name)
    import glob
    for path in glob.glob(os.path.join(HERE, "test_*.py")):
        with open(path) as f:
            names |= set(re.findall(r"^def (test_\w+)", f.read(), re.M))
    missing = sorted(all_known_issue_tests() - names)
    if missing:
        raise pytest.UsageError(f"known-issues.toml names tests that do not exist: {', '.join(missing)}")
    for item in items:
        issue = affected.get(item.originalname or item.name)
        if issue:
            who = {"peer": f"peer XRouter {peer_version}", "xnet": "XNet 1.38", "tnn": "TNN 1.79",
                   "thenet": "TheNet X1J", "linbpq": "LinBPQ"}.get(issue.get("applies_to", ""), f"XRouter {version}")
            item.add_marker(pytest.mark.xfail(
                reason=f"known issue {issue['id']} in {who}: {issue['title']}",
                strict=issue.get("strict", True)))


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.setdefault("XRI_UID", str(os.getuid()))
    env.setdefault("XRI_GID", str(os.getgid()))
    env["XRI_OUT"] = OUT
    env.setdefault("XROUTER_PEER_TAG", xrouter_peer_version())
    # `down` must see every profile, or it leaves peer containers behind.
    env["COMPOSE_PROFILES"] = ",".join(ALL_PEERS if args and args[0] == "down" else PEERS)
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


def _port_open(port: int, greets: bool = True) -> bool:
    """True once something listens on the port (and, if it greets, says hello)."""
    import socket
    try:
        with socket.create_connection((HOST, port), timeout=2) as s:
            if not greets:
                return True
            s.settimeout(2)
            return bool(s.recv(64))
    except OSError:
        return False


def _ready() -> bool:
    ports = [XR_TELNET, BPQ_TELNET, BPQ2_TELNET, BPQ3_TELNET]
    if "xrpeer" in PEERS:
        ports.append(XRPEER_TELNET)
    if "tnn" in PEERS:
        ports.append(TNN_TELNET)
    quiet = []
    # The XNet and TheNet consoles say nothing until spoken to.
    if "xnet" in PEERS:
        quiet.append(XNET_CONSOLE)
    if "thenet" in PEERS:
        quiet.append(THENET_CONSOLE)
    return all(_port_open(p) for p in ports) and all(_port_open(p, greets=False) for p in quiet)


def _collect_logs() -> None:
    os.makedirs(OUT, exist_ok=True)
    for svc in SERVICES:
        r = subprocess.run(["docker", "logs", f"xri-{svc}"], capture_output=True, text=True)
        with open(os.path.join(OUT, f"{svc}.log"), "w") as f:
            f.write(r.stdout + r.stderr)
    # XRouter keeps its real logs in /data/LOG; LinBPQ in /data/logs.
    for svc, path in [("xrouter", "/data/LOG"), ("linbpq", "/data/logs"), ("linbpq2", "/data/logs"),
                      ("linbpq3", "/data/logs"), ("xrpeer", "/data/LOG")]:
        if svc not in SERVICES:
            continue
        dest = os.path.join(OUT, f"{svc}-files")
        subprocess.run(["docker", "cp", f"xri-{svc}:{path}", dest], capture_output=True)
    for svc, files in [("xrouter", ["XRNODES"]), ("linbpq", ["BPQNODES.dat"]), ("linbpq2", ["BPQNODES.dat"]),
                        ("linbpq3", ["BPQNODES.dat"]), ("xrpeer", ["XRNODES"])]:
        if svc not in SERVICES:
            continue
        for name in files:
            subprocess.run(["docker", "cp", f"xri-{svc}:/data/{name}", os.path.join(OUT, f"{svc}-{name}")],
                           capture_output=True)


@pytest.fixture(scope="session")
def stack():
    os.makedirs(OUT, exist_ok=True)
    if os.environ.get("XRI_REUSE") == "1":
        yield {"started": time.time() - 600, "out": OUT, "xrouter_tag": os.environ.get("XROUTER_TAG", "latest"),
               "xrouter_peer_tag": xrouter_peer_version(), "peers": PEERS}
        return
    for name in ("relay.jsonl", "relay.txt"):
        p = os.path.join(OUT, name)
        if os.path.exists(p):
            os.remove(p)
    compose("down", "-v", "--remove-orphans", check=False)
    # Belt and braces: a stack from an interrupted run can leave containers
    # with our fixed names behind, which makes `up` fail with a name clash.
    subprocess.run(["docker", "rm", "-f", *[f"xri-{s}" for s in CORE_SERVICES + list(ALL_PEERS)]],
                   capture_output=True)
    # XNet and TNN are built locally from upstream downloads (never published).
    # `up` builds them if the images are missing; XRI_BUILD=1 rebuilds anyway.
    if {"xnet", "tnn"} & set(PEERS) and os.environ.get("XRI_BUILD") == "1":
        build = compose("build", *[p for p in ("xnet", "tnn") if p in PEERS], check=False)
        if build.returncode != 0:
            pytest.exit(f"docker compose build failed:\n{build.stdout[-3000:]}\n{build.stderr[-3000:]}", returncode=3)
    up = compose("up", "-d", check=False)
    if up.returncode != 0:
        pytest.exit(f"docker compose up failed:\n{up.stdout}\n{up.stderr}", returncode=3)
    started = time.time()
    ok = wait_for(_ready, 90)
    if not ok:
        _collect_logs()
        pytest.exit("nodes did not open their consoles within 90 s; see the logs in " + OUT, returncode=3)
    info = {"started": started, "out": OUT, "xrouter_tag": os.environ.get("XROUTER_TAG", "latest"),
            "xrouter_peer_tag": xrouter_peer_version(), "peers": PEERS}
    with open(os.path.join(OUT, "versions.txt"), "w") as f:
        f.write(f"xrouter {xrouter_version()}\nxrouter_peer {xrouter_peer_version()}\npeers {' '.join(PEERS) or 'none'}\n")
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


@pytest.fixture
def xrp(stack):
    """Console of the second XRouter."""
    with XRouterConsole(HOST, XRPEER_TELNET, name="xrpeer") as c:
        yield c


@pytest.fixture
def thenet(stack):
    with TheNetConsole(HOST, THENET_CONSOLE) as c:
        yield c


@pytest.fixture
def xnet(stack):
    with XNetConsole(HOST, XNET_CONSOLE) as c:
        yield c


@pytest.fixture
def tnn(stack):
    with TnnConsole(HOST, TNN_TELNET) as c:
        yield c


PEER_LINKS = {"xnet": (LINK_XNET, XNET_CALL), "tnn": (LINK_TNN, TNN_CALL), "xrpeer": (LINK_XRPEER, XRPEER_CALL)}


@pytest.fixture(scope="session")
def peers_converged(stack, wire, converged):
    """Like `converged`, for the other implementations: every INP3 peer has
    exchanged RIFs with XRouter and XRouter has passed its node on to LinBPQ,
    and TheNet has heard XRouter's NODES and sent its own. Never fails by
    itself; gives up after 4 minutes from the start of the stack."""
    def done():
        for peer, (link, call) in PEER_LINKS.items():
            if peer not in PEERS:
                continue
            if not (wire.rifs(link, "xrouter") and wire.rifs(link, peer)):
                return False
            if not any(rip["call"] == call and rip["tt"] < 60000 for rip, _ in wire.rips(LINK, "xrouter")):
                return False
        if "thenet" in PEERS:
            nodes = lambda frm: [r for r in wire.frames(link=LINK_THENET, frm=frm, kind="NODES")
                                 if r["frame"]["netrom"]["entries"]]
            if not (nodes("xrouter") and nodes("thenet")):
                return False
        return True
    wait_for(done, max(10, stack["started"] + 240 - time.time()), 3)
    return True
