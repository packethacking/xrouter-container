# RHP send and sendto on a listening socket reply without the socket handle (505o)
labels: xrouter-bug, reported, fixed-upstream
state: open

## What happens

On 505o, a `send` or `sendto` on a socket that is listening is answered with an error reply that has no `handle` field:

```
> {"type":"send","id":6,"handle":1,"data":"x"}
< {"type": "sendReply", "id": 6, "errCode": 16, "errText": "Operation not supported"}
```

`sendto` on a listening socket does the same.

## Expected

The reply carries the handle of the socket it is about, as 505c did and as every other reply does, so a client can match it to its socket:

```
< {"type": "sendReply", "id": 6, "handle": 1, "errCode": 16, "errText": "Operation not supported"}
```

The change of error code from 17 "Not connected" to 16 "Operation not supported" is deliberate (since 505d) and is not part of this issue; neither is LISTEN on an already listening socket now failing. The tests do not pin error codes or texts.

## How to reproduce

1. Run a stock 505o with `RHPPORT=9000` in XROUTER.CFG.
2. Over a TCP connection to port 9000 (each request as JSON with a 2-byte big-endian length in front): `socket` (ax25, stream), `bind` to a callsign, `listen` with flags 0, then `send` with some data, or `sendto` with `remote` and `port`.
3. The send or sendto reply has no `handle`.

## Versions

- 505o: affected.
- 505c and 505a: the reply carries the handle.

## Reported

Reported on the xrouter group on 2026-10-11 (for send). The author confirmed it the same day, found the same in sendto, and has fixed both for a future build. This issue stays open until a released build with the fix passes the tests below.

## Tests

- `test_rhp_send_on_listener_reply_carries_handle`
- `test_rhp_sendto_on_listener_reply_carries_handle`
- Finding: https://github.com/packethacking/xrouter-container/blob/main/interop/FINDINGS.md#13-505o-rhp-send-and-sendto-on-a-listening-socket-reply-without-the-handle

Status: open, fixed upstream, waiting for a release.
