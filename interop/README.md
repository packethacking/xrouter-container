# XRouter <-> LinBPQ NET/ROM + INP3 interop suite

This checks that XRouter and LinBPQ can talk NET/ROM and INP3 to each other: that they become neighbours, measure the link with L3RTT, swap routes by INP3, carry layer 4 circuits, and withdraw and restore routes when a link fails. It runs against any XRouter image tag, so you can see whether a new release changed anything.

## The network

```
 LinBPQ3 PN0BQC        XRouter PN0XR (XRNODE)        LinBPQ PN0BQ (BPQNOD)        LinBPQ2 PN0BQB
   (BPQC)      <---->    app PN0XR-1 (XRAPP)  <---->   app PN0BQ-1 (BQAPP)  <---->    (BPQB)
             relay                          relay                         relay
```

Every AXUDP link goes through a small Python relay (`relay/axudp_relay.py`). It forwards each datagram unchanged and logs it decoded. LinBPQ2 only links to LinBPQ, so XRouter can only learn about it second-hand by INP3. LinBPQ3 only links to XRouter, so XRouter has to relay INP3 routes in both directions, not just announce its own. Timers (NODES, L3RTT, INP3, T3) are shortened in the configs so a full run takes five to seven minutes.

## What it checks

- `test_01_link`: the AXUDP link carries valid frames both ways and the AX.25 interlink comes up.
- `test_02_netrom`: both sides send NODES, and each lists the other in ROUTES and NODES.
- `test_03_inp3`: L3RTT probes flow and are reflected both ways; both sides send RIFs; RIF fields are in the ranges the INP3 spec allows; each node's own RIP has hop count 1; no duplicate RIPs; no positive route is sent back to the neighbour it came from; each side marks the other as an INP3 neighbour; applications and the third-party node propagate by INP3 in both directions with sensible hop counts and trip times.
- `test_03b_transit`: XRouter relays LinBPQ's routes to LinBPQ3 (one hop more, a longer trip time, aliases kept) and LinBPQ3's route to LinBPQ; LinBPQ3 learns the whole network through XRouter; a three-hop circuit through XRouter works.
- `test_04_l4`: NET/ROM circuits from XRouter to LinBPQ, LinBPQ to XRouter, and two hops each way via LinBPQ, with data passing.
- `test_04b_refresh`: both sides re-send their routes on the schedule they are configured for (XRouter `INPBCINTERVAL`, LinBPQ `RIFINTERVAL`).
- `test_05_withdrawal`: drop the LinBPQ2 link and check LinBPQ sends negative information, XRouter stops time-routing to it and passes the news on to LinBPQ3 within 10 seconds, then bring it back; drop the XRouter link and check both sides withdraw, LinBPQ tells LinBPQ2, XRouter tells LinBPQ3, and everything recovers when the link returns.

Tests that fail are left failing. `FINDINGS.md` explains each failure we believe is a real interop problem rather than a harness fault, with the wire evidence.

## Running it

You need Docker and Python 3 with pytest (the script makes a venv if pytest is missing).

```sh
interop/run.sh                  # XRouter :latest
interop/run.sh 505o 505c 505a   # several versions, one after another
interop/run.sh 505o -- -k inp3  # extra pytest arguments after --
```

Results, the relay log and every node's logs land in `interop/out/<tag>/`. Set `XRI_KEEP=1` to leave the stack running afterwards; the consoles are then on `telnet 127.0.0.1 17023` (XRouter, log in with any callsign), `17010` (LinBPQ), `17011` (LinBPQ2) and `17012` (LinBPQ3); the LinBPQs take user `sysop`, password `sysop`. Tear it down with `docker compose -f interop/docker-compose.yml down -v`.

In GitHub Actions the `inp3-interop` workflow runs the suite after every image publish, and on demand with an optional tag. Each version gets its own job, a pass/fail table in the run summary, and an artifact with the logs.

## Known issues

`known-issues.toml` lists XRouter bugs we already know about, which tests they break, and which versions they affect. In those versions the tests show as expected failures (XFAIL) and the run stays green. In any later version they are expected to pass, so a new release that has not fixed a bug goes red until someone reports it again or moves the issue's `until` forward. If a listed test passes in a version marked as affected, the run also goes red: the bug may be fixed, so check and update the file.

## Reading the relay log

`relay.txt` has one line per frame and is the quickest read:

```
1791708521.624 xr-bpq linbpq->xrouter PN0BQ>PN0XR I RIF: BPQNOD:PN0BQ h1 tt1, BQAPP:PN0BQ-1 h1 tt1
1791708510.700 xr-bpq xrouter->linbpq PN0XR>PN0BQ I L3RTT PN0XR>L3RTT ttl2: L3RTT: 180 0 0 19804 XRNODE ...
```

That is: Unix time, relay link, direction, AX.25 source and destination, frame type, then the NET/ROM content. In a RIF, `h` is the hop count and `tt` the trip time in 10 ms units (60000 means unreachable). `mark BEGIN <test>` lines show where each test starts.

`relay.jsonl` has the same frames as JSON, one per line, with every decoded field plus the raw datagram in hex (`raw`), so any line can be quoted as evidence or re-decoded. Frames the relay dropped on purpose carry `"action": "dropped"`. A `stats` line every 30 seconds shows the relay was alive through quiet spells.

The relay also has a small control API on `127.0.0.1:17080`, which the withdrawal tests use: `POST /links/xr-bpq?drop=1` (or `drop=0`, or `delay_ms=300`) and `GET /links`.

## Adding a node

To add a third or fourth implementation (for example a TheNet or XNet emulator): add a service to `docker-compose.yml` with the next fixed address, give it a config under `config/`, and add a link for it in `relay/links.json` naming the two nodes, their AXUDP ports and two free relay ports. Point the node's AXUDP peer at the relay's port for its side. New tests can then use the same `wire` fixture to look at its frames.
