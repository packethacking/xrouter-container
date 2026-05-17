#!/usr/bin/env python3
"""
axudp-fuzz.py -- generation + mutation fuzzer for XRouter's AX.25/NetRom
parsers, delivered over AXUDP.

Wire format (per AXUDP.9.MAN in the XRouter support pack):
    UDP payload = raw AX.25 frame + 2-byte CRC-16-CCITT FCS

Stack of parsers the fuzzer reaches:
    Layer 2 (AX.25):   address field, control byte, PID
    Layer 3 (NetRom):  src/dst callsign, TTL, circuit, seq, opcode
    Layer 3 (NODES):   routing broadcast: signature + record array
    Layer 4 (NetRom):  CONREQ window+caller, INFO body, DISC/UA/RST flags
    Plus mutations on each of those + random garbage at every length.

A liveness probe (HTTP GET on the target's configured HTTP port) runs
every --probe-every frames. If it fails, the last batch since the
previous good probe is saved as a hex-per-line dump to
<corpus>/batch-*.txt. With --restart-cmd, the fuzzer then restarts the
target and keeps going; otherwise it exits and lets the operator
restart manually.

To reduce a crash batch to its minimal single-frame trigger, re-run
with --replay <batch.txt> --restart-cmd "<how-to-restart-target>". The
fuzzer binary-searches the batch, restarting the target between trials.
Stateful crashes (parser state built up over many earlier frames)
won't reduce to a single frame and the bisector will say so — re-run
the original campaign with the same --seed to reproduce those, since
the PRNG is deterministic.

Quick start
-----------
1) Boot a target xrouter with an AXUDP port; fuzz/XROUTER.CFG and
   fuzz/run-demo.sh in this directory do that for you.

2) Run the fuzzer:
       fuzz/axudp-fuzz.py --target 127.0.0.1:10093 \
                          --health http://127.0.0.1:8080/ \
                          --duration 300

3) Crashes land in fuzz/crashes/ as both the raw .bin and a .txt that
   decodes the AX.25 / NetRom header so the bug is reviewable without
   re-running the fuzzer.

The fuzzer is intentionally dependency-free (stdlib only) so it runs
the same on a Pi (armv7) or a workstation (amd64).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import socket
import struct
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# AX.25 helpers
# ---------------------------------------------------------------------------

# PIDs (AX.25 2.0 §3.3)
PID_ISO8208 = 0x01
PID_IP = 0xCC
PID_ARP = 0xCD
PID_NETROM = 0xCF
PID_NOL3 = 0xF0
PID_ESCAPE = 0xFF

# U-frame control bytes (P/F = 0 in low nibble form; |0x10 toggles P/F)
U_SABM = 0x2F
U_SABME = 0x6F
U_DISC = 0x43
U_DM = 0x0F
U_UA = 0x63
U_FRMR = 0x87
U_UI = 0x03
U_XID = 0xAF
U_TEST = 0xE3


def ax25_address(call: str, ssid: int = 0, *, last: bool = False,
                 cr: bool = False, has_been_repeated: bool = False) -> bytes:
    """Encode one 7-byte AX.25 address subfield.

    Each callsign char is left-shifted by 1; padding is space (0x20 -> 0x40).
    SSID byte layout (per AX.25 2.0 §3.12):
        bit7 = C/R (command/response, or "has-been-repeated" on digipeaters)
        bits6-5 = reserved (set to 1)
        bits4-1 = SSID
        bit0 = extension bit (1 only on the last address)
    """
    call = (call.upper() + "      ")[:6]
    addr = bytes(((ord(c) << 1) & 0xFE) for c in call)
    ssid_byte = 0x60 | ((ssid & 0x0F) << 1)
    if last:
        ssid_byte |= 0x01
    if cr:
        ssid_byte |= 0x80
    if has_been_repeated:
        ssid_byte |= 0x80  # caller decides which sense it means
    return addr + bytes([ssid_byte])


def crc16_ccitt(data: bytes) -> int:
    """AX.25 FCS: CRC-16-CCITT, polynomial 0x1021 reflected (0x8408)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    return crc ^ 0xFFFF


def with_fcs(frame: bytes) -> bytes:
    return frame + struct.pack("<H", crc16_ccitt(frame))


