# Findings

What the suite found running XRouter against LinBPQ 6.0.25.41 (`m0lte/linbpq:latest`, 2026-09-29). Each entry says which XRouter versions show it, what we expected and why, and what the wire shows. Wire quotes are lines from `relay.txt` (one line per frame); the matching `relay.jsonl` lines carry the raw datagram in hex. Times are Unix seconds.

Spec references: [INP3] is "A New Routing Specification for Packet Radio Datagram Networks", Andreas Gal DB7KG (https://wiki.oarc.uk/_media/packet:internodeprotocolnp.pdf). MAN pages are XRouter's own, from the image's `/opt/xrouter/skel/MAN` (support files 504k). BPQ source references are to G8BPQ's LinBPQ source.

Summary:

| | 505a | 505c | 505o |
|---|---|---|---|
| 1. XRouter sends LinBPQ no RIF for minutes after the link comes up | fails | fails | fixed |
| 2. XRouter never re-sends its routes on schedule | not reached | fails | fails |
| 3. XRouter's own-node RIP has trip time 0 | not reached | fails | fails |
| 4. On link loss XRouter re-advertises the lost routes as reachable | not tested | fails | passes |
| 5. LinBPQ sometimes repeats a RIP in one RIF (LinBPQ, not XRouter) | | | seen once |

"Not reached" means XRouter sent no RIF during that run, so the check had nothing to look at. 505a was run against the first version of the suite, before LinBPQ3 was added, so the transit checks behind finding 4 were not run on it.

Everything else passes on 505o: NET/ROM neighbours and NODES, L3RTT both ways, RIF both ways, route flags, propagation of applications and third-party nodes in both directions, XRouter relaying INP3 between two LinBPQs (hop count +1, trip time increased, aliases kept), NET/ROM circuits up to three hops with XRouter in the middle, negative information forwarded by XRouter within the 10 seconds [INP3] asks for, and withdrawal and recovery on link loss.

---

## 1. 505a and 505c send LinBPQ no RIF for minutes after the link comes up (fixed in 505o)

**Versions:** 505a, 505c fail. 505o passes.

**Expected:** once the interlink is up and L3RTT has been answered, each side sends a RIF with at least its own node. [INP3]: "For the own node, a RIP is created and sent after the interlink has been established."

**Wire (505c):** the link comes up, L3RTT is exchanged and reflected both ways with `$N` on both sides, and LinBPQ sends RIFs, but XRouter sends none for the whole run (about seven minutes):

```
1791710416.747 xr-bpq linbpq->xrouter PN0BQ>PN0XR SABM
1791710416.755 xr-bpq xrouter->linbpq PN0XR>PN0BQ UA
1791710427.750 xr-bpq linbpq->xrouter PN0BQ>PN0XR I L3RTT PN0BQ>L3RTT ttl2: L3RTT:     861653          0          0          1 BPQNOD LEVEL3_V2.1 BPQ32003 $M9000 $N $H4
1791710427.752 xr-bpq xrouter->linbpq PN0XR>PN0BQ I L3RTT PN0BQ>L3RTT ttl1: L3RTT:     861653          0          0          1 BPQNOD LEVEL3_V2.1 BPQ32003 $M9000 $N $H4
1791710435.317 xr-bpq xrouter->linbpq PN0XR>PN0BQ I L3RTT PN0XR>L3RTT ttl2: L3RTT:        540          0          0      21731 XRNODE LEVEL3_V2.1 XRouter505c $M5000 $N $H15
1791710435.347 xr-bpq linbpq->xrouter PN0BQ>PN0XR I L3RTT PN0XR>L3RTT ttl1: L3RTT:        540          0          0      21731 XRNODE LEVEL3_V2.1 XRouter505c $M5000 $N $H15
1791710435.821 xr-bpq linbpq->xrouter PN0BQ>PN0XR I RIF: BPQNOD:PN0BQ h1 tt1, BQAPP:PN0BQ-1 h1 tt1
```

In a later 505c run, with LinBPQ3 also attached, XRouter's first RIF to LinBPQ came six minutes after the link was established (UA at 1791712484.577):

```
1791712843.593 xr-bpq xrouter->linbpq PN0XR>PN0BQ I RIF: XRNODE:PN0XR h1 tt0, BPQC:PN0BQC h2 tt2, XRAPP:PN0XR-1 h1 tt1
```

XRouter does learn LinBPQ's routes from LinBPQ's RIFs, so until then INP3 works one way only: LinBPQ (and anything behind it) never gets trip-time routes to XRouter. The other 505a/505c failures (`test_bpq_marks_xrouter_route_as_inp3`, `test_xrouter_nodes_reach_bpq2_through_bpq`, `test_bpq_learns_xrouter_application_by_inp3`, the transit tests, `test_bpq_tells_bpq2_that_xrouter_is_gone`) all follow from this one.

505o sends its RIF about 10 seconds after the link comes up, so this is the BPQ compatibility work doing its job.

## 2. XRouter never re-sends its routes on schedule

**Versions:** 505o and 505c fail. Not reached on 505a (no RIF in that run).

**Expected:** XRouter's own documentation says positive information is sent on a schedule. MAN INP3: "Positive information is not time critical and, like NetRom nodes broadcasts, is sent at scheduled intervals only." MAN XROUTER.CFG: "INPBCINTERVAL Secs between scheduled INP3 unicasts". The suite sets `INPBCINTERVAL=120`.

This matters to LinBPQ. For a neighbour that is not BPQ, LinBPQ assumes timed refreshes and drops any INP3 route not refreshed for 3 hours (BPQINP3.c: `timeoutRoutes = 1` in the "XR or others" branch of `ProcessRTTMsg`, then `DecayINP3Routes` with `INP3NodeTimeout = 3600 * 3`). So on a quiet, stable network LinBPQ will lose every INP3 route it learned from XRouter 3 hours after the last change.

**Wire (505o):** XRouter sends RIFs when links come up and after topology changes, never on a timer. In a 400 second soak with nothing changing, LinBPQ sent its own node six times (its `RIFINTERVAL=60`); XRouter sent it once:

```
1791711586.370 xr-bpq xrouter->linbpq PN0XR>PN0BQ I RIF: XRNODE:PN0XR h1 tt0, XRAPP:PN0XR-1 h1 tt1
1791711586.370 xr-bpq xrouter->linbpq PN0XR>PN0BQ I RIF: :PN0BQC h31 tt60000, :PN0BQB h31 tt60000, :PN0BQ-1 h31 tt60000
1791711596.268 xr-bpq xrouter->linbpq PN0XR>PN0BQ I RIF: BPQC:PN0BQC h2 tt2
(no further RIF from XRouter up to 1791711970, 384 s later)
```

XRouter's console agrees that nothing is scheduled. `N BC T` shows:

```
INP3 Unicast Times:
  Interval (secs):      120
  Last Full Update:     ---
  Next Full Update:     ---
  Last Unscheduled:     09:39:26
```

With the interval left at its default, `N BC T` reports 3600 seconds (MAN XROUTER.CFG says 600) and still shows `Next Full Update: ---`.

We have not run a 3 hour soak to watch LinBPQ actually drop the routes; the timeout is read from the BPQ source.

## 3. XRouter sends its own node with trip time 0

**Versions:** 505o and 505c fail (the late 505c RIF quoted under finding 1 has `XRNODE:PN0XR h1 tt0` too). Not reached on 505a.

**Expected:** [INP3] figure 1 gives the RIP transport time as `1 .. 60000`. [INP3] also says "For the own node ... the target time is ignored by the receiver", so this is low severity, but 0 is outside the stated range and XRouter is not consistent with itself: its application in the same RIF gets 1. LinBPQ sends its own node with 1. A comment in LinBPQ's `SendOurRIF` ("For no logical reason XR sends our routes at 10mS") suggests earlier XRouters sent 1 here too.

**Wire (505o), every run:**

```
1791712130.209 xr-bpq xrouter->linbpq PN0XR>PN0BQ I RIF: XRNODE:PN0XR h1 tt0, XRAPP:PN0XR-1 h1 tt1
```

The raw datagram from `relay.jsonl`; after the `ff` RIF signature comes PN0XR (`a09c60b0a440 00`), hops `01`, trip time `0000`:

```
a09c6084a240e0a09c60b0a44061a6cfffa09c60b0a44000010000080058524e4f44450a100004b68bfffffd120511073f0706173530356f041400000815494f3931574c00a09c60b0a4400201000107005852415050007d2a
```

LinBPQ copes: it adds its own link time on receipt, and relays XRouter on to LinBPQ2 as `XRNODE:PN0XR h2 tt1` or `tt2`. The visible effect is that XRouter's node looks 10 ms closer than its own application everywhere downstream. A receiver that applies the spec's range literally could reject or mishandle the entry.

## 4. 505c: on link loss, XRouter re-advertises the lost routes as reachable

**Versions:** 505c fails. 505o passes. Not tested on 505a.

**Expected:** [INP3] "Interlink Failure: On a AX.25 link failure, all routes to and from this neighbor are dropped", and negative information is propagated immediately. When the XRouter to LinBPQ link fails, LinBPQ3 (whose only path to PN0BQ, PN0BQ-1 and PN0BQB is through XRouter) should be sent those three at trip time 60000.

**Wire (505c):** the relay dropped the XRouter to LinBPQ link; XRouter's own table showed the routes gone about 13 s later. The only RIF XRouter then sent LinBPQ3 in the next 60 s advertised the lost nodes as reachable:

```
1791713076.885 xrouter->linbpq3 PN0XR>PN0BQC I RIF XRNODE:PN0XR hops=1 tt=0, BPQB:PN0BQB hops=3 tt=49, BPQNOD:PN0BQ hops=2 tt=47, BQAPP:PN0BQ-1 hops=2 tt=47, XRAPP:PN0XR-1 hops=1 tt=1
```

505o gets this right: it sends `:PN0BQB h31 tt60000, :PN0BQ h31 tt60000, :PN0BQ-1 h31 tt60000` to LinBPQ3 within seconds of noticing the loss.

## 5. LinBPQ sometimes lists one destination twice in a RIF

**Versions:** LinBPQ behaviour, independent of the XRouter version. Seen in one of the 505o runs; the test passes when it does not happen.

**Expected:** one RIP per destination in a RIF. [INP3] does not forbid repeats outright, but nothing is gained and the receiver processes the same route twice.

**Wire:** at link start, LinBPQ's first RIF to XRouter listed LinBPQ2 twice:

```
1791709520.957 linbpq->xrouter PN0BQ>PN0XR I RIF BPQB:PN0BQB hops=2 tt=4, BPQB:PN0BQB hops=2 tt=4
```

It looks like a race between `SendRIFToNewNeighbour` and the regular send path as the neighbour comes up. One for G8BPQ rather than G8PZT.

---

## Observations that are not failures

These break nothing we test, but someone reading XRouter's documentation would be surprised by them.

- **L3RTT units.** MAN L3RTT says the L3RTT timestamp is in 10 ms units. In XRouter's probes it advances by about 18.2 per second, the old PC clock tick (probes 29.7 s apart differ by 540). Only the sender reads the timestamp, so this is harmless. The `rtt` field, which MAN L3RTT calls "Last round trip time", carries the one-way time: with 300 ms of delay added each way in the relay, XRouter reported `rtt` 31 (310 ms) against a measured round trip of about 625 ms. LinBPQ reads the neighbour's SRTT from this text and shows it in `R V`, so the two nodes display different numbers for the same link.
- **Repeated RIPs across back-to-back RIFs.** XRouter often sends two RIFs in the same millisecond with a destination in both, for example `BPQC:PN0BQC h2 tt2` in both RIFs at 1791711264.347 and .348 in one run.
- **NODES interval.** With `NODESINTERVAL=1` XRouter broadcasts NODES about every 74 seconds rather than 60.
- **Alias on re-advertisement.** After a withdrawn route comes back, both XRouter and LinBPQ re-advertise it without the alias option (`:PN0BQB h3 tt5`). [INP3] sends options "with the first positive information to a network segment", which arguably includes a route returning after withdrawal. Both behave the same, so there is no interop effect.

## Not covered

- TheNet / XNet compatibility, which XRouter's author also flagged; a separate emulator is planned and the harness is ready for it (see README).
- XRouter talking INP3 to another XRouter, for example 505o to 505c.
- Long soaks, such as the 3 hour LinBPQ timeout behind finding 2.
