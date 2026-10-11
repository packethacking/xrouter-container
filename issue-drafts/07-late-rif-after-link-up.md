# INP3: no RIF for minutes after an interlink comes up, and changes held back (fixed in 505o)
labels: xrouter-bug, inp3, fixed
state: closed

## What happened

On 505a and 505c, after an INP3 interlink came up and L3RTT had been exchanged and reflected in both directions (both sides sending `$N`), XRouter often sent the neighbour no RIF for minutes. In one 505c run it sent none at all in the seven minutes the run lasted, while the neighbour sent its own RIFs from the start; in another, XRouter's first RIF came six minutes after the link was established. Until then INP3 worked one way only: XRouter learnt the neighbour's routes, but the neighbour never got trip-time routes to XRouter.

Changes were held back the same way. In one 505c run XRouter sent a neighbour a burst of RIFs in its first 90 seconds, then nothing for eight and a half minutes until the 10 minute full update, and nothing between that and the next, although two links behind it were dropped and restored in that time. So neighbours heard of nodes coming back only at the next full update.

## Expected

The INP3 specification ("A New Routing Specification for Packet Radio Datagram Networks", Andreas Gal DB7KG (https://wiki.oarc.uk/_media/packet:internodeprotocolnp.pdf)): "For the own node, a RIP is created and sent after the interlink has been established." Changes should follow within seconds, as they do in 505o.

## How to reproduce (505a, 505c)

One INP3 neighbour on an AXUDP port. Let the link come up and watch for XRouter's first RIF on it: it may take minutes or not come at all before the 10 minute full update.

## Versions

- 505a and 505c: affected (how long varied from run to run, so some runs looked fine).
- 505o: fixed. It sends its RIF about 10 s after the link comes up, and changes within seconds.

## Tests

- `test_xrouter_sends_rif`
- `test_own_node_rip_has_hop_count_one`
- `test_xrouter_resends_own_rif_after_link_restored`
- `test_routes_recover_when_link_restored`
- `test_xrouter_forwards_negative_info_to_xnet`, `..._to_tnn`, `..._to_xrpeer`
- `test_xnet_recovers_when_link_restored`, `test_tnn_recovers_when_link_restored`
- `test_xrpeer_recovers_when_link_restored` (the same behaviour in a 505c second XRouter)
- and the rest of the `late-initial-rif` entry in interop/known-issues.toml
- Finding: https://github.com/packethacking/xrouter-container/blob/main/interop/FINDINGS.md#1-505a-and-505c-hold-rifs-back-for-minutes-after-the-link-comes-up-fixed-in-505o

Status: closed, fixed in 505o.
