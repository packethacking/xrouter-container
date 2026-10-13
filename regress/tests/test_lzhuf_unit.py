"""Unit tests for lzhuf.py (no docker needed: `pytest regress/tests/test_lzhuf_unit.py`).

REF holds what a reference build of LinFBB's own src/lzhuf.c (core copied
verbatim, kuroneko/linfbb mirror of the SourceForge tree, commit 2c2dc7b)
wrote for each input in CASES: the B1 form, CRC-16 + 4-byte length + code,
exactly as FBB keeps it in its MBINDIR file. The big case is stored as a
SHA-256 of that output to keep this file small.
"""

from __future__ import annotations

import hashlib
import os
import struct

import pytest

import lzhuf


def lcg_bytes(n: int, seed: int) -> bytes:
    """Deterministic noise (the C library's old rand() LCG)."""
    out = bytearray()
    x = seed
    for _ in range(n):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        out.append(x >> 16 & 0xFF)
    return bytes(out)


def words(n: int, seed: int) -> bytes:
    """Deterministic text-like input: random picks from a small vocabulary."""
    w = b"CQ DE PN0DUT BBS the quick brown fox jumps over lazy dog 73 QSL R: @ GBR EURO\r\n".split(b" ")
    out = bytearray()
    x = seed
    while len(out) < n:
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        out += w[(x >> 16) % len(w)] + b" "
    return bytes(out[:n])


MSG = (b"R:261013/1200Z @:PN0DUT.#NL.NLD.EURO #:123 [Test] Z:1234\r\n"
       b"\r\nHello from the regress suite.\r\nThis is a test of FBB compressed forwarding.\r\n73\r\n")

CASES = {
    "hello": b"Hello hello hello world\r\n",
    "msg": MSG,
    "allbytes": bytes(range(256)) * 4,
    "random600": lcg_bytes(600, 7),
    "repeat5k": b"CQ CQ DE PN0DUT\r\n" * 300,
    "words6k": words(6000, 3),
    "random40k": lcg_bytes(40000, 11),
}