# ---------------------------------------------------------------------------
# Frame templates (seed corpus)
# ---------------------------------------------------------------------------

DEFAULT_SRC = ("FUZZER", 7)
DEFAULT_DST = ("G9DUM", 1)
NODES_DST = ("NODES", 0)


def ui_frame(dst: tuple[str, int], src: tuple[str, int], pid: int,
             info: bytes, *, pf: bool = False) -> bytes:
    """AX.25 UI (Unnumbered Information) frame."""
    addr = (ax25_address(*dst, cr=True) +
            ax25_address(*src, last=True))
    ctl = U_UI | (0x10 if pf else 0)
    return addr + bytes([ctl, pid]) + info


def i_frame(dst, src, ns: int, nr: int, pid: int, info: bytes,
            *, pf: bool = False) -> bytes:
    """AX.25 Information frame (modulo 8)."""
    addr = (ax25_address(*dst, cr=True) +
            ax25_address(*src, last=True))
    ctl = ((nr & 7) << 5) | ((1 if pf else 0) << 4) | ((ns & 7) << 1)
    return addr + bytes([ctl, pid]) + info


def u_frame(dst, src, ctl: int) -> bytes:
    """AX.25 Unnumbered frame (SABM/DISC/UA/DM/...)."""
    addr = (ax25_address(*dst, cr=True) +
            ax25_address(*src, last=True))
    return addr + bytes([ctl])


def s_frame(dst, src, code: int, nr: int, *, pf: bool = False) -> bytes:
    """AX.25 Supervisory frame (RR/RNR/REJ)."""
    addr = (ax25_address(*dst, cr=True) +
            ax25_address(*src, last=True))
    ctl = ((nr & 7) << 5) | ((1 if pf else 0) << 4) | code
    return addr + bytes([ctl])


# ---------------------------------------------------------------------------
# NetRom L3 / L4
# ---------------------------------------------------------------------------

# L4 opcodes (low nibble of the flags byte)
NR_OP_PROTO_EXT = 0x00
NR_OP_CONREQ = 0x01
NR_OP_CONACK = 0x02
NR_OP_DISCREQ = 0x03
NR_OP_DISCACK = 0x04
NR_OP_INFO = 0x05
NR_OP_INFOACK = 0x06
NR_OP_RESET = 0x07
# Top nibble flag bits
NR_FL_MORE = 0x20
NR_FL_NAK = 0x40
NR_FL_CHOKE = 0x80


def netrom_l3_header(src: tuple[str, int], dst: tuple[str, int], *,
                     ttl: int = 25, idx: int = 0, cid: int = 0,
                     ns: int = 0, nr: int = 0, flags: int = NR_OP_INFO) -> bytes:
    """20-byte NetRom L3 header. Source/dest addresses use bit-7 only for C/R,
    the end-bit semantics from AX.25 do NOT apply at L3."""
    return (ax25_address(*src) + ax25_address(*dst) +
            bytes([ttl & 0xFF, idx & 0xFF, cid & 0xFF,
                   ns & 0xFF, nr & 0xFF, flags & 0xFF]))


def netrom_conreq(src, dst, *, window: int = 4,
                  orig: tuple[str, int] = DEFAULT_SRC,
                  caller_dst: tuple[str, int] = DEFAULT_DST) -> bytes:
    """L4 connect request: header (with flags=CONREQ) + window + 2 callsigns."""
    hdr = netrom_l3_header(src, dst, flags=NR_OP_CONREQ)
    return hdr + bytes([window & 0xFF]) + ax25_address(*orig) + ax25_address(*caller_dst)


def netrom_info(src, dst, payload: bytes, *, ns: int = 0, nr: int = 0,
                more: bool = False) -> bytes:
    fl = NR_OP_INFO | (NR_FL_MORE if more else 0)
    return netrom_l3_header(src, dst, ns=ns, nr=nr, flags=fl) + payload


def netrom_disc(src, dst, *, idx: int = 0, cid: int = 0) -> bytes:
    return netrom_l3_header(src, dst, idx=idx, cid=cid, flags=NR_OP_DISCREQ)


