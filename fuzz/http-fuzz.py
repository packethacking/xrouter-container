#!/usr/bin/env python3
"""http-fuzz.py -- HTTP request fuzzer for XRouter's web admin surface.

Targets the routes the security review already showed are unauthenticated:
    /exec?cmd=...                 — known RCE; we fuzz the query/body shape
    /api/v1/config (GET, POST)    — accepts JSON config without auth
    /api/v1/restart, /userpass    — known DoS in bootstrap; try in configured too
    /admin, /info                 — admin panels with no auth
    /<random path>                — generic path fuzzing
plus header smashing, oversized URLs, weird verbs, malformed Content-Length.

Speaks raw HTTP/1.0 over a fresh TCP socket per request so we can poke
"impossible" requests that a real HTTP library won't generate (NUL in
path, oversized lengths, body without CL, etc.).
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

# Endpoints worth poking, biased toward the ones with known parsing /
# auth-bypass shapes.
PATHS = [
    "/", "/info", "/admin", "/exec",
    "/api/v1/config", "/api/v1/restart", "/api/v1/userpass",
    "/api/v1", "/api/v2/config", "/api/v1/../etc/passwd",
    "/exec?cmd=help", "/exec?cmd=sh+id", "/exec?cmd=" + "A" * 4000,
    "/info/" + "B" * 256, "/" + "/" * 60, "/?" + "=" * 100,
    "/cgi-bin/foo", "/HELP/INDEX.HTM", "/MAN/AXUDP.9.MAN",
]

VERBS = ["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH",
         "TRACE", "CONNECT", "FOO", "GETT", "GET ", ""]

HEADERS_TEMPLATES = [
    [("Host", "127.0.0.1"), ("User-Agent", "fuzz")],
    [("Host", "127.0.0.1"), ("Content-Length", "0")],
    [("Host", "127.0.0.1"), ("Content-Length", "999999")],
    [("Host", "x" * 8192)],
    [("Host", "127.0.0.1"), ("Authorization", "Basic " + "A" * 200)],
    [("Host", "127.0.0.1"), ("Cookie", "x=" + "A" * 4000)],
    [("Host", "127.0.0.1"), ("Transfer-Encoding", "chunked")],
    [("Host", "127.0.0.1"), ("X-Forwarded-For", "127.0.0.1, " * 200)],
    [],  # no Host
]

JSON_BODIES = [
    b"{}",
    b'{"NODECALL":"FUZZ"}',
    b'{"NODECALL":"' + b"A" * 4000 + b'"}',
    b'{' + b'"x":1,' * 500 + b'"y":1}',
    b'\x00' * 64,
    b'[]',
    b'null',
    b'{"' + b"\x00" * 32 + b'":1}',
    b'{"a":{"b":{"c":{"d":{"e":{"f":1}}}}}}',
    b'{"a":' + b'[' * 200 + b'1' + b']' * 200 + b'}',
]


def build_request(path: str, verb: str, headers: list[tuple[str, str]],
                  body: bytes) -> bytes:
    line = f"{verb} {path} HTTP/1.0\r\n".encode("latin-1", "replace")
    hbytes = b"".join(f"{k}: {v}\r\n".encode("latin-1", "replace")
                      for k, v in headers)
    return line + hbytes + b"\r\n" + body


def send_one(port: int, payload: bytes, *, timeout: float = 2.0) -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    except OSError:
        return False
    try:
        s.settimeout(timeout)
        s.sendall(payload)
        try:
            s.recv(4096)
        except (socket.timeout, OSError):
            pass
        return True
    finally:
        try:
            s.close()
        except OSError:
            pass


def mutate_bytes(buf: bytes, rng: random.Random) -> bytes:
    a = bytearray(buf)
    rounds = rng.randint(1, 4)
    for _ in range(rounds):
        if not a:
            break
        op = rng.randrange(5)
        i = rng.randrange(len(a))
        if op == 0: a[i] ^= 1 << rng.randrange(8)
        elif op == 1: a[i] = rng.randrange(256)
        elif op == 2 and len(a) < 16384:
            a[i:i] = bytes(rng.randrange(256) for _ in range(rng.randint(1, 16)))
        elif op == 3 and len(a) > 1:
            n = rng.randint(1, min(8, len(a) - 1))
            pos = rng.randrange(len(a) - n + 1)
            del a[pos:pos + n]
        else:
            a[i] = rng.choice([0, 0x0A, 0x0D, 0x20, 0xFF])
    return bytes(a)


def make_request(rng: random.Random) -> bytes:
    path = rng.choice(PATHS)
    verb = rng.choice(VERBS)
    hdrs = list(rng.choice(HEADERS_TEMPLATES))
    body = rng.choice(JSON_BODIES) if verb in ("POST", "PUT", "PATCH") else b""
    if body and not any(k.lower() == "content-length" for k, _ in hdrs):
        hdrs.append(("Content-Length", str(len(body))))
    if body and not any(k.lower() == "content-type" for k, _ in hdrs):
        hdrs.append(("Content-Type", "application/json"))
    req = build_request(path, verb, hdrs, body)
    if rng.random() < 0.45:
        req = mutate_bytes(req, rng)
    return req


def fuzz(target: TargetController, *, seed: int, duration: int,
         probe_every: int) -> int:
    rng = random.Random(seed)
    port = target.http_port
    print(f"[+] http target=127.0.0.1:{port}  health={target.health_url}  "
          f"seed={seed}")
    if not target.health_ok():
        print("[!] target not healthy before fuzzing", file=sys.stderr)
        return 2

    sent = 0
    crashes = 0
    started = now()
    deadline = started + duration if duration else None
    last_status = started
    last_batch: list[bytes] = []

    while True:
        if deadline and now() >= deadline:
            break
        req = make_request(rng)
        send_one(port, req)
        sent += 1
        last_batch.append(req)

        if sent % probe_every == 0:
            time.sleep(0.2)
            if not target.health_ok():
                crashes += 1
                trigger = last_batch[-1] if last_batch else None
                target.restart()
                for core in target.collect_cores():
                    info = target.triage(core)
                    if info and target.record_crash(info, trigger=trigger,
                                                    extra={"fuzzer": "http",
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
            print(f"  http sent={sent}  rate={rate:.1f}/s  crashes={crashes}")
            last_status = now()

    print(f"[+] http done. sent={sent}  crashes={crashes}  "
          f"elapsed={now() - started:.1f}s")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="http")
    ap.add_argument("--http-port", type=int, default=18080)
    ap.add_argument("--udp-port", type=int, default=20080)
    ap.add_argument("--duration", type=int, default=0)
    ap.add_argument("--probe-every", type=int, default=200)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)
    seed = args.seed if args.seed is not None else random.randint(0, 2**32 - 1)
    target = TargetController(args.name, args.http_port, args.udp_port)
    return fuzz(target, seed=seed, duration=args.duration,
                probe_every=args.probe_every)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
