"""Console command output, compared with 505c's.

Deliberate changes in a later version are recorded as that version's own
golden copy, golden/<version>/console/<id>.txt, holding only the commands
whose output changed on purpose (XRR_ACCEPT=<id>,<id> writes them). For a
version V the newest golden copy of a command from a version <= V is used,
so 505o's accepted changes also apply to 505p unless 505p changes again.

Each command's output is normalised (numbers, times, the version string) and
compared with the golden copy in golden/<baseline>/console/, recorded from
505c with XRR_UPDATE_GOLDEN=1. A difference is not necessarily a bug, but
every one needs a look: it is either a regression, a deliberate change (then
list it in known-issues.toml as such, or re-record), or noise to normalise.

`head` commands compare only their first lines (tables whose rows depend on
timing, such as NODES); the rest compare in full. The raw output of every
command for the version under test is kept in out/<tag>/console/.
"""

from __future__ import annotations

import os
import re

import pytest

from conftest import OUT, REGRESS, VERSION

BASELINE = os.environ.get("XRR_BASELINE", "505c")
GOLDEN = os.path.join(REGRESS, "golden", BASELINE, "console")
UPDATE = os.environ.get("XRR_UPDATE_GOLDEN") == "1"
ACCEPT = set(filter(None, os.environ.get("XRR_ACCEPT", "").split(",")))


def golden_path(cid: str) -> str:
    """The golden copy for this version: the newest version <= VERSION that has one."""
    from conftest import version_key
    root = os.path.join(REGRESS, "golden")
    vers = sorted((v for v in os.listdir(root) if os.path.exists(os.path.join(root, v, "console", f"{cid}.txt"))
                   and version_key(v) <= version_key(VERSION)), key=version_key, reverse=True)
    return os.path.join(root, vers[0] if vers else BASELINE, "console", f"{cid}.txt")

# (id, command, lines to compare or None for all). User-level commands first.
USER_COMMANDS = [
    ("help", "?", None),
    ("help-star", "? *", None),
    ("help-starstar", "? **", None),
    ("help-full", "H", None),
    ("info", "I", None),
    ("version", "V", None),
    ("ports", "P", None),
    ("users", "U", 2),
    ("links", "L", 2),
    ("l4links", "L4", 2),
    ("nodes", "N", 2),
    ("routes", "R", 2),
    ("mheard-1", "MH 1", 2),
    ("j", "J", 2),
    ("stats", "S", None),
    ("iproutes", "IPR", None),
    ("arp-user", "ARP", None),
    ("time", "TI", 1),
    ("date", "DATE", 1),
    ("lang", "LANG", None),
    ("ansi", "ANSI", None),
    ("blog", "BLOG", None),
    ("wall", "WALL", None),
    ("wx", "WX", None),
    ("dx", "DX", None),
    ("send-syntax", "SEND", None),
    ("connect-syntax", "C", None),
    ("ping-syntax", "PING", None),
    ("finger", "FINGER", None),
    ("bogus", "XYZZY", None),
]
# Help for each user command, e.g. "? nodes".
HELP_TOPICS = ["arp", "bye", "connect", "chat", "info", "links", "mheard", "nodes", "ports", "ping",
               "pms", "routes", "send", "stats", "users", "version", "telnet", "nping", "ntracert"]
