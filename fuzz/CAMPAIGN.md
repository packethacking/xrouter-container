# XRouter fuzzing campaign — May 2026

Long-running multi-surface fuzzing campaign against `xrouter` version
`505c-amd64`. The aim was to broaden the original `fuzz/FINDINGS.md`
single-surface AXUDP fuzz into a comprehensive look at every parser
the daemon exposes, then triage each crash to a stable bug signature
and a fixable root cause.

## Fuzzers built

All Python 3 stdlib only; each is in `fuzz/`.

| Fuzzer                    | Surface                                    |
|---------------------------|--------------------------------------------|
| `axudp-fuzz.py`           | AX.25 / NetRom over UDP (UDPLOCAL)         |
| `agw-fuzz.py`             | AGWPE TCP protocol (AGWPORT, default 8000) |
| `http-fuzz.py`            | HTTP admin/API (HTTPPORT)                  |
| `mqtt-fuzz.py`            | MQTT broker + `xrouter/put/...` topics    |
| `aprs-fuzz.py`            | APRS-IS server (APRSPORT, default 1448)    |
| `finger-fuzz.py`          | Finger (FINGERPORT, default 79)            |
| `netrom-circuit-fuzz.py`  | NetRom L4 stream (SABM + L4 segments)      |
| `kiss-fuzz.py`            | KISS framing over UDP (NB: needs TYPE=UDP PROTOCOL=KISS port; current xrouter rejects that combo with a `Missing COM` config error, so this fuzzer is built but unable to launch without a target-side fix) |

Supporting tooling:

- `xrouter-runner.sh` — launches a dedicated instance with named ports
- `restart-target.sh` — kills + relaunches an instance, sweeps cores
- `common.py` — `TargetController` shared by all fuzzers (health probe,
  restart, core collection, triage, JSONL findings log)
- `triage.py` — dedup signature from `(signal, RIP, insn)`
- `sweep-triage.py` — walk every instance's cores, produce summary
- `run-all.sh` — start every fuzzer in parallel, each against its own
  xrouter instance on a distinct port set

The whole stack runs against the bare static binary extracted from
the container (`docker create --name x ghcr.io/...:505c-amd64 ; docker cp x:/usr/local/bin/xrouter ./`)
rather than re-running the container per crash. Restart cost dropped
from ~5s to ~1s, which is what made bisection and parallel campaigns
practical.

## Findings

Four unique bug signatures so far (post-dedup). Each links to a
detailed per-bug writeup with disassembly, reproducer, and fix
suggestion.

| Signature        | Signal   | RIP        | Where reached from                                 | Severity         |
|------------------|----------|------------|---------------------------------------------------|------------------|
| [`c0338d880e86`](bugs/c0338d880e86.md) | SIGSEGV  | `0x41222f` | AXUDP, AGW, HTTP, NetRom, Finger              | CRITICAL — pre-auth, single packet, every published version, every arch |
| [`e6ee13e65a37`](bugs/e6ee13e65a37.md) | SIGABRT  | `0x63ac9c` | HTTP, AXUDP, NetRom                            | HIGH — **stack buffer overflow** caught by canary; without canary this would be RCE |
| [`a526a4b04337`](bugs/a526a4b04337.md) | SIGSEGV  | `0x4063e2` | AXUDP                                          | MEDIUM-HIGH — NULL-pointer deref in APRS-extension formatter |
| [`c7bfce022cac`](bugs/c7bfce022cac.md) | SIGSEGV  | `0x493feb` | HTTP                                           | MEDIUM-HIGH — NULL-pointer deref reached via conflicting `Transfer-Encoding` + `Content-Length` headers |

### Coverage gap that matters

`c0338d880e86` was originally believed to be a PID 0xCD (ARP-over-AX.25)
parser bug. The multi-surface fuzzers prove it is reachable through
**five** distinct entry parsers, all hitting the same RIP, with the
same wild-pointer (`RAX = 0x992f80` consistently across runs). The
root cause is a corrupted callsign / record-table entry that something
upstream is writing badly, not a single parser doing arithmetic wrong.
Whoever fixes it should be looking for the *writer* of `0x992f80`, not
just adding bounds checks at the read sites.

`e6ee13e65a37` was originally believed to be opaque (SIGABRT inside
libc `raise()`, no symbols, no bt). A gdb-attached run with the
deterministic seed `127256512` produced a backtrace where eight stack
frames above the abort site are `0x4141414141414141` — i.e. the
attacker-supplied `Authorization: Basic AAAA…` header's `A` bytes had
overwritten the saved frame pointer, return address, and several
slots beyond. The vulnerable function is at `0x47151e`; its sole
caller is `0x47c2ee`, itself called from three HTTP dispatcher sites.

## Operating notes

- All instances run as `root` because the demo XROUTER.CFG sets up
  low ports (HTTP, FTP, etc.); cores land in `/work/xr/cores/` per the
  kernel `core_pattern`, then `restart-target.sh` sweeps them into
  `/work/xr/run-<inst>/cores/`.
- Each fuzzer maintains a `findings.jsonl` and per-signature
  artefacts in `bugs/<sig>/{core,trigger.bin,first.json}` (or
  `triage.json` for cores discovered post-hoc by `sweep-triage.py`).
- `axudp-fuzz.py` predates the shared `TargetController` and uses its
  own `--restart-cmd` mechanism; its crashes are picked up by
  `sweep-triage.py` rather than reported live with `[!] NEW BUG`.

## How to reproduce the campaign

```sh
# Extract the binary out of the published image
docker create --name x ghcr.io/packethacking/xrouter:505c-amd64
docker cp x:/usr/local/bin/xrouter   /work/xr/xrouter
docker cp x:/opt/xrouter/skel/.       /work/xr/skel/
docker rm x
chmod +x /work/xr/xrouter

# Enable core dumps
ulimit -c unlimited
sysctl -w kernel.core_pattern="/work/xr/cores/core.%p"
mkdir -p /work/xr/cores

# Run the full multi-fuzzer campaign for 45 minutes
fuzz/run-all.sh 2700

# Then triage and summarise
python3 fuzz/sweep-triage.py
```

The campaign uses ports `18200..18244` (TCP, per-instance HTTP) and
`20200..20240` (UDP, per-instance AXUDP).
