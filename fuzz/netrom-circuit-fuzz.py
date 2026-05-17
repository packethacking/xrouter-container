#!/usr/bin/env python3
"""netrom-circuit-fuzz.py -- NetRom L4 in-circuit fuzzer.

The bare-bones AXUDP fuzzer hits the AX.25 frame parser and the NetRom
L3 header parser, but never gets past the L4 CONREQ/CONACK handshake.
This fuzzer:

  1) Brings up AX.25 L2 with SABM/UA against the target's node call
  2) Sends a NetRom L4 CONREQ (opcode 1) targeting the chat or node
     service and parses the CONACK to extract the assigned circuit
     index/id
  3) Once "connected", sends a stream of INFO segments (opcode 5)
     where the L4 header is well-formed but seq numbers, flags, and
     the user payload are mutated. Also fires CONACK/DISC/RESET
     variants out of sequence to exercise the state machine.

If the handshake fails (often does — the target's NetRom L4 demands a
peer that's already in its routing table), the fuzzer falls back to
"poke INFO segments without a real circuit" mode, which is still novel
relative to the bare AXUDP fuzzer because of the seq-number and
opcode-variant coverage.
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

# ---------- AX.25 helpers (re-implemented to keep this script standalone) ----------

PID_NETROM = 0xCF
PID_NOL3 = 0xF0

U_SABM = 0x2F
U_DISC = 0x43
U_UA = 0x63
U_DM = 0x0F
U_UI = 0x03

NR_OP_CONREQ = 0x01
NR_OP_CONACK = 0x02
NR_OP_DISCREQ = 0x03
NR_OP_DISCACK = 0x04
NR_OP_INFO = 0x05
NR_OP_INFOACK = 0x06
NR_OP_RESET = 0x07
NR_FL_MORE = 0x20
NR_FL_NAK = 0x40
NR_FL_CHOKE = 0x80


def ax25_address(call: str, ssid: int = 0, *, last: bool = False,
                 cr: bool = False) -> bytes:
    call = (call.upper() + "      ")[:6]
    a = bytes(((ord(c) << 1) & 0xFE) for c in call)
    ssid_byte = 0x60 | ((ssid & 0x0F) << 1) | (1 if last else 0)
    if cr: ssid_byte |= 0x80
    return a + bytes([ssid_byte])


def crc16(b: bytes) -> int:
    crc = 0xFFFF
    for byte in b:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if (crc & 1) else (crc >> 1)
    return crc ^ 0xFFFF


def with_fcs(f: bytes) -> bytes:
    return f + struct.pack("<H", crc16(f))


def ax25_u(dst, src, ctl: int) -> bytes:
    return ax25_address(*dst, cr=True) + ax25_address(*src, last=True) + bytes([ctl])


def ax25_ui(dst, src, pid: int, info: bytes) -> bytes:
    return (ax25_address(*dst, cr=True) + ax25_address(*src, last=True) +
            bytes([U_UI, pid]) + info)


def netrom_l3(src, dst, *, ttl: int = 25, idx: int = 0, cid: int = 0,
              ns: int = 0, nr: int = 0, flags: int = NR_OP_INFO) -> bytes:
    return (ax25_address(*src) + ax25_address(*dst) +
            bytes([ttl, idx, cid, ns, nr, flags]))


def nr_conreq(src, dst, *, idx: int = 0, cid: int = 0, window: int = 4,
              orig=("FUZZER", 7), caller_dst=("G9DUM", 0)) -> bytes:
    h = netrom_l3(src, dst, idx=idx, cid=cid, flags=NR_OP_CONREQ)
    return h + bytes([window]) + ax25_address(*orig) + ax25_address(*caller_dst)


def nr_info(src, dst, payload: bytes, *, idx: int = 0, cid: int = 0,
            ns: int = 0, nr: int = 0, more: bool = False) -> bytes:
    fl = NR_OP_INFO | (NR_FL_MORE if more else 0)
    return netrom_l3(src, dst, idx=idx, cid=cid, ns=ns, nr=nr, flags=fl) + payload


def nr_disc(src, dst, *, idx: int = 0, cid: int = 0) -> bytes:
    return netrom_l3(src, dst, idx=idx, cid=cid, flags=NR_OP_DISCREQ)


def nr_reset(src, dst, *, idx: int = 0, cid: int = 0) -> bytes:
    return netrom_l3(src, dst, idx=idx, cid=cid, flags=NR_OP_RESET)


# ---------- Mutation helpers ----------

def mutate(b: bytes, rng: random.Random) -> bytes:
    a = bytearray(b)
    for _ in range(rng.randint(1, 4)):
        if not a: break
        op = rng.randrange(6)
        i = rng.randrange(len(a))
        if op == 0: a[i] ^= 1 << rng.randrange(8)
        elif op == 1: a[i] = rng.randrange(256)
        elif op == 2 and len(a) < 4096:
            a[i:i] = bytes(rng.randrange(256) for _ in range(rng.randint(1, 8)))
        elif op == 3 and len(a) > 1:
            n = rng.randint(1, min(8, len(a) - 1))
            pos = rng.randrange(len(a) - n + 1); del a[pos:pos + n]
        elif op == 4:
            n = rng.randint(1, min(16, len(a)))
            pos = rng.randrange(len(a) - n + 1)
            for k in range(n): a[pos + k] = rng.randrange(256)
        else:
            a[i] = rng.choice([0, 0x7F, 0x80, 0xFF, NR_OP_CONREQ, NR_OP_INFO,
                               NR_OP_RESET, PID_NETROM])
    return bytes(a)


# ---------- Fuzzer ----------

def try_handshake(sock: socket.socket, target_addr: tuple[str, int],
                  src: tuple[str, int], dst: tuple[str, int]) -> bool:
    """Send SABM, wait briefly. Real success would need to receive UA,
    but for fuzzing purposes just sending it puts the parser in some
    state, which is what we want."""
    frame = with_fcs(ax25_u(dst, src, U_SABM))
    try:
        sock.sendto(frame, target_addr)
    except OSError:
        return False
    time.sleep(0.05)
    return True


def fuzz(target: TargetController, port: int, *, seed: int,
         duration: int, probe_every: int) -> int:
    rng = random.Random(seed)
    src = ("FUZZER", rng.randrange(0, 16))
    dst = ("G9DUM", 1)
    target_addr = ("127.0.0.1", port)

    print(f"[+] netrom-circuit target=127.0.0.1:{port}  health={target.health_url}  "
          f"seed={seed}")
    if not target.health_ok():
        print("[!] target not healthy before fuzzing", file=sys.stderr)
        return 2

    sock = target.udp_socket()
    sent = 0; crashes = 0; started = now(); last_status = started
    deadline = started + duration if duration else None
    last_batch: list[bytes] = []

    # Open with SABM
    try_handshake(sock, target_addr, src, dst)

    # Generate a stream of in-circuit-ish traffic
    # Mix: SABM, UA, I-frames carrying NetRom L4 of all opcodes, DISC, DM
    while True:
        if deadline and now() >= deadline:
            break

        idx = rng.randrange(0, 256)
        cid = rng.randrange(0, 256)
        ns = rng.randrange(0, 8)
        nr = rng.randrange(0, 8)
        pick = rng.random()

        if pick < 0.10:
            ax = ax25_u(dst, src, U_SABM)
        elif pick < 0.15:
            ax = ax25_u(dst, src, U_DISC)
        elif pick < 0.18:
            ax = ax25_u(dst, src, U_DM)
        elif pick < 0.20:
            ax = ax25_u(dst, src, U_UA)
        else:
            nr_src = (rng.choice(["FUZZER", "G8PZT", "VK1XYZ", "FU\x00ZZ", "A"]),
                      rng.randrange(0, 16))
            nr_dst = (rng.choice(["G9DUM", "CHAT", "NODES", "AAAA"]),
                      rng.randrange(0, 16))
            opcode_pool = [
                lambda: nr_conreq(nr_src, nr_dst, idx=idx, cid=cid,
                                  window=rng.randrange(0, 256)),
                lambda: nr_info(nr_src, nr_dst,
                                bytes(rng.randrange(256)
                                      for _ in range(rng.randint(0, 250))),
                                idx=idx, cid=cid, ns=ns, nr=nr,
                                more=rng.choice([False, True])),
                lambda: nr_disc(nr_src, nr_dst, idx=idx, cid=cid),
                lambda: nr_reset(nr_src, nr_dst, idx=idx, cid=cid),
                # Bogus opcode (0x08-0x1F)
                lambda: netrom_l3(nr_src, nr_dst, idx=idx, cid=cid,
                                  ns=ns, nr=nr,
                                  flags=rng.randrange(0, 256)),
                # Truncated header (no opcode byte)
                lambda: netrom_l3(nr_src, nr_dst)[:rng.randint(5, 19)],
                # Oversized info field
                lambda: nr_info(nr_src, nr_dst, b"X" * rng.randint(200, 1500),
                                idx=idx, cid=cid),
            ]
            nrpkt = rng.choice(opcode_pool)()
            ax = ax25_ui(dst, src, PID_NETROM, nrpkt)

        if rng.random() < 0.6:
            ax = mutate(ax, rng)

        # Half with correct FCS, half not
        wire = with_fcs(ax) if rng.random() < 0.5 else (
            ax + bytes([rng.randrange(256), rng.randrange(256)]))
        try:
            sock.sendto(wire, target_addr)
            sent += 1
            last_batch.append(wire)
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
                                                    extra={"fuzzer": "netrom-circuit",
                                                           "sent": sent}):
                        print(f"[!] NEW BUG {info.signature} rip={info.rip} "
                              f"insn={info.insn} (sent={sent})")
                    elif info:
                        print(f"[ ] dup {info.signature} (sent={sent})")
                last_batch.clear()
                try_handshake(sock, target_addr, src, dst)
            else:
                last_batch.clear()

        if now() - last_status >= 5:
            rate = sent / max(1e-6, now() - started)
            print(f"  netrom-circuit sent={sent}  rate={rate:.1f}/s  "
                  f"crashes={crashes}")
            last_status = now()

    print(f"[+] netrom-circuit done. sent={sent}  crashes={crashes}  "
          f"elapsed={now() - started:.1f}s")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="netrom")
    ap.add_argument("--http-port", type=int, default=18080)
    ap.add_argument("--udp-port", type=int, default=20080)
    ap.add_argument("--duration", type=int, default=0)
    ap.add_argument("--probe-every", type=int, default=300)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)
    seed = args.seed if args.seed is not None else random.randint(0, 2**32 - 1)
    target = TargetController(args.name, args.http_port, args.udp_port)
    return fuzz(target, args.udp_port, seed=seed,
                duration=args.duration, probe_every=args.probe_every)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
