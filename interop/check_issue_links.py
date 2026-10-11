#!/usr/bin/env python3
"""Check that known-issues.toml and the GitHub issues agree.

    python3 interop/check_issue_links.py            # structure plus GitHub (needs gh and a token)
    python3 interop/check_issue_links.py --offline  # structure only

Structure (both modes):
  - every entry about XRouter (no `applies_to`, or "peer", the second XRouter)
    has an `issue` URL for an issue in this repo;
  - entries for the other implementations (xnet, tnn, thenet, linbpq) have none;
  - `fixed_in`, where set, is a later version than `until`;
  - every test an entry names exists in interop/tests.

GitHub (unless --offline), for each linked issue, with `gh issue view`:
  - the issue exists;
  - if it is closed, every entry linking it has `fixed_in`;
  - if it is open, no entry linking it has `fixed_in`.

Issue numbers not filled in yet (ISSUE_<n> placeholders) are allowed offline
and an error online. Exits non-zero with one line per problem.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import tomllib

INTEROP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(INTEROP, "tests"))

from xrversions import version_key  # noqa: E402

REPO = "packethacking/xrouter-container"
ISSUE_URL = re.compile(rf"https://github\.com/{re.escape(REPO)}/issues/(\d+|ISSUE_\d+)")
XROUTER = ("tested", "peer")          # applies_to values that mean an XRouter bug
OTHERS = ("xnet", "tnn", "thenet", "linbpq")


def load_issues() -> list[dict]:
    with open(os.path.join(INTEROP, "known-issues.toml"), "rb") as f:
        return tomllib.load(f)["issue"]


def suite_test_names() -> set[str]:
    names = set()
    for path in glob.glob(os.path.join(INTEROP, "tests", "test_*.py")):
        with open(path) as f:
            names |= set(re.findall(r"^def (test_\w+)", f.read(), re.M))
    return names


def is_xrouter(entry: dict) -> bool:
    return entry.get("applies_to", "tested") in XROUTER


def issue_ref(entry: dict) -> str | None:
    """The issue number (or ISSUE_<n> placeholder) an entry links, or None."""
    m = ISSUE_URL.fullmatch(entry.get("issue", ""))
    return m.group(1) if m else None


def structure_errors(entries: list[dict], test_names: set[str]) -> list[str]:
    errors = []
    for e in entries:
        eid = e.get("id", "?")
        which = e.get("applies_to", "tested")
        if which not in XROUTER + OTHERS:
            errors.append(f"{eid}: unknown applies_to {which!r}")
            continue
        if is_xrouter(e):
            if "issue" not in e:
                errors.append(f"{eid}: XRouter known issue with no `issue` URL; open a GitHub issue and link it")
            elif issue_ref(e) is None:
                errors.append(f"{eid}: `issue` is not an issue URL in {REPO}: {e['issue']!r}")
        elif "issue" in e or "fixed_in" in e:
            errors.append(f"{eid}: a {which} bug is not XRouter's; it takes no `issue` or `fixed_in`")
        if "fixed_in" in e:
            try:
                if "until" in e and version_key(e["fixed_in"]) <= version_key(e["until"]):
                    errors.append(f"{eid}: fixed_in {e['fixed_in']} is not later than until {e['until']}")
            except ValueError as exc:
                errors.append(f"{eid}: {exc}")
        missing = [t for t in e.get("tests", []) if t not in test_names]
        if missing:
            errors.append(f"{eid}: names tests that do not exist: {', '.join(missing)}")
    return errors


def github_errors(entries: list[dict]) -> list[str]:
    errors = []
    by_ref: dict[str, list[dict]] = {}
    for e in entries:
        ref = issue_ref(e) if is_xrouter(e) else None
        if ref:
            by_ref.setdefault(ref, []).append(e)
    for ref, linked in sorted(by_ref.items()):
        ids = ", ".join(e["id"] for e in linked)
        if ref.startswith("ISSUE_"):
            errors.append(f"{ids}: issue number not filled in yet ({ref})")
            continue
        r = subprocess.run(["gh", "issue", "view", ref, "--repo", REPO, "--json", "number,state,title"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            errors.append(f"{ids}: issue #{ref} not found in {REPO}: {r.stderr.strip()}")
            continue
        state = json.loads(r.stdout)["state"].upper()
        for e in linked:
            if state == "CLOSED" and "fixed_in" not in e:
                errors.append(f"{e['id']}: issue #{ref} is closed but the entry has no fixed_in")
            elif state == "OPEN" and "fixed_in" in e:
                errors.append(f"{e['id']}: issue #{ref} is open but the entry has fixed_in {e['fixed_in']}")
    return errors


def main() -> int:
    offline = "--offline" in sys.argv[1:]
    entries = load_issues()
    errors = structure_errors(entries, suite_test_names())
    if not offline:
        errors += github_errors(entries)
    linked = sorted({e["issue"] for e in entries if is_xrouter(e) and "issue" in e})
    if errors:
        print(f"known-issues.toml: {len(errors)} problem(s):", file=sys.stderr)
        for line in errors:
            print(f"  - {line}", file=sys.stderr)
        return 1
    placeholders = [u for u in linked if "/ISSUE_" in u]
    note = f", {len(placeholders)} still placeholders" if placeholders else ""
    mode = "structure only" if offline else "structure and GitHub"
    print(f"known-issues.toml OK ({mode}): {len(entries)} entries, {len(linked)} linked issues{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
