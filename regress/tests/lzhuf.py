"""LZHUF as F6FBB's BBS uses it for compressed forwarding (SID flags B and B1).

This is a line-by-line port of the codec in LinFBB's src/lzhuf.c (Yoshizaki's
LZHUF of 1988, adapted by F6FBB in 1990), and `encode` produces the same
bytes as that C code: LZSS with a 2048-byte ring buffer (N), 60-byte
lookahead (F) and THRESHOLD 2, the ring pre-filled with spaces; match
lengths and literals share one adaptive Huffman tree of 314 symbols (rebuilt
when the root count reaches 0x8000); match positions are coded with the
fixed p_len/p_code tables (upper 6 bits) plus 6 literal bits.

Stream layouts, as FBB keeps them on disk (MBINDIR) and sends them:

    B0 ("B" in the SID):  len(4, LE) + huffman code              = encode()
    B1 ("B1" in the SID): crc(2, LE) + len(4, LE) + huffman code = b1_wrap()

`len` is the size of the uncompressed text. `crc` is CRC-16/XMODEM (poly
0x1021, init 0, not reflected, no final xor) over everything after it, i.e.
the 4 length bytes and the code. FBB always writes the B1 form; to a B0
partner it simply starts sending at byte 2.

What FBB compresses for an ASCII message (`fbb_text` reproduces the line
ending part): its own "R:" line, then the stored message text (with earlier
R: lines), every line ending CR LF (stored CRs are dropped, each LF becomes
CR LF). The title is not in the compressed text; it travels in the SOH
header of the block framing (`fbb_blocks`). There is no /EX or Ctrl-Z.

Note FBB never clears the ring between messages, so for the last few bytes of
a message its match search can see bytes left over from the previous one and
pick a different (equally valid) match position. `encode` always starts from
a fresh ring, as a freshly started FBB would; the decoded text is the same
either way, so compare decoded text, not compressed bytes, with a live peer.
"""

from __future__ import annotations

import struct

N = 2048  # ring buffer size
F = 60  # lookahead buffer size
THRESHOLD = 2  # matches longer than this are coded as matches
NIL = N  # "no node" in the search trees

N_CHAR = 256 - THRESHOLD + F  # literals 0..255, then match lengths 3..60
T = N_CHAR * 2 - 1  # Huffman table size
R = T - 1  # root position
MAX_FREQ = 0x8000  # rebuild the tree when the root count gets here

SOH, STX, EOT = 0x01, 0x02, 0x04
FBB_BLOCK = 250  # FBB reads the file 250 bytes at a time per STX block

# upper 6 bits of a match position: code lengths and codes (encoding)
P_LEN = bytes(
    [3] + [4] * 3 + [5] * 8 + [6] * 12 + [7] * 24 + [8] * 16
)
P_CODE = bytes([
    0x00, 0x20, 0x30, 0x40, 0x50, 0x58, 0x60, 0x68,
    0x70, 0x78, 0x80, 0x88, 0x90, 0x94, 0x98, 0x9C,
    0xA0, 0xA4, 0xA8, 0xAC, 0xB0, 0xB4, 0xB8, 0xBC,
    0xC0, 0xC2, 0xC4, 0xC6, 0xC8, 0xCA, 0xCC, 0xCE,
    0xD0, 0xD2, 0xD4, 0xD6, 0xD8, 0xDA, 0xDC, 0xDE,
    0xE0, 0xE2, 0xE4, 0xE6, 0xE8, 0xEA, 0xEC, 0xEE,
    0xF0, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7,
    0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF,
])


def _decode_tables() -> tuple[bytes, bytes]:
    """d_code/d_len (indexed by the next 8 input bits), derived from
    P_LEN/P_CODE; they equal the literal tables in lzhuf.c."""
    d_code = bytearray(256)
    d_len = bytearray(256)
    for upper, (length, code) in enumerate(zip(P_LEN, P_CODE)):
        for b in range(code, code + (1 << (8 - length))):
            d_code[b] = upper
            d_len[b] = length
    return bytes(d_code), bytes(d_len)


D_CODE, D_LEN = _decode_tables()


