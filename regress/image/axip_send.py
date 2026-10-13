#!/usr/bin/env python3
"""Send one AX.25 frame (hex, without FCS) as AXIP (IP protocol 93).

    axip_send.py <src_ip> <dst_ip> <frame_hex>

Run inside the XRouter container: the Linux stack routes dst_ip through the
TUN interface to XRouter, as a datagram from an AMPRNet AXIP partner would
arrive. src_ip must be a local Linux address (the tests add it to lo).
"""
import socket
import sys


def fcs16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


src, dst, frame = sys.argv[1], sys.argv[2], bytes.fromhex(sys.argv[3])
c = fcs16(frame)
s = socket.socket(socket.AF_INET, socket.SOCK_RAW, 93)
s.bind((src, 0))
s.sendto(frame + bytes([c & 0xFF, c >> 8]), (dst, 0))