SYSOP_COMMANDS = [
    ("sysop-help-star", "? *", None),
    ("frack-1", "FRACK 1", None),
    ("resptime-1", "RESPTIME 1", None),
    ("retries-1", "RETRIES 1", None),
    ("maxframe-1", "MAXFRAME 1", None),
    ("paclen-1", "PACLEN 1", None),
    ("quality-1", "QUALITY 1", None),
    ("quality-2", "QUALITY 2", None),
    ("minqual-1", "MINQUAL 1", None),
    ("mintxqual-1", "MINTXQUAL 1", None),
    ("digiflag-1", "DIGIFLAG 1", None),
    ("digiflag-2", "DIGIFLAG 2", None),
    ("digiport-1", "DIGIPORT 1", None),
    ("cflags-1", "CFLAGS 1", None),
    ("ctflags-1", "CTFLAGS 1", None),
    ("mhflags-1", "MHFLAGS 1", None),
    ("mhsize-1", "MHSIZE 1", None),
    ("unproto-1", "UNPROTO 1", None),
    ("idpath-1", "IDPATH 1", None),
    ("idtext-0", "IDTEXT 0", None),
    ("nodesint-0", "NODESINT 0", None),
    ("nodesint-1", "NODESINT 1", None),
    ("txok-1", "TXOK 1", None),
    ("udplocal-1", "UDPLOCAL 1", None),
    ("udpremote-1", "UDPREMOTE 1", None),
    ("iplink-1", "IPLINK 1", None),
    ("ipaddress-0", "IPADDRESS 0", None),
    ("iface-list", "IFACE L", None),
    ("ip-route-list", "IP ROUTE LIST", None),
    ("ip-config", "IP CONFIG", None),
    ("arp-list", "ARP L", None),
    ("axroutes", "AX", 1),
    ("bcast-times", "N BC T", 3),
    ("stats-star", "S *", None),
    ("stats-l2", "S L2", None),
    ("stats-l3", "S L3", None),
    ("stats-ip", "S IP", None),
    ("peers", "PEERS", 2),
    ("man", "MAN", None),
    ("man-nodes", "MAN NODES", 10),
    ("cmd", "CMD", None),
    ("acl", "ACL", None),
    ("nat", "NAT", None),
    ("rip", "RIP", None),
    ("dns", "DNS", None),
    ("tcp", "TCP", None),
    ("udp", "UDP", None),
    ("motd", "MOTD", None),
]


def normalise(text: str, keep: int | None) -> str:
    out = []
    for line in text.replace("\t", " ").splitlines():
        line = re.sub(r"\b50\d[a-z]\b", "<VER>", line)               # version
        line = re.sub(r"\(\d+/\d+/\d+\)", "(<DATE>)", line)           # build date
        line = re.sub(r"\d+", "#", line)                              # all numbers
        line = re.sub(r"#(?:[:./]#)+", "#", line)                     # times, dates, IPs
        line = re.sub(r"\s+", " ", line).rstrip()
        if line.strip():
            out.append(line)
    # The reply starts with the node prompt; anything before it is echo noise.
    if keep is not None:
        out = out[:keep + 1]
    return "\n".join(out) + "\n"


def run_and_compare(console, cid: str, command: str, keep: int | None) -> None:
    raw = console.cmd(command, 1.5)
    os.makedirs(os.path.join(OUT, "console"), exist_ok=True)
    with open(os.path.join(OUT, "console", f"{cid}.txt"), "w") as f:
        f.write(f">>> {command}\n{raw}")
    got = normalise(raw, keep)
    path = golden_path(cid)
    if UPDATE or cid in ACCEPT:
        d = GOLDEN if UPDATE else os.path.join(REGRESS, "golden", VERSION, "console")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{cid}.txt"), "w") as f:
            f.write(got)
        return
    if not os.path.exists(path):
        pytest.skip(f"no golden output for {cid} (record with XRR_UPDATE_GOLDEN=1 on {BASELINE})")
    with open(path) as f:
        want = f.read()
    if got != want:
        import difflib
        diff = "".join(difflib.unified_diff(want.splitlines(True), got.splitlines(True),
                                            os.path.relpath(path, REGRESS), f"{VERSION}/{cid}"))
        pytest.fail(f"`{command}` output differs from {os.path.relpath(path, REGRESS)}:\n{diff}", pytrace=False)


@pytest.mark.parametrize("cid,command,keep", USER_COMMANDS, ids=[c[0] for c in USER_COMMANDS])
def test_console_user(dut_user, cid, command, keep):
    run_and_compare(dut_user, cid, command, keep)


@pytest.mark.parametrize("topic", HELP_TOPICS)
def test_console_help_topic(dut_user, topic):
    run_and_compare(dut_user, f"help-{topic}", f"? {topic}", None)


@pytest.mark.parametrize("cid,command,keep", SYSOP_COMMANDS, ids=[c[0] for c in SYSOP_COMMANDS])
def test_console_sysop(dut, cid, command, keep):
    run_and_compare(dut, cid, command, keep)