REF = {
    "hello": (
        "771c19000000ea7c7f187fbd67d2500a0785febdf0cce580"
    ),
    "msg": (
        "63498d000000ef71b7dc2deef3077fbbbd878173cdace662773b577a1e1f06eb"
        "5f6bd8b1ab53694fa3678bdbb8b0a97a9dfcdf3d97c7fe01e9a573020ce06672"
        "d3735d4a1fc4c7edef97fa5ff2fcffd20c92b1fe6e19a06324401faba6eb3a74"
        "f23619755a805ed5427d1c2ddcb2fa5ce786fbdeca7f2744cdfc1aa4e8a06f85"
        "b3aefd462a16f0d34180"
    ),
    "allbytes": (
        "96d700040000c66371d8fc86472593ca6572d97cc667359bce6773d9fd068745"
        "a3d26974da7d46a755abd66b75dafd86c765b3da6d76db7dc6e775bbde6f77db"
        "fe070785c3e27178dc7e472795cbe67379dcfe8747a5d3ea757add7ec767b5db"
        "ee777bddff0787c5e3f2797cde7f47a7d5ebf67b7ddeff87c7e5f3fa7d7edf7f"
        "c7e7f5fbfe7f7fdff000102030405060708090a0b0c0d0e0f101112131415161"
        "718191a1b1c1d1e1f2021222324252627282827262524232221201f1e1d1c1b1"
        "a191817161514131211100f0e0d0c0b0a09080706050403020100ffffbfbfcfd"
        "febf3f8fbfdbebf4f9fcbe3f0f7fbbdbecf5fabd3e8f3f9bcbe4f1f8bc3e0eff"
        "7bbbdcedf6bb3d8ebf5babd4e9f4ba3d0e7f3b9bcce5f2b93c8e3f1b189ff153"
        "fe14ff893fde9ff04ff827fc13fd93fdd3fdd3fdd3fcc27e"
    ),
    "random600": (
        "7b0058020000fc768007b3fb1d76eb7a5ab382959e79e77d7e4b5b088d7b1b30"
        "ceb08fdbf6c910fe93859831f47e9b4a4f1eab91e97aa7f526758773beb9be3f"
        "77954ddf30d11cc671e2104aae4f9317f625731c008f2ab4f842a29357a7cbf7"
        "281849320117c87b525f0cf02b95d0232ce5a89e3964505e2cc38356101be814"
        "cd4c24f8335720c62e0d695ab7a98797ee509fb62334c9cd3a5e197ebed98cba"
        "8624f5ef417b90ed242edd03affe8a107806e9f9ee78ec3824fec91259826b0b"
        "ce7820297fb37abcd2345e827eebd2995e468bd4192d706e480d7ca9dd54a287"
        "0d6f8ada9ee7157b8eaa4e1c4f0dd9ef72cf9af4f27faa083447f2bca9a3c135"
        "710d0b2dc6d79e87e629bc6a739540e9cf8b86a3f6ef1420e78d517088b6c946"
        "0dc62e5d6d7b9e12d3b091e79577458b649e446f82565b821b5226bb72e096d7"
        "2a3959c9c43050bafee46c2bebdc83027b7038cd3da4aca38c1ebaec1ec77cf7"
        "cdb249f9d035a0cf2b5c8356c30b2716ea13c847dddcec93c227a0277cbff951"
        "09ccd16025af3448496ebbcad745ad2926d37c297013613215774c0e67361b80"
        "ca4cfdf07d72e592e9039d5632696d3fc8ee5d597679cb37badd90769b62d82f"
        "014f2b4c8999b46f6ecddc3cf76e99ce9b23a6a0f9ddaa13d831d3933c579b1b"
        "af8672c950d1a77a17208dfc71a09d72f226968c1ba27deb18f2f4a75cea660a"
        "2c24b0767e877dfb991f71fe1565eeee613219fbb9ba7e08d2dfbedfcced45f9"
        "d054bf36aa733c2babd863c9852c1203627c98fa8e81a84b5aed803332c5009b"
        "9830cac15f61c660ee3c986cd5727be72529c799b503a4e8ff13ba5d130e84dc"
        "5dfb5fd11bf5f7f6650bb273ded9e208e134ec7950"
    ),
    "repeat5k": (
        "cde7ec130000e7f763405d0e8eb3b9dade61787c199cb73c217010b410b610b0"
        "216042c085a10a842a10a842a10a842a10a842c1090848424212109084842421"
        "410a085042821410a08504282141061061061061061061061081081081081081"
        "0810810810810810810810810810810810810810810810810810810810810020"
        "0400801002004008210420841082104208410821042084108210b80400"
    ),
    "words6k": (
        "767470170000e8f87bddbcce5b59cc8c00e1f1aff87bfb9f8f68302de833f605"
        "f1ff5cee76b79d0c4f051598b47f407ebeffbc786f9d49df9a1ff959824fd395"
        "2e344544777d3807d2c5ff091f37f3fbb2a16c5100e92deeb09007fabd821f23"
        "1ec603694948823fed53f9fe7fdf174e096746b3f0dac48bc4f7e422e45af820"
        "d190e089e25dc9b2e8f942123687b17c1ea0d74d27398080f9c58b0f9c4b9ff9"
        "cac0159295085b66e35a9064b349310d9956150c4948d28c421520a9454956ba"
        "90259166269479ff13c61a64331711ca3b58b07f82c39969455271812eb060cc"
        "992b1cabc92d282cc65a5a0457d45224ea4300027ea67eaf1743752bd10800b8"
        "18b812ef95e2063cc5fe8999b2f54711500b4cf19c24f1145e5c1e3d0ea7d12d"
        "0efbda3104764501bd11f3e483ca53cefc43253a8f7d94214802efecc50a06f5"
        "7da31e19c635c65ee3ccf3d2d6ea6327c7ff35b60460d09b9523f25ff6da0a63"
        "d9ee0cab40fbeb0b6b6fe478b941941051e4e14a3593211638e9047ba44621b6"
        "4cc7ddf639c11f165b1e850d90ccc4d146fb9aefc731b77f32b5f81bf6adee7d"
        "f521bb2def50f846b5c5a5812c35b0c9fa57ab3ef953ee1284a7685171f75cad"
        "6c67dd20a6e4e38d3f4a76ec0cd5b3e8446c8d6e657c5615cdc7b1b2f7b009ee"
        "8c3f642f99de12d19e944bfaf0ce6a72d44e14136c81e148e297b47974b73ad0"
        "15382b59ffb85dcf7f8170bee198dbc3f1f15b87dc57c6f5323fe530eed13c72"
        "5e97bd8be8cc90dd9cc8f85677688ecbaeb03f7491b077739af9c4e57f6b7bbb"
        "7961dd603355fd73fdc8e1c08d1a657179060ee6778e95284af6034d83ea22f3"
        "08b6b177412eb5f2ee1a7e2985eab8e827eeb5f3b109458b3431b4c84322ad8c"
        "1bc22304d754c64aef1e466d4a40ce98459f018ce9daa8a7c59ca65ee2cbad65"
        "ccf44273eaceca91a2c476cccd258ba95f7c26b005b0c6a1fcec19862ab2d4f2"
        "33345eb4822099bb7556ebb527b3c0f684b73fcd0333a80548822d5674074705"
        "3b5fcfbd4ac1f9ad7958f48c3fbafcc378c56baa08658868536d35f25b4e1dcd"
        "95943228b4288fcf8058b75b6d354e2286eb91fd59665ca12797e8a01706662a"
        "5b3552adf456d24f87f7a3ad3a3f3ac4b61b5aa1e9f45b13af5aaef0d972b350"
        "376ab2c9b150e79828b7a1734ed202ec61c41809b6956091c2e42be1ccf624b8"
        "3b8881704fd44a9b6199d0bbe2069c0d50b5e43a3f5480f32c1b0cda44c66c8f"
        "f64858481a629c2a6e58587bee2671137692913389152a460f679a6054c29dd7"
        "908a8460a951d055a02c631b74484ef7f0b83478f3498c90d7c8f45403e36e79"
        "d7475515c102b3468e688f032a7235272b896642e2489065386a1e9fd102126f"
        "ce0a7e97b44f602e674fd29e7f27a94f1ab32e531304b11779391849713bb91c"
        "2f535c3a5a2d711c2c84ba748c3b041be28b92dfb6d7ccd395d723c42be783e7"
        "4dab6a2266f8f9f35924cbb20658d038db2854c9af375fff70a3e534c949afaf"
        "60405f1d7bba8b85c3bc0d39d3861dc070b908f84109aa6731efe023f7b3b396"
        "894b2774f2960ad98c20e022211b2b0508b638f08563a208e70ca9b8ca607319"
        "28c310c2d07ca8c30b9f838f657709bbd1fad75756a58aff1a339657bbb6768d"
        "df4324c122fabe6738af1b27ed824e34c9944f168e33158bb721957dc619aeb7"
        "979cb886d35bb4719605d27bf679eb1ae5bafac2d1aa13f24a8cdaab6c0cf94d"
        "964b3950b4ba864680e1f3e6ca264c8ea3e035ac72ccce5f6d97f7e58214b48d"
        "60e59a7dc096e63b232ae33b645383262bfe8a029a42a45aaf34ee66f38b2392"
        "be6bcbc64b376f62ac8f0f4feae8cfd87551a43ff4ae976f640a1c86ea722d5b"
        "e8d64776ecb7d1ab0fe4015ab5ab9fdc215b1151ced6a64e0e91ff7cfb21d88f"
        "d549a4d864839d2d65a4ea63aca41d35603ecaf6d7bf17372304d94cd8d93122"
        "3fb1bdf901b47d2833a69fefcf5a3eab2bc3e7edacf5c92420d6f7cbfba42014"
        "4478203c1bf569ec26161bba14e2f74abbf476e91971ee1403e9476c66a10d50"
        "0178dd505e521da012a8ad9b8cd10b76e8f32f1f250f32ca14bc37466cc3a512"
        "e3e2ae4b5925d9e7d6d29c87799d86449f1d236a361913326957eb549c05dd87"
        "65d62f91519345832e16e6bd5d4e5aa9474b8a4f19b7dddde58131c3cf316508"
        "727c6b22feef6a471449f877b0a76f4ec073893f725de5e7b9c3eb152017d782"
        "54ed9b18acf2108d6575cf04d2c6d205bb6d5da6ee76443a599343cad52b0d"
    ),
    "random40k": "sha256:d81633837750dab191f0919557c3668cfba5ac028083b4fd940edbfba151aab5",
}


