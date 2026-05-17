#!/usr/bin/env python3
"""agw-fuzz.py -- generation + mutation fuzzer for XRouter's AGWPE
emulator (TCP port AGWPORT, default 8000).

Wire format (per the AGW Packet Engine API doc, which xrouter emulates):

    36-byte header: port:u32 LE  | datakind:u8  | reserved:u8 |
                    pid:u8       | reserved:u8  |
                    callfrom:10  | callto:10    |
                    datalen:u32 LE | user:u32 LE
    payload      : datalen bytes (semantics depend on datakind)

Common frame kinds we send:
    'G'  ask port info          (no payload)
    'g'  ask port capabilities  (no payload)
    'X'  register callsign      (no payload, callfrom = the call)
    'x'  unregister callsign
    'k'  send raw KISS-style ax25 frame on a port (payload = ax25)
    'C'  ask for connect        (payload depends)
    'D'  send connected data
    'M'  send UI frame          (payload = ax25 info field)
    'V'  send via digipeaters
    'P'  application login      (payload = "USER\\0PASS")
    'p'  application logout
    'M'  same as above (uppercase variant)
    'y'  ask outstanding frames on a connection

Strategy mirrors the AXUDP fuzzer: a small seed corpus of well-formed
frames + a mutator that bit-flips / replaces bytes / inserts magic
values / extends or truncates the payload. Inputs are streamed over the
same long-lived TCP socket; when the daemon dies the socket goes EOF
and the harness restarts the target.
"""

from __future__ import annotations

import argparse
import random
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import TargetController, now  # noqa: E402

# Datakinds we know about. The lowercase / uppercase pairs are both
# valid AGWPE verbs.
DATAKINDS = [
    b"G", b"g", b"R", b"X", b"x", b"M", b"V", b"C", b"D", b"d",
    b"K", b"k", b"y", b"Y", b"P", b"p", b"H", b"m", b"T", b"S",
    b"v", b"V", b"@",  # @-something undocumented; let's poke it
]

PADDED_CALL = b"FUZZER-7\x00\x00"        # 10 bytes, mixed case
PADDED_CALL2 = b"G9DUM-1 \x00\x00"


def header(port: int, kind: bytes, pid: int, callfrom: bytes,
           callto: bytes, payload: bytes, user: int = 0) -> bytes:
    """Build a single 36-byte AGWPE header + payload."""
    if len(callfrom) < 10:
        callfrom = callfrom.ljust(10, b"\x00")
    if len(callto) < 10:
        callto = callto.ljust(10, b"\x00")
    return (
        struct.pack("<I", port & 0xFFFFFFFF) +
        kind[:1] + b"\x00" +              # datakind + reserved
        bytes([pid & 0xFF]) + b"\x00" +   # pid + reserved
        callfrom[:10] + callto[:10] +
        struct.pack("<I", len(payload) & 0xFFFFFFFF) +
        struct.pack("<I", user & 0xFFFFFFFF) +
        payload
    )


def build_seeds() -> list[tuple[str, bytes]]:
    seeds: list[tuple[str, bytes]] = []
    seeds.append(("ask_port_info", header(0, b"G", 0, b"", b"", b"")))
    seeds.append(("ask_caps",      header(0, b"g", 0, b"", b"", b"")))
    seeds.append(("register",      header(0, b"X", 0, PADDED_CALL, b"", b"")))
    seeds.append(("unregister",    header(0, b"x", 0, PADDED_CALL, b"", b"")))
    seeds.append(("ask_outstanding", header(0, b"y", 0, PADDED_CALL, b"", b"")))
    seeds.append(("monitor_on",    header(0, b"m", 0, b"", b"", b"")))
    seeds.append(("send_ui_short", header(0, b"M", 0xF0, PADDED_CALL, PADDED_CALL2, b"hello")))
    seeds.append(("send_ui_long",  header(0, b"M", 0xF0, PADDED_CALL, PADDED_CALL2, b"A" * 250)))
    seeds.append(("send_kiss_min", header(0, b"k", 0, PADDED_CALL, PADDED_CALL2, b"\x00" * 16)))
    seeds.append(("connect_req",   header(0, b"C", 0, PADDED_CALL, PADDED_CALL2, b"")))
    seeds.append(("disconnect",    header(0, b"d", 0, PADDED_CALL, PADDED_CALL2, b"")))
    seeds.append(("send_data",     header(0, b"D", 0, PADDED_CALL, PADDED_CALL2, b"data payload")))
    seeds.append(("via_digis",     header(0, b"V", 0xF0, PADDED_CALL, PADDED_CALL2,
                                          b"\x01" + PADDED_CALL + b"hello")))
    seeds.append(("login",         header(0, b"P", 0, b"", b"", b"user\x00pass")))
    seeds.append(("logout",        header(0, b"p", 0, b"", b"", b"")))

    # Aimed at known parser sore spots
    seeds.append(("huge_datalen",  bytes.fromhex("00000000") + b"M\x00\xf0\x00" +
                                   PADDED_CALL + PADDED_CALL2 +
                                   struct.pack("<I", 0xFFFFFF00) +  # huge claimed length
                                   struct.pack("<I", 0) +
                                   b"x"))  # body shorter than claimed
    seeds.append(("negative_pid",  header(0, b"M", 0xFF, PADDED_CALL, PADDED_CALL2, b"x")))
    seeds.append(("port_uint_max", header(0xFFFFFFFF, b"G", 0, b"", b"", b"")))
    seeds.append(("kind_null",     header(0, b"\x00", 0, b"", b"", b"")))
    seeds.append(("empty_payload", b""))
    seeds.append(("short_header_5", b"\x00\x00\x00\x00G"))     # truncated header
    seeds.append(("short_header_35", header(0, b"G", 0, b"", b"", b"")[:35]))
    return seeds


