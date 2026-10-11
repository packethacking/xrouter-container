# Daily upstream check

Instructions for the scheduled Claude session that keeps this repo in step with the XRouter binaries on groups.io. Follow them in order. Plain ASCII in everything you write (commit messages, reports): no em or en dashes.

## Rules

- Never mention BPQ (LinBPQ, BPQ32, or the interop suite's BPQ side) in anything sent to the XRouter author, Paula Dowie (G8PZT), on groups.io or anywhere else. Results that involve the other node go to Tom only.
- Never print the OARC token or put it on a command line other than through the command `ingest.sh` already uses.
- Do not push partial state. Either every new or changed file in the plan is ingested and committed together, or nothing is pushed.
- If nothing changed, do not commit. No noise commits.
- Do not edit `versions.json` or `upstream.json` by hand. Only `ingest.sh` and `upstream_diff.py --touch` write them.
- Containers you start yourself are named with an `xrt-` prefix; remove only those. Never use pkill.

## 1. Get a clean checkout

```sh
rm -rf /tmp/xrc-check && git clone https://github.com/packethacking/xrouter-container /tmp/xrc-check
cd /tmp/xrc-check
```

Work only in that checkout.

## 2. List the four upstream folders

With the groups.io MCP tools (find them with ToolSearch "groups.io"), call `list_files` with `group_name: "xrouter"`, `max_results: 100` and each of these `dir` values:

- `00-XrLin64-static` (amd64)
- `00-XrPi64-static` (arm64)
- `00-XrPi32-static` (armv7)
- `00-XrLin64-vanessa` (dynamically linked amd64)

If a result has `has_more: true`, fetch the next page with `page_token` and append its `results` to that folder's result before saving.

Save the four results, exactly as returned, as a JSON array to `/tmp/xrc-check-listing.json` (outside the checkout). The `download_url` values in them do not matter; they expire within minutes and are not used.

## 3. Work out the plan

```sh
python3 scripts/upstream_diff.py /tmp/xrc-check-listing.json > /tmp/xrc-check-plan.json
```

The plan has these lists:

- `new`: upstream files we do not track yet. Each has `version`, `arch`, `linkage` (static or dynamic) and `newer_than_latest`.
- `changed`: tracked files whose groups.io `id`, `size_bytes` or `updated` differ from `upstream.json`, which usually means upstream replaced the binary under the same name.
- `disappeared`: tracked files no longer on groups.io. Do not act on these; mention them in the report. Our mirror keeps them buildable.
- `deferred`: dynamic-only (vanessa) builds younger than 48 hours. Upstream usually uploads the static build a few minutes later, so wait. Mention them only if one is still there after two days.
- `ignored`: everything else, with a reason. Vanessa builds for versions that have a static amd64 build are always here; that is normal and needs no mention.

If `action_needed` is false, go to step 7.

## 4. Ingest each new or changed file

Handle the items in `new` and then `changed`, one at a time. For each one, without delay between the two calls:

1. Call `get_file` with `group_name: "xrouter"` and `path` set to the item's `full_path`. This returns a fresh `download_url`. Check that its `id` and `size_bytes` match the plan item; if not, the file changed again since the listing, so start over from step 2.
2. Run, at once (the link expires within minutes):

   ```sh
   scripts/ingest.sh <version> <arch> '<download_url>' --meta '<the get_file result as compact JSON>' [--dynamic]
   ```

   Add `--dynamic` when the item's `linkage` is `dynamic`. Quote the URL and the JSON in single quotes.

`ingest.sh` downloads the file, checks it is an ELF for that arch containing the version string, works out runtime packages for a dynamic build, boots it in the current image, uploads it to OARC (as `xrouter-<ver>-<arch>`, or `xrouter-<ver>-<arch>-<sha8>` for a replacement), checks the public copy, and updates `versions.json` and `upstream.json`. Its last line is `result: <added|replaced|restored|unchanged> ...`. Note each result line for the report.

- `unchanged` means the bytes are the ones we already have (for example groups.io gave the file a new id). That is fine; only `upstream.json` changed.
- If the download fails because the link expired, call `get_file` again and rerun straight away.
- If `ingest.sh` says this host cannot run the target arch's containers, rerun it (with a fresh link) adding `--no-boot-test`. The CI smoke test boots every image before anything is published as a version or latest tag. Say in the report that the local boot test was skipped for that arch.
- Any other failure: stop. Run `git checkout -- versions.json upstream.json` so nothing half-done is left, do not commit or push, and report the failure (step 8) with the error text. Any OARC upload that already happened is harmless; say which ones there were.

## 5. Check and commit

```sh
python3 scripts/upstream_diff.py /tmp/xrc-check-listing.json --touch > /tmp/xrc-check-plan2.json
python3 -c 'import json; p=json.load(open("/tmp/xrc-check-plan2.json")); assert not p["new"] and not p["changed"], p'
python3 -m unittest discover -s scripts/tests
git diff --stat
```

The first command records today's date as `last_checked`; the second confirms everything in the plan is now recorded. Read the `versions.json` diff and make sure it is what you expect: new version blocks in version order, `latest` and `latest_<arch>` moved only for newer versions, and for a replacement the old binary under `previous`.

Commit on `main` with a short subject and an unwrapped body, for example:

- new release: `Add XRouter 505p (amd64, arm64, armv7)`
- replacement: `XRouter 505o amd64: upstream replaced the binary`

In the body, list each file with its result and sha256, and for a replacement the old and new sha8 tags. End the message with the `Co-Authored-By:` line your session's attribution instructions give.

```sh
git push origin main
```

## 6. Watch the runs

The push starts `build-and-publish` (only if `versions.json` changed; a commit that only touches `upstream.json` builds nothing, so skip this step), and `inp3-interop` starts when that succeeds.

```sh
sha=$(git rev-parse HEAD)
gh run list --repo packethacking/xrouter-container --workflow build-and-publish.yml --commit "$sha" --json databaseId,status
gh run watch <id> --repo packethacking/xrouter-container --exit-status
gh run list --repo packethacking/xrouter-container --workflow inp3-interop.yml --event workflow_run --limit 3 --json databaseId,headSha,status
gh run watch <id> --repo packethacking/xrouter-container --exit-status
```

If `build-and-publish` fails, find the failed cells (`gh run view <id> --log-failed`), and report them; do not try to fix things. `inp3-interop` tests `latest_amd64` and the last four versions with an amd64 build. If a replacement was for an older version that is not in that set, run it for that version too: `gh workflow run inp3-interop.yml --repo packethacking/xrouter-container -f xrouter_tag=<version>`, and watch that run.

For the interop summary, download each version's results and count them:

```sh
gh run download <id> --repo packethacking/xrouter-container --dir /tmp/xrc-check-interop
python3 - <<'PY'
import glob, re, xml.etree.ElementTree as ET
for p in sorted(glob.glob("/tmp/xrc-check-interop/inp3-interop-*/junit.xml")):
    tag = p.split("inp3-interop-")[1].split("/")[0]
    c = {"passed": 0, "known issues": 0, "regressions": 0, "possibly fixed": 0}
    for tc in ET.parse(p).getroot().iter("testcase"):
        fail = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
        skip = tc.find("skipped")
        if fail is not None and "XPASS(strict)" in (fail.get("message") or ""):
            c["possibly fixed"] += 1
            m = re.search(r"https://github\.com/\S+/issues/\d+", fail.get("message") or "")
            print(tag, "possibly fixed:", tc.get("name"), m.group(0) if m else "(no issue: not an XRouter bug)")
        elif fail is not None:
            c["regressions"] += 1
        elif skip is not None and skip.get("type") == "pytest.xfail":
            c["known issues"] += 1
        else:
            c["passed"] += 1
    print(tag, c)
PY
```

### Possibly fixed known issues

A test listed as "possibly fixed" passed in a version where `interop/known-issues.toml` says an XRouter bug should break it. Its failure message ends with the GitHub issue URL. For each such issue, once per version (check the issue's comments first with `gh issue view <n> --repo packethacking/xrouter-container --comments`), add a short comment:

```sh
gh issue comment <n> --repo packethacking/xrouter-container --body "XRouter <version>: the interop suite's checks for this passed (<run url>), so it may be fixed in this version. Leaving the issue open until a person has looked."
```

Issues are public and the XRouter author may read them, so the Rules above apply: no mention of BPQ, and if a passing test's name contains `bpq`, leave the test names out of the comment. Do not close the issue, do not change `known-issues.toml`, and do not touch issue labels; say in the report which issues you commented on. A possibly fixed test whose known issue is not XRouter's (no issue URL) is only mentioned in the report.

## 7. Nothing changed

If `action_needed` was false in step 3:

```sh
python3 scripts/upstream_diff.py /tmp/xrc-check-listing.json --touch > /dev/null
```

This updates `last_checked` in the local checkout only. Do not commit or push it.

## 8. Report

Finish with a few plain sentences for Tom, no tables or jargon. Say:

- whether anything was new or replaced upstream, naming versions and arches;
- for a replacement, that `:<ver>-<arch>` now points at the new binary and the old one stays available as `:<ver>-<arch>-<old sha8>`;
- whether the images built and published, and for each version the interop suite ran on, how many tests passed, how many were known issues, and any regressions or possibly fixed tests by name, with the GitHub issue each possibly fixed test belongs to and whether you commented on it;
- anything that disappeared upstream, any long-deferred dynamic-only build, any skipped local boot test;
- on failure, what failed, the error, and that nothing was pushed.

If nothing changed, one sentence is enough: "Checked groups.io: no new or replaced XRouter binaries."
