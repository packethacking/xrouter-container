# Scheduled NODES broadcasts only go out on the first port
labels: xrouter-bug, netrom, reported
state: open

## What happens

With several ports, XRouter's scheduled NetRom NODES broadcasts go out on the first port only. Every port gets the broadcast at start-up, then only the first port gets the scheduled ones. With `NODESINTERVAL=1` they come about every 74 seconds rather than 60. The other ports never hear a scheduled broadcast.

## Expected

MAN NODESINT(7): "NODESINTERVAL is both a global and PORT directive ... If used in the "global" section of XROUTER.CFG, it sets the global NODESINTERVAL, the default for all PORTs. If used in a PORT block, it applies to that port only." So every port should get a broadcast every NODESINTERVAL minutes.

## How to reproduce

A bare XRouter with two AXUDP ports, each pointing at its own UDP listener (for example `nc -lu` or a small script on 10001 and 10002):

```
NODECALL=PN0XR
NODEALIAS=XRNODE
IPADDRESS=172.28.77.11
NODESINTERVAL=1

INTERFACE=1
    TYPE=AXUDP
    MTU=256
ENDINTERFACE

PORT=1
    INTERFACENUM=1
    IPLINK=172.28.77.10
    UDPLOCAL=10093
    UDPREMOTE=10001
    QUALITY=200
ENDPORT

PORT=2
    INTERFACENUM=1
    IPLINK=172.28.77.10
    UDPLOCAL=10094
    UDPREMOTE=10002
    QUALITY=200
ENDPORT
```

Both listeners get the start-up broadcast; after that only the port 1 listener gets NODES, about every 74 s.

The result is the same with `NODESINTERVAL=1` in each PORT block as well as globally, with each port on its own AXUDP interface, with three ports, and with the ports numbered 7, 8 and 9 (then port 7 gets them). `N BC T` shows one global schedule (`Interval (mins): 1`).

## Effect

A neighbour on any port but the first never hears XRouter's NODES. Some node software will not open a link to a neighbour it has not heard in NODES, and NetRom-only nodes can only learn routes from NODES, so they cannot route through XRouter on those ports.

Workaround: send the broadcast on the other ports from CRONTAB.SYS with `BC <port>` (MAN BCAST), for example `* * * * * BC 2`.

## Versions

504z, 505a, 505c and 505o: every version tried.

## Reported

Reported on the xrouter group on 2026-10-11.

## Tests

- The `nodes-first-port-only` entry in interop/known-issues.toml (one check, on XRouter's second port; the suite's CRONTAB.SYS works around the bug on ports 3 to 6 and leaves port 2 alone so the bug stays visible).
- Finding: https://github.com/packethacking/xrouter-container/blob/main/interop/FINDINGS.md#6-xrouter-sends-its-scheduled-nodes-broadcasts-only-on-its-first-port

Status: open.
