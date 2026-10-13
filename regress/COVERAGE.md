# Test coverage assessment

How much of XRouter's behaviour `regress/` (with `interop/` alongside) is likely to catch, judged against the feature inventory (`INVENTORY.md`). XRouter is closed source, so this measures behaviour, not code. "Exercised" means a test drives the feature and checks the result. "Shape" means only the console output's form is compared with 505c's, with numbers normalised.

## Summary

| Area | Coverage | Notes |
|---|---|---|
| User console commands | **31 of 51** exercised, mostly shape only | The everyday ones (P, N, R, U, L, MH, I, V, S, C, B, PMS/BBS, CHAT, SEND, PING, ARP, IPR) and help for 19 of them. Missing: CQ, CX, LISTEN, WATCH, ECHO, NPING, NRR, NTRACERT, TRACERT, HOST, TELNET, TTYLINK, NFTP, YELL, AMSG, APRS, AXTEST, G* |
| Sysop console commands | **about 35 of 104**, read-only, shape only | Port and global parameter reads, IFACE L, IP ROUTE LIST, ARP L, STATS, MAN, PEERS. None of the *setting* forms are checked (set then read back); nor SAVENODES/LOADNODES, KILL, CMD ADD, ACL/NAT edits, MON/MPORT tracing, SHELL/DOS, RESTART |
| XROUTER.CFG | **low (~15% of keywords)** | One DUT config, mostly defaults. Exercised: QUALITY, DIGIFLAG, BCAST, PORTALIAS2, APPL blocks, PMSTYPE 4, CTFLAGS default, TUN (IOADDR), AXIP, AXUDP, DEDHOST/ASYNC, TELNET/HTTP/RHP/AGW ports. Not: KISS/serial TNCs, AXTCP, AGW/TCP KISS interfaces (interop has TCP KISS), MHEARD/MHFLAGS settings, EXCLUDE, MINQUAL/MAXTT/MAXHOPS, PIPE, IDINTERVAL/IDPATH, VALIDCALLS, PMSTYPE 1–3, CHATLINKS, MQTT, IGATE |
| AX.25 L2 | **basic** | Connect, I-frames, RR, disconnect, UI, digipeating (UI, SABM, aliases, WIDEn-n, TRACEn-n). Not: mod-128 (CX), REJ/SREJ recovery, retries and link failure, RNR/busy, window limits, PACLEN segmentation of long output, FRMR, XID |
| NET/ROM / INP3 | **good with interop** | regress: NODES out and in, empty-NODES behaviour, L4 circuits both ways, BBS and service 2 over L4, route choice in 7 variants (incl. LinBPQ). interop: INP3 in depth against LinBPQ, XNet, TNN, TheNet and another XRouter, incl. withdrawal. Not: L4 windowing/choke/retries, NRR/NPING/NTRACERT, obsolescence and MINQUAL filtering, SAVENODES persistence across restart |
| IP | **moderate** | ICMP over AX.25 both ways, ARP, forwarding, TUN gateway (route with/without gateway, default, kernel mode), AX.25↔44-net, AXIP through the tunnel. Not: IP over NET/ROM (mode n) or VC (v), ENCAP/IPIP/IPUDP tunnels, NAT, RIP44, DNS, DHCP, TCP over XRouter's own stack (e.g. telnet to the 44 address), fragmentation, TRACERT |
| BBS / PMS | **good for the paths in the reports** | User greeting, SP/SB, L, R n, bare n, K, B over telnet, AX.25 and L4. FBB forwarding in (ASCII, compressed B0) and out (FA, FB, MBL, bulletins), bad compressed data, FBB SID handling, REST mail. Not: the BBS *calling out* (FWD.SYS connect scripts C/W/S, polling), duplicate rejection (`FS -`), B1 resume, multi-block large messages, expiry/housekeeping, HOLD/REJECT/BADWORDS, white pages, PMSTYPE 1–3 |
| Chat | **basic** | Enter, register, join, two users see each other. Not: chat links between nodes, BPQChat gateway, most /commands |
| HTTP / REST / RHP / AGW | **moderate** | HTTP page status, /exec, 404; REST nodes, routes, circuits, mail GET/POST, 415; RHP socket/open/bind/listen/close/status/bad type (plus interop's RHP checks); AGW version, ports, unproto. Not: HTTP auth/ban/proxy, REST wall/blog/wx, RHP data transfer on a live connection, AGW connected mode and monitoring, MQTT, APRS server, telnet proxy, FTP, FINGER, RLOGIN, SOCKS |
| Platforms | **amd64 static only** | Most XRouter users run arm64/armv7 builds on a Pi. The suite does not run those builds (it could under QEMU, slowly) |
| Robustness | **minimal** | One hang found by malformed input (#12). Not: malformed frames in general (AX.25, NET/ROM, RIF, IP), long runs/memory, restart and state persistence, config errors |

## What this means

- **The reported problems are well covered.** Every groups.io report since 505o has targeted tests. Where we could not reproduce one (G7, G11), the variants tried are recorded.
- **Commonly used read-only behaviour is reasonably covered,** but mostly by output shape. A change in what a command does, as opposed to how its output looks, would often get through. The route-choice, BBS and IP tests are the exceptions: they check behaviour.
- **Changes made through commands, and anything stateful over time, are barely covered:** setting parameters, persistence across restart, timers and retries, link failure on L2.
- Rough estimate: of the features a typical node sysop uses day to day, about half are exercised in some form, and perhaps a fifth are checked in depth.

## Gaps worth closing next (by likely value)

1. **AX.25 L2 robustness:** retries, link failure, REJ, RNR, window, long-output segmentation. Every service depends on it, and the probe's L2 client can be extended to misbehave on purpose.
2. **arm64 / armv7 builds**, run under QEMU: most sysops run XRouter on Raspberry Pis, so a Pi-only regression would get past the suite today.
3. **The BBS calling out** with FWD.SYS connect scripts and polling, plus duplicate rejection and large multi-block messages: the forwarding path PA2SNK uses.
4. **Parameter-setting commands** (set, read back, survive restart where applicable), and SAVENODES/LOADNODES.
5. **IP over NET/ROM and ENCAP/IPIP**, plus TCP services over XRouter's own stack: the remaining AMPRNet paths.
6. **Fuzz-style malformed input** on each protocol entry point (AX.25, NET/ROM, RIF, NODES, IP, RHP JSON, AGW, FBB blocks). #12 suggests input validation is a real risk area.
