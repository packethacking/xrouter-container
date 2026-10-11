# XRouter NET/ROM + INP3 interop suite

This checks that XRouter can talk NET/ROM and INP3 to the other node software it meets on the air: LinBPQ, XNet, TheNetNode (TNN), TheNet X1J, and another XRouter of a different version. For each it checks that they become neighbours, measure the link with L3RTT, swap routes by INP3 (TheNet: NODES only), carry layer 4 circuits, and withdraw and restore routes when a link fails. It runs against any XRouter image tag, so you can see whether a new release changed anything.

## The network

```
                                  XNet PN0XN (XNET)    TNN PN0TN (TNN)
                                           \                 /
                                       relay\               /relay
                                             \             /
 LinBPQ3 PN0BQC  <-relay->  XRouter PN0XR (XRNODE)  <-relay->  LinBPQ PN0BQ (BPQNOD)  <-relay->  LinBPQ2 PN0BQB
   (BPQC)                   app PN0XR-1 (XRAPP)                 app PN0BQ-1 (BQAPP)                  (BPQB)
                                             /             \
                            relay (KISS tap)/               \relay
                                           /                 \
                     TheNet X1J PN0TH (THENET)      second XRouter PN0XP (XRPEER)
                     on tnc2-emu, TCP KISS          app PN0XP-1 (XPAPP)
```

