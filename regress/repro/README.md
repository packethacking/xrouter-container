# Bug reproductions

Stand-alone reproductions for the XRouter bugs that `regress/` found
(GitHub issues #2-#7, #11, #12, #13, #14, #22, #23). They need only a published
XRouter binary, Python 3.8 or later (standard library only) and a shell.
No Docker and no root.

```sh
# 1. Any published Linux build, e.g. from the groups.io Files area
#    (00-XrLin64-static) or the OARC mirror in versions.json:
curl -fLo xrlin64v505o-static https://compute.oarc.uk/storage/public/folders/4851/xrouter-505o-amd64

# 2. Start a fresh node from it in ./xrrepro-node (a clean directory with
#    the config files from node/), and run one reproduction:
regress/repro/start-node.sh ./xrlin64v505o-static
python3 regress/repro/repro.py 13

# 3. Stop the node (-9: the node hung by #12 ignores SIGTERM):
kill -9 $(cat xrrepro-node/xrouter.pid)
```

Start a fresh node for each reproduction: some leave mail behind, and #12
hangs the node. The node listens on 127.0.0.1 only: telnet 8023, AGW 8000,
RHP 9000, and two AXUDP ports that send to 127.0.0.1:9999 and :9998 (the
#6 and #11 scripts listen there to see what goes out on air; #4, #5 and
#7 play fake INP3 neighbours there).

Each reproduction prints every line it sends (`->`) and receives (`<-`),
then a verdict line, `BUG PRESENT: ...` (exit 1) or `NOT REPRODUCED: ...`
(exit 0).

| | Bug | 505c | 505n | 505o | 505p (armv7) | First seen |
|---|---|---|---|---|---|---|
| 2 | RHP bind reply is not valid JSON | not reproduced | not reproduced | **present** | not reproduced | 505o |
| 3 | RHP send/sendto on a listening socket reply without the handle | not reproduced | **present** | **present** | not reproduced | 505d |
| 4 | INPBCINTERVAL has no effect: no scheduled full INP3 update within 5 min (6 min) | **present** | **present** | **present** | **present** (x86-64 build: fixed) | 505c or earlier |
| 5 | Node advertises itself in INP3 with trip time 0 (505c: 10 min) | **present** | **present** | **present** | not reproduced | 505c or earlier |
| 6 | Scheduled NODES broadcasts only on the first port (3 min) | **present** | **present** | **present** | **present** | 505c or earlier |
| 7 | First positive INP3 RIP for a newly learnt node has no alias (11 min on 505c) | not reproduced (sends only full updates) | **present** | **present** | **present** | 505m (505k, 505l never relay the node at all) |
| 11 | AGW `M` (unproto) from an unregistered client is not sent | not reproduced | **present** | **present** | **present** | 505d |
| 12 | Undecodable compressed (FA) BBS message hangs the node | n/a (no FBB) | **present** | **present** | **present** | 505d |
| 13 | `R n` shows no body for a forwarded message | **present** | **present** | **present** | **present** | 505c or earlier |
| 14 | No answer to user commands after an FBB SID | not reproduced (disconnects) | **present** | **present** | **present** | 505d |
| 22 | FBB ASCII forwarding out ends with `/EX`, not Ctrl-Z | n/a (no FBB) | **present** | **present** | **present** | 505d |
| 23 | MBL forwarding out puts a NUL byte before `/EX` | **present** | not reproduced | not reproduced | not reproduced | 505c or earlier (fixed in 505d) |

Verified 2026-10-14 with the x86-64 static builds of 505c, 505n and 505o,
run as an unprivileged user. 505p exists only as an armv7 build so far; it
was run under qemu-arm through a two-line wrapper script
(`exec qemu-arm ./xrpi32v505p-static "$@"`) passed to start-node.sh.
The x86-64 505p (uploaded 2026-10-14, run natively) matches the armv7 column except #4, which it fixes.
"First seen" comes from running the repros on the intermediate builds the
author uploaded on 2026-10-13 (505d, 505h, 505i, 505k, 505l, 505m). (505n was uploaded to groups.io on
2026-10-13, after 505o, though its letter is earlier.)
