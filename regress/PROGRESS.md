# 505o regression hunt: plan and progress

Tracking for the work to record XRouter's pre-505o behaviour in tests and run
them against 505o. Baseline version: **505c** (the release before 505o).

## Resume here

This file and GitHub issue #10 (with its sub-issues) are the durable record;
the session that wrote them may be gone. To pick the work up:

1. Read this section, then `README.md` (how the suite works and runs) and
   `FINDINGS.md` (what it found).
2. **The work queue is the open sub-issues of #10**: each has a checklist and
   says when it is done. Pick one, tick its boxes as you go, close it with a
   comment saying what was done. Do not keep a second to-do list here.
3. Run `regress/run.sh 505c 505o` (Docker, Python 3 + pytest, /dev/net/tun;
   about 45 min). Expected (2026-10-14): 505c 237 passed, 9 skipped,
   4 xfailed; 505o 239 passed, 11 xfailed. Anything else is new information: a flaky test, a
   harness break, or (on a new XRouter version) a behaviour change.
4. After each meaningful step: update the tables below and the Log, commit,
   push. Bugs go in their own issue (XRouter bugs: label `xrouter-bug`) and
   in `known-issues.toml`; findings go in `FINDINGS.md`. Maintainer
   decision: XRouter bug reports stay as GitHub issues here; do not post
   them to groups.io (#20). Every XRouter bug issue leads with a verified
   stand-alone reproduction from `repro/` (published binary, no Docker,
   no root): add one to `repro/repro.py` for each new bug and paste the
   real output into the issue.
6. Check groups.io (group `xrouter`) for new reports at the start of each
   session; add them to the reports table below.
5. A new XRouter version: run the suite on it; triage every failure as
   regression (issue + known-issues entry), deliberate change (accepted
   console output: `XRR_ACCEPT=<id>,... regress/run.sh <ver> -- -k console`),
   or test noise (fix the test).

### Open work (sub-issues of #10)

| Issue | What | Blocked on |
|---|---|---|
| #16 | G11 TUN/44-net: rebuild with the reporter's config | **parked** until VE2PKT volunteers his config (maintainer decision) |
| #24 | Coverage: AX.25 L2 robustness | - |
| #25 | Coverage: arm64 / armv7 builds under QEMU | - |
| #26 | Coverage: BBS calling out, duplicates, large messages | - |
| #27 | Coverage: sysop set-and-read-back, state across restart | - |
| #28 | Coverage: IP over NET/ROM/VC, ENCAP/IPIP, TCP over XRouter's stack | - |
| #29 | Coverage: malformed input on every protocol entry point | - |

Coverage and the gaps worth closing next: `COVERAGE.md`.

### Bugs found (issues)

| Issue | Bug | Versions |
|---|---|---|
| #11 | AGW unproto from an unregistered client is dropped | 505n, 505o |
| #12 | Undecodable compressed FBB message hangs the whole node | 505n, 505o |
| #13 | `R n` / `n` empty body for forwarded mail | all (newly exposed by 505o's FBB forwarding) |
| #14 | No answer to user commands after an FBB SID | 505n, 505o |
| #22 | FBB ASCII forwarding out ends with /EX, not Ctrl-Z | 505n, 505o |
| #23 | MBL forwarding out: stray NUL before /EX | 505c (fixed in 505n and 505o) |
| #2, #6 | Known from interop: RHP bind reply; NODES only on first port | |

### State of the suite (last full runs, 2026-10-14)

- 505c: 237 passed, 9 skipped (FBB tests; 505c has no F in its SID),
  4 xfailed (#13, #23, DEDHOST channel-0 unproto).
- 505o: 239 passed, 11 xfailed (#2, #6, #11, #12 x2, #13 x3, #14, #22,
  DEDHOST). No unexpected failures. CI (regress workflow) agrees.

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
| G7 | Danny PA2SNK | INP3 route via neighbour preferred over direct 1-hop quality 192 RF route; can't connect to that node any more | 4400/4401 | test_50_routing, test_51_routing_slow_rf | not reproduced: 505o prefers the direct route in every variant: direct neighbour NET/ROM-only or INP3, slow (0.8 s) direct link, sysop-locked q192 route, neighbour XRouter 505c or 505o (505o neighbour sends the node INP3-only, qty 0). LinBPQ neighbour and link failure/recovery variants also fine (test_52, #15 closed) |
| G8 | Danny PA2SNK | Beacon digi (unproto via the node) no longer relayed | 4400 | test_20_digi, test_60 AGW | digipeating and BCAST same as 505c; FOUND: AGW 'M' unproto from an unregistered client is not sent on 505o (505c sends it). Possibly Danny's case. |
| G9 | Danny PA2SNK | BBS: compressed forward ok, but message retrieval by number disconnects | 4400 | test_40_pms, test_41_fbb | FOUND: R n / n show an EMPTY body for every forwarded message without a blank line after the R: lines (#13; pre-existing for MBL forwarding, but now hits all FBB/compressed forwarded mail). FOUND: undecodable compressed data hangs the whole node (#12). FOUND: after an FBB SID user commands get no answer (#14). Valid B0 compressed and ASCII FBB forwarding work |
| G10 | Danny PA2SNK | BBS connect text / prompt changed: only header and prompt | 4400 | test_40_pms greetings, test_55 BBS over L4 | not reproduced for plain users (greeting identical apart from SID); likely the FBB-SID path above |
| G11 | Jean VE2PKT | AMPRNet (44/8) IP traffic not routed out the TUN interface; can't ping any 44 station; AXUDP/AXTCP fine | 4386-4397 | test_31_ip_gateway (node config/ip) | not reproduced: all 13 gateway tests pass on 505o; variants tried by hand (TUN port w/o IPADDRESS, port IP = 44 address, persistent tunnel) identical on 505c/505o. Further work: #16 |
| G12 | Paula (author) | 505n and 505o: NetRom security change; in some circumstances XRouter tears down an L4 circuit from a BPQ node on its first L4 INFO frame. Versions before 505n and after 505o not affected | 4410 | interop test_04_l4 | not reproduced: interop L4 tests in both directions (INFO from LinBPQ included) pass on 505n and 505o; the triggering circumstances are not stated |
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
- [x] W9 Run 505c vs 505o, write FINDINGS, open GitHub issues (#10-#14)
- [x] W10 CI workflow (.github/workflows/regress.yml; first run: #18)
- [ ] W11 onwards: the open sub-issues of #10 (table at the top)

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
- 2026-10-13: FBB work. LZHUF codec (tests/lzhuf.py, byte-exact with LinFBB)
  by a subagent. Found #12, #13, #14. G7 slow-RF variants: no difference.
  Chat and telnet access tests added (test_45). G11 variants by hand: none
  differ between 505c and 505o.
- 2026-10-13: full-suite runs: 505c 223 pass / 4 flaky, 505o 225 pass / 9 xfail /
  6 (flaky + DEDHOST uncalibrated). Fixed flakiness (multi-frame NODES,
  state-dependent console tables), DEDHOST on a persistent pty bridge. G7 with
  505o neighbour and locked-route variants: not reproduced.
- 2026-10-13: final full runs: 505c 233 passed, 6 skipped (FBB tests, no F in
  SID), 3 xfailed (pre-existing #13, DEDHOST unproto); 505o 232 passed,
  10 xfailed (#2, #6, #11, #12, #13, #14, DEDHOST unproto), no unexpected
  failures.
- 2026-10-13: tracking reorganised for resumability: open work moved into
  sub-issues #15-#21 of #10; this file now starts with "Resume here".
- 2026-10-14: groups.io follow-ups: 4404 VE2PKT still no 44.x on 505o, asks
  about 505m; 4405 PA2SNK nothing new; 4406 ZL2BAU 505o fine for 44-net,
  AXIP, AXUDP. Decisions: #16 parked, #19 done (image now has iproute2 and
  net-tools; build-and-publish rebuilds all versions), #20 closed (reports
  stay as GitHub issues), #18 command posted for the maintainer.
- 2026-10-14: #21 done (regress/check_known_issues.py, in CI and at collection;
  interop's checker now uses the REST API). #17 done: reverse forwarding
  tests (FA compressed, FB ASCII, MBL, bulletins); found #22, recorded #23.
- 2026-10-14: #15 done: test_52_routing_bpq (LinBPQ as INP3 neighbour; the
  probe's L2 now answers XID with FRMR so v2.2 callers fall back to SABM);
  direct link failure and recovery. G7 still not reproduced. COVERAGE.md
  written.
- 2026-10-14: first CI run (automatic after the #19 image publish) matches
  local results: 505c green, 505o 232 passed / 10 xfailed. #18 closed.
  Coverage gaps filed as #24-#29.
- 2026-10-14: full runs with #15/#17 additions: all green against known
  issues (after fixing the DEDHOST fixture for the BBS config's PMS/ subdir).
- 2026-10-14: repro/ kit: start-node.sh (any published binary, plain
  directory) + repro.py (stdlib only) for #11 #12 #13 #14 #22 #23; verified
  on 505c and 505o as a non-root user and from a fresh clone; every bug
  issue rewritten to lead with those steps and the real output.
- 2026-10-14: #11-#14, #22 reported to the author by private email
  (label `reported`; #2-#6 went to the xrouter group on 2026-10-11; #7 not
  yet). New upstream build found:
  `xrlin64v505n-static` (groups.io files, uploaded 2026-10-13 after 505o,
  SID `[XR-505n-BFHM$]`; not yet in versions.json). Repros and interop on
  505n: same as 505o except #2 (bind reply valid) and #23 (clean). #3
  also on 505n (known-issues `from` moved to 505n, likewise #11 #12 #14
  #22). repro/ now covers #2 #3 #6 too. All open issues reviewed and
  updated with 505n results.
- 2026-10-14: repro/ adds #4, #5, #7 (fake INP3 neighbours over AXUDP,
  stdlib). 505n/505o: all three present. 505c: #4 and #5 present (no RIF
  at link set-up; first full update ~600 s after start-up); #7 not
  reproduced (505c sends no change RIFs there, only full updates). Every
  XRouter bug issue now leads with a verified repro.py run.
- 2026-10-14: groups.io 4407-4410 "Intermediate versions Available": Paula
  uploaded intermediate builds 505d, 505h, 505i, 505k, 505l, 505m (x86-64
  static; most 32-bit and Pi32 too) to bisect 505c->505o regressions. She
  says: RHP broke in 505o (our #3 is already on 505n); INP3 rework began in
  505d and settled in 505m; ageing reinstated in 505m; new G12 (L4 INFO
  from BPQ tears down circuit, 505n/505o only); TUN (#16), Danny's route
  choice (G7) and BBS (G9/G10) under investigation. Next: run repro/ on
  each intermediate build to find where each bug came in.
- 2026-10-14: upstream check (fired early) ingested 505d-505n amd64 and the
  arm builds, plus 505p armv7 (newest version; latest_armv7 and latest now
  505p, amd64/arm64 stay 505o). Repros on the intermediates: #3 #11 #12
  #14 #22 first in 505d, #23 fixed in 505d, #7 first in 505m (505k/505l
  relay nothing). Interop on 505l fails exactly the #8/#9 tests: both fixed
  in 505m, not 505o. 505p (armv7 under qemu-arm): #2 #3 #5 fixed (closed,
  fixed_in 505p); #4 #6 #7 #11 #12 #13 #14 #22 still present.
- 2026-10-14: interop on 505p (armv7 binary under qemu-arm inside the amd64
  505o image, tagged 505p locally; peers LinBPQ, TheNet, 505o): #8/#9 all
  22 runnable tests pass; #4 #6 #7 xfail as expected. L4 V checks now accept
  the "XrPi" banner (69ca4aa). TheNet tests flaky under emulation (a
  different one failed in each of three runs, each passed at least once);
  not recorded as a known issue. Bug matrix artifact:
  https://claude.ai/artifact/SvgMibKE5mjqHMWooqfmwc
- 2026-10-15: 505p x86-64 uploaded 2026-10-14 (ingested by the upstream
  check, latest_amd64 now 505p). Native repros + interop: #4 FIXED (full
  updates every ~128 s; armv7 505p from 12 Oct still had it), closed with
  fixed_in 505p. Otherwise same as armv7 505p: #2 #3 #5 #8 #9 #23 fixed;
  #6 #7 #11 #12 #13 #14 #22 present. TheNet interop tests all pass natively,
  so the earlier failures were qemu timing.
- 2026-10-15: CI on 505p: regress green (240 passed, 10 xfailed: #6 #11
  #12 #13 #14 #22 + dedhost; console output unchanged against goldens).
  Interop red only on #4's four strict XPASSes (run predates the fixed_in
  commit 6cbe659); 505m/505n/505o green. With XNet/TNN present, 505p passed
  seven non-strict #7 alias checks; repro.py 7 still shows #7, so it stays
  open. Noted on #2 that a fixed image (:505p) is on GHCR (DAPPS waits on it).
