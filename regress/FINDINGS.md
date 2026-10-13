# Findings: 505o against 505c

These are the results of the regress suite. The baseline is 505c and the version under test is 505o, both x86-64 static builds. The neighbour XRouter is 505c unless stated otherwise. Every test passes on 505c, so each 505o failure below is a difference between the two versions. Each entry gives what was tested, what 505c does and what 505o does. Evidence comes from the probes' frame log (`out/<tag>/probes.txt`) and the console log (`out/<tag>/consoles.txt`).

## Summary

| | Finding | 505c | 505o | Issue |
|---|---|---|---|---|
| R1 | AGW `M` (send unproto) from a client that has not registered a callsign with `X` | sent | **dropped** | #11 |
| R2 | RHP bind reply malformed | ok | fails | #2 (already known, fixed upstream) |
| R3 | An FBB compressed (FA) message XRouter cannot decode hangs the whole node at 100% CPU, telnet dead | n/a | **hangs** | #12 |
| R4 | After a client sends an FBB SID, user commands get no answer at all | `>` then disconnect | **silence** | #14 |
| R5 | FBB ASCII forwarding *out* (`FB`) ends messages with `/EX`, not Ctrl-Z, so a real FBB partner never sees the end | n/a | **wrong** | #22 |
| F1 | MBL forwarding out puts a NUL byte before `/EX` | stray NUL | fixed | #23 |
| B1 | `R n` / `n` show an empty body for a forwarded message with no blank line after its `R:` lines | empty | empty, and now every FBB/compressed forwarded message | #13 |
| C1 | BBS SID advertises FBB and compressed forwarding | `[XR-505c-HM$]` | `[XR-505o-BFHM$]` | n/a (new feature) |
| C2 | A BBS session that sends an FBB SID becomes an FBB forwarding session | `>` prompt, then disconnects on `R n` | no prompt; `R n`, `n` and `L` are ignored silently; `FF` gives `FQ` and disconnect | see G9 |
| C3 | FBB ASCII forwarding (`FB` proposal, `FS +`, message, `FF`/`FQ`) | not supported (disconnects) | works; message stored | n/a |
| C4 | New console command `GO` ("Display/execute 'door' programs") | — | present | accepted change |
| C5 | STATS: `Mem blocks: Min/Cur/Max/Out`, `L4 Conns Tried/Made/Rcvd/Rej`, `S L3` adds `In Pkts Faulty` and `Brdcast Pkts Sent`, `S ?` lists `ARP` | — | present | accepted change |
| C6 | `N <call>` route table adds a `Last-Update` column | — | present | accepted change |
| P1 | A NODES broadcast with no entries (a lone node) is ignored: the sender gets no route | same | same | pre-existing |
| P2 | Scheduled NODES go out on the first port only | same | same | #6 (known) |

Reports from groups.io that the suite has not reproduced so far (see PROGRESS.md for the variants tried):

| | Report | What the suite shows |
|---|---|---|
| G7 | PA2SNK: INP3 route via a neighbour chosen over a direct 1-hop quality-192 route | With a direct neighbour at quality 192 and a 2-hop INP3 path to the same node through another XRouter, 505o uses the direct route and a connect goes direct, as on 505c. That held in every variant tried: direct neighbour NET/ROM-only or INP3; direct link slow (0.8 s) while the INP3 path is fast; route locked by the sysop at 192; neighbour XRouter 505c or 505o. Not tried: LinBPQ as the INP3 neighbour. Danny's `N JOURE` and `R` output would narrow it down |
| G8 | PA2SNK: beacon digi (unproto request) no longer relayed | UI and connected-mode digipeating via the node call, the alias, PORTALIAS2, WIDEn-n and TRACEn-n, BCAST of MAIL and FBB beacons, and `SEND` with digis all behave as on 505c. The one unproto path that changed is AGW `M` (R1) |
| G9 | PA2SNK: BBS read by number disconnects (tsthost, compressed forward) | **Likely explained by B1, R3 and R4.** Messages that arrive by FBB/compressed forwarding read as empty with `R n` (B1); undecodable compressed data hangs the node (R3); after an FBB SID user commands get no answer (R4). A plain user reading local mail works |
| G10 | PA2SNK: BBS connect text / prompt shows only header and prompt | A plain user gets the same greeting as on 505c apart from the SID. An FBB-SID client gets no prompt at all after its SID (C2) |
| G11 | VE2PKT: no 44-net traffic out of the TUN interface | With XRouter as an AMPRNet gateway on a TUN interface, 505o routes 44-net out of the tunnel with a gateway, without one and by default route, and also forwards between AX.25 users and 44-net both ways. AXIP to a 44.x partner works out and back through the tunnel. A TUN port with no IPADDRESS, a port address in 44-net, and a persistent tunnel all behave the same in 505c and 505o |

## R1. AGW unproto from an unregistered client is dropped

Issue: https://github.com/packethacking/xrouter-container/issues/11

An AGW client connected to `AGWPORT` sends `M` (port 0, from `PN0AGW`, to `BEACON`, PID F0, data). 505c transmits `PN0AGW>BEACON` on XRouter port 1. 505o transmits nothing. If the client first registers `PN0AGW` with `X` (reply `X`, data `01`), 505o transmits it. AGWPE does not require registration for unproto, and beacon and APRS programs often skip it. This could be what PA2SNK saw as "beacon digi (unproto request) is not relayed anymore". He has not said how his beacons are sent.

Tests: `test_60_services.py::test_agw_send_ui_unregistered` (505o fails), `test_agw_send_ui_registered` (passes on both).

