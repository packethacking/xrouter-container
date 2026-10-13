"""Start the regress stack once per test session and tear it down after.

The stack is two containers on the docker network xrr-net (172.28.78.0/24):

    xrr-dut  172.28.78.11  the XRouter under test (XROUTER_TAG), PN0DUT
    xrr-nbr  172.28.78.12  a neighbour XRouter (XRR_NBR_TAG, default 505c), PN0NB

both run from xrr-local/xrouter:<tag>, the published image plus the Linux
network tools (image/Dockerfile). The test process itself is the other end
of the DUT's AXUDP ports 1 and 2 and the neighbour's port 2: it binds UDP
30001 to 30003 on the docker host, which the containers reach as
172.28.78.1. See config/dut/XROUTER.CFG for the port plan.

Environment:
    XROUTER_TAG   XRouter version under test (default: latest in versions.json)
    XRR_NBR_TAG   the neighbour XRouter's version (default 505c)
    XRR_OUT       where logs go (default regress/out/<tag>)
    XRR_KEEP=1    leave the stack running afterwards
    XRR_REUSE=1   use a stack that is already running
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import tomllib

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REGRESS = os.path.dirname(HERE)
REPO = os.path.dirname(REGRESS)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "interop", "tests"))

from ax25 import Probe  # noqa: E402
from xrversions import resolve, version_key  # noqa: E402

VERSION = resolve(os.environ.get("XROUTER_TAG", "latest"))
NBR_VERSION = resolve(os.environ.get("XRR_NBR_TAG", "505c"))
OUT = os.path.abspath(os.environ.get("XRR_OUT", os.path.join(REGRESS, "out", VERSION)))

HOST = "127.0.0.1"
NET = "xrr-net"
SUBNET = "172.28.78.0/24"
GATEWAY = "172.28.78.1"
DUT_IP, NBR_IP = "172.28.78.11", "172.28.78.12"
DUT_TELNET, DUT_HTTP, DUT_RHP, DUT_AGW, NBR_TELNET = 18023, 18080, 18090, 18000, 18024
PROBE_A, PROBE_B, PROBE_C = 30001, 30002, 30003
DUT_UDP = {1: 10093, 2: 10094}     # DUT's UDPLOCAL for the probe ports
NBR_UDP = {2: 10094}

DUT_CALL, DUT_ALIAS = "PN0DUT", "DUT"
NBR_CALL, NBR_ALIAS = "PN0NB", "NBR"
SYSOP_PASSWORD = "abcdefghijklmnopqrstuvwxyz"   # config/*/PASSWORD.SYS


def image(tag: str) -> str:
    return f"xrr-local/xrouter:{tag}"


def sh(*args: str, check: bool = True, timeout: float = 600) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), check=check, capture_output=True, text=True, timeout=timeout)


def build_image(tag: str) -> None:
    src = f"ghcr.io/packethacking/xrouter:{tag}-amd64"
    if sh("docker", "image", "inspect", src, check=False).returncode != 0:
        sh("docker", "pull", "-q", src)
    sh("docker", "build", "-q", "--build-arg", f"XROUTER_IMAGE={src}", "-t", image(tag),
       os.path.join(REGRESS, "image"))


def start_node(name: str, ip: str, tag: str, confdir: str, ports: dict[int, int]) -> None:
    sh("docker", "rm", "-f", name, check=False)
    args = ["docker", "run", "-d", "--name", name, "--network", NET, "--ip", ip,
            "--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW", "--device", "/dev/net/tun"]
    for host_port, cport in ports.items():
        args += ["-p", f"127.0.0.1:{host_port}:{cport}"]
    for f in sorted(os.listdir(confdir)):
        args += ["-v", f"{os.path.join(confdir, f)}:/data/{f}:ro"]
    args.append(image(tag))
    sh(*args)


def wait_booted(name: str, timeout: float = 60) -> None:
    end = time.time() + timeout
    while time.time() < end:
        logs = sh("docker", "logs", name, check=False).stdout
        if re.search(r"version \w+ started", logs):
            return
        time.sleep(1)
    raise RuntimeError(f"{name} did not boot: {logs[-2000:]}")


def dexec(name: str, cmd: str, check: bool = False, timeout: float = 120) -> subprocess.CompletedProcess:
    return sh("docker", "exec", name, "sh", "-c", cmd, check=check, timeout=timeout)


def save_logs() -> None:
    os.makedirs(OUT, exist_ok=True)
    for name in ("xrr-dut", "xrr-nbr"):
        r = sh("docker", "logs", name, check=False)
        with open(os.path.join(OUT, f"{name}.log"), "w") as f:
            f.write(r.stdout + r.stderr)


# ---------------------------------------------------------------- known issues

def known_issues() -> dict[str, dict]:
    """Map test name -> known issue affecting it in VERSION (known-issues.toml)."""
    with open(os.path.join(REGRESS, "known-issues.toml"), "rb") as f:
        issues = tomllib.load(f).get("issue", [])
    v = version_key(VERSION)
    out = {}
    for issue in issues:
        lo = version_key(issue["from"]) if "from" in issue else None
        hi = version_key(issue["until"]) if "until" in issue else None
        if (lo is None or v >= lo) and (hi is None or v <= hi):
            for t in issue["tests"]:
                out.setdefault(t, issue)
    return out


def pytest_collection_modifyitems(config, items):
    affected = known_issues()
    for item in items:
        name = item.originalname or item.name
        issue = affected.get(name) or affected.get(item.name)
        if issue:
            link = f" ({issue['issue']})" if issue.get("issue") else ""
            item.add_marker(pytest.mark.xfail(
                reason=f"known issue {issue['id']} in {VERSION}: {issue['title']}{link}",
                strict=issue.get("strict", True)))


def pytest_report_header(config):
    return [f"XRouter under test: {VERSION}, neighbour: {NBR_VERSION}, logs: {OUT}"]


# ---------------------------------------------------------------- fixtures

class Log:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.f = open(path, "a", buffering=1)

    def __call__(self, line: str) -> None:
        self.f.write(line + "\n")


@pytest.fixture(scope="session")
def wirelog():
    return Log(os.path.join(OUT, "probes.txt"))


@pytest.fixture(scope="session")
def stack(wirelog):
    reuse = os.environ.get("XRR_REUSE") == "1"
    if not reuse:
        for tag in {VERSION, NBR_VERSION}:
            build_image(tag)
        sh("docker", "rm", "-f", "xrr-dut", "xrr-nbr", "xrr-ip", check=False)
        if sh("docker", "network", "inspect", NET, check=False).returncode != 0:
            sh("docker", "network", "create", "--subnet", SUBNET, NET)
    # Probes first, so nothing XRouter sends at boot is lost.
    probes = {
        "A": Probe("A", ("0.0.0.0", PROBE_A), (DUT_IP, DUT_UDP[1]), wirelog),
        "B": Probe("B", ("0.0.0.0", PROBE_B), (DUT_IP, DUT_UDP[2]), wirelog),
        "C": Probe("C", ("0.0.0.0", PROBE_C), (NBR_IP, NBR_UDP[2]), wirelog),
    }
    t0 = time.time()
    if not reuse:
        start_node("xrr-nbr", NBR_IP, NBR_VERSION, os.path.join(REGRESS, "config", "nbr"),
                   {NBR_TELNET: 23})
        start_node("xrr-dut", DUT_IP, VERSION, os.path.join(REGRESS, "config", "dut"),
                   {DUT_TELNET: 23, DUT_HTTP: 80, DUT_RHP: 9000, DUT_AGW: 8000})
        wait_booted("xrr-nbr")
        wait_booted("xrr-dut")
        time.sleep(3)
    yield {"probes": probes, "t0": t0}
    for p in probes.values():
        p.close()
    save_logs()
    if not reuse and os.environ.get("XRR_KEEP") != "1":
        sh("docker", "rm", "-f", "xrr-dut", "xrr-nbr", check=False)


@pytest.fixture(scope="session")
def probe_a(stack):
    return stack["probes"]["A"]


@pytest.fixture(scope="session")
def probe_b(stack):
    return stack["probes"]["B"]


@pytest.fixture(scope="session")
def probe_c(stack):
    return stack["probes"]["C"]


@pytest.fixture(scope="module")
def dut(stack):
    """A sysop telnet session on the DUT."""
    from xrconsole import XRConsole
    c = XRConsole(HOST, DUT_TELNET, "PN0TST", name="dut", log=Log(os.path.join(OUT, "consoles.txt")))
    c.sysop(SYSOP_PASSWORD)
    yield c
    c.close()


@pytest.fixture(scope="module")
def dut_user(stack):
    """A plain (non-sysop) telnet session on the DUT."""
    from xrconsole import XRConsole
    c = XRConsole(HOST, DUT_TELNET, "PN0USR", name="dut-user", log=Log(os.path.join(OUT, "consoles.txt")))
    yield c
    c.close()


@pytest.fixture(scope="module")
def nbr(stack):
    from xrconsole import XRConsole
    c = XRConsole(HOST, NBR_TELNET, "PN0TST", name="nbr", log=Log(os.path.join(OUT, "consoles.txt")))
    c.sysop(SYSOP_PASSWORD)
    yield c
    c.close()


# ---------------------------------------------------------------- IP gateway node

IP_IP, IP_TELNET, PROBE_D, IP_BRIDGE = "172.28.78.13", 18025, 30004, 30111


@pytest.fixture(scope="session")
def ipgw(stack, wirelog):
    """The IP gateway node xrr-ip (config/ip), started on first use, with the
    UDP bridge for its AX.25 port and the Linux side of the AMPRNet set up:
    44.130.2.2 on lo (the AXIP partner) and 44.130.0.0/16 into the tunnel."""
    reuse = os.environ.get("XRR_REUSE") == "1"
    if not reuse:
        start_node("xrr-ip", IP_IP, VERSION, os.path.join(REGRESS, "config", "ip"), {IP_TELNET: 23})
        wait_booted("xrr-ip")
        end = time.time() + 20
        while time.time() < end and dexec("xrr-ip", "ip link show tun99 | grep -q UP").returncode:
            time.sleep(0.5)
        dexec("xrr-ip", "ip addr add 44.130.2.2/32 dev lo; ip route add 44.130.0.0/16 dev tun99", check=True)
        sh("docker", "exec", "-d", "xrr-ip", "python3", "/usr/local/bin/udpbridge.py",
           "10093", "30011", str(IP_BRIDGE), GATEWAY, str(PROBE_D))
        time.sleep(2)
    probe = Probe("D", ("0.0.0.0", PROBE_D), (IP_IP, IP_BRIDGE), wirelog)
    yield {"probe": probe}
    probe.close()
    r = sh("docker", "logs", "xrr-ip", check=False)
    with open(os.path.join(OUT, "xrr-ip.log"), "w") as f:
        f.write(r.stdout + r.stderr)
    if not reuse and os.environ.get("XRR_KEEP") != "1":
        sh("docker", "rm", "-f", "xrr-ip", check=False)


@pytest.fixture(scope="module")
def ipcon(ipgw):
    from xrconsole import XRConsole
    c = XRConsole(HOST, IP_TELNET, "PN0TST", name="ipgw", log=Log(os.path.join(OUT, "consoles.txt")))
    c.sysop(SYSOP_PASSWORD)
    yield c
    c.close()
