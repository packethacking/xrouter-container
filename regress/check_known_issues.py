#!/usr/bin/env python3
"""Check that regress/known-issues.toml and the GitHub issues agree.

    python3 regress/check_known_issues.py            # structure plus GitHub (needs gh and a token)
    python3 regress/check_known_issues.py --offline  # structure only

Structure:
  - every entry has an `issue` URL for an issue in this repo, or says why it
    has none in `no_issue` (for behaviour we have not established as a bug);
  - `from`, `until` and `fixed_in` are XRouter versions; `fixed_in`, where
    set, comes with `until` and is later than it;
  - every test an entry names exists in regress/tests (a parametrised test
    by its base name).

GitHub (unless --offline), as interop/check_issue_links.py: a closed issue's
entries have `fixed_in`; an open issue's entries have none.
"""

from __future__ import annotations

import glob
import os
import re
import sys
import tomllib

REGRESS = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(REGRESS)
sys.path.insert(0, os.path.join(REPO_ROOT, "interop"))
sys.path.insert(0, os.path.join(REPO_ROOT, "interop", "tests"))

from check_issue_links import REPO, github_errors, issue_ref  # noqa: E402
from xrversions import version_key  # noqa: E402


def load_entries() -> list[dict]:
    with open(os.path.join(REGRESS, "known-issues.toml"), "rb") as f:
        return tomllib.load(f).get("issue", [])


def suite_test_names() -> set[str]:
    names = set()
    for path in glob.glob(os.path.join(REGRESS, "tests", "test_*.py")):
        with open(path) as f:
            names |= set(re.findall(r"^def (test_\w+)", f.read(), re.M))
    return names


def structure_errors(entries: list[dict], test_names: set[str]) -> list[str]:
    errors = []
    ids = [e.get("id", "?") for e in entries]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"{dup}: id used more than once")
    for e in entries:
        eid = e.get("id", "?")
        if "issue" in e:
            if issue_ref(e) is None:
                errors.append(f"{eid}: `issue` is not an issue URL in {REPO}: {e['issue']!r}")
            if "no_issue" in e:
                errors.append(f"{eid}: has both `issue` and `no_issue`")
        elif not e.get("no_issue"):
            errors.append(f"{eid}: no `issue` URL; open a GitHub issue and link it, or say why not in `no_issue`")
        for key in ("from", "until", "fixed_in"):
            if key in e:
                try:
                    version_key(e[key])
                except ValueError as exc:
                    errors.append(f"{eid}: {key}: {exc}")
        if "fixed_in" in e:
            if "until" not in e:
                errors.append(f"{eid}: fixed_in without until (the last affected version)")
            elif version_key(e["fixed_in"]) <= version_key(e["until"]):
                errors.append(f"{eid}: fixed_in {e['fixed_in']} is not later than until {e['until']}")
        if not e.get("tests"):
            errors.append(f"{eid}: lists no tests")
        missing = [t for t in e.get("tests", []) if t not in test_names]
        if missing:
            errors.append(f"{eid}: names tests that do not exist: {', '.join(missing)}")
    return errors


def main() -> int:
    offline = "--offline" in sys.argv[1:]
    entries = load_entries()
    errors = structure_errors(entries, suite_test_names())
    if not offline:
        errors += github_errors([e for e in entries if "issue" in e])
    if errors:
        print(f"regress/known-issues.toml: {len(errors)} problem(s):", file=sys.stderr)
        for line in errors:
            print(f"  - {line}", file=sys.stderr)
        return 1
    linked = {e["issue"] for e in entries if "issue" in e}
    mode = "structure only" if offline else "structure and GitHub"
    print(f"regress/known-issues.toml OK ({mode}): {len(entries)} entries, {len(linked)} linked issues")
    return 0


if __name__ == "__main__":
    sys.exit(main())