MAGIC = [0, 1, 0x7F, 0x80, 0xFF, 0xCF, 0xF0, 0xCC, 0xCD]


def mutate(buf: bytes, rng: random.Random) -> bytes:
    a = bytearray(buf)
    rounds = rng.randint(1, 5)
    for _ in range(rounds):
        if not a:
            a = bytearray(rng.randint(0, 32))
            continue
        op = rng.randrange(7)
        if op == 0:                                    # bit flip
            i = rng.randrange(len(a)); a[i] ^= 1 << rng.randrange(8)
        elif op == 1:                                  # byte replace
            i = rng.randrange(len(a)); a[i] = rng.randrange(256)
        elif op == 2:                                  # magic value
            i = rng.randrange(len(a)); a[i] = rng.choice(MAGIC) & 0xFF
        elif op == 3 and len(a) < 4096:                # insert
            n = rng.randint(1, 8); pos = rng.randrange(len(a) + 1)
            a[pos:pos] = bytes(rng.randrange(256) for _ in range(n))
        elif op == 4 and len(a) > 1:                   # delete
            n = rng.randint(1, min(8, len(a) - 1))
            pos = rng.randrange(len(a) - n + 1); del a[pos:pos + n]
        elif op == 5:                                  # chunk randomize
            n = rng.randint(1, min(16, len(a)))
            pos = rng.randrange(len(a) - n + 1)
            for k in range(n): a[pos + k] = rng.randrange(256)
        else:                                          # bash the u32 len field
            if len(a) >= 32:
                bogus = rng.choice([0, 1, 0xFFFFFF, 0x7FFFFFFF, 0xFFFFFFFF])
                a[28:32] = struct.pack("<I", bogus)
    return bytes(a)


def random_garbage(rng: random.Random) -> bytes:
    weights = [(0, 8, 20), (8, 36, 35), (36, 200, 25),
               (200, 1024, 15), (1024, 8192, 5)]
    total = sum(w for *_, w in weights)
    r = rng.randint(1, total); acc = 0; lo, hi = 0, 8
    for a, b, w in weights:
        acc += w
        if r <= acc:
            lo, hi = a, b; break
    n = rng.randint(lo, max(lo, hi - 1))
    return bytes(rng.randrange(256) for _ in range(n))


def fuzz(target: TargetController, port: int, *, seed: int,
         duration: int, max_frames: int, probe_every: int,
         settle: float, mutation_bias: float) -> int:
    rng = random.Random(seed)
    seeds = build_seeds()
    print(f"[+] agw target=127.0.0.1:{port}  health={target.health_url}"
          f"  seed={seed}  seeds={len(seeds)}")

    if not target.health_ok():
        print("[!] target not healthy before fuzzing", file=sys.stderr)
        return 2

    sock = target.tcp_connect(port)
    sent = 0
    crashes = 0
    started = now()
    deadline = started + duration if duration else None
    last_status = started
    last_batch: list[bytes] = []

    while True:
        if deadline and now() >= deadline:
            break
        if max_frames and sent >= max_frames:
            break

        if rng.random() < mutation_bias:
            label, base = rng.choice(seeds)
            frame = mutate(base, rng)
        else:
            label, frame = "random", random_garbage(rng)

        try:
            sock.sendall(frame)
        except (BrokenPipeError, ConnectionResetError, OSError):
            sock = None
        sent += 1
        last_batch.append(frame)

        # Periodically: liveness probe
        if sent % probe_every == 0:
            time.sleep(settle)
            if not target.health_ok():
                crashes += 1
                trigger = last_batch[-1] if last_batch else None
                # restart and triage
                target.restart()
                # Triage any new cores
                for core in target.collect_cores():
                    info = target.triage(core)
                    if info and target.record_crash(info, trigger=trigger,
                                                    extra={"fuzzer": "agw",
                                                           "sent": sent}):
                        print(f"[!] NEW BUG {info.signature}  rip={info.rip}  "
                              f"insn={info.insn}  (sent={sent})")
                    elif info:
                        print(f"[ ] dup  {info.signature}  (sent={sent})")
                last_batch.clear()
                try:
                    sock = target.tcp_connect(port)
                except (ConnectionRefusedError, OSError):
                    print("[!] could not reconnect to AGW port; aborting")
                    return 3
            else:
                last_batch.clear()

        # Reconnect if socket died from a write error not yet detected
        if sock is None:
            try:
                sock = target.tcp_connect(port)
            except (ConnectionRefusedError, OSError):
                # Possibly daemon down; let next probe deal with it
                pass

        if now() - last_status >= 5:
            rate = sent / max(1e-6, now() - started)
            print(f"  agw sent={sent}  rate={rate:.1f}/s  crashes={crashes}")
            last_status = now()

    print(f"[+] agw done. sent={sent}  crashes={crashes}  "
          f"elapsed={now() - started:.1f}s")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="agw")
    ap.add_argument("--http-port", type=int, default=18080)
    ap.add_argument("--udp-port", type=int, default=20080)
    ap.add_argument("--agw-port", type=int, default=18082)
    ap.add_argument("--duration", type=int, default=0)
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--probe-every", type=int, default=500)
    ap.add_argument("--settle", type=float, default=0.2)
    ap.add_argument("--mutation-bias", type=float, default=0.85)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)

    seed = args.seed if args.seed is not None else random.randint(0, 2**32 - 1)
    target = TargetController(args.name, args.http_port, args.udp_port)
    return fuzz(target, args.agw_port,
                seed=seed, duration=args.duration,
                max_frames=args.max_frames, probe_every=args.probe_every,
                settle=args.settle, mutation_bias=args.mutation_bias)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
