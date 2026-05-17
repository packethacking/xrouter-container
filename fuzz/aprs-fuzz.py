#!/usr/bin/env python3
"""aprs-fuzz.py -- APRS-IS server fuzzer for XRouter's APRSPORT (default 1448).

APRS-IS is a line-based, text-mostly protocol. A client connects, sends
a login line ("user CALL pass PW vers app NN filter ...") and then
streams TNC2-format APRS packets terminated by CRLF. Server responses
are mostly comments.

We fuzz: login line variants, TNC2-frame variants, command lines
(#filter etc.), absurd lengths, NUL/CR/LF placement, and the rate
limits the server probably applies.
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

SEED_LINES = [
    b"user FUZZER-7 pass -1 vers fuzz 1.0\r\n",
    b"user FUZZER-7 pass 12345 vers fuzz 1.0 filter m/500\r\n",
    b"#filter m/500\r\n",
    b"FUZZER-7>APRS,TCPIP*:>fuzz status\r\n",
    b"FUZZER-7>APRS:=5824.22N/00515.00W-fuzz\r\n",
    b"FUZZER-7>APRS:!5824.22N/00515.00W-pos\r\n",
    b"FUZZER-7>APRS,WIDE1-1,WIDE2-2:>fuzz path\r\n",
    b"FUZZER-7>APRS:T#001,123,456,789,012,345,01010101\r\n",
    b"FUZZER-7>APRS:;OBJ      *123456z5824.22N/00515.00W-object\r\n",
    b"FUZZER-7>APRS::MSGCALL  :hello world{12345\r\n",
    b"FUZZER-7>APRS:}DIGI>APRS,TCPIP*:>3rd party\r\n",
    b"FUZZER-7>APRS:`fuzz mic-e body\x1f`\r\n",
    b"FUZZER-7>APRS:" + b"A" * 4000 + b"\r\n",
    b"FUZZER-7" + b"-" + b"99" + b">APRS:>weird ssid\r\n",
    b"" + b"X" * 4000 + b"\r\n",                         # huge garbage
    b">noheader\r\n",
    b"\r\n",                                              # empty line
    b"\n",
    b"\r",
    b"FUZZER>APRS:\x00\x00\x00\r\n",
    b"FUZZER>APRS:\xff\xff\xfe\xfd\r\n",
    b"FUZZER>APRS,WIDE1-1,WIDE2-2," * 30 + b":>too many digis\r\n",
]


def mutate(line: bytes, rng: random.Random) -> bytes:
    a = bytearray(line)
    rounds = rng.randint(1, 4)
    for _ in range(rounds):
        if not a:
            break
        op = rng.randrange(5)
        i = rng.randrange(len(a))
        if op == 0: a[i] ^= 1 << rng.randrange(8)
        elif op == 1: a[i] = rng.randrange(256)
        elif op == 2 and len(a) < 8192:
            n = rng.randint(1, 16); pos = rng.randrange(len(a) + 1)
            a[pos:pos] = bytes(rng.randrange(256) for _ in range(n))
        elif op == 3 and len(a) > 1:
            n = rng.randint(1, min(16, len(a) - 1))
            pos = rng.randrange(len(a) - n + 1); del a[pos:pos + n]
        else:
            a[i] = rng.choice([0, 0x0A, 0x0D, 0x20, 0xFF, ord("\""), ord("'"),
                               ord("<"), ord(">"), ord(":")])
    return bytes(a)


def fuzz(target: TargetController, port: int, *, seed: int,
         duration: int, probe_every: int) -> int:
    rng = random.Random(seed)
    print(f"[+] aprs target=127.0.0.1:{port}  health={target.health_url}  "
          f"seed={seed}")
    if not target.health_ok():
        print("[!] target not healthy before fuzzing", file=sys.stderr)
        return 2

    sock: socket.socket | None = None
    sent = 0; crashes = 0; started = now(); last_status = started
    deadline = started + duration if duration else None
    last_batch: list[bytes] = []

    def reconnect():
        nonlocal sock
        if sock is not None:
            try: sock.close()
            except OSError: pass
        try:
            sock = target.tcp_connect(port)
            # APRS-IS expects a login line first
            sock.sendall(b"user FUZZER-7 pass -1 vers fuzz 1.0\r\n")
            try: sock.recv(4096)
            except (socket.timeout, OSError): pass
        except (ConnectionRefusedError, OSError):
            sock = None

    reconnect()

    while True:
        if deadline and now() >= deadline:
            break
        if sock is None:
            reconnect()
            if sock is None:
                time.sleep(0.2)
                continue

        if rng.random() < 0.85:
            base = rng.choice(SEED_LINES)
            line = mutate(base, rng) if rng.random() < 0.7 else base
        else:
            n = rng.randint(1, 600)
            line = bytes(rng.randrange(256) for _ in range(n))

        try:
            sock.sendall(line)
            sent += 1
            last_batch.append(line)
        except OSError:
            sock = None

        if sent and sent % probe_every == 0:
            time.sleep(0.25)
            if not target.health_ok():
                crashes += 1
                trigger = last_batch[-1] if last_batch else None
                target.restart()
                for core in target.collect_cores():
                    info = target.triage(core)
                    if info and target.record_crash(info, trigger=trigger,
                                                    extra={"fuzzer": "aprs",
                                                           "sent": sent}):
                        print(f"[!] NEW BUG {info.signature} rip={info.rip} "
                              f"insn={info.insn} (sent={sent})")
                    elif info:
                        print(f"[ ] dup {info.signature} (sent={sent})")
                last_batch.clear()
                reconnect()
            else:
                last_batch.clear()

        if now() - last_status >= 5:
            rate = sent / max(1e-6, now() - started)
            print(f"  aprs sent={sent}  rate={rate:.1f}/s  crashes={crashes}")
            last_status = now()

    print(f"[+] aprs done. sent={sent}  crashes={crashes}  "
          f"elapsed={now() - started:.1f}s")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="aprs")
    ap.add_argument("--http-port", type=int, default=18080)
    ap.add_argument("--udp-port", type=int, default=20080)
    ap.add_argument("--aprs-port", type=int, default=18083)
    ap.add_argument("--duration", type=int, default=0)
    ap.add_argument("--probe-every", type=int, default=300)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)
    seed = args.seed if args.seed is not None else random.randint(0, 2**32 - 1)
    target = TargetController(args.name, args.http_port, args.udp_port)
    return fuzz(target, args.aprs_port, seed=seed,
                duration=args.duration, probe_every=args.probe_every)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
