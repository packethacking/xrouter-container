# INP3: on link loss, lost destinations are not withdrawn and may be re-advertised as reachable (fixed in 505o)
labels: xrouter-bug, inp3, fixed
state: closed

## What happened

On 505a and 505c, when an INP3 interlink failed, XRouter dropped the routes from its own table (they were gone about 13 s later in `N`), but did not send its other neighbours negative information for them. Instead:

- After one neighbour's link was dropped, the only RIF XRouter sent another neighbour in the next 60 s still listed the three nodes behind the lost link as reachable, at hops 2 and 3 with trip times around 47.
- In a 505c run with four neighbour links dropped at once, XRouter's table showed them gone within 12 s, but in the next two minutes it sent the remaining neighbour only one withdrawal (`:PN0TH h30 tt60000`), and nothing for PN0XN, PN0TN or PN0XP. That neighbour kept trip-time routes to all three through XRouter.
- On 505a, when the link to a NetRom-only neighbour (PN0TH) failed, XRouter never sent negative information for it; its next full update simply left PN0TH out.

## Expected

The INP3 specification ("A New Routing Specification for Packet Radio Datagram Networks", Andreas Gal DB7KG (https://wiki.oarc.uk/_media/packet:internodeprotocolnp.pdf)): "Interlink Failure: On a AX.25 link failure, all routes to and from this neighbor are dropped", and negative information is propagated at once. MAN INP3: "Any update of positive information with a slower target time (or route loss) is called negative information. This is always propogated immediately." So the other neighbours should get each lost node at the horizon (trip time 60000) within seconds.

## How to reproduce (505a, 505c)

Three nodes in a line, A - XRouter - B, all INP3 and converged. Cut the A link (for example drop its UDP traffic). Watch the RIFs XRouter sends B over the next minute: no horizon RIPs for A's nodes, and possibly a positive RIP for them.

## Versions

- 505a and 505c: affected (timing dependent, so not every run).
- 505o: fixed. It sends horizon RIPs for each lost node to every other neighbour within seconds of noticing the loss.

## Tests

- The `stale-routes-on-link-loss` entry in interop/known-issues.toml (eight checks: XRouter withdrawing a lost neighbour's nodes towards each of its other neighbours, including another XRouter, XNet and TNN).
- Finding: https://github.com/packethacking/xrouter-container/blob/main/interop/FINDINGS.md#4-505a-and-505c-on-link-loss-xrouter-re-advertises-the-lost-routes-or-never-withdraws-them

Status: closed, fixed in 505o.
