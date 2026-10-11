# Findings

What the suite found running XRouter against LinBPQ 6.0.25.41 (`m0lte/linbpq:latest`, 2026-09-29), XNet 1.38 (Linux build, DL1GJI), TheNetNode 1.79 (dl1ne/tnn179 at 53aa7c2, 32-bit), TheNet X1J release 2 (on `tnc2-emu` 0.1.0) and a second XRouter of the previous version. Each entry says which XRouter versions show it, what we expected and why, and what the wire shows. Wire quotes are lines from `relay.txt` (one line per frame); the matching `relay.jsonl` lines carry the raw datagram in hex. Times are Unix seconds.

Spec references: [INP3] is "A New Routing Specification for Packet Radio Datagram Networks", Andreas Gal DB7KG (https://wiki.oarc.uk/_media/packet:internodeprotocolnp.pdf). MAN pages are XRouter's own, from the image's `/opt/xrouter/skel/MAN` (support files 504k). BPQ source references are to G8BPQ's LinBPQ source.

Summary, XRouter's own behaviour:

| | 505a | 505c | 505o |
|---|---|---|---|
| 1. XRouter holds RIFs back for minutes (first RIF after link-up, and changes) | fails | fails | fixed |
| 2. XRouter ignores INPBCINTERVAL and re-sends its routes only every 10 minutes | fails | fails | fails |
| 3. XRouter's own-node RIP has trip time 0 | fails | fails | fails |
| 4. On link loss XRouter re-advertises lost routes, or never withdraws them | fails | fails | passes |
| 6. XRouter sends scheduled NODES broadcasts only on its first port | fails | fails | fails |
| 7. XRouter's first positive RIP for a node often has no alias | some runs | some runs | some runs |
| 12. RHP bind reply is not valid JSON | passes | passes | fails |
| 13. RHP send and sendto on a listening socket reply without the handle | passes | passes | fails |

The other implementations (not XRouter's to fix):

| | |
|---|---|
| 5. LinBPQ sometimes repeats a RIP in one RIF | seen in some runs |
| 8. TNN adds one to every hop count it receives | always |
| 9. XNet and TNN send their own node by RIF only when the link comes up; XNet sends it with trip time 0 | always |
| 10. TNN forgets a node's alias when a RIP arrives without one | always |
| 11. TheNet X1J on the emulator once stopped transmitting altogether | once in four runs |

The second XRouter shows its own version's behaviour from the table above towards the XRouter under test, nothing new.

**What works with each peer on 505o:** XNet, TNN and the second XRouter all link up, exchange and reflect L3RTT, swap RIFs with fields in range (apart from finding 3 and XNet's own trip time 0), mark each other as INP3, and learn each other's nodes. XRouter relays LinBPQ's routes to each of them and theirs to LinBPQ, one hop further and slower, with the poisoned reverse in place; LinBPQ2 reaches each of them three INP3 hops away; NET/ROM circuits work both ways and through XRouter, three hops end to end. When LinBPQ2's link drops, XRouter forwards the negative information to all of them within 10 s; when the LinBPQ link drops, it tells all of them; when a peer's link drops, XRouter withdraws it and tells LinBPQ at once, and everything recovers. TheNet X1J works over plain NET/ROM: NODES both ways, routes, circuits both ways and through XRouter to LinBPQ2, and XRouter's INP3 does it no harm (TheNet is not flagged INP3, gets no RIFs, and the link survives the L3RTT probes it cannot answer). Between two XRouters the hop count carries an extra flag (see Observations); the 505c peer decodes it correctly.

**505a and 505c against 505o, for the new peers:** everything that goes wrong for the peers on 505a and 505c is findings 1 and 4 again (and 7, as on 505o), and it hits them harder than LinBPQ because they hear about LinBPQ's side only through XRouter: changes and withdrawals reach XNet, TNN and the second XRouter only at the next 10 minute full update, a peer's link loss is never passed on to LinBPQ as negative information, a re-linked XNet or TNN is not re-advertised to LinBPQ for minutes, and XNet ends up with `#tmp` aliases for nodes whose first RIP had none. 505o fixes all of that. Findings 2, 3, 6 and 7 remain in 505o. Nothing we saw is worse on 505o than on 505c: the BPQ compatibility rewrite has not broken TheNet, XNet or TNN; it made them work better.

Wire evidence can be affected by the test machine itself: when the host stalls for several seconds, every node's timers fire at once and links reset. The relay logs such stalls (`stall` events), and the L3RTT checks ignore probes around them.

---

## 1. 505a and 505c hold RIFs back for minutes after the link comes up (fixed in 505o)

Issue: https://github.com/packethacking/xrouter-container/issues/ISSUE_7

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

**With the other peers (505a, 505c):** the same holding back hits changes, not just the first RIF. In one 505c run XRouter sent LinBPQ a burst of RIFs in the first minute and a half, then nothing for eight and a half minutes until the 10 minute full update (finding 2), and between that and the next one nothing either, although LinBPQ2's and LinBPQ's own links were dropped and restored in that time. RIF send times to LinBPQ, seconds after start (run starting 1791728487.434): 25, 25, 35, 45, 65, 85, 609, 609, 1213, 1213, then 1342 and 1411 for TheNet. LinBPQ3 got its first RIF at 403 s. So in 505a and 505c XNet, TNN and the second XRouter heard of LinBPQ2 coming back after its link was restored, and LinBPQ heard of XNet and TNN coming back after theirs, only at the next full update; `test_xrouter_forwards_recovered_third_party_to_bpq3`, the `..._relearns_bpq_side_after_link_restored` and `..._recovers_when_link_restored` tests fail for that reason. 505o sends the changes within seconds.

## 2. XRouter ignores INPBCINTERVAL: it re-sends its routes only every 10 minutes

Issue: https://github.com/packethacking/xrouter-container/issues/ISSUE_3

**Versions:** 505a, 505c and 505o fail.

**Correction:** this entry used to say XRouter never re-sends its routes. Longer runs with the new peers show it does, every 10 minutes counted from start-up, to every INP3 neighbour at once, whatever INPBCINTERVAL says (120 here). The 400 second soak quoted below was simply too short to see one. LinBPQ's 3 hour timeout is therefore not reached; what remains is that the setting has no effect and `N BC T` predicts a "Next Full Update" that never happens.

**Expected:** XRouter's own documentation says positive information is sent on a schedule. MAN INP3: "Positive information is not time critical and, like NetRom nodes broadcasts, is sent at scheduled intervals only." MAN XROUTER.CFG: "INPBCINTERVAL Secs between scheduled INP3 unicasts". The suite sets `INPBCINTERVAL=120`.

Refreshes matter to LinBPQ: for a neighbour that is not BPQ, it assumes timed refreshes and drops any INP3 route not refreshed for 3 hours (BPQINP3.c: `timeoutRoutes = 1` in the "XR or others" branch of `ProcessRTTMsg`, then `DecayINP3Routes` with `INP3NodeTimeout = 3600 * 3`). XRouter's 10 minute full update is well inside that, so LinBPQ keeps XRouter's routes; XNet and TNN do not refresh at all (finding 9).

**Wire:** full updates (a RIF with XRouter's own node, to every INP3 neighbour in the same second, not following a link set-up), in seconds after XRouter started:

```
505a: 604, 1208          (run starting 1791730067.794)
505c: 610, 1214          (run starting 1791728487.434)
505o: 607, 1211          (quiet soak, LinBPQs only, starting 1791731691.863)
```

`N BC T` on 505o, 14 minutes into a run, still promised a full update two minutes after the last one, long overdue:

```
INP3 Unicast Times:
  Interval (secs):      120
  Last Full Update:     13:40:11
  Next Full Update:     13:42:11
  Last Unscheduled:     13:40:21
```

The original 400 second soak (505o), with nothing changing: LinBPQ sent its own node six times (its `RIFINTERVAL=60`); XRouter sent it once:

```
1791711586.370 xr-bpq xrouter->linbpq PN0XR>PN0BQ I RIF: XRNODE:PN0XR h1 tt0, XRAPP:PN0XR-1 h1 tt1
1791711586.370 xr-bpq xrouter->linbpq PN0XR>PN0BQ I RIF: :PN0BQC h31 tt60000, :PN0BQB h31 tt60000, :PN0BQ-1 h31 tt60000
1791711596.268 xr-bpq xrouter->linbpq PN0XR>PN0BQ I RIF: BPQC:PN0BQC h2 tt2
(no further RIF from XRouter up to 1791711970, 384 s later)
```

Early in a run `N BC T` shows `Last Full Update: ---` and `Next Full Update: ---`. With the interval left at its default it reports 3600 seconds (MAN XROUTER.CFG says 600). The XNet, TNN and second XRouter links show the same 10 minute rhythm (`test_xrouter_refreshes_rif_to_*`); the refresh checks allow 1.5 intervals and list every later re-send in their failure message.

## 3. XRouter sends its own node with trip time 0

Issue: https://github.com/packethacking/xrouter-container/issues/ISSUE_4

**Versions:** 505a, 505c and 505o fail, towards every INP3 neighbour (LinBPQ, XNet, TNN, another XRouter). XNet 1.38 does the same (finding 9).

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

## 4. 505a and 505c: on link loss, XRouter re-advertises the lost routes, or never withdraws them

Issue: https://github.com/packethacking/xrouter-container/issues/ISSUE_8

**Versions:** 505a and 505c fail. 505o passes.

**Expected:** [INP3] "Interlink Failure: On a AX.25 link failure, all routes to and from this neighbor are dropped", and negative information is propagated immediately. When the XRouter to LinBPQ link fails, LinBPQ3 (whose only path to PN0BQ, PN0BQ-1 and PN0BQB is through XRouter) should be sent those three at trip time 60000.

**Wire (505c):** the relay dropped the XRouter to LinBPQ link; XRouter's own table showed the routes gone about 13 s later. The only RIF XRouter then sent LinBPQ3 in the next 60 s advertised the lost nodes as reachable:

```
1791713076.885 xrouter->linbpq3 PN0XR>PN0BQC I RIF XRNODE:PN0XR hops=1 tt=0, BPQB:PN0BQB hops=3 tt=49, BPQNOD:PN0BQ hops=2 tt=47, BQAPP:PN0BQ-1 hops=2 tt=47, XRAPP:PN0XR-1 hops=1 tt=1
```

505o gets this right: it sends `:PN0BQB h31 tt60000, :PN0BQ h31 tt60000, :PN0BQ-1 h31 tt60000` to LinBPQ3 within seconds of noticing the loss.

**With the other peers (505a, 505c):** when the LinBPQ link fails, XNet, TNN and the second XRouter are not told either (`test_xrouter_tells_*_that_bpq_side_is_gone`). When a peer's own link fails, XRouter's table shows the loss but LinBPQ is never told. 505c, all four peer links dropped by the relay at 1791729702.04; XRouter's table showed XNet gone 12 s later, yet in the next two minutes it sent LinBPQ only TheNet's withdrawal:

```
1791729700.837 xr-bpq xrouter->linbpq PN0XR>PN0BQ I RIF: XRNODE:PN0XR h1 tt0, BPQC:PN0BQC h2 tt2, THENET:PN0TH h2 tt104, TNN:PN0TN h2 tt7, XNET:PN0XN h2 tt2, XPAPP:PN0XP-1 h2 tt2, XRAPP:PN0XR-1 h1 tt1
1791729702.037 control xr-xnet drop=True delay_ms=0
1791729829.540 xr-bpq xrouter->linbpq PN0XR>PN0BQ I RIF: :PN0TH h30 tt60000
```

LinBPQ kept time routes to PN0XN, PN0TN and PN0XP through XRouter. 505o sends the negative RIPs for each within seconds of noticing (`test_xrouter_tells_bpq_that_*_is_gone`).

505a did the same for TheNet, which XRouter advertises by INP3 (see Observations): its link to TheNet failed at 1791735940.942 (`DM`, then five `SABM` retries), and XRouter never told LinBPQ; its next full update simply left PN0TH out, so LinBPQ kept `THENET:PN0TH h2 tt122` from 1791735868.232.

## 5. LinBPQ sometimes lists one destination twice in a RIF

**Versions:** LinBPQ behaviour, independent of the XRouter version. Seen in a 505o run and a 505c run; the test passes when it does not happen, so it is a non-strict known issue (`applies_to = "linbpq"`).

**Expected:** one RIP per destination in a RIF. [INP3] does not forbid repeats outright, but nothing is gained and the receiver processes the same route twice.

**Wire:** at link start, LinBPQ's first RIF to XRouter listed LinBPQ2 twice:

```
1791709520.957 linbpq->xrouter PN0BQ>PN0XR I RIF BPQB:PN0BQB hops=2 tt=4, BPQB:PN0BQB hops=2 tt=4
```

It looks like a race between `SendRIFToNewNeighbour` and the regular send path as the neighbour comes up. One for G8BPQ rather than G8PZT.

## 6. XRouter sends its scheduled NODES broadcasts only on its first port

Issue: https://github.com/packethacking/xrouter-container/issues/ISSUE_5

**Versions:** 505a, 505c and 505o fail in the suite; 504z too in a bench run (below). Every version we tried.

**Expected:** MAN NODESINT(7): NODESINTERVAL "is both a global and PORT directive ... If used in the "global" section of XROUTER.CFG, it sets the global NODESINTERVAL, the default for all PORTs". The suite sets `NODESINTERVAL=1`, so every port should get a NODES broadcast every minute.

**Wire (505o):** port 1 (LinBPQ) gets a broadcast about every 74 seconds; port 2 (LinBPQ3) never gets one, nor do ports 3 to 6 apart from the broadcasts our CRONTAB.SYS triggers with `BC <port>` once a minute:

```
1791725478.293 xr-bpq xrouter->linbpq PN0XR>NODES UI NODES from XRNODE: BPQC:PN0BQC via PN0BQC q200, ...
1791725552.544 xr-bpq xrouter->linbpq PN0XR>NODES UI NODES from XRNODE: BPQB:PN0BQB via PN0BQ q156, ...
1791725626.792 xr-bpq xrouter->linbpq PN0XR>NODES UI NODES from XRNODE: BPQB:PN0BQB via PN0BQ q156, ...
(11 broadcasts on xr-bpq in 15 minutes, none on xr-bpq3, xr-xnet, xr-tnn, xr-thenet or xr-xrpeer)
```

The only NODES XRouter sends on the other ports unprompted is the `NODES_POLL` at start-up. `N BC T` shows one global schedule (`Interval (mins): 1`). To rule out our configuration we ran a bare XRouter with one application and three AXUDP ports at a UDP listener: the broadcast went only to the first port's address, with `NODESINTERVAL=1` global only, with `NODESINTERVAL=1` in every PORT block as well, with each port on its own AXUDP interface, and with the ports numbered 7, 8, 9 (then port 7 got it). 504z and 505c behaved the same.

**Effect:** a neighbour on any other port never hears XRouter's NODES. LinBPQ3 still learns XRouter by INP3. XNet does not even open the link to a neighbour it has not heard in NODES, and TheNet can only ever learn routes from NODES, so without the work-around neither of them would talk to XRouter at all on ports 3 and 5.

## 7. XRouter's first positive RIP for a node often carries no alias

Issue: https://github.com/packethacking/xrouter-container/issues/ISSUE_6

**Versions:** 505a, 505c and 505o, in some runs and not others (each version failed at least one of these checks in at least one of our runs). A non-strict known issue, because it depends on timing.

**Expected:** [INP3] sends the optional fields, the alias among them, "with the first positive information to a network segment". The previous version of this file noted the alias missing when a withdrawn route comes back; this is the first time a neighbour hears of the node at all.

**What happens:** XRouter puts aliases in its full updates (at link set-up and every 10 minutes, finding 2) but not in the change RIFs it sends in between. So whether a neighbour learns a node's alias by INP3 depends on whether it first hears of the node in a full update or a change. **Wire (505o):** XNet sends its own alias; XRouter passes XNet on to LinBPQ, LinBPQ3, TNN and the second XRouter 0.4 s later without it, and LinBPQ3 never receives XNet's alias by INP3 in the rest of the run:

```
1791727514.404 xr-xnet xnet->xrouter PN0XN>PN0XR I RIF: XNET:PN0XN h1 tt0
1791727514.810 xr-bpq3 xrouter->linbpq3 PN0XR>PN0BQC I RIF: :PN0TH h2 tt171, :PN0XN h2 tt2
1791727514.819 xr-xrpeer xrouter->xrpeer PN0XR>PN0XP I RIF: :PN0TH h2 tt171, :PN0XN h130 tt2
```

TheNet (PN0TH), which XRouter turns into an INP3 route (see Observations), never gets its alias in any RIF, although XRouter knows it from TheNet's NODES. **Wire (505c),** XRouter's first news of LinBPQ's side to XNet:

```
1791728522.737 xr-xnet xrouter->xnet PN0XR>PN0XN I RIF: :PN0BQC h30 tt60000, :PN0TN h30 tt60000, :PN0BQB h3 tt11, :PN0BQ-1 h2 tt9, :PN0XP-1 h2 tt10, :PN0XP h2 tt10
```

**Effect:** XNet lists such nodes as `#tmp:PN0BQB`, `#tmp:PN0BQ-1` and so on, and `C BPQB` from XNet fails with `Node 'BPQB' unknown` until the next full update or a NODES broadcast fixes it (505c: `test_xnet_knows_aliases_of_relayed_nodes`). LinBPQ and TNN take aliases from NODES as well, which hides it for them while NODES are flowing.

## 12. 505o: the RHP bind reply is not valid JSON

Issue: https://github.com/packethacking/xrouter-container/issues/ISSUE_1

**Versions:** 505o fails. 505a and 505c pass. Reported on the xrouter group on 2026-10-11; the author confirmed it and has fixed it for a later build.

**Expected:** every RHP reply is a JSON object, and a bind is answered with a `bindReply` carrying `errCode`, `errText` and the socket handle, as 505c does.

**What happens (505o):** the type is `bind` instead of `bindReply`, and `Ok` appears without its `"errText":` label, so a JSON parser rejects the whole reply. An RHP application has to bind before it can listen, so this stops RHP server applications working on 505o.

```
> {"type":"bind","id":3,"handle":1,"local":"PN9TST-1"}
505c < {"type": "bindReply", "id": 3, "handle": 1, "errCode": 0, "errText": "Ok"}
505o < {"type": "bind", "id": 3, "handle": 1, "errCode": 0, Ok}
```

## 13. 505o: RHP send and sendto on a listening socket reply without the handle

Issue: https://github.com/packethacking/xrouter-container/issues/ISSUE_2

**Versions:** 505o fails. 505a and 505c pass. Reported on the xrouter group on 2026-10-11; the author confirmed it for send, found the same in sendto, and has fixed both for a later build.

**Expected:** the reply carries the socket handle it is about, so a client can match it to its socket. The error code itself changed on purpose in 505d (16, "Operation not supported", instead of 17, "Not connected"), and so did LISTEN on a socket that is already listening; the tests do not pin either.

```
> {"type":"send","id":6,"handle":1,"data":"x"}
505c < {"type": "sendReply", "id": 6, "handle": 1, "errCode": 17, "errText": "Not connected"}
505o < {"type": "sendReply", "id": 6, "errCode": 16, "errText": "Operation not supported"}
```

---

# The other implementations

These are not XRouter's to fix, but they matter to anyone running XRouter next to these nodes. Each has a known-issue entry with `applies_to` set, so it shows as an expected failure whatever the XRouter version.

## 8. TNN adds one to every hop count it receives

**TNN 1.79.** `src/l3inp.c` reads the hop counter of each RIP and then increments it ("Hop-Counter erhoehen"), except for the neighbour itself, which it forces to 1. But in INP3 the sender has already counted the hop: XRouter sends its own node at hop 1 and LinBPQ2 at hop 3 (XRouter, LinBPQ, LinBPQ2), as LinBPQ and XNet's RIFs do. So TNN's `LT` column is one too high for everything beyond its neighbour:

```
1791726466.840 xr-tnn xrouter->tnn PN0XR>PN0TN I RIF: ..., BPQB:PN0BQB h3 tt4, ...
TNN:  NODES BPQB  ->  >    450     40      0   4   DG   0     410  0 PN0XR
```

XNet also shows one hop more than INP3 everywhere, including its direct neighbour (`2 hops` for XRouter), which looks like a display convention rather than a different metric. The suite's console checks allow for both.

## 9. XNet and TNN send their own node by RIF only when the link comes up

**XNet 1.38, TNN 1.79.** Each sends its own node once after the link is set up and never again while it stays up (`test_xnet_refreshes_rif_on_schedule`, `test_tnn_refreshes_rif_on_schedule`). XNet has no setting for it. TNN does send a full refresh to INP3 neighbours (hourly; the suite builds it with two minutes), but the refresh walks the routing table, and TNN's own node is not in it, so nothing goes out when XRouter is its only neighbour. XRouter keeps both routes alive from the L3RTT probes, so this does not hurt XRouter; LinBPQ, which times out unrefreshed routes from non-BPQ neighbours after 3 hours (finding 2), would lose them. **Wire (505o):** own-node RIFs only after link set-ups:

```
1791727454.385 xr-xnet xnet->xrouter PN0XN>PN0XR I RIF: XNET:PN0XN h1 tt0
1791727514.404 xr-xnet xnet->xrouter PN0XN>PN0XR I RIF: XNET:PN0XN h1 tt0      (after a re-link at 1791727495)
1791727445.770 xr-tnn tnn->xrouter PN0TN>PN0XR I RIF: TNN:PN0TN h1 tt1
1791727485.166 xr-tnn tnn->xrouter PN0TN>PN0XR I RIF: TNN:PN0TN h1 tt1          (after a re-link at 1791727480)
```

XNet also sends its own node with trip time 0, as XRouter does (finding 3), and after one re-link with 2 (`XNET:PN0XN h1 tt2` at 1791728174.671).

## 10. TNN forgets a node's alias when a RIP arrives without one

**TNN 1.79.** XRouter advertised the second XRouter to TNN with its alias, and later (after a change) without it, which [INP3] allows. TNN then showed the node with no alias:

```
1791726466.840 xr-tnn xrouter->tnn PN0XR>PN0TN I RIF: ..., XRPEER:PN0XP h2 tt2
1791727044.015 xr-tnn xrouter->tnn PN0XR>PN0TN I RIF: :PN0XP-1 h2 tt2, :PN0XP h2 tt2
TNN:  NODES  ->  ...   :pn0xp        XPAPP:PN0XP-1 ...
```

Together with finding 7 this means TNN users may see aliases come and go. TNN prints a callsign in lower case when the node carries INP3 options.

## 11. TheNet X1J on the emulator once stopped transmitting altogether

**TheNet X1J on tnc2-emu 0.1.0.** In one 505a run TheNet answered XRouter's poll at 16:24:18 and then never transmitted again: no answers to polls or SABMs, and none of its own NODES broadcasts, which come every 60 s whatever XRouter does. It went on receiving (the emulator logged every frame XRouter sent). The last activity was a NET/ROM circuit from LinBPQ to TheNet that was opened and closed at once (`test_l4_connect_bpq_to_thenet`), eight seconds earlier, and our console session closing. XRouter handled it correctly (link failed, route marked failed). We could not tell whether the firmware or the emulator hung; it did not happen in the other three full runs. `test_thenet_recovers_when_link_restored` is a non-strict known issue for it, and its failure message says when TheNet last sent anything.

```
2026-10-11T16:24:18.165Z TX PN0TH>PN0XR <RR1 R F>
2026-10-11T16:24:21.187Z RX PN0XR>PN0TH <RR6 C P>
...
2026-10-11T16:25:40.943Z RX PN0XR>PN0TH <DM R F>
2026-10-11T16:25:47.431Z RX PN0XR>PN0TH <SABM C P>
(no TX line after 16:24:18 in the rest of the run)
```

## Other notes on the peers

- **TNN sends no NODES to an INP3 neighbour,** by design: `src/l3misc.c` sends only RIFs to a peer of type INP. At link-up it sends one NODES-format UI frame with no entries to the neighbour's own callsign (`PN0TN>PN0XR UI`, info `ff 544e4e202020`), which the relay logs as `NODES from TNN:` with nothing after it.
- **XNet opens the link only after it hears a NODES broadcast** from the neighbour, then switches it to INP3 by itself once L3RTT is answered. Its minimum NODES interval is 300 s.
- **TheNet X1J** knows nothing of L3RTT or RIFs and is not bothered by them: XRouter sends it a few L3RTT probes early on and then stops; TheNet neither answers nor forwards them.
- **The second XRouter** (505c with 505o under test; 505b with 505c; 504z with 505a) behaves as its version does in findings 1 to 3: in particular a 505c peer that loses its link to a 505o sends no RIF again for minutes, so the 505o XRouter shows it at the horizon trip time until then (`test_xrpeer_recovers_when_link_restored`).

---

## Observations that are not failures

These break nothing we test, but someone reading XRouter's documentation would be surprised by them.

- **L3RTT units.** MAN L3RTT says the L3RTT timestamp is in 10 ms units. In XRouter's probes it advances by about 18.2 per second, the old PC clock tick (probes 29.7 s apart differ by 540). Only the sender reads the timestamp, so this is harmless. The `rtt` field, which MAN L3RTT calls "Last round trip time", carries the one-way time: with 300 ms of delay added each way in the relay, XRouter reported `rtt` 31 (310 ms) against a measured round trip of about 625 ms. LinBPQ reads the neighbour's SRTT from this text and shows it in `R V`, so the two nodes display different numbers for the same link.
- **Repeated RIPs across back-to-back RIFs.** XRouter often sends two RIFs in the same millisecond with a destination in both, for example `BPQC:PN0BQC h2 tt2` in both RIFs at 1791711264.347 and .348 in one run.
- **NODES interval.** With `NODESINTERVAL=1` XRouter broadcasts NODES about every 74 seconds rather than 60.
- **Alias on re-advertisement.** After a withdrawn route comes back, both XRouter and LinBPQ re-advertise it without the alias option (`:PN0BQB h3 tt5`). [INP3] sends options "with the first positive information to a network segment", which arguably includes a route returning after withdrawal. Both behave the same, so there is no interop effect. See finding 7 for the case where it is the first information.
- **XRouter to XRouter hop counts.** Between two XRouters that both send `$V4` in L3RTT ("INP version number (v4 and above)", MAN L3RTT), XRouter sets the top bit of the hop count for routes it learned from other neighbours: `BPQNOD:PN0BQ h130 tt87`, `BPQB:PN0BQB h131 tt90`, where LinBPQ, XNet and TNN get `h2` and `h3`. The 505c peer reads them as 2 and 3, so it is a private extension both ends understand, but MAN INP3 still gives the hop field as 1 to 30. XRouter does not send it to neighbours without `$V4`. Raw RIF from 505o to the 505c peer (`82` is hop 130): `...a09c6084a2400082005708004250514e4f4400...`. The two XRouters also exchange L3 frames with opcode 0 (`PN0XP>PN0XR PROTEXT`) carrying the version and locator.
- **TheNet as an INP3 route.** XRouter gives TheNet, which never answers L3RTT, a smoothed transport time anyway (`R T` shows `Sntt 2.19` and flags 0 for PN0TH), and advertises it by INP3 to every other neighbour at hop 2 with that time (`THENET:PN0TH h2 tt137`). That is a sensible way to bring a NET/ROM-only neighbour into the INP3 network; it just has no alias (finding 7).
- **Horizon RIPs for nodes never advertised.** At start-up XRouter sometimes tells a neighbour that a node it never advertised to it is unreachable (`:PN0XP h31 tt60000` to TNN, then `XRPEER:PN0XP h2 tt2` ten seconds later). Harmless.
- **505c uses hop 30 as the horizon in negative RIPs, 505o hop 31.** Both are at or above MAN INP3's horizon of 30.

## Not covered

- Long soaks, such as the 3 hour LinBPQ timeout behind finding 9.
- XNet and TNN as transit nodes: each links only to XRouter here, so what they relay onwards is not tested.
- TheNet with the TNC-2's crosslink (KISS) serial port, and real radio timing beyond the emulator's perfect 1200 bit/s channel.