| Node | Address | XRouter port | Link |
|---|---|---|---|
| LinBPQ PN0BQ | 172.28.77.12 | 1 | AXUDP |
| LinBPQ3 PN0BQC | 172.28.77.14 | 2 | AXUDP |
| XNet 1.38 PN0XN | 172.28.77.15 | 3 | AXUDP |
| TNN 1.79 PN0TN | 172.28.77.16 | 4 | AXUDP (TNN's AX25IP) |
| TheNet X1J PN0TH | 172.28.77.17 | 5 | TCP KISS, simulated 1200 bit/s radio |
| XRouter PN0XP | 172.28.77.18 | 6 | AXUDP |

Every link goes through a small Python relay (`relay/axudp_relay.py`). It forwards each AXUDP datagram unchanged and logs it decoded; for TheNet it sits in the TCP KISS stream instead and logs each KISS frame the same way. LinBPQ2 only links to LinBPQ, so XRouter can only learn about it second-hand by INP3. Every other node links only to XRouter, so XRouter has to relay routes between all of them, not just announce its own. Timers (NODES, L3RTT, INP3, T3) are shortened in the configs.

XNet and TNN are built locally by compose (`peers/xnet`, `peers/tnn`): XNet from the upstream tarball, checked against a sha256, and TNN from source at a pinned commit, as a 32-bit build. Neither licence allows publishing them, so those images must never be pushed anywhere. TheNet runs on the public `tnc2-emu` image. The second XRouter is the newest version in `versions.json` older than the one under test, or `XROUTER_PEER_TAG`.

`config/xrouter/CRONTAB.SYS` sends a NODES broadcast every minute on ports 3 to 6, working around XRouter only broadcasting on its first port (FINDINGS 6). XNet will not even open the link until it hears one.

## What it checks

- `test_01_link`: the AXUDP link carries valid frames both ways and the AX.25 interlink comes up.
- `test_02_netrom`: both sides send NODES, and each lists the other in ROUTES and NODES; XRouter broadcasts NODES on its second port (LinBPQ3) too.
- `test_03_inp3`: L3RTT probes flow and are reflected both ways; both sides send RIFs; RIF fields are in the ranges the INP3 spec allows; each node's own RIP has hop count 1; no duplicate RIPs; no positive route is sent back to the neighbour it came from; each side marks the other as an INP3 neighbour; applications and the third-party node propagate by INP3 in both directions with sensible hop counts and trip times.
- `test_03b_transit`: XRouter relays LinBPQ's routes to LinBPQ3 (one hop more, a longer trip time, aliases kept) and LinBPQ3's route to LinBPQ; LinBPQ3 learns the whole network through XRouter; a three-hop circuit through XRouter works.
- `test_04_l4`: NET/ROM circuits from XRouter to LinBPQ, LinBPQ to XRouter, and two hops each way via LinBPQ, with data passing.
- `test_04b_refresh`: both sides re-send their routes on the schedule they are configured for (XRouter `INPBCINTERVAL`, LinBPQ `RIFINTERVAL`).
- `test_05_withdrawal`: drop the LinBPQ2 link and check LinBPQ sends negative information, XRouter stops time-routing to it and passes the news on to LinBPQ3 within 10 seconds, then bring it back; drop the XRouter link and check both sides withdraw, LinBPQ tells LinBPQ2, XRouter tells LinBPQ3, and everything recovers when the link returns.
- `test_06_rhp`: XRouter's RHP API answers bind, and send or sendto on a listening socket, with valid JSON that carries the socket handle.
- `test_03c_xnet`, `test_03d_tnn`, `test_03f_xrpeer`: the same ground as the LinBPQ checks for each INP3 peer: link up, NODES, L3RTT both ways (and that the number fields fit), RIFs both ways with fields in range, own node at hop 1, no duplicates, poisoned reverse, each side marks the other as INP3, XRouter relays LinBPQ's routes to the peer and the peer's to LinBPQ (hop count +1, longer trip time, aliases kept, the peer's alias reaching LinBPQ3), the peer reaches LinBPQ2 and LinBPQ2 reaches the peer, and NET/ROM circuits both ways and through XRouter.
- `test_03e_thenet`: TheNet X1J over plain NET/ROM: NODES both ways, routes, LinBPQ's nodes reaching TheNet and TheNet reaching LinBPQ through XRouter, circuits both ways and through XRouter, and that XRouter's INP3 does no harm (TheNet not flagged INP3, no RIFs sent to it, link survives the L3RTT probes).
- `test_04c_peer_refresh`: scheduled RIF refresh on the peer links, both directions.
- `test_05_withdrawal` also checks that XRouter passes LinBPQ's losses and recoveries on to every INP3 peer; `test_05b_peer_withdrawal` drops the peer links and checks XRouter withdraws each peer, tells LinBPQ at once, and that everything returns.

Test names say whose behaviour they check: `test_xnet_...`, `test_tnn_...`, `test_thenet_...`, `test_xrpeer_...` for the peers, `test_xrouter_..._xnet` and so on for XRouter towards them. Known bugs are expected failures in the versions they affect (see Known issues below). `FINDINGS.md` explains each failure we believe is a real interop problem rather than a harness fault, with the wire evidence, including bugs in the other implementations.

## Running it

You need Docker and Python 3 with pytest (the script makes a venv if pytest is missing).

```sh
interop/run.sh                  # XRouter :latest
interop/run.sh 505o 505c 505a   # several versions, one after another
interop/run.sh 505o -- -k inp3  # extra pytest arguments after --
XRI_PEERS=none interop/run.sh 505o           # LinBPQ only, the old 6 minute run
XRI_PEERS=xnet,tnn interop/run.sh 505o       # just some of the peers
XROUTER_PEER_TAG=504z interop/run.sh 505o    # pick the second XRouter
```

`XRI_PEERS` takes any of `xnet`, `tnn`, `thenet`, `xrpeer` (default all); tests for a peer that is not started are skipped. `XRI_BUILD=1` rebuilds the XNet and TNN images. With every peer a 505o run takes about 14 minutes here, and 505a or 505c about 25, because the checks they fail wait out their time limits. `XRI_PEERS=none` is the old LinBPQ-only run.

Results, the relay log and every node's logs land in `interop/out/<tag>/`. Set `XRI_KEEP=1` to leave the stack running afterwards; the consoles are then on `127.0.0.1`: `telnet 17023` (XRouter, log in with any callsign), `17024` (the second XRouter), `17010`, `17011`, `17012` (the LinBPQs, user `sysop`, password `sysop`), `17014` (TNN, any callsign, then `SYSOP` and five `S`), and raw TCP `17015` (XNet) and `17013` (TheNet): press Escape, then `C PN0XN` or `C`. Tear it down with `COMPOSE_PROFILES=xnet,tnn,thenet,xrpeer docker compose -f interop/docker-compose.yml down -v`.

In GitHub Actions the `inp3-interop` workflow runs the suite after every image publish, and on demand with an optional tag. Each version gets its own job, a pass/fail table in the run summary, and an artifact with the logs.

## Known issues

`known-issues.toml` lists bugs we already know about, which tests they break, and which versions they affect. Most are XRouter's; `applies_to = "peer"` marks a bug in the second XRouter (matched against its version), and `applies_to = "xnet"`, `"tnn"` or `"thenet"` a bug in that implementation, which applies to every XRouter version since those are pinned. In those versions the tests show as expected failures (XFAIL) and the run stays green. In any later version they are expected to pass, so a new release that has not fixed a bug goes red until someone reports it again or moves the issue's `until` forward. If a listed test passes in a version marked as affected, the run also goes red: the bug may be fixed, so check and update the file.

## Reading the relay log

`relay.txt` has one line per frame and is the quickest read:

```
1791708521.624 xr-bpq linbpq->xrouter PN0BQ>PN0XR I RIF: BPQNOD:PN0BQ h1 tt1, BQAPP:PN0BQ-1 h1 tt1
1791708510.700 xr-bpq xrouter->linbpq PN0XR>PN0BQ I L3RTT PN0XR>L3RTT ttl2: L3RTT: 180 0 0 19804 XRNODE ...
```

That is: Unix time, relay link, direction, AX.25 source and destination, frame type, then the NET/ROM content. Lines starting `kiss` record the TheNet KISS session connecting and closing. In a RIF, `h` is the hop count and `tt` the trip time in 10 ms units (60000 means unreachable). `mark BEGIN <test>` lines show where each test starts.

`relay.jsonl` has the same frames as JSON, one per line, with every decoded field plus the raw datagram in hex (`raw`), so any line can be quoted as evidence or re-decoded. Frames the relay dropped on purpose carry `"action": "dropped"`. A `stats` line every 30 seconds shows the relay was alive through quiet spells. A `stall` line means the relay itself was frozen for that long: the whole test machine stalled, every node's timers fired at once when it woke, and links may have reset for no fault of any node. The L3RTT checks ignore probes sent around a stall.

The relay also has a small control API on `127.0.0.1:17080`, which the withdrawal tests use: `POST /links/xr-bpq?drop=1` (or `drop=0`, or `delay_ms=300`) and `GET /links`. The links are `xr-bpq`, `bpq-bpq2`, `xr-bpq3`, `xr-xnet`, `xr-tnn`, `xr-thenet` and `xr-xrpeer`.

## Adding a node

Add a service to `docker-compose.yml` with the next fixed address and its own profile, give it a config under `config/` (or `peers/` if it is built here), and add a link for it in `relay/links.json` naming the two nodes, their AXUDP ports and two free relay ports (or `"kind": "kiss_tcp"` for a TCP KISS server). Point the node's AXUDP peer at the relay's port for its side, and add a port for it to XRouter's config. `tests/peerchecks.py` has the INP3 checks the peer tests share.
