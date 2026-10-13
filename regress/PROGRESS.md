# 505o regression hunt: plan and progress

Tracking file for the work to capture XRouter's pre-505o behaviour in tests and
run them against 505o. Kept up to date as work proceeds so a fresh session can
pick it up. Baseline version: **505c** (the release before 505o).

## Goal

1. Capture as much 505c behaviour as is practical in an automated, repeatable
   suite (`regress/`), lighter than `interop/` (no LinBPQ/XNet/TNN needed).
2. Run it against 505o; every difference is either a regression, a deliberate
   change, or noise. Record which.
3. Cover every problem reported on groups.io since Paula's 505o announcement
   (2026-10-10, https://groups.io/g/xrouter/topic/121690916).

## Reports on groups.io since the 505o announcement

| # | Reporter | Report | Msg | Test(s) | Status |
|---|---|---|---|---|---|
| G1 | Tom M0LTE | RHP bind reply malformed JSON | 4373 | interop test_06_rhp | known, issue #2, fixed upstream |
| G2 | Tom M0LTE | RHP listen on listening socket fails (deliberate since 505d) | 4373 | regress (rhp) | deliberate |
| G3 | Tom M0LTE | RHP send/sendto on listener reply without handle | 4373/4375 | interop test_06_rhp | known, issue #3 |
| G4 | Tom M0LTE | INPBCINTERVAL ignored | 4374/4378 | interop | known, issue #4 |
| G5 | Tom M0LTE | own node tt 0 | 4374 | interop | known, issue #5 |
| G6 | Tom M0LTE | NODES broadcasts on first port only | 4377 | interop | known, issue #6 |
| G7 | Danny PA2SNK | INP3 route via neighbour preferred over direct 1-hop quality 192 RF route; can't connect to that node any more | 4400/4401 | test_50_routing | written |
| G8 | Danny PA2SNK | Beacon digi (unproto via the node) no longer relayed | 4400 | test_20_digi | written |
| G9 | Danny PA2SNK | BBS: compressed forward ok, but message retrieval by number disconnects | 4400 | test_40_pms (read by number over AX.25 and telnet); compressed forwarding not covered | written |
| G10 | Danny PA2SNK | BBS connect text / prompt changed: only header and prompt | 4400 | test_40_pms greetings, test_55 BBS over L4 | written |
| G11 | Jean VE2PKT | AMPRNet (44/8) IP traffic not routed out the TUN interface; can't ping any 44 station; AXUDP/AXTCP fine | 4386-4397 | test_31_ip_gateway (node config/ip) | written |
| G12 | Danny Moss VK7HDM | no 32-bit stretch build | 4371 | n/a (packaging) | not testable |
| G13 | Danny PA2SNK | systemd service still starts 505c | 4383 | n/a (local setup) | not a bug |

## Plan / work items

- [x] W1 Feature inventory from the OARC wiki (commands, CFG directives, services): regress/INVENTORY.md
- [x] W2 Harness: XRouter container + Python AXUDP probe (raw AX.25 frames, minimal L2), telnet console helper (tests/conftest.py, ax25.py, xrconsole.py)
- [x] W3 Console command snapshot tests (505c golden vs 505o): test_10_console, golden/505c/console
- [x] W4 Digipeating tests (G8): test_20_digi
- [x] W5 IP routing tests: test_30_ip_ax25, test_31_ip_gateway (G11)
- [x] W6 Route selection: test_50_routing (G7), NET/ROM basics test_55_netrom
- [x] W7 BBS / PMS tests (G9, G10): test_40_pms
- [x] W8 HTTP / REST / RHP / AGW: test_60_services
- [ ] W9 Run 505c vs 505o, write FINDINGS, open GitHub issues
- [ ] W10 CI workflow

## Log

- 2026-10-13: read groups.io threads, created this file.
- 2026-10-13: harness boots 505c DUT + 505c neighbour, probes A/B/C hear them.
  Harness notes learned the hard way:
  * Sysop on telnet: PASSWORD.SYS entry + `@ <password>` in plain text.
  * The published image lacks ip/ifconfig, so TUN with IOADDR cannot come up;
    regress/image/Dockerfile adds iproute2, net-tools, tcpdump etc.
  * With a TUN (or Ethernet) port present, AXUDP and AXIP to non-localhost
    peers go through XRouter's own IP stack (MAN AXUDP-IFACE, AXIP-IFACE), and
    TCP services given one port number may not listen on Linux. Hence the IP
    gateway scenario (G11) needs its own node, config/ip.
  * Quick manual check: XRouter PING over TUN and AXIP transmit over TUN to a
    44.x partner behave the same on 505c and 505o (basic case). G11 needs
    more variants (receive path, AX.25 -> TUN forwarding, route forms).
- 2026-10-13: tests written for every area; calibrating on 505c (the suite
  must be green on 505c before its 505o results mean anything). Fixes from
  calibration: BCAST needs the destination in the receiving port's list too;
  CTEXT is only sent for alias connects by default (CTFLAGS 9).