def nodes_broadcast(origin_alias: str = "FUZZRX", records: list[tuple[str, int, str, str, int, int]] | None = None) -> bytes:
    """NODES broadcast payload (carried in a UI frame to AX.25 dest "NODES")."""
    if records is None:
        records = [("G8PZT", 0, "KIDDER", "G8PZT", 0, 200)]
    out = bytes([0xFF]) + (origin_alias.upper() + "      ")[:6].encode()
    for dest_call, dest_ssid, dest_alias, nbr_call, nbr_ssid, quality in records:
        out += ax25_address(dest_call, dest_ssid)
        out += (dest_alias.upper() + "      ")[:6].encode()
        out += ax25_address(nbr_call, nbr_ssid)
        out += bytes([quality & 0xFF])
    return out


# ---------------------------------------------------------------------------
# Seed corpus
# ---------------------------------------------------------------------------

def build_seed_corpus() -> list[tuple[str, bytes]]:
    """Each seed is (label, ax25_frame_without_fcs)."""
    seeds: list[tuple[str, bytes]] = []

    seeds.append(("ax25_sabm", u_frame(DEFAULT_DST, DEFAULT_SRC, U_SABM)))
    seeds.append(("ax25_sabme", u_frame(DEFAULT_DST, DEFAULT_SRC, U_SABME)))
    seeds.append(("ax25_disc", u_frame(DEFAULT_DST, DEFAULT_SRC, U_DISC)))
    seeds.append(("ax25_ua", u_frame(DEFAULT_DST, DEFAULT_SRC, U_UA)))
    seeds.append(("ax25_dm", u_frame(DEFAULT_DST, DEFAULT_SRC, U_DM)))
    seeds.append(("ax25_test", u_frame(DEFAULT_DST, DEFAULT_SRC, U_TEST) + b"TESTDATA"))
    seeds.append(("ax25_xid", u_frame(DEFAULT_DST, DEFAULT_SRC, U_XID) + b"\x82\x80\x00"))
    seeds.append(("ax25_frmr", u_frame(DEFAULT_DST, DEFAULT_SRC, U_FRMR) + b"\x00\x00\x00"))

    seeds.append(("ax25_rr_nr0", s_frame(DEFAULT_DST, DEFAULT_SRC, 0x01, 0)))
    seeds.append(("ax25_rnr_nr3", s_frame(DEFAULT_DST, DEFAULT_SRC, 0x05, 3)))
    seeds.append(("ax25_rej_nr7", s_frame(DEFAULT_DST, DEFAULT_SRC, 0x09, 7)))

    seeds.append(("ax25_i_short", i_frame(DEFAULT_DST, DEFAULT_SRC, 0, 0, PID_NOL3, b"hello")))
    seeds.append(("ax25_i_big", i_frame(DEFAULT_DST, DEFAULT_SRC, 3, 1, PID_NOL3, b"A" * 250)))
    seeds.append(("ax25_ui_text", ui_frame(DEFAULT_DST, DEFAULT_SRC, PID_NOL3, b"CQ CQ DE FUZZER")))

    # NetRom L3/L4 carried in a UI frame with PID 0xCF
    seeds.append(("nr_l4_conreq", ui_frame(
        ("G9DUM", 0), DEFAULT_SRC, PID_NETROM,
        netrom_conreq(DEFAULT_SRC, ("G9DUM", 1)))))
    seeds.append(("nr_l4_info",  ui_frame(
        ("G9DUM", 0), DEFAULT_SRC, PID_NETROM,
        netrom_info(DEFAULT_SRC, ("G9DUM", 1), b"netrom payload"))))
    seeds.append(("nr_l4_disc",  ui_frame(
        ("G9DUM", 0), DEFAULT_SRC, PID_NETROM,
        netrom_disc(DEFAULT_SRC, ("G9DUM", 1)))))
    seeds.append(("nr_l4_reset", ui_frame(
        ("G9DUM", 0), DEFAULT_SRC, PID_NETROM,
        netrom_l3_header(DEFAULT_SRC, ("G9DUM", 1), flags=NR_OP_RESET))))

    seeds.append(("nr_nodes_bc", ui_frame(
        NODES_DST, DEFAULT_SRC, PID_NETROM,
        nodes_broadcast(records=[
            ("G8PZT", 0, "KIDDER", "G8PZT", 0, 200),
            ("VK1UDP", 7, "VKDOT", "VK1UDP", 7, 180),
        ]))))

    # Things specifically aimed at known parser sore spots
    seeds.append(("ax25_no_end_bit", (
        ax25_address(*DEFAULT_DST, cr=True) +       # no last bit
        ax25_address(*DEFAULT_SRC) +                 # no last bit either
        bytes([U_UI, PID_NOL3]) + b"x")))
    seeds.append(("ax25_max_digis", (
        ax25_address(*DEFAULT_DST, cr=True) +
        ax25_address(*DEFAULT_SRC) +
        b"".join(ax25_address(f"DIGI{i}", i) for i in range(7)) +
        ax25_address("DIGI8", 8, last=True) +
        bytes([U_UI, PID_NOL3]) + b"x")))
    seeds.append(("ax25_truncated_addr", b"\x82\x84\x66\x40\x40\x40\xE0"))  # just one address
    seeds.append(("ax25_empty", b""))

    # Known regression triggers found by previous runs. Kept here so they get
    # re-fired and mutated on every campaign — useful both as canaries (any
    # campaign should crash the target if these still bite) and as starting
    # points for finding related parser bugs nearby.
    #
    # arp_short: 38-byte UI frame with PID 0xCD (ARP-over-AX.25) carrying
    # only 20 bytes of info. The minimum well-formed ARP payload is 30
    # bytes, so the parser reads past the end. Crashes 504p..505c on every
    # arch (SIGSEGV).
    seeds.append(("arp_short_segfault", bytes.fromhex(
        "8e7288aa9a40e08caab4b48aa46f"   # dst G9DUM-0, src FUZZER-7
        "03cd"                            # ctl=UI, pid=0xCD (ARP)
        "8caab4b48aa46e8e7288aa9a4062190000000003"  # 20-byte short info
    )))

    return seeds


