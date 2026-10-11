# INP3: own node advertised with trip time 0 (range is 1 to 60000)
labels: xrouter-bug, inp3, reported
state: open

## What happens

In every RIF XRouter sends, the RIP for its own node has trip time 0, while the RIP for its own application in the same RIF has 1. For a node PN0XR (alias XRNODE) with an application PN0XR-1 (XRAPP), decoded:

```
RIF: XRNODE:PN0XR hops 1 tt 0, XRAPP:PN0XR-1 hops 1 tt 1
```

In the raw frame, after the `ff` signature: PN0XR `a09c60b0a440 00`, hops `01`, trip time `0000`. This happens towards every INP3 neighbour, including another XRouter.

## Expected

A trip time from 1 to 60000. MAN INP3, packet structure: "<trip time>   Trip time to target in 10ms units (1-60000)". The INP3 specification ("A New Routing Specification for Packet Radio Datagram Networks", Andreas Gal DB7KG (https://wiki.oarc.uk/_media/packet:internodeprotocolnp.pdf)) gives the same range in figure 1.

The spec also says the receiver ignores the target time of the sender's own node, so this is low severity, but 0 is outside the stated range, and a receiver that applies the range literally could reject or mishandle the entry. Downstream, XRouter's node appears 10 ms closer than its own application.

## How to reproduce

Any XROUTER.CFG with one INP3 neighbour (an AXUDP port with L3RTT answered). Capture the first RIF XRouter sends after the link comes up and decode the RIP for NODECALL.

## Versions

505a, 505c and 505o (seen in every run on each).

## Reported

Reported on the xrouter group on 2026-10-11.

## Tests

- `test_xrouter_rif_fields_in_spec_range`
- `test_xrouter_rif_to_xnet_fields_in_spec_range`
- `test_xrouter_rif_to_tnn_fields_in_spec_range`
- `test_xrouter_rif_to_xrpeer_fields_in_spec_range`
- `test_xrpeer_rif_fields_in_spec_range` (the same behaviour in the second XRouter)
- Finding: https://github.com/packethacking/xrouter-container/blob/main/interop/FINDINGS.md#3-xrouter-sends-its-own-node-with-trip-time-0

Status: open.
