# XRouter regression suite

This suite records how XRouter behaved before 505o, using 505c as the baseline. It then checks any other version against that behaviour. It is lighter than `interop/`: it needs only XRouter (two or three containers of it) and the test process itself, which plays the radio stations over AXUDP. It does not need LinBPQ, XNet or TNN.

It was started to chase the problems reported on the xrouter groups.io list after the 505o release. [PROGRESS.md](PROGRESS.md) maps each report to its tests and says how to resume the work. Open work is tracked as sub-issues of [#10](https://github.com/packethacking/xrouter-container/issues/10). [FINDINGS.md](FINDINGS.md) has the results. [INVENTORY.md](INVENTORY.md) is the feature inventory, drawn from the OARC wiki and the MAN pages, that the tests were planned from.

## The set-up

```
  test process (docker host, 172.28.78.1)
     probe A :30001 ---- port 1 ---\
     probe B :30002 ---- port 2 ----  xrr-dut PN0DUT (DUT)  -- port 3 --  xrr-nbr PN0NB (NBR)
                                                                           |
     probe C :30003 ----------------------------------------- port 2 -----/

     probe D :30004 -- udpbridge -- port 2 -- xrr-ip PN0IP (IPGW) -- port 1 TUN tun99 -- Linux
                                                                  -- port 3 AXIP to 44.130.2.2 (Linux, via tun99)
```

- **xrr-dut** is the version under test (`XROUTER_TAG`), a node with a full BBS (PMSTYPE=4), an application, chat, HTTP, RHP and AGW. See `config/dut/XROUTER.CFG`.
- **xrr-nbr** is a second XRouter (`XRR_NBR_TAG`, default 505c). It is the DUT's INP3 neighbour.
- **xrr-ip** is the version under test again, set up as an AMPRNet gateway (`config/ip`). It has a TUN interface to the container's Linux stack, AXIP to a 44.x partner through the tunnel, and AX.25 users on an AXUDP port. While a TUN port exists, XRouter sends AXUDP and AXIP to non-localhost peers through its own IP stack, so this node's AX.25 port points at 127.0.0.1 and `image/udpbridge.py` relays it.
- **Probes** are AXUDP endpoints in the test process (`tests/ax25.py`). They can send any frame and see everything XRouter sends on that port. They also include a small AX.25 connected-mode client. `tests/fakenode.py` builds a NET/ROM node on top of a probe: it sends NODES broadcasts and, optionally, enough INP3 to count as an INP3 neighbour (L3RTT and RIFs).

All the XRouter containers run `xrr-local/xrouter:<tag>`. That is the published image plus iproute2, tcpdump and python3 (`image/Dockerfile`). XRouter shells out to `ip`/`ifconfig` to bring up a TUN interface from `IOADDR`, and the published image does not have them. This test image is built locally and never pushed.

## What it checks

| Module | What |
|---|---|
| `test_00_smoke` | the stack is up |
| `test_10_console` | about 100 console commands, user and sysop. Each reply is normalised (numbers, version) and compared with 505c's in `golden/505c/console/` |
| `test_20_digi` | UI and connected-mode digipeating via the node call, the alias, PORTALIAS2, WIDEn-n and TRACEn-n; BCAST re-broadcast of MAIL/FBB beacons; SEND; the ID beacon |
| `test_30_ip_ax25` | IP over AX.25: ping both ways, ARP, forwarding |
| `test_31_ip_gateway` | the TUN gateway: pings both ways, each IPROUTE form (gateway, no gateway, default, kernel), AX.25 users to 44-net and back, AXIP out and in through the tunnel |
| `test_40_pms` | the BBS over telnet and over AX.25: greeting and prompt, send, list, read by number, kill, bye |
| `test_41_fbb` | the BBS as an FBB forwarding partner (throwaway node per test): SID, ASCII (`FB`) and compressed (`FA`, LZHUF via `tests/lzhuf.py`, byte-exact with LinFBB) forwarding in, bad compressed data, reading forwarded mail, user commands after an FBB SID |
| `test_45_chat_access` | the chat server (CHAT command and AX.25 to CHATCALL, two users), telnet login rules and CTEXT |
| `test_50_routing` | a direct quality-192 neighbour versus an INP3 path to the same node through the other XRouter: which route is used |
| `test_55_netrom` | NODES broadcasts, learning from NODES, the neighbour link, L4 circuits both ways, the BBS and service 2 over L4 |
| `test_51_routing_slow_rf` | the same with a slow (0.8 s) direct link, direct neighbour with and without INP3 |
| `test_60_services` | HTTP pages, `/exec`, REST (nodes, routes, circuits, mail), RHP (socket, open, bind/listen, close, status), AGW (version, ports, unproto with and without registration) |
| `test_70_dedhost` | the WA8DED host-mode emulation (on a pty bridged to TCP by socat): host mode, MYCALL, unproto beacons with and without digis, connect |
| `test_lzhuf_unit` | the LZHUF codec on its own (no docker) |

Every test passes on 505c. A failure on another version is either a regression, a deliberate change, or noise in the test. Once someone has looked at it, it goes into `known-issues.toml`. That file uses the same rules as interop's: expected failures for the affected versions, and red again once a version claims a fix.

## Running it

You need Docker and Python 3 with pytest. The host must provide `/dev/net/tun`.

```sh
regress/run.sh 505o                 # one version; results in regress/out/505o/
regress/run.sh 505c 505o            # several
regress/run.sh 505o -- -k digi      # pytest arguments after --
XRR_KEEP=1 regress/run.sh 505o      # leave the containers up afterwards
XRR_UPDATE_GOLDEN=1 regress/run.sh 505c -- -k console   # re-record the console golden output
```

A full run takes about 25 minutes. The routing tests wait for INP3 to settle, and some checks wait out timeouts. `out/<tag>/` holds every frame the probes saw (`probes.txt`), every console exchange (`consoles.txt`), the raw console output per command (`console/`), the BBS sessions (`pms/`) and the node logs. With `XRR_KEEP=1`, the consoles are telnet `127.0.0.1:18023` (DUT), `18024` (NBR) and `18025` (IP gateway). Log in with any callsign, then type `@ abcdefghijklmnopqrstuvwxyz` for sysop.

CI: the `regress` workflow runs on demand. It also runs after each image publish, against the latest version and 505c.