# ---------------------------------------------------------------------------
# Mutators
# ---------------------------------------------------------------------------

MAGIC_VALUES = [
    0, 1, 2, 3, 0x7F, 0x80, 0xFE, 0xFF,
    0x10, 0x40, 0x60, 0xC0,                  # AX.25 control / SSID bits
    PID_NETROM, PID_IP, PID_ARP, PID_NOL3,
    U_UI, U_SABM, U_DISC, U_UA, U_DM, U_FRMR, U_XID, U_TEST,
    NR_OP_CONREQ, NR_OP_INFO, NR_OP_DISCREQ, NR_OP_RESET,
]


def m_bit_flip(buf: bytearray, rng: random.Random) -> None:
    if not buf:
        return
    i = rng.randrange(len(buf))
    buf[i] ^= 1 << rng.randrange(8)


def m_byte_replace(buf: bytearray, rng: random.Random) -> None:
    if not buf:
        return
    i = rng.randrange(len(buf))
    buf[i] = rng.randrange(256)


def m_magic(buf: bytearray, rng: random.Random) -> None:
    if not buf:
        return
    i = rng.randrange(len(buf))
    buf[i] = rng.choice(MAGIC_VALUES) & 0xFF


def m_insert(buf: bytearray, rng: random.Random) -> None:
    if len(buf) > 1024:
        return
    n = rng.randint(1, 8)
    pos = rng.randrange(len(buf) + 1) if buf else 0
    buf[pos:pos] = bytes(rng.randrange(256) for _ in range(n))


def m_delete(buf: bytearray, rng: random.Random) -> None:
    if len(buf) < 2:
        return
    n = rng.randint(1, min(8, len(buf) - 1))
    pos = rng.randrange(len(buf) - n + 1)
    del buf[pos:pos + n]


