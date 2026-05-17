#!/usr/bin/env python3
"""finger-fuzz.py -- finger protocol fuzzer for XRouter's FINGERPORT.

Finger (RFC 1288) is trivially simple: client connects to port 79,
sends a query line terminated by CRLF, server replies with the
matching FINGER/*.TXT contents (or error). Despite that, XRouter
implements the protocol from scratch, including handling of the
forwarding "@" syntax ("user@host"). We poke:

  - long query lines
  - embedded NUL, CR, LF
  - "/W" verbose-mode flag
  - directory traversal: "../etc/passwd", "..", "."
  - multiple @ characters: "user@host@host@host..."
  - empty / just-CRLF queries
  - non-ASCII bytes
"""

from __future__ import annotations

import argparse
import random
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import TargetController, now  # noqa: E402

SEEDS = [
    b"\r\n",
    b"root\r\n",
    b"/W\r\n",
    b"/W root\r\n",
    b"sysop\r\n",
    b"G8PZT\r\n",
    b"user@example.com\r\n",
    b"user@" + b"x" * 200 + b"\r\n",
    b"@" * 100 + b"\r\n",
    b"/W " + b"A" * 4000 + b"\r\n",
    b"../etc/passwd\r\n",
    b"..\\..\\windows\\system32\r\n",
    b"\x00\x00\x00\r\n",
    b"\xff\xfe\xfd\xfc\r\n",
    b"%s%s%s%s%s%s\r\n",
    b"$(whoami)\r\n",
    b"`cat /etc/passwd`\r\n",
    b"<script>alert(1)</script>\r\n",
    b"A" * 8192 + b"\r\n",       # no terminator before huge run
    b"\r\n\r\n\r\n",               # multiple terminators
    b"",                            # empty
    b"abc",                        # no CRLF
]


def mutate(line: bytes, rng: random.Random) -> bytes:
    a = bytearray(line)
    for _ in range(rng.randint(1, 4)):
        if not a: break
        op = rng.randrange(5)
        i = rng.randrange(len(a))
        if op == 0: a[i] ^= 1 << rng.randrange(8)
        elif op == 1: a[i] = rng.randrange(256)
        elif op == 2 and len(a) < 8192:
            n = rng.randint(1, 8); pos = rng.randrange(len(a) + 1)
            a[pos:pos] = bytes(rng.randrange(256) for _ in range(n))
        elif op == 3 and len(a) > 1:
            n = rng.randint(1, min(8, len(a) - 1))
            pos = rng.randrange(len(a) - n + 1); del a[pos:pos + n]
        else:
            a[i] = rng.choice([0, 0x0A, 0x0D, ord("@"), ord("/"), ord(" "), 0xFF])
    return bytes(a)


def fuzz(target: TargetController, port: int, *, seed: int,
         duration: int, probe_every: int) -> int:
    rng = random.Random(seed)
    print(f"[+] finger target=127.0.0.1:{port}  health={target.health_url}  "
          f"seed={seed}")
    if not target.health_ok():
        print("[!] target not healthy before fuzzing", file=sys.stderr)
        return 2

    sent = 0; crashes = 0; started = now(); last_status = started
    deadline = started + duration if duration else None
    last_batch: list[bytes] = []

    while True:
        if deadline and now() >= deadline:
            break
        if rng.random() < 0.85:
            base = rng.choice(SEEDS)
            q = mutate(base, rng) if rng.random() < 0.7 else base
        else:
            n = rng.randint(0, 300)
            q = bytes(rng.randrange(256) for _ in range(n))
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            try:
                s.sendall(q)
                try: s.recv(2048)
                except (socket.timeout, OSError): pass
            finally:
                try: s.close()
                except OSError: pass
            sent += 1
            last_batch.append(q)
        except OSError:
            pass

        if sent and sent % probe_every == 0:
            time.sleep(0.2)
            if not target.health_ok():
                crashes += 1
                trigger = last_batch[-1] if last_batch else None
                target.restart()
                for core in target.collect_cores():
                    info = target.triage(core)
                    if info and target.record_crash(info, trigger=trigger,
                                                    extra={"fuzzer": "finger",
                                                           "sent": sent}):
                        print(f"[!] NEW BUG {info.signature} rip={info.rip} "
                              f"insn={info.insn} (sent={sent})")
                    elif info:
                        print(f"[ ] dup {info.signature} (sent={sent})")
                last_batch.clear()
            else:
                last_batch.clear()

        if now() - last_status >= 5:
            rate = sent / max(1e-6, now() - started)
            print(f"  finger sent={sent}  rate={rate:.1f}/s  crashes={crashes}")
            last_status = now()

    print(f"[+] finger done. sent={sent}  crashes={crashes}  "
          f"elapsed={now() - started:.1f}s")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="finger")
    ap.add_argument("--http-port", type=int, default=18080)
    ap.add_argument("--udp-port", type=int, default=20080)
    ap.add_argument("--finger-port", type=int, default=18084)
    ap.add_argument("--duration", type=int, default=0)
    ap.add_argument("--probe-every", type=int, default=200)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)
    seed = args.seed if args.seed is not None else random.randint(0, 2**32 - 1)
    target = TargetController(args.name, args.http_port, args.udp_port)
    return fuzz(target, args.finger_port, seed=seed,
                duration=args.duration, probe_every=args.probe_every)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