def ref_stream(name: str) -> bytes:
    return bytes.fromhex(REF[name])


SMALL = [n for n in REF if not REF[n].startswith("sha256:")]


@pytest.mark.parametrize("data", [
    b"", b"A", b"AB", b"ABC", b"\r\n", b" " * 61, b"\x00" * 3000,
    MSG, b"CQ CQ DE PN0DUT\r\n" * 400, os.urandom(5000), lcg_bytes(4500, 1),
], ids=["empty", "1", "2", "3", "crlf", "spaces", "zeros", "msg", "repeat", "urandom", "lcg"])
def test_lzhuf_round_trip(data: bytes) -> None:
    stream = lzhuf.encode(data)
    assert struct.unpack_from("<I", stream)[0] == len(data)
    assert lzhuf.decode(stream) == data
    assert lzhuf.decode(lzhuf.b1_unwrap(lzhuf.b1_wrap(stream))) == data


def test_lzhuf_compresses_text() -> None:
    data = b"CQ CQ DE PN0DUT\r\n" * 400
    assert len(lzhuf.encode(data)) < len(data) // 20


@pytest.mark.parametrize("name", SMALL)
def test_lzhuf_encode_matches_fbb(name: str) -> None:
    assert lzhuf.b1_wrap(lzhuf.encode(CASES[name])) == ref_stream(name)


