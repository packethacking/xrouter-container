# INP3: the first positive RIP for a node often has no alias option
labels: xrouter-bug, inp3
state: open

## What happens

XRouter includes alias options in its full RIF updates (at link set-up and every 10 minutes) but not in the change RIFs it sends in between. So whether a neighbour learns a node's alias by INP3 depends on whether it first hears of the node in a full update or in a change. When it is a change, the first positive RIP has no alias, and the neighbour does not get the alias until the next full update.

505o example: XNet (PN0XN) sends its RIF with its alias to XRouter (PN0XR); 0.4 s later XRouter passes PN0XN on to another XRouter (PN0XP) without it:

```
1791727514.404 PN0XN>PN0XR I RIF: XNET:PN0XN h1 tt0
1791727514.819 PN0XR>PN0XP I RIF: :PN0TH h2 tt171, :PN0XN h130 tt2
```

(`h130` is hop 2 with the top bit set, which XRouter uses towards another XRouter that sends `$V4`.) Other neighbours got the same RIF without the alias, and one of them did not receive XNet's alias by INP3 for the rest of the run. A NetRom-only neighbour that XRouter advertises by INP3 (PN0TH here, a TheNet node) never has an alias in any RIF, although XRouter knows it from that node's NODES broadcasts.

## Expected

The INP3 specification ("A New Routing Specification for Packet Radio Datagram Networks", Andreas Gal DB7KG (https://wiki.oarc.uk/_media/packet:internodeprotocolnp.pdf)) sends the optional fields, the alias among them, "with the first positive information to a network segment". MAN INP3 lists the alias among the RIP's optional fields.

## Effect

A neighbour that learns routes only by INP3 can end up with no alias for the node. XNet, for example, lists such nodes as `#tmp:<call>`, and connecting to the node by alias fails ("Node '...' unknown") until the next full update or a NODES broadcast fills it in.

## How to reproduce

Intermittent, as it depends on timing. Three nodes in a line, A - XRouter - B, all INP3. Bring the A link up after the XRouter - B link is established and its full update has gone out. Decode the first RIF XRouter sends to B that mentions A: it usually has no alias option.

## Versions

505a, 505c and 505o, in some runs and not others (each version failed at least one of these checks in at least one run).

## Reported

Not reported to the author yet.

## Tests

- `test_alias_travels_with_route_relayed_to_xnet`
- `test_alias_travels_with_route_relayed_to_tnn`
- `test_xnet_knows_aliases_of_relayed_nodes`
- `test_tnn_knows_aliases_of_relayed_nodes`
- and four more checks of aliases relayed on XRouter's second port, in the `first-rip-without-alias` entry of interop/known-issues.toml
- Finding: https://github.com/packethacking/xrouter-container/blob/main/interop/FINDINGS.md#7-xrouters-first-positive-rip-for-a-node-often-carries-no-alias

Status: open.
