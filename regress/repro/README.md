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

| | Bug | 505c | 505n | 505o |
|---|---|---|---|---|
| 2 | RHP bind reply is not valid JSON | not reproduced | not reproduced | **present** |
| 3 | RHP send/sendto on a listening socket reply without the handle | not reproduced | **present** | **present** |
| 6 | Scheduled NODES broadcasts only on the first port (3 min) | **present** | **present** | **present** |
| 11 | AGW `M` (unproto) from an unregistered client is not sent | not reproduced | **present** | **present** |
| 12 | Undecodable compressed (FA) BBS message hangs the node | n/a (no FBB) | **present** | **present** |
| 13 | `R n` shows no body for a forwarded message | **present** | **present** | **present** |
| 14 | No answer to user commands after an FBB SID | not reproduced (disconnects) | **present** | **present** |
| 22 | FBB ASCII forwarding out ends with `/EX`, not Ctrl-Z | n/a (no FBB) | **present** | **present** |
| 23 | MBL forwarding out puts a NUL byte before `/EX` | **present** | not reproduced | not reproduced |

Verified 2026-10-14 with the x86-64 static builds of 505c, 505n and 505o,
run as an unprivileged user. (505n was uploaded to groups.io on
2026-10-13, after 505o, though its letter is earlier.)
