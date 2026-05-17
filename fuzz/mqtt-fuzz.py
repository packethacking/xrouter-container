#!/usr/bin/env python3
"""mqtt-fuzz.py -- MQTT broker + xrouter/put/<call>/... control surface fuzzer.

XRouter ships its own MQTT broker (no auth, port MQTTPORT) and also
listens internally on xrouter/put/<NODECALL>/# for remote-control
publications. This script:

1) Hammers the broker by sending raw, partially-malformed MQTT packets
   on the wire (CONNECT, PUBLISH, SUBSCRIBE, PINGREQ, DISCONNECT,
   plus some malformed variants that break the variable-length
   "remaining length" encoding).
2) Sends well-formed PUBLISHes to xrouter/put/<call>/{various subtopics}
   with mutated bodies so the inbound control-message parser sees
   garbage from a "trusted" producer.

No external MQTT client library — raw socket.
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

NODECALL = "G9DUM-1"


def encode_remaining_length(n: int) -> bytes:
    """MQTT remaining length: 1-4 bytes, 7 bits each, MSB = continuation."""
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def utf8_str(s: str | bytes) -> bytes:
    if isinstance(s, str):
        s = s.encode("utf-8")
    return struct.pack(">H", len(s)) + s


def mqtt_connect(client_id: str = "fuzz", protocol_level: int = 4,
                 user: bytes | None = None, password: bytes | None = None,
                 keepalive: int = 60) -> bytes:
    var = utf8_str(b"MQTT") + bytes([protocol_level])
    flags = 0x02   # clean session
    if user is not None: flags |= 0x80
    if password is not None: flags |= 0x40
    var += bytes([flags]) + struct.pack(">H", keepalive)
    payload = utf8_str(client_id)
    if user is not None: payload += utf8_str(user)
    if password is not None: payload += utf8_str(password)
    body = var + payload
    return bytes([0x10]) + encode_remaining_length(len(body)) + body


def mqtt_publish(topic: str, body: bytes, qos: int = 0, retain: bool = False,
                 packet_id: int = 0) -> bytes:
    flags = (1 if retain else 0) | ((qos & 3) << 1)
    var = utf8_str(topic)
    if qos > 0:
        var += struct.pack(">H", packet_id)
    var += body
    return bytes([0x30 | flags]) + encode_remaining_length(len(var)) + var


def mqtt_subscribe(topic: str, packet_id: int = 1, qos: int = 0) -> bytes:
    var = struct.pack(">H", packet_id) + utf8_str(topic) + bytes([qos])
    return bytes([0x82]) + encode_remaining_length(len(var)) + var


def mqtt_pingreq() -> bytes:
    return b"\xC0\x00"


def mqtt_disconnect() -> bytes:
    return b"\xE0\x00"


SEED_TOPICS = [
    f"xrouter/put/{NODECALL}/test",
    f"xrouter/put/{NODECALL}/cmd",
    f"xrouter/put/{NODECALL}/chat/send",
    f"xrouter/put/{NODECALL}/blog/post",
    f"xrouter/put/{NODECALL}/pms/store",
    f"xrouter/put/{NODECALL}/wall/post",
    f"xrouter/put/{NODECALL}/wx/update",
    f"xrouter/put/{NODECALL}/" + "A" * 1024,
    f"xrouter/get/{NODECALL}/status",
    f"xrouter/put//empty-call",
    "xrouter/put/" + "B" * 256 + "/garbage",
    "$SYS/broker/load/messages/received/15min",
    "#",
    "/",
    "",
]


def build_seeds() -> list[tuple[str, bytes]]:
    s: list[tuple[str, bytes]] = []
    s.append(("connect_ok", mqtt_connect("fuzz")))
    s.append(("connect_userpass", mqtt_connect("fuzz", user=b"u", password=b"p")))
    s.append(("connect_huge_id", mqtt_connect("F" * 4000)))
    s.append(("connect_proto3", mqtt_connect("fuzz", protocol_level=3)))
    s.append(("connect_proto255", mqtt_connect("fuzz", protocol_level=0xFF)))
    s.append(("publish_short", mqtt_publish("xrouter/put/G9DUM-1/test", b"hi")))
    s.append(("publish_zerobody", mqtt_publish("xrouter/put/G9DUM-1/test", b"")))
    s.append(("publish_huge", mqtt_publish("xrouter/put/G9DUM-1/test", b"X" * 4000)))
    s.append(("subscribe_hash", mqtt_subscribe("#")))
    s.append(("subscribe_plus", mqtt_subscribe("+/+/+")))
    s.append(("subscribe_huge", mqtt_subscribe("A" * 4000)))
    s.append(("ping", mqtt_pingreq()))
    s.append(("disconnect", mqtt_disconnect()))
    # Malformed: bogus remaining length
    s.append(("bad_remlen", b"\x10\xFF\xFF\xFF\xFF"))  # invalid encoding (>=128 bits)
    s.append(("trunc_connect", b"\x10\x0A\x00\x04MQT"))
    s.append(("zero_remlen_pub", b"\x30\x00"))
    return s


def random_garbage(rng: random.Random) -> bytes:
    n = rng.randint(1, 256)
    return bytes(rng.randrange(256) for _ in range(n))


def mutate(buf: bytes, rng: random.Random) -> bytes:
    a = bytearray(buf)
    rounds = rng.randint(1, 5)
    for _ in range(rounds):
        if not a:
            a = bytearray(rng.randint(0, 32))
            continue
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
            a[i] = rng.choice([0, 0x7F, 0x80, 0xFF])
    return bytes(a)


def fuzz(target: TargetController, mqtt_port: int, *, seed: int,
         duration: int, probe_every: int) -> int:
    rng = random.Random(seed)
    print(f"[+] mqtt target=127.0.0.1:{mqtt_port}  health={target.health_url}  "
          f"seed={seed}")
    if not target.health_ok():
        print("[!] target not healthy before fuzzing", file=sys.stderr)
        return 2

    seeds = build_seeds()
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
            sock = target.tcp_connect(mqtt_port)
            sock.sendall(mqtt_connect(f"fuzz-{rng.randrange(1 << 30)}"))
            try: sock.recv(64)
            except (socket.timeout, OSError): pass
        except (ConnectionRefusedError, OSError):
            sock = None

    reconnect()

    while True:
        if deadline and now() >= deadline:
            break

        if rng.random() < 0.6:
            # Send a structured PUBLISH to a control topic
            topic = rng.choice(SEED_TOPICS)
            body = bytes(rng.randrange(256) for _ in range(rng.randint(0, 200)))
            packet = mqtt_publish(topic, body, qos=rng.choice([0, 1]),
                                  packet_id=rng.randrange(1, 0xFFFF))
            if rng.random() < 0.5:
                packet = mutate(packet, rng)
        elif rng.random() < 0.5:
            label, base = rng.choice(seeds)
            packet = mutate(base, rng)
        else:
            packet = random_garbage(rng)

        if sock is None:
            reconnect()
            if sock is None:
                time.sleep(0.2)
                continue

        try:
            sock.sendall(packet)
            sent += 1
            last_batch.append(packet)
        except OSError:
            sock = None

        if sent and sent % probe_every == 0:
            time.sleep(0.3)
            if not target.health_ok():
                crashes += 1
                trigger = last_batch[-1] if last_batch else None
                target.restart()
                for core in target.collect_cores():
                    info = target.triage(core)
                    if info and target.record_crash(info, trigger=trigger,
                                                    extra={"fuzzer": "mqtt",
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
            print(f"  mqtt sent={sent}  rate={rate:.1f}/s  crashes={crashes}")
            last_status = now()

    print(f"[+] mqtt done. sent={sent}  crashes={crashes}  "
          f"elapsed={now() - started:.1f}s")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="mqtt")
    ap.add_argument("--http-port", type=int, default=18080)
    ap.add_argument("--udp-port", type=int, default=20080)
    ap.add_argument("--mqtt-port", type=int, default=18081)
    ap.add_argument("--duration", type=int, default=0)
    ap.add_argument("--probe-every", type=int, default=400)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)
    seed = args.seed if args.seed is not None else random.randint(0, 2**32 - 1)
    target = TargetController(args.name, args.http_port, args.udp_port)
    return fuzz(target, args.mqtt_port, seed=seed,
                duration=args.duration, probe_every=args.probe_every)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
