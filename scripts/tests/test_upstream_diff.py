#!/usr/bin/env python3
"""Unit tests for upstream_diff.py and xrouter_manifest.py.

Run: python3 -m unittest discover -s scripts/tests
"""

import copy
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import upstream_diff as ud  # noqa: E402
import xrouter_manifest as xm  # noqa: E402

NOW = datetime.datetime(2026, 10, 11, 12, 0, tzinfo=datetime.timezone.utc)
T0 = "2026-10-09T04:54:11.770451454-07:00"


def f(folder, name, fid, size, created=T0, updated=None):
    return {"id": fid, "name": name, "full_path": f"{folder}/{name}", "is_folder": False,
            "kind": "file", "size_bytes": size, "created": created, "updated": updated or created}


def tracked(entry, ver, arch, linkage, sha="a" * 64):
    return {"id": entry["id"], "folder": entry["full_path"].rsplit("/", 1)[0], "name": entry["name"],
            "size_bytes": entry["size_bytes"], "created": entry["created"], "updated": entry["updated"],
            "sha256": sha, "source": "test", "version": ver, "arch": arch, "linkage": linkage,
            "first_seen": "2026-10-11", "last_checked": "2026-10-11"}


A = f("00-XrLin64-static", "xrlin64v505o-static", 1, 4771568)
R = f("00-XrPi64-static", "xrpi64v505o-static", 2, 4159064)
V = f("00-XrPi32-static", "xrpi32v505o-static", 3, 3102868)
D = f("00-XrLin64-vanessa", "xrlin64v504x-vanessa", 4, 2277176)
SHADOWED = f("00-XrLin64-vanessa", "xrlin64v505o-vanessa", 5, 2360520)


def listing(lin=(), pi64=(), pi32=(), van=()):
    return [
        {"dir": "00-XrLin64-static", "results": list(lin), "has_more": False},
        {"dir": "00-XrPi64-static", "results": list(pi64), "has_more": False},
        {"dir": "00-XrPi32-static", "results": list(pi32), "has_more": False},
        {"dir": "00-XrLin64-vanessa", "results": list(van), "has_more": False},
    ]


UPSTREAM = {"files": [tracked(A, "505o", "amd64", "static"), tracked(R, "505o", "arm64", "static"),
                      tracked(V, "505o", "armv7", "static"), tracked(D, "504x", "amd64", "dynamic")]}
VERSIONS = {"latest": "505o", "latest_amd64": "505o", "latest_arm64": "505o", "latest_armv7": "505o",
            "versions": {"504x": {"amd64": {"url": "u", "sha256": "d" * 64, "packages": "libasound2"}},
                         "505o": {a: {"url": "u", "sha256": "a" * 64} for a in xm.ARCHES}}}
BASE = listing([A], [R], [V], [D, SHADOWED])