def test_lzhuf_encode_matches_fbb_large() -> None:
    """40 KB of noise: enough symbols for the Huffman tree to be rebuilt."""
    out = lzhuf.b1_wrap(lzhuf.encode(CASES["random40k"]))
    assert "sha256:" + hashlib.sha256(out).hexdigest() == REF["random40k"]


@pytest.mark.parametrize("name", SMALL)
def test_lzhuf_decode_fbb_stream(name: str) -> None:
    b1 = ref_stream(name)
    assert lzhuf.decode(lzhuf.b1_unwrap(b1)) == CASES[name]
    assert lzhuf.decode(b1[2:]) == CASES[name]  # the B0 form is B1 minus the CRC


def test_lzhuf_b1_crc() -> None:
    """B1 prefix is CRC-16/XMODEM, little-endian, over length + code."""
    assert lzhuf.crc16_xmodem(b"123456789") == 0x31C3
    b1 = ref_stream("hello")
    assert b1[:2] == struct.pack("<H", lzhuf.crc16_xmodem(b1[2:]))
    bad = bytearray(b1)
    bad[-1] ^= 1
    with pytest.raises(ValueError):
        lzhuf.b1_unwrap(bytes(bad))


def test_lzhuf_decode_truncated() -> None:
    stream = lzhuf.encode(lcg_bytes(2000, 5))
    with pytest.raises(ValueError):
        lzhuf.decode(stream[:100])


def test_lzhuf_fbb_text() -> None:
    assert lzhuf.fbb_text(b"a\nb\r\nc\rd") == b"a\r\nb\r\ncd"


def test_lzhuf_blocks_round_trip() -> None:
    payload = lzhuf.b1_wrap(lzhuf.encode(CASES["words6k"]))
    raw = lzhuf.fbb_blocks("Test message", payload)
    assert raw[:2] == bytes([lzhuf.SOH, len("Test message") + 1 + 6 + 1])
    assert raw[2:22] == b"Test message\0     0\0"
    assert raw[22:24] == bytes([lzhuf.STX, 250])
    assert raw[-2] == lzhuf.EOT
    assert (sum(payload) + raw[-1]) & 0xFF == 0
    assert lzhuf.parse_fbb_blocks(raw) == ("Test message", 0, payload, True)


def test_lzhuf_blocks_256_and_offset() -> None:
    payload = bytes(range(256)) * 2 + b"xyz"
    raw = lzhuf.fbb_blocks("T", payload, offset=1234, block=256)
    assert raw[2:2 + raw[1]] == b"T\0  1234\0"
    assert raw[2 + raw[1]:2 + raw[1] + 2] == bytes([lzhuf.STX, 0])  # 0 means 256
    assert lzhuf.parse_fbb_blocks(raw) == ("T", 1234, payload, True)
    broken = raw[:-1] + bytes([(raw[-1] + 1) & 0xFF])
    assert lzhuf.parse_fbb_blocks(broken)[3] is False


def test_lzhuf_blocks_empty_and_errors() -> None:
    raw = lzhuf.fbb_blocks("", b"")
    assert raw == b"\x01\x08\0     0\0\x04\x00"
    assert lzhuf.parse_fbb_blocks(raw) == ("", 0, b"", True)
    with pytest.raises(ValueError):
        lzhuf.parse_fbb_blocks(raw[:-2])  # no EOT
    with pytest.raises(ValueError):
        lzhuf.parse_fbb_blocks(b"\x02\x01x")


def test_lzhuf_b1_resume_payload() -> None:
    b1 = ref_stream("words6k")
    resumed = lzhuf.b1_resume_payload(b1, 500)
    assert resumed[:6] == b1[:6] and resumed[6:] == b1[500:]
