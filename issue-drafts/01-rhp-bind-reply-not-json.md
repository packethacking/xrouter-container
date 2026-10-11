# RHP bind reply is not valid JSON (505o)
labels: xrouter-bug, reported, fixed-upstream
state: open

## What happens

On 505o, every RHP `bind` request gets a reply that a JSON parser rejects. The `errText` label is missing in front of `Ok`, and the reply type is `bind` rather than `bindReply`:

```
> {"type":"bind","id":3,"handle":1,"local":"PN9TST-1"}
< {"type": "bind", "id": 3, "handle": 1, "errCode": 0, Ok}
```

An RHP application has to bind before it can listen for incoming connects, so this stops RHP server-type applications working on 505o.

## Expected

A valid JSON `bindReply`, as 505c sends for the same request:

```
< {"type": "bindReply", "id": 3, "handle": 1, "errCode": 0, "errText": "Ok"}
```

## How to reproduce

1. Run a stock 505o with `RHPPORT=9000` in XROUTER.CFG.
2. Open a TCP connection to port 9000 and send each request as JSON with a 2-byte big-endian length in front: `{"type":"socket","id":1,"pfam":"ax25","mode":"stream"}`, then the `bind` above with the handle it returned.
3. The bind reply is the one shown under "What happens".

## Versions

- 505o: affected.
- 505c and 505a: correct.

## Reported

Reported on the xrouter group on 2026-10-11. The author confirmed it the same day and has fixed it for a future build (a wrong function was called to produce the reply during a rewrite). This issue stays open until a released build with the fix passes the test below.

## Tests

- `test_rhp_bind_reply_is_valid_json` (interop/tests/test_06_rhp.py)
- Finding: https://github.com/packethacking/xrouter-container/blob/main/interop/FINDINGS.md#12-505o-the-rhp-bind-reply-is-not-valid-json

Status: open, fixed upstream, waiting for a release.