class DiffTests(unittest.TestCase):
    def run_plan(self, lst, upstream=UPSTREAM, versions=VERSIONS, now=NOW):
        return ud.plan(lst, copy.deepcopy(upstream), versions, now)

    def test_nothing_changed(self):
        p = self.run_plan(BASE)
        self.assertEqual(p["unchanged"], 4)
        self.assertFalse(p["action_needed"])
        self.assertEqual(p["new"] + p["changed"] + p["disappeared"] + p["deferred"], [])
        self.assertEqual([i["full_path"] for i in p["ignored"]], [SHADOWED["full_path"]])

    def test_new_version(self):
        new = [f("00-XrLin64-static", "xrlin64v505p-static", 10, 4800000),
               f("00-XrPi32-static", "xrpi32v505p-static", 11, 3200000)]
        lst = listing([A, new[0]], [R], [V, new[1]], [D, SHADOWED])
        p = self.run_plan(lst)
        self.assertTrue(p["action_needed"])
        got = {(i["version"], i["arch"], i["linkage"], i["newer_than_latest"]) for i in p["new"]}
        self.assertEqual(got, {("505p", "amd64", "static", True), ("505p", "armv7", "static", True)})
        self.assertEqual(p["unchanged"], 4)

    def test_replacement(self):
        swapped = dict(A, id=99, size_bytes=4771600, updated="2026-10-10T01:00:00-07:00")
        p = self.run_plan(listing([swapped], [R], [V], [D, SHADOWED]))
        self.assertEqual(len(p["changed"]), 1)
        c = p["changed"][0]
        self.assertEqual((c["version"], c["arch"]), ("505o", "amd64"))
        self.assertEqual(set(c["differences"]), {"id", "size_bytes", "updated"})
        self.assertEqual(c["recorded_sha256"], "a" * 64)
        self.assertTrue(p["action_needed"])

    def test_same_size_replacement_caught_by_updated(self):
        swapped = dict(R, updated="2026-10-10T01:00:00-07:00")
        p = self.run_plan(listing([A], [swapped], [V], [D, SHADOWED]))
        self.assertEqual(list(p["changed"][0]["differences"]), ["updated"])

    def test_disappearance(self):
        p = self.run_plan(listing([A], [], [V], [D, SHADOWED]))
        self.assertEqual([(i["version"], i["arch"]) for i in p["disappeared"]], [("505o", "arm64")])
        self.assertFalse(p["action_needed"])

    def test_unknown_files_ignored(self):
        junk = [f("00-XrLin64-static", "readme.txt", 20, 100),
                f("00-XrLin64-static", "xrpi64v505p-static", 21, 100)]
        p = self.run_plan(listing([A] + junk, [R], [V], [D, SHADOWED]))
        reasons = {i["full_path"].split("/")[1]: i["reason"] for i in p["ignored"]}
        self.assertEqual(reasons["readme.txt"], "name not recognised")
        self.assertIn("arm64 static build in 00-XrLin64-static", reasons["xrpi64v505p-static"])
        self.assertEqual(p["new"], [])

    def test_extra_folder_ignored(self):
        lst = BASE + [{"dir": "00-Other", "results": [f("00-Other", "x", 30, 1)], "has_more": False}]
        p = self.run_plan(lst)
        self.assertIn({"full_path": "00-Other/x", "reason": "not a tracked folder"}, p["ignored"])

    def test_dynamic_only_version(self):
        dyn = f("00-XrLin64-vanessa", "xrlin64v505q-vanessa", 40, 2400000,
                created="2026-10-11T02:00:00-07:00")
        p = self.run_plan(listing([A], [R], [V], [D, SHADOWED, dyn]))
        self.assertEqual([i["version"] for i in p["deferred"]], ["505q"])
        self.assertEqual(p["new"], [])
        later = NOW + datetime.timedelta(days=3)
        p = self.run_plan(listing([A], [R], [V], [D, SHADOWED, dyn]), now=later)
        self.assertEqual([(i["version"], i["linkage"]) for i in p["new"]], [("505q", "dynamic")])

    def test_dynamic_with_static_twin_ignored(self):
        dyn = f("00-XrLin64-vanessa", "xrlin64v505q-vanessa", 40, 2400000)
        st = f("00-XrLin64-static", "xrlin64v505q-static", 41, 4800000)
        p = self.run_plan(listing([A, st], [R], [V], [D, SHADOWED, dyn]))
        self.assertEqual([(i["version"], i["linkage"]) for i in p["new"]], [("505q", "static")])
        self.assertIn(dyn["full_path"], [i["full_path"] for i in p["ignored"]])

    def test_static_replacing_dynamic_flagged(self):
        st = f("00-XrLin64-static", "xrlin64v504x-static", 50, 4600000)
        p = self.run_plan(listing([A, st], [R], [V], [D, SHADOWED]))
        self.assertTrue(p["new"][0]["replaces_dynamic"])
        # once the static build exists, a later change to the vanessa file is not ingested
        p = self.run_plan(listing([A, st], [R], [V], [dict(D, id=77), SHADOWED]))
        self.assertEqual(p["changed"], [])
        self.assertIn("superseded", [i for i in p["ignored"] if i["full_path"] == D["full_path"]][0]["reason"])

    def test_paginated_listing_rejected(self):
        lst = copy.deepcopy(BASE)
        lst[0]["has_more"] = True
        with self.assertRaises(SystemExit):
            self.run_plan(lst)

    def test_missing_folder_rejected(self):
        with self.assertRaises(SystemExit):
            self.run_plan(BASE[:3])

    def test_keyed_input_shape(self):
        p = self.run_plan({r["dir"]: r for r in BASE})
        self.assertEqual(p["unchanged"], 4)

    def test_touch(self):
        up = copy.deepcopy(UPSTREAM)
        swapped = dict(A, id=99)
        p = ud.plan(listing([swapped], [R], [V], [D, SHADOWED]), up, VERSIONS, NOW)
        for x in up["files"]:
            x["last_checked"] = "2026-01-01"
        ud.touch(up, p, "2026-10-12")
        got = {x["name"]: x["last_checked"] for x in up["files"]}
        self.assertEqual(got["xrlin64v505o-static"], "2026-01-01")
        self.assertEqual(got["xrpi64v505o-static"], "2026-10-12")
        self.assertEqual(up["last_checked"], "2026-10-12")


