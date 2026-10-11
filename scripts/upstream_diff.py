#!/usr/bin/env python3
"""Compare a fresh groups.io listing with upstream.json and print a plan.

Input: a JSON file holding the list_files results for the four tracked
folders, exactly as the groups.io MCP tool returns them. Accepted shapes:
a list of results, an object keyed by anything whose values are results,
or a single result. Each result needs "dir" and "results".

Output (stdout, JSON):
    new          files we do not track yet and should ingest
    changed      tracked files whose id, size_bytes or updated differ
    disappeared  tracked files no longer in the listing
    deferred     dynamic-only builds held back for now (see below)
    ignored      files that are not ours to ingest, with a reason
    unchanged    count of tracked files that look the same
    action_needed  true if new or changed is non-empty

A dynamic (vanessa) amd64 build is only wanted when upstream has no
static amd64 build of that version. Upstream tends to upload the vanessa
build a few minutes before the static one, so a vanessa build with no
static twin is held in "deferred" until it is DEFER_HOURS old.

Usage:
    upstream_diff.py LISTING.json [--upstream upstream.json] [--versions versions.json]
                     [--now ISO8601] [--touch]

--touch writes today's date into last_checked (top level and every
unchanged file) in upstream.json. Use it only when the plan is empty or
after ingesting, so a failed run does not claim a successful check.
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xrouter_manifest as xm  # noqa: E402

DEFER_HOURS = 48


def parse_time(s):
    return datetime.datetime.fromisoformat(fix_fraction(s))


def fix_fraction(s):
    # groups.io sends nanoseconds; Python before 3.11 wants at most 6 digits
    if "." not in s:
        return s
    head, rest = s.split(".", 1)
    digits = ""
    while rest and rest[0].isdigit():
        digits += rest[0]
        rest = rest[1:]
    return f"{head}.{digits[:6].ljust(6, '0')}{rest}"


def results_from(data):
    if isinstance(data, dict) and "results" in data and "dir" in data:
        return [data]
    if isinstance(data, dict):
        return list(data.values())
    if isinstance(data, list):
        return data
    raise SystemExit("listing: unrecognised JSON shape")


def plan(listing, upstream, versions, now):
    results = results_from(listing)
    seen_dirs = {}
    for r in results:
        if r.get("has_more"):
            raise SystemExit(f"listing for {r.get('dir')} is paginated (has_more); fetch every page")
        seen_dirs.setdefault(r.get("dir"), []).extend(r.get("results", []))
    missing = [d for d in xm.FOLDERS if d not in seen_dirs]
    if missing:
        raise SystemExit(f"listing lacks folder(s): {', '.join(missing)}")

    tracked = {f"{f['folder']}/{f['name']}": f for f in upstream.get("files", [])}
    out = {"checked": now.isoformat(timespec="seconds"), "new": [], "changed": [],
           "disappeared": [], "deferred": [], "ignored": [], "unchanged": 0}

    files = []
    for d, items in seen_dirs.items():
        for f in items:
            path = f.get("full_path") or f"{d}/{f['name']}"
            files.append((d, path, f))

    # versions that have (or will have) a static amd64 build
    static_amd64 = {f["version"] for f in upstream.get("files", [])
                    if f["arch"] == "amd64" and f["linkage"] == "static"}
    for d, path, f in files:
        p = xm.parse_name(f["name"])
        if d == "00-XrLin64-static" and p and p[2] == "static":
            static_amd64.add(p[0])

    vers = versions.get("versions", {})
    for d, path, f in files:
        if d not in xm.FOLDERS:
            out["ignored"].append({"full_path": path, "reason": "not a tracked folder"})
            continue
        if f.get("is_folder") or f.get("kind") == "folder":
            out["ignored"].append({"full_path": path, "reason": "folder"})
            continue
        p = xm.parse_name(f["name"])
        if not p:
            out["ignored"].append({"full_path": path, "reason": "name not recognised"})
            continue
        ver, arch, linkage = p
        if (arch, linkage) != xm.FOLDERS[d]:
            out["ignored"].append({"full_path": path, "reason": f"{arch} {linkage} build in {d}"})
            continue
        item = {
            "full_path": path, "folder": d, "name": f["name"], "id": f["id"],
            "size_bytes": f["size_bytes"], "created": f["created"], "updated": f["updated"],
            "version": ver, "arch": arch, "linkage": linkage,
        }
        old = tracked.pop(path, None)
        if old:
            diffs = {k: [old[k], f[k]] for k in ("id", "size_bytes", "updated") if old[k] != f[k]}
            if diffs and linkage == "dynamic" and ver in static_amd64:
                # we now use the static build for this version; leave the record as it was
                out["ignored"].append({"full_path": path, "reason": "changed, but superseded by a static amd64 build"})
            elif diffs:
                item["differences"] = diffs
                item["recorded_sha256"] = old.get("sha256")
                out["changed"].append(item)
            else:
                out["unchanged"] += 1
            continue
        if linkage == "dynamic":
            if ver in static_amd64:
                out["ignored"].append({"full_path": path, "reason": "static amd64 build exists for this version"})
                continue
            age = now - parse_time(f["created"])
            if age < datetime.timedelta(hours=DEFER_HOURS):
                item["reason"] = f"dynamic only so far; waiting {DEFER_HOURS}h for a static amd64 build"
                out["deferred"].append(item)
                continue
        cur = vers.get(ver, {}).get(arch)
        item["in_versions_json"] = bool(cur)
        if cur and cur.get("packages") and linkage == "static":
            item["replaces_dynamic"] = True
        latest = versions.get(f"latest_{arch}", "")
        item["newer_than_latest"] = xm.newer(ver, latest)
        out["new"].append(item)

    for path, old in tracked.items():
        out["disappeared"].append({"full_path": path, "version": old["version"], "arch": old["arch"],
                                   "linkage": old["linkage"], "sha256": old.get("sha256")})

    out["new"].sort(key=lambda i: (xm.version_key(i["version"]), i["arch"]))
    out["action_needed"] = bool(out["new"] or out["changed"])
    return out


def touch(upstream, plan_out, today):
    upstream["last_checked"] = today
    unchanged_paths = set()
    flagged = {i["full_path"] for i in plan_out["changed"]} | {i["full_path"] for i in plan_out["disappeared"]}
    for f in upstream.get("files", []):
        path = f"{f['folder']}/{f['name']}"
        if path not in flagged:
            f["last_checked"] = today
            unchanged_paths.add(path)
    return unchanged_paths


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("listing")
    ap.add_argument("--upstream", default=os.path.join(root, "upstream.json"))
    ap.add_argument("--versions", default=os.path.join(root, "versions.json"))
    ap.add_argument("--now", help="override the current time (ISO 8601), for tests")
    ap.add_argument("--touch", action="store_true", help="update last_checked in upstream.json")
    a = ap.parse_args()

    now = parse_time(a.now) if a.now else datetime.datetime.now(datetime.timezone.utc)
    upstream = xm.load(a.upstream)
    out = plan(xm.load(a.listing), upstream, xm.load(a.versions), now)
    if a.touch:
        touch(upstream, out, now.date().isoformat())
        xm.save(a.upstream, upstream)
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
