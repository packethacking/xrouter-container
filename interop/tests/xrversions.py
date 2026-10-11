"""XRouter versions for the interop suite: the one under test and the second
XRouter it is linked to. Also a command line helper for CI:

    python3 interop/tests/xrversions.py peer 505o    # prints 505c
"""

from __future__ import annotations

import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _manifest() -> dict:
    with open(os.path.join(REPO, "versions.json")) as f:
        return json.load(f)


def version_key(v: str) -> tuple[int, str]:
    # XRouter versions are a number then a letter: 504z, 505a, 505o.
    m = re.fullmatch(r"(\d+)([a-z]*)", v)
    if not m:
        raise ValueError(f"not an XRouter version: {v!r}")
    return int(m.group(1)), m.group(2)


def resolve(tag: str) -> str:
    """"latest" -> the newest version in versions.json; anything else as is."""
    return _manifest()["latest"] if tag == "latest" else tag


def xrouter_version() -> str:
    """The XRouter version under test (XROUTER_TAG, default latest)."""
    return resolve(os.environ.get("XROUTER_TAG", "latest"))


def peer_of(version: str) -> str:
    """The newest amd64 version in versions.json older than `version`, or
    `version` itself if there is none."""
    me = version_key(resolve(version))
    older = [v for v, arches in _manifest()["versions"].items() if "amd64" in arches and version_key(v) < me]
    return max(older, key=version_key) if older else resolve(version)


def xrouter_peer_version() -> str:
    """The second XRouter's version: XROUTER_PEER_TAG, or peer_of() the one under test."""
    return os.environ.get("XROUTER_PEER_TAG") or peer_of(xrouter_version())


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "peer":
        print(peer_of(sys.argv[2]))
    else:
        sys.exit("usage: xrversions.py peer <tag>")