class ManifestTests(unittest.TestCase):
    def test_version_order(self):
        vs = ["505a", "504z", "505o", "504p", "505aa", "504x"]
        self.assertEqual(sorted(vs, key=xm.version_key), ["504p", "504x", "504z", "505a", "505o", "505aa"])

    def test_parse_name(self):
        self.assertEqual(xm.parse_name("xrpi32v505o-static"), ("505o", "armv7", "static"))
        self.assertEqual(xm.parse_name("xrlin64v504x-vanessa"), ("504x", "amd64", "dynamic"))
        self.assertIsNone(xm.parse_name("xrlin64v505o-static.zip"))

    def test_record_new_version_moves_latest(self):
        v = copy.deepcopy(VERSIONS)
        self.assertEqual(xm.record(v, "505p", "arm64", "b" * 64, "u2", "", "2026-10-12"), "added")
        self.assertEqual(list(v["versions"])[-1], "505p")
        self.assertEqual((v["latest"], v["latest_arm64"], v["latest_amd64"]), ("505p", "505p", "505o"))

    def test_record_old_version_keeps_latest(self):
        v = copy.deepcopy(VERSIONS)
        xm.record(v, "504y", "arm64", "b" * 64, "u2", "", "2026-10-12")
        self.assertEqual(list(v["versions"]), ["504x", "504y", "505o"])
        self.assertEqual(v["latest_arm64"], "505o")

    def test_record_replacement_and_restore(self):
        v = copy.deepcopy(VERSIONS)
        self.assertEqual(xm.record(v, "504x", "amd64", "b" * 64, "u-bbbbbbbb", "", "2026-10-12"), "replaced")
        e = v["versions"]["504x"]["amd64"]
        self.assertEqual((e["url"], e["sha256"]), ("u-bbbbbbbb", "b" * 64))
        self.assertNotIn("packages", e)
        self.assertEqual(e["previous"], [{"url": "u", "sha256": "d" * 64, "packages": "libasound2",
                                          "replaced": "2026-10-12"}])
        self.assertEqual(xm.lookup(v, "504x", "amd64", "d" * 64), "previous")
        self.assertEqual(xm.record(v, "504x", "amd64", "d" * 64, "unused", "", "2026-10-13"), "restored")
        e = v["versions"]["504x"]["amd64"]
        self.assertEqual((e["url"], e["packages"]), ("u", "libasound2"))
        self.assertEqual([p["sha256"] for p in e["previous"]], ["b" * 64])
        self.assertEqual(xm.record(v, "504x", "amd64", "d" * 64, "x", "", "2026-10-14"), "unchanged")


if __name__ == "__main__":
    unittest.main()