## C1 to C3. The BBS now speaks FBB forwarding protocol

505o's BBS SID is `[XR-505o-BFHM$]`; 505c's was `[XR-505c-HM$]`. That matches PA2SNK's note that compressed forwarding now works.

The side effect: a client whose SID has `F` now gets FBB protocol, not the user command set. With `[TSTHOST-1.43-B1FHM$]` sent after the greeting (tsthost's own PMS forwards with FBB), 505o:

```
-> [TSTHOST-1.43-B1FHM$]
<- (nothing)
-> R 1
<- (nothing)
-> 1
<- (nothing)
-> L
<- (nothing)
-> FF
<- FQ, then disconnect
```

505c answered the SID with `>` (MBL/RLI forwarding) and disconnected at `R 1`. Neither behaviour is useful to a person who uses a terminal that sends its SID. Whether that is what PA2SNK means by "after asking for the msg nr by tsthost the bbs disconnects" depends on what tsthost sends. See R3, R4 and B1 below for what compressed forwarding turned up.

## R3. Undecodable compressed data hangs the node

Issue: https://github.com/packethacking/xrouter-container/issues/12

After `FS +` for an `FA` proposal, a partner sends the blocks with a correct checksum, but the data is not a B0 LZHUF stream XRouter can decode. In the cases tried this was a B1 stream with the 2-byte CRC in front, sent after B0 had been negotiated, or 512 junk bytes. XRouter stops answering and the process spins at 100% of a core; telnet is dead for as long as we watched (minutes). XRouter probably trusts the stream's 4-byte length field and decodes megabytes to gigabytes of nothing. B0 is negotiated correctly when the partner offers B1 (XRouter's SID has plain `B`), and valid B0 streams are stored correctly. Test: `test_41_fbb.py::test_fbb_bad_compressed_data_does_not_hang_node`.

## B1. Forwarded messages read as empty

Issue: https://github.com/packethacking/xrouter-container/issues/13

`R n` and a bare `n` (read without routing headers) skip everything up to the first blank line of a forwarded message. Forwarded FBB messages run straight from their `R:` lines into the body, so the reader sees only the header block. `RH n` shows everything, and the stored file is intact. 505c does the same for MBL-forwarded mail, so this is not new code. It is new exposure: on 505o, every message that arrives by the new FBB or compressed forwarding reads as empty. That is very likely PA2SNK's "msg retrieval does not work correctly". Tests: `test_read_forwarded_message_shows_body[ascii|compressed]`, `test_read_mbl_forwarded_message_shows_body`.

FBB ASCII forwarding into the 505o BBS works: proposal `FB P PN0FWD PN0DUT PN0DUT 4711_PN0FWD 40`, `F> <checksum>`, the BBS answers `FS +`, takes the message, sends `FF`, and answers our `FF` with `FQ`. The message is stored and listed.

## Forwarding out (reverse forwarding)

The throwaway BBS has a forwarding partner, PN0FWD (PMS/DISTRIB.SYS `P * PN0FWD PN0FWD` and `B * WW PN0FWD`; PMS/FWD.SYS `@PN0FWD F`). When the partner connects and sends `FF`, 505o proposes the queued personal mail as `FA` (with `B` in the partner's SID) or `FB` (without). Bulletins @WW are proposed as `FA B ... WW <category>`; categories are cut to 6 characters. The compressed data decodes correctly with our LinFBB-compatible codec, so LZHUF interoperates in both directions. The ASCII `FB` message, though, ends with `/EX` where FBB uses Ctrl-Z (R5, #22). MBL reverse forwarding (`F>`) works on both versions; 505c added a stray NUL before `/EX` (#23, fixed in 505o). XRouter forwards with RFC 822 style headers (Date, From, To, Subject, Message-ID) and a blank line after its `R:` line. That is why messages XRouter forwards itself read fine with `R n` (B1).

## C4 to C6. Console output changes accepted as deliberate

These are recorded in `golden/505o/console/`. Help lists gain `go`; STATS gains fields. In `N <call>`, the route table gains a `Last-Update` column, which the routing test's parser allows for.

## P1. Empty NODES broadcasts are ignored

On 505c and 505o alike, a NODES broadcast with no entries (only the sender's alias) creates no route to the sender. A node with nothing else to announce, or another XRouter with no applications, is therefore never learned from NODES. On a port other than XRouter's first, XRouter's own scheduled broadcasts don't arrive either (#6), so two such XRouters never find each other. This is not a 505o regression. It is noted here because it shaped the test set-up: the neighbour has an application.

## Other observations

- A 505o neighbour passes a node it learned by INP3 on as INP3 only: the DUT's route via it shows quality 0. A 505c neighbour also sends it in NODES (quality 156 here).
- XRouter's WA8DED host-mode emulation (DEDHOST) works for applications on both versions: a connect on channel 1 enters the node shell, and node commands and onward connects work. Channel-0 unproto from the host does not transmit on either version (`test_70_dedhost`). This may be a set-up detail we have not found.

## Harness notes

- The published image lacks `ip`/`ifconfig`, so a TUN interface with `IOADDR` never comes up: XRouter shells out to them. `regress/image/Dockerfile` adds them for the tests. Worth fixing in the image itself, or documenting.
- When any TUN (or Ethernet) port exists, AXUDP and AXIP to non-localhost peers use XRouter's own IP stack (MAN AXUDP-IFACE, AXIP-IFACE). The same applies to TCP services given a single port number, which then do not listen on Linux. This is documented behaviour in both versions, but it can catch out a sysop who adds a TUN interface to a working AXUDP node.