def crc16_xmodem(data: bytes, crc: int = 0) -> int:
    """CRC-16/XMODEM, FBB's updcrc() from include/crc.h."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


class _Huffman:
    """The adaptive Huffman tree shared by encoder and decoder."""

    def __init__(self) -> None:
        self.freq = [0] * (T + 1)
        self.prnt = [0] * (T + N_CHAR)
        self.son = [0] * T
        for i in range(N_CHAR):
            self.freq[i] = 1
            self.son[i] = i + T
            self.prnt[i + T] = i
        i, j = 0, N_CHAR
        while j <= R:
            self.freq[j] = self.freq[i] + self.freq[i + 1]
            self.son[j] = i
            self.prnt[i] = self.prnt[i + 1] = j
            i += 2
            j += 1
        self.freq[T] = 0xFFFF
        self.prnt[R] = 0

    def _reconst(self) -> None:
        freq, son, prnt = self.freq, self.son, self.prnt
        j = 0
        for i in range(T):
            if son[i] >= T:
                freq[j] = (freq[i] + 1) // 2
                son[j] = son[i]
                j += 1
        i, j = 0, N_CHAR
        while j < T:
            f = freq[j] = freq[i] + freq[i + 1]
            k = j - 1
            while f < freq[k]:
                k -= 1
            k += 1
            freq[k + 1:j + 1] = freq[k:j]
            freq[k] = f
            son[k + 1:j + 1] = son[k:j]
            son[k] = i
            i += 2
            j += 1
        for i in range(T):
            k = son[i]
            if k >= T:
                prnt[k] = i
            else:
                prnt[k] = prnt[k + 1] = i

    def update(self, c: int) -> None:
        """Count one more `c` and restore the sibling property."""
        freq, son, prnt = self.freq, self.son, self.prnt
        if freq[R] == MAX_FREQ:
            self._reconst()
        c = prnt[c + T]
        while True:
            freq[c] += 1
            k = freq[c]
            l = c + 1
            if k > freq[l]:
                l += 1
                while k > freq[l]:
                    l += 1
                l -= 1
                freq[c] = freq[l]
                freq[l] = k
                i = son[c]
                prnt[i] = l
                if i < T:
                    prnt[i + 1] = l
                j = son[l]
                son[l] = i
                prnt[j] = c
                if j < T:
                    prnt[j + 1] = c
                son[c] = j
                c = l
            c = prnt[c]
            if c == 0:
                break


class _BitWriter:
    """Putcode()/EncodeEnd() from lzhuf.c, 16-bit arithmetic included."""

    def __init__(self) -> None:
        self.out = bytearray()
        self.buf = 0
        self.len = 0

    def put(self, nbits: int, code: int) -> None:
        """Append the top `nbits` bits of the 16-bit `code`."""
        self.buf = (self.buf | (code >> self.len)) & 0xFFFF
        self.len += nbits
        if self.len >= 8:
            self.out.append(self.buf >> 8)
            self.len -= 8
            if self.len >= 8:
                self.out.append(self.buf & 0xFF)
                self.len -= 8
                self.buf = (code << (nbits - self.len)) & 0xFFFF
            else:
                self.buf = (self.buf << 8) & 0xFFFF

    def end(self) -> bytes:
        if self.len:
            self.out.append(self.buf >> 8)
        return bytes(self.out)


class _Encoder:
    """Encode() from lzhuf.c with its binary-tree match finder."""

    def __init__(self) -> None:
        self.text = bytearray(N + F - 1)
        self.lson = [NIL] * (N + 1)
        self.rson = [NIL] * (N + 257)
        self.dad = [NIL] * (N + 1)
        self.match_position = 0
        self.match_length = 0
        self.huff = _Huffman()
        self.bits = _BitWriter()

    def insert_node(self, r: int) -> None:
        text, lson, rson, dad = self.text, self.lson, self.rson, self.dad
        cmp = 1
        p = N + 1 + text[r]
        rson[r] = lson[r] = NIL
        self.match_length = 0
        while True:
            if cmp >= 0:
                if rson[p] != NIL:
                    p = rson[p]
                else:
                    rson[p] = r
                    dad[r] = p
                    return
            else:
                if lson[p] != NIL:
                    p = lson[p]
                else:
                    lson[p] = r
                    dad[r] = p
                    return
            i = 1
            while i < F:
                cmp = text[r + i] - text[p + i]
                if cmp:
                    break
                i += 1
            if i > THRESHOLD:
                if i > self.match_length:
                    self.match_position = ((r - p) & (N - 1)) - 1
                    self.match_length = i
                    if i >= F:
                        break
                elif i == self.match_length:
                    c = (((r - p) & (N - 1)) - 1) & 0xFFFF
                    if c < self.match_position:
                        self.match_position = c
        # the new node replaces p, which has an identical F-byte key
        dad[r] = dad[p]
        lson[r] = lson[p]
        rson[r] = rson[p]
        dad[lson[p]] = r
        dad[rson[p]] = r
        if rson[dad[p]] == p:
            rson[dad[p]] = r
        else:
            lson[dad[p]] = r
        dad[p] = NIL

    def delete_node(self, p: int) -> None:
        lson, rson, dad = self.lson, self.rson, self.dad
        if dad[p] == NIL:
            return
        if rson[p] == NIL:
            q = lson[p]
        elif lson[p] == NIL:
            q = rson[p]
        else:
            q = lson[p]
            if rson[q] != NIL:
                while rson[q] != NIL:
                    q = rson[q]
                rson[dad[q]] = lson[q]
                dad[lson[q]] = dad[q]
                lson[q] = lson[p]
                dad[lson[p]] = q
            rson[q] = rson[p]
            dad[rson[p]] = q
        dad[q] = dad[p]
        if rson[dad[p]] == p:
            rson[dad[p]] = q
        else:
            lson[dad[p]] = q
        dad[p] = NIL

    def encode_char(self, c: int) -> None:
        prnt = self.huff.prnt
        code = 0
        nbits = 0
        k = prnt[c + T]
        while True:  # leaf to root, an odd node is the "1" branch
            code >>= 1
            if k & 1:
                code += 0x8000
            nbits += 1
            k = prnt[k]
            if k == R:
                break
        self.bits.put(nbits, code)
        self.huff.update(c)

    def encode_position(self, c: int) -> None:
        i = c >> 6
        self.bits.put(P_LEN[i], P_CODE[i] << 8)
        self.bits.put(6, ((c & 0x3F) << 10) & 0xFFFF)

    def run(self, data: bytes) -> bytes:
        text = self.text
        pos = 0  # next unread byte of `data`
        s = 0
        r = N - F
        for i in range(r):
            text[i] = 0x20
        length = min(F, len(data))
        text[r:r + length] = data[:length]
        pos = length
        for i in range(1, F + 1):
            self.insert_node(r - i)
        self.insert_node(r)
        while True:
            if self.match_length > length:
                self.match_length = length
            if self.match_length <= THRESHOLD:
                self.match_length = 1
                self.encode_char(text[r])
            else:
                self.encode_char(255 - THRESHOLD + self.match_length)
                self.encode_position(self.match_position)
            last_match_length = self.match_length
            i = 0
            while i < last_match_length and pos < len(data):
                c = data[pos]
                pos += 1
                self.delete_node(s)
                text[s] = c
                if s < F - 1:
                    text[s + N] = c
                s = (s + 1) & (N - 1)
                r = (r + 1) & (N - 1)
                self.insert_node(r)
                i += 1
            while i < last_match_length:
                i += 1
                self.delete_node(s)
                s = (s + 1) & (N - 1)
                r = (r + 1) & (N - 1)
                length -= 1
                if length:
                    self.insert_node(r)
            if length <= 0:
                break
        return self.bits.end()


def encode(data: bytes) -> bytes:
    """Compress `data` as is (no line ending changes) to FBB's B0 stream:
    4-byte little-endian length, then the LZHUF code. Like FBB, an empty
    input still codes one (garbage) symbol; FBB refuses length 0 anyway."""
    return struct.pack("<I", len(data)) + _Encoder().run(bytes(data))


def decode(stream: bytes) -> bytes:
    """Expand a B0 stream (4-byte LE length + code) back to the original."""
    if len(stream) < 4:
        raise ValueError("LZHUF stream shorter than its length field")
    (size,) = struct.unpack_from("<I", stream)
    code = stream[4:]
    limit = 8 * len(code) + 16  # FBB reads zeros past the end; we stop
    bitpos = 0

    def get_bits(n: int) -> int:
        nonlocal bitpos
        v = 0
        for _ in range(n):
            byte = bitpos >> 3
            bit = (code[byte] >> (7 - (bitpos & 7))) & 1 if byte < len(code) else 0
            v = (v << 1) | bit
            bitpos += 1
        return v

    huff = _Huffman()
    son = huff.son
    text = bytearray(b" " * N)
    r = N - F
    out = bytearray()
    while len(out) < size:
        if bitpos > limit:
            raise ValueError("LZHUF stream truncated")
        c = son[R]
        while c < T:
            c = son[c + get_bits(1)]
        c -= T
        huff.update(c)
        if c < 256:
            out.append(c)
            text[r] = c
            r = (r + 1) & (N - 1)
        else:
            i = get_bits(8)
            upper = D_CODE[i]
            i = (i << (D_LEN[i] - 2)) | get_bits(D_LEN[i] - 2)
            start = (r - ((upper << 6) | (i & 0x3F)) - 1) & (N - 1)
            for k in range(c - 255 + THRESHOLD):
                b = text[(start + k) & (N - 1)]
                out.append(b)
                text[r] = b
                r = (r + 1) & (N - 1)
    return bytes(out)


def b1_wrap(stream: bytes) -> bytes:
    """B0 stream to B1: prefix the CRC-16/XMODEM of the stream, LE."""
    return struct.pack("<H", crc16_xmodem(stream)) + stream


def b1_unwrap(data: bytes) -> bytes:
    """B1 stream to B0, raising ValueError if the CRC does not match."""
    if len(data) < 6:
        raise ValueError("B1 stream too short")
    (crc,) = struct.unpack_from("<H", data)
    stream = data[2:]
    if crc16_xmodem(stream) != crc:
        raise ValueError(f"B1 CRC mismatch: sent {crc:04x}, computed {crc16_xmodem(stream):04x}")
    return stream


def b1_resume_payload(b1: bytes, offset: int) -> bytes:
    """What FBB sends for a B1 message resumed at `offset` (the peer's "A<n>"
    / "!<n>" answer): the 6 CRC+length bytes, then the B1 stream from byte
    `offset` on. The header carries the same offset. FBB sends the 6 bytes as
    a block of their own; its receiver only needs them first."""
    return b1[:6] + b1[offset:]


def fbb_text(text: bytes) -> bytes:
    """Line endings as FBB's take() feeds text to the compressor: every CR is
    dropped and every LF becomes CR LF (so CR, LF and CR LF lines all end up
    CR LF, and lone CRs vanish)."""
    return text.replace(b"\r", b"").replace(b"\n", b"\r\n")


def fbb_blocks(title: str, payload: bytes, offset: int = 0, block: int = FBB_BLOCK) -> bytes:
    """On-air framing of one compressed message, as FBB's bin_hdr() and
    bloc_message() send it: SOH, header length, title, NUL, offset as "%6d"
    (space padded, as FBB does), NUL; STX blocks of up to `block` bytes (FBB
    uses 250; length byte 0 means 256); EOT and the checksum, the two's
    complement of the sum of all block data bytes, mod 256."""
    if not 1 <= block <= 256:
        raise ValueError("block size must be 1..256")
    hdr = title.encode("latin-1") + b"\0" + b"%6d" % offset + b"\0"
    if len(hdr) > 255:
        raise ValueError("title too long for the SOH header")
    out = bytearray([SOH, len(hdr)]) + hdr
    for i in range(0, len(payload), block):
        chunk = payload[i:i + block]
        out += bytes([STX, len(chunk) & 0xFF]) + chunk
    out += bytes([EOT, -sum(payload) & 0xFF])
    return bytes(out)


def parse_fbb_blocks(raw: bytes) -> tuple[str, int, bytes, bool]:
    """Undo `fbb_blocks`: (title, offset, payload, checksum_ok). Raises
    ValueError if the framing is broken or EOT is missing."""
    if len(raw) < 2 or raw[0] != SOH:
        raise ValueError("does not start with SOH")
    hdr = raw[2:2 + raw[1]]
    if len(hdr) != raw[1]:
        raise ValueError("SOH header truncated")
    title, _, rest = hdr.partition(b"\0")
    off = rest.split(b"\0", 1)[0].strip()
    offset = int(off) if off else 0
    pos = 2 + raw[1]
    payload = bytearray()
    while pos < len(raw):
        kind = raw[pos]
        if pos + 1 >= len(raw):
            break
        n = raw[pos + 1]
        if kind == STX:
            n = n or 256
            chunk = raw[pos + 2:pos + 2 + n]
            if len(chunk) != n:
                raise ValueError("STX block truncated")
            payload += chunk
            pos += 2 + n
        elif kind == EOT:
            return title.decode("latin-1"), offset, bytes(payload), (sum(payload) + n) & 0xFF == 0
        else:
            raise ValueError(f"unexpected frame type {kind:#04x} at {pos}")
    raise ValueError("no EOT")
