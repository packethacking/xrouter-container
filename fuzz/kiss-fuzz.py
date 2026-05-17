#!/usr/bin/env python3
"""kiss-fuzz.py -- KISS framing fuzzer (UDP transport).

KISS is the wire protocol between a host and a KISS TNC. It frames
arbitrary octet sequences with FEND (0xC0) bracket bytes and escapes
literal 0xC0 / 0xDB in the payload using FESC (0xDB) + TFEND (0xDC) /
TFESC (0xDD). The first byte after FEND is a command byte:

    0x00       data frame (payload is an AX.25 frame WITHOUT CRC)
    0x01..0x06 TNC config (TXDELAY, P, SLOT, TXTAIL, FULL_DUPLEX, ...)
    0x0F       return (exit KISS mode)
    upper 4 bits select port index, lower 4 bits = command

The fuzzer targets two distinct parser paths:
  1) the KISS framer/unframer itself (escape sequences, unbalanced
     FEND, oversized frames, unknown command bytes, port-index abuse)
  2) the AX.25 frame parser that the KISS payload is handed off to

Wire transport is UDP. The xrouter target needs an interface with
TYPE=UDP, PROTOCOL=KISS — xrouter-runner.sh sets this up on
UDPLOCAL = $UDP+1.
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

FEND = 0xC0
FESC = 0xDB
TFEND = 0xDC
TFESC = 0xDD


def kiss_escape(payload: bytes) -> bytes:
    out = bytearray()
    for b in payload:
        if b == FEND:
            out += bytes([FESC, TFEND])
        elif b == FESC:
            out += bytes([FESC, TFESC])
        else:
            out.append(b)
    return bytes(out)


def kiss_frame(cmd: int, payload: bytes, *, escape: bool = True) -> bytes:
    body = kiss_escape(payload) if escape else payload
    return bytes([FEND, cmd & 0xFF]) + body + bytes([FEND])


def ax25_address(call: str, ssid: int = 0, *, last: bool = False,
                 cr: bool = False) -> bytes:
    call = (call.upper() + "      ")[:6]
    a = bytes(((ord(c) << 1) & 0xFE) for c in call)
    sb = 0x60 | ((ssid & 0x0F) << 1) | (1 if last else 0)
    if cr: sb |= 0x80
    return a + bytes([sb])


def ui(dst, src, pid: int, info: bytes) -> bytes:
    return (ax25_address(*dst, cr=True) + ax25_address(*src, last=True) +
            bytes([0x03, pid]) + info)


def build_seeds() -> list[tuple[str, bytes]]:
    DST = ("G9DUM", 1); SRC = ("FUZZER", 7)
    s: list[tuple[str, bytes]] = []
    # Well-formed
    s.append(("data_ui_short", kiss_frame(0x00, ui(DST, SRC, 0xF0, b"hello"))))
    s.append(("data_ui_long",  kiss_frame(0x00, ui(DST, SRC, 0xF0, b"A" * 250))))
    s.append(("data_pid_cf",   kiss_frame(0x00, ui(DST, SRC, 0xCF, b"netrom"))))
    s.append(("data_pid_cd",   kiss_frame(0x00, ui(DST, SRC, 0xCD, b"\x00" * 20))))
    # TNC config commands
    s.append(("set_txdelay",   kiss_frame(0x01, b"\x10")))
    s.append(("set_p",         kiss_frame(0x02, b"\x40")))
    s.append(("set_slot",      kiss_frame(0x03, b"\x10")))
    s.append(("set_txtail",    kiss_frame(0x04, b"\x05")))
    s.append(("set_fulldup",   kiss_frame(0x05, b"\x01")))
    s.append(("hw_command",    kiss_frame(0x06, b"\x00")))
    s.append(("exit_kiss",     kiss_frame(0x0F, b"")))
    # Port-index high nibble exercise
    s.append(("port_15_data",  kiss_frame(0xF0, ui(DST, SRC, 0xF0, b"x"))))
    s.append(("port_7_data",   kiss_frame(0x70, ui(DST, SRC, 0xF0, b"x"))))
    # Framing weirdness
    s.append(("no_start_fend", bytes([0x00]) + ui(DST, SRC, 0xF0, b"x") + bytes([FEND])))
    s.append(("no_end_fend",   bytes([FEND, 0x00]) + ui(DST, SRC, 0xF0, b"x")))
    s.append(("double_fend",   bytes([FEND, FEND, 0x00]) +
                              ui(DST, SRC, 0xF0, b"x") + bytes([FEND])))
    s.append(("trailing_esc",  bytes([FEND, 0x00, FESC, FEND])))  # FESC right before END
    s.append(("orphan_tfend",  bytes([FEND, 0x00, TFEND, FEND])))
    s.append(("orphan_tfesc",  bytes([FEND, 0x00, TFESC, FEND])))
    s.append(("nested_esc",    bytes([FEND, 0x00, FESC, FESC, FEND])))
    s.append(("oversized",     kiss_frame(0x00, b"X" * 4000)))
    s.append(("empty_data",    kiss_frame(0x00, b"")))
    s.append(("just_fend",     bytes([FEND])))
    s.append(("garbage_cmd",   kiss_frame(0xFF, b"garbage")))
    return s


def mutate(b: bytes, rng: random.Random) -> bytes:
    a = bytearray(b)
    for _ in range(rng.randint(1, 4)):
        if not a: break
        op = rng.randrange(6)
        i = rng.randrange(len(a))
        if op == 0: a[i] ^= 1 << rng.randrange(8)
        elif op == 1: a[i] = rng.randrange(256)
        elif op == 2 and len(a) < 4096:
            n = rng.randint(1, 8); pos = rng.randrange(len(a) + 1)
            a[pos:pos] = bytes(rng.randrange(256) for _ in range(n))
        elif op == 3 and len(a) > 1:
            n = rng.randint(1, min(8, len(a) - 1))
            pos = rng.randrange(len(a) - n + 1); del a[pos:pos + n]
        elif op == 4:
            a[i] = rng.choice([0, FEND, FESC, TFEND, TFESC, 0xFF, 0xCF, 0xF0])
        else:
            # Insert a stray FEND, breaking framing
            if len(a) < 4096:
                a[rng.randrange(len(a) + 1):0] = bytes([FEND])
    return bytes(a)


def random_garbage(rng: random.Random) -> bytes:
    n = rng.randint(0, 600)
    return bytes(rng.randrange(256) for _ in range(n))


def fuzz(target: TargetController, port: int, *, seed: int,
         duration: int, probe_every: int) -> int:
    rng = random.Random(seed)
    print(f"[+] kiss target=127.0.0.1:{port}  health={target.health_url}  "
          f"seed={seed}")
    if not target.health_ok():
        print("[!] target not healthy before fuzzing", file=sys.stderr)
        return 2

    seeds = build_seeds()
    sock = target.udp_socket()
    sent = 0; crashes = 0; started = now(); last_status = started
    deadline = started + duration if duration else None
    last_batch: list[bytes] = []

    while True:
        if deadline and now() >= deadline:
            break
        if rng.random() < 0.85:
            label, base = rng.choice(seeds)
            frame = mutate(base, rng) if rng.random() < 0.7 else base
        else:
            frame = random_garbage(rng)
        try:
            sock.sendto(frame, ("127.0.0.1", port))
            sent += 1
            last_batch.append(frame)
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
                                                    extra={"fuzzer": "kiss",
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
            print(f"  kiss sent={sent}  rate={rate:.1f}/s  crashes={crashes}")
            last_status = now()

    print(f"[+] kiss done. sent={sent}  crashes={crashes}  "
          f"elapsed={now() - started:.1f}s")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="kiss")
    ap.add_argument("--http-port", type=int, default=18080)
    ap.add_argument("--udp-port", type=int, default=20080,
                    help="AXUDP UDPLOCAL; KISS UDPLOCAL is auto-derived as +1")
    ap.add_argument("--duration", type=int, default=0)
    ap.add_argument("--probe-every", type=int, default=400)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)
    seed = args.seed if args.seed is not None else random.randint(0, 2**32 - 1)
    target = TargetController(args.name, args.http_port, args.udp_port)
    return fuzz(target, args.udp_port + 1, seed=seed,
                duration=args.duration, probe_every=args.probe_every)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
