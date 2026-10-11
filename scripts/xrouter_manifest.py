#!/usr/bin/env python3
"""Shared helpers for versions.json and upstream.json.

Used by scripts/upstream_diff.py (imported) and scripts/ingest.sh (as a
small command line tool). Plain stdlib only.

Command line:
    xrouter_manifest.py record --versions FILE --upstream FILE \
        --version VER --arch ARCH --sha256 SHA --url URL \
        [--packages "pkg pkg"] [--meta JSON] [--today YYYY-MM-DD]

    Prints one word describing what happened: "added", "replaced",
    "restored" or "unchanged".

    xrouter_manifest.py lookup --versions FILE --version VER --arch ARCH \
        --sha256 SHA

    Prints "current", "previous" or "none": where this binary already
    sits in versions.json for that (version, arch).
"""

import argparse
import datetime
import json
import re
import sys

ARCHES = ("amd64", "arm64", "armv7")

# groups.io folder -> (arch, linkage)
FOLDERS = {
    "00-XrLin64-static": ("amd64", "static"),
    "00-XrPi64-static": ("arm64", "static"),
    "00-XrPi32-static": ("armv7", "static"),
    "00-XrLin64-vanessa": ("amd64", "dynamic"),
}

NAME_RE = re.compile(r"^xr(lin64|pi64|pi32)v(\d+[a-z]+)-(static|vanessa)$")
NAME_ARCH = {"lin64": "amd64", "pi64": "arm64", "pi32": "armv7"}


def parse_name(name):
    """xrlin64v505o-static -> ("505o", "amd64", "static"), else None."""
    m = NAME_RE.match(name)
    if not m:
        return None
    linkage = "static" if m.group(3) == "static" else "dynamic"
    return m.group(2), NAME_ARCH[m.group(1)], linkage


def version_key(ver):
    """Order versions by numeric part, then letters (504z < 505a < 505aa)."""
    m = re.match(r"^(\d+)([a-z]*)$", ver)
    if not m:
        raise ValueError(f"unparseable version: {ver}")
    return (int(m.group(1)), len(m.group(2)), m.group(2))


def load(path):
    with open(path) as f:
        return json.load(f)


def save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def sorted_versions(versions):
    return {k: versions[k] for k in sorted(versions, key=version_key)}


def newer(a, b):
    """True if version a is newer than b (b may be empty)."""
    return not b or version_key(a) > version_key(b)


def record(vdata, version, arch, sha, url, packages, today):
    """Put a verified binary into versions.json data. Returns what happened."""
    versions = vdata.setdefault("versions", {})
    ver_entry = versions.setdefault(version, {})
    cur = ver_entry.get(arch)
    new = {"url": url, "sha256": sha}
    if packages:
        new["packages"] = packages
    if cur is None:
        # keep arch keys in amd64, arm64, armv7 order
        ver_entry[arch] = new
        versions[version] = {a: ver_entry[a] for a in ARCHES if a in ver_entry}
        what = "added"
    elif cur["sha256"] == sha:
        return "unchanged"
    else:
        previous = cur.pop("previous", [])
        restored = [p for p in previous if p["sha256"] == sha]
        previous = [p for p in previous if p["sha256"] != sha]
        old = {k: cur[k] for k in ("url", "sha256", "packages") if k in cur}
        old["replaced"] = today
        previous.append(old)
        if restored:
            # upstream went back to a binary we already hold: reuse it
            new = {k: restored[0][k] for k in ("url", "sha256", "packages") if k in restored[0]}
            what = "restored"
        else:
            what = "replaced"
        new["previous"] = previous
        ver_entry[arch] = new
    vdata["versions"] = sorted_versions(versions)
    key = f"latest_{arch}"
    if newer(version, vdata.get(key, "")):
        vdata[key] = version
    if newer(version, vdata.get("latest", "")):
        vdata["latest"] = version
    return what


def record_upstream(udata, meta, version, arch, linkage, sha, today, source):
    """Insert or refresh the upstream.json entry for one groups.io file."""
    folder = meta["full_path"].rsplit("/", 1)[0]
    files = udata.setdefault("files", [])
    old = next((f for f in files if f["folder"] == folder and f["name"] == meta["name"]), None)
    entry = {
        "id": meta["id"],
        "folder": folder,
        "name": meta["name"],
        "size_bytes": meta["size_bytes"],
        "created": meta["created"],
        "updated": meta["updated"],
        "sha256": sha,
        "source": source,
        "version": version,
        "arch": arch,
        "linkage": linkage,
        "first_seen": old["first_seen"] if old else today,
        "last_checked": today,
    }
    if old:
        files[files.index(old)] = entry
    else:
        files.append(entry)
    order = list(FOLDERS)
    files.sort(key=lambda f: (order.index(f["folder"]) if f["folder"] in order else 99,
                              version_key(f["version"])))


def lookup(vdata, version, arch, sha):
    cur = vdata.get("versions", {}).get(version, {}).get(arch)
    if not cur:
        return "none"
    if cur["sha256"] == sha:
        return "current"
    if any(p["sha256"] == sha for p in cur.get("previous", [])):
        return "previous"
    return "none"


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--versions", required=True)
    r.add_argument("--upstream", required=True)
    r.add_argument("--version", required=True)
    r.add_argument("--arch", required=True, choices=ARCHES)
    r.add_argument("--sha256", required=True)
    r.add_argument("--url", required=True)
    r.add_argument("--packages", default="")
    r.add_argument("--linkage", default="static", choices=("static", "dynamic"))
    r.add_argument("--meta", default="", help="the list_files/get_file entry for this file, as JSON")
    r.add_argument("--today", default=datetime.date.today().isoformat())
    lk = sub.add_parser("lookup")
    lk.add_argument("--versions", required=True)
    lk.add_argument("--version", required=True)
    lk.add_argument("--arch", required=True, choices=ARCHES)
    lk.add_argument("--sha256", required=True)
    a = ap.parse_args()

    if a.cmd == "lookup":
        print(lookup(load(a.versions), a.version, a.arch, a.sha256))
        return 0

    vdata = load(a.versions)
    what = record(vdata, a.version, a.arch, a.sha256, a.url, a.packages, a.today)
    save(a.versions, vdata)
    if a.meta:
        meta = json.loads(a.meta)
        udata = load(a.upstream)
        record_upstream(udata, meta, a.version, a.arch, a.linkage, a.sha256, a.today,
                        f"download-verified {a.today}")
        save(a.upstream, udata)
    else:
        print("warning: no --meta given, upstream.json not updated", file=sys.stderr)
    print(what)
    return 0


if __name__ == "__main__":
    sys.exit(main())