def m_duplicate(buf: bytearray, rng: random.Random) -> None:
    if len(buf) < 2 or len(buf) > 800:
        return
    n = rng.randint(1, min(16, len(buf) // 2))
    src = rng.randrange(len(buf) - n + 1)
    dst = rng.randrange(len(buf) + 1)
    buf[dst:dst] = bytes(buf[src:src + n])


def m_chunk_random(buf: bytearray, rng: random.Random) -> None:
    """Overwrite a random run with random bytes."""
    if len(buf) < 2:
        return
    n = rng.randint(1, min(16, len(buf)))
    pos = rng.randrange(len(buf) - n + 1)
    for k in range(n):
        buf[pos + k] = rng.randrange(256)


MUTATORS = (m_bit_flip, m_byte_replace, m_magic, m_insert, m_delete,
            m_duplicate, m_chunk_random)


def mutate(seed: bytes, rng: random.Random) -> bytes:
    buf = bytearray(seed)
    rounds = rng.randint(1, 6)
    for _ in range(rounds):
        rng.choice(MUTATORS)(buf, rng)
    return bytes(buf)


def random_garbage(rng: random.Random) -> bytes:
    """A frame that isn't even pretending to be AX.25. Catches asserts on
    address-field length / control-byte presence / underflow."""
    # Length distribution biased toward short and small-mtu frames where
    # parser arithmetic bugs are most likely.
    weights = [(0, 16, 30), (16, 64, 30), (64, 256, 25), (256, 340, 10),
               (340, 1500, 4), (1500, 4096, 1)]
    total = sum(w for *_, w in weights)
    r = rng.randint(1, total)
    acc = 0
    lo, hi = 0, 16
    for a, b, w in weights:
        acc += w
        if r <= acc:
            lo, hi = a, b
            break
    n = rng.randint(lo, max(lo, hi - 1))
    return bytes(rng.randrange(256) for _ in range(n))


# ---------------------------------------------------------------------------
# Frame decoding for crash artefacts
# ---------------------------------------------------------------------------

def _decode_call(addr: bytes) -> tuple[str, int]:
    call = "".join(chr((b >> 1) & 0x7F) for b in addr[:6]).rstrip()
    ssid = (addr[6] >> 1) & 0x0F
    return call, ssid


def describe_frame(frame: bytes) -> str:
    if len(frame) < 14:
        return f"<truncated, {len(frame)} bytes>"
    parts: list[str] = []
    dst = _decode_call(frame[0:7])
    src = _decode_call(frame[7:14])
    parts.append(f"dst={dst[0]}-{dst[1]} src={src[0]}-{src[1]}")
    # Walk digi addresses until end bit
    i = 14
    if not (frame[13] & 0x01):
        while i + 7 <= len(frame):
            digi = _decode_call(frame[i:i + 7])
            parts.append(f"digi={digi[0]}-{digi[1]}")
            stop = bool(frame[i + 6] & 0x01)
            i += 7
            if stop:
                break
    if i >= len(frame):
        return " ".join(parts) + " <no control>"
    ctl = frame[i]
    parts.append(f"ctl=0x{ctl:02X}")
    i += 1
    if (ctl & 0x03) != 0x03 or ctl in (U_UI | 0x00, U_UI | 0x10):
        # I-frame or UI: has PID
        if i < len(frame):
            pid = frame[i]
            parts.append(f"pid=0x{pid:02X}")
            i += 1
    info_len = max(0, len(frame) - i - 2)  # minus FCS if present
    parts.append(f"info_len={info_len}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

@dataclass
class Stats:
    sent: int = 0
    bytes_sent: int = 0
    probes_ok: int = 0
    probes_fail: int = 0
    crashes: int = 0
    started: float = field(default_factory=time.monotonic)

    def rate(self) -> float:
        dt = max(1e-6, time.monotonic() - self.started)
        return self.sent / dt


def health_ok(url: str, timeout: float) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return False


def save_crash(corpus: Path, frame: bytes, *, suffix: str = "") -> Path:
    corpus.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    n = len(list(corpus.glob("crash-*.bin")))
    base = corpus / f"crash-{ts}-{n:04d}{suffix}"
    base.with_suffix(".bin").write_bytes(frame)
    base.with_suffix(".txt").write_text(
        f"length: {len(frame)}\n"
        f"hex   : {frame.hex()}\n"
        f"decode: {describe_frame(frame)}\n"
    )
    return base.with_suffix(".bin")


def save_batch(corpus: Path, batch: list[bytes]) -> Path:
    """Save a batch of frames as one-hex-per-line, for offline bisection."""
    corpus.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    n = len(list(corpus.glob("batch-*.txt")))
    path = corpus / f"batch-{ts}-{n:04d}.txt"
    with path.open("w") as fp:
        for frame in batch:
            fp.write(frame.hex() + "\n")
    return path


def load_batch(path: Path) -> list[bytes]:
    out: list[bytes] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(bytes.fromhex(line))
    return out


def restart_and_wait(restart_cmd: str, health: str, *,
                     probe_timeout: float, boot_grace: float) -> bool:
    """Restart the target, then poll the health URL until it's serving."""
    import subprocess
    subprocess.run(restart_cmd, shell=True, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + boot_grace
    while time.monotonic() < deadline:
        if health_ok(health, probe_timeout):
            return True
        time.sleep(0.25)
    return False


def replay_bisect(batch: list[bytes], sock: socket.socket,
                  target: tuple[str, int], health: str,
                  *, restart_cmd: str, settle: float,
                  probe_timeout: float, boot_grace: float) -> tuple[int, bytes] | None:
    """Binary-search a batch to find a single frame that crashes the target.
    Returns (index_in_batch, frame) or None if not reproducible.
    """
    if not batch:
        return None

    def send_and_check(frames: list[bytes]) -> bool:
        """Return True if target stays alive after sending these frames."""
        if not restart_and_wait(restart_cmd, health,
                                probe_timeout=probe_timeout,
                                boot_grace=boot_grace):
            raise RuntimeError("target failed to come back after restart")
        for f in frames:
            sock.sendto(f, target)
        time.sleep(settle)
        return health_ok(health, probe_timeout)

    # Reproducibility check
    if send_and_check(batch):
        return None

    lo, hi = 0, len(batch)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        first_alive = send_and_check(batch[lo:mid])
        if not first_alive:
            hi = mid
            continue
        second_alive = send_and_check(batch[mid:hi])
        if not second_alive:
            lo = mid
            continue
        # Both halves are individually safe but the union crashed —
        # stateful bug. Bail out with the smallest known-bad range.
        return None
    return lo, batch[lo]


def parse_target(spec: str) -> tuple[str, int]:
    host, _, port = spec.rpartition(":")
    if not host:
        raise ValueError(f"target must be host:port, got {spec!r}")
    return host, int(port)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="AXUDP fuzzer for XRouter.")
    ap.add_argument("--target", required=True, help="host:port (UDP)")
    ap.add_argument("--health", required=True, help="HTTP URL to probe for liveness")
    ap.add_argument("--duration", type=int, default=0,
                    help="seconds to fuzz; 0 = until ctrl-c")
    ap.add_argument("--max-frames", type=int, default=0,
                    help="stop after this many frames; 0 = unbounded")
    ap.add_argument("--probe-every", type=int, default=200,
                    help="run liveness probe every N frames")
    ap.add_argument("--probe-timeout", type=float, default=3.0)
    ap.add_argument("--settle", type=float, default=0.2,
                    help="seconds to wait after a batch before probing")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--rate", type=float, default=0,
                    help="cap frames/sec; 0 = unbounded")
    ap.add_argument("--mutation-bias", type=float, default=0.85,
                    help="fraction of frames built from seed+mutation (vs random garbage)")
    ap.add_argument("--bad-fcs-prob", type=float, default=0.5,
                    help="fraction of frames sent with an intentionally wrong FCS")
    ap.add_argument("--corpus", type=Path, default=Path("fuzz/crashes"),
                    help="directory for crash artefacts and findings.jsonl")
    ap.add_argument("--continue-on-crash", action="store_true",
                    help="keep going after a crash (don't try to bisect)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--replay", type=Path, default=None,
                    help="bisect mode: load a batch dump (one hex frame per line) and "
                         "binary-search it for a minimal crashing frame")
    ap.add_argument("--restart-cmd", default=None,
                    help="shell command to restart the target between bisect trials")
    ap.add_argument("--boot-grace", type=float, default=30.0,
                    help="max seconds to wait for target to come back after restart")
    args = ap.parse_args(argv)

    target = parse_target(args.target)

    if args.replay is not None:
        if not args.restart_cmd:
            ap.error("--replay requires --restart-cmd")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        batch = load_batch(args.replay)
        print(f"[+] replay: {len(batch)} frames from {args.replay}")
        result = replay_bisect(batch, sock, target, args.health,
                               restart_cmd=args.restart_cmd,
                               settle=args.settle,
                               probe_timeout=args.probe_timeout,
                               boot_grace=args.boot_grace)
        if result is None:
            print("[-] crash not reproduced on replay (or stateful interaction)")
            return 2
        idx, frame = result
        path = save_crash(args.corpus, frame, suffix=f"-minimal-idx{idx}")
        print(f"[+] minimal trigger: frame #{idx} ({len(frame)} bytes)")
        print(f"    decode: {describe_frame(frame)}")
        print(f"    saved : {path}")
        return 0

    rng = random.Random(args.seed)
    seed = args.seed if args.seed is not None else rng.randint(0, 2**32 - 1)
    rng.seed(seed)

    seeds = build_seed_corpus()
    if not args.quiet:
        print(f"[+] target = {target[0]}:{target[1]}/udp")
        print(f"[+] health = {args.health}")
        print(f"[+] seeds  = {len(seeds)}  rng-seed = {seed}")
        print(f"[+] corpus = {args.corpus.resolve()}")

    if not health_ok(args.health, args.probe_timeout):
        print(f"[!] health probe failed BEFORE fuzzing — is target up?",
              file=sys.stderr)
        return 2

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stats = Stats()
    args.corpus.mkdir(parents=True, exist_ok=True)
    findings = open(args.corpus / "findings.jsonl", "a", buffering=1)

    deadline = stats.started + args.duration if args.duration else None
    batch: list[bytes] = []
    last_status = stats.started
    rate_token = stats.started

    try:
        while True:
            if deadline and time.monotonic() >= deadline:
                break
            if args.max_frames and stats.sent >= args.max_frames:
                break

            if rng.random() < args.mutation_bias:
                label, base = rng.choice(seeds)
                ax = mutate(base, rng)
            else:
                label, ax = "random", random_garbage(rng)

            if rng.random() < args.bad_fcs_prob:
                # Send a syntactically AX.25-ish frame with random trailing bytes
                # — the parser may or may not check the FCS but should not crash.
                wire = ax + bytes([rng.randrange(256), rng.randrange(256)])
            else:
                wire = with_fcs(ax)

            try:
                sock.sendto(wire, target)
            except OSError as e:
                # Likely "message too long"; try truncating
                if len(wire) > 1472:
                    sock.sendto(wire[:1472], target)
                else:
                    raise
            stats.sent += 1
            stats.bytes_sent += len(wire)
            batch.append(wire)

            if args.rate > 0:
                rate_token += 1.0 / args.rate
                slack = rate_token - time.monotonic()
                if slack > 0:
                    time.sleep(slack)

            if stats.sent % args.probe_every == 0:
                time.sleep(args.settle)
                if health_ok(args.health, args.probe_timeout):
                    stats.probes_ok += 1
                    batch.clear()
                else:
                    stats.probes_fail += 1
                    stats.crashes += 1
                    sample_path = save_batch(args.corpus, batch)
                    finding = {
                        "ts": time.time(),
                        "kind": "health-probe-fail",
                        "frames_in_batch": len(batch),
                        "sent_total": stats.sent,
                        "rng_seed": seed,
                        "last_label": label,
                        "batch_dump": str(sample_path),
                    }
                    findings.write(json.dumps(finding) + "\n")
                    print(f"\n[!] CRASH at frame {stats.sent} "
                          f"(batch of {len(batch)}). Dump: {sample_path}",
                          file=sys.stderr)
                    if args.restart_cmd:
                        ok = restart_and_wait(args.restart_cmd, args.health,
                                              probe_timeout=args.probe_timeout,
                                              boot_grace=args.boot_grace)
                        if not ok:
                            print("[!] target did not come back after restart; "
                                  "stopping.", file=sys.stderr)
                            return 3
                        print(f"[+] target restarted; continuing", file=sys.stderr)
                    elif not args.continue_on_crash:
                        print("[!] Restart the target and re-run with the same "
                              "--seed to reproduce. Pass --restart-cmd to keep "
                              "fuzzing past crashes.", file=sys.stderr)
                        return 3
                    batch.clear()

            now = time.monotonic()
            if not args.quiet and now - last_status >= 5:
                print(f"  sent={stats.sent:>8}  bytes={stats.bytes_sent:>10}  "
                      f"rate={stats.rate():>7.1f}/s  probes_ok={stats.probes_ok}  "
                      f"crashes={stats.crashes}")
                last_status = now

    except KeyboardInterrupt:
        print("\n[+] stopped by user")
    finally:
        findings.close()

    if not args.quiet:
        print(f"\n[+] done. sent={stats.sent} crashes={stats.crashes} "
              f"elapsed={time.monotonic() - stats.started:.1f}s")
    return 1 if stats.crashes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
