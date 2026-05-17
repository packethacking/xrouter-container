/*
 * axudp-fuzz.c -- generation + mutation fuzzer for XRouter's AX.25/NetRom
 * parsers, delivered over AXUDP. C port of axudp-fuzz.py.
 *
 * Wire format and behaviour match the Python original (see axudp-fuzz.py
 * for the full design notes). The PRNG is xoshiro256** rather than the
 * Python MT19937, so the same --seed produces a different frame sequence
 * across the two implementations. Each implementation is internally
 * deterministic.
 *
 * Build:
 *     cc -O2 -Wall -Wextra -o axudp-fuzz axudp-fuzz.c
 *
 * Dependency-free POSIX C11. Tested on Linux (glibc + musl).
 */

#define _POSIX_C_SOURCE 200809L

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <netdb.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <time.h>
#include <unistd.h>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>

/* ------------------------------------------------------------------ */
/* PRNG: xoshiro256** seeded via splitmix64                           */
/* ------------------------------------------------------------------ */

typedef struct { uint64_t s[4]; } rng_t;

static uint64_t splitmix64(uint64_t *x) {
    uint64_t z = (*x += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static void rng_seed(rng_t *r, uint64_t seed) {
    uint64_t x = seed;
    for (int i = 0; i < 4; i++) r->s[i] = splitmix64(&x);
}

static inline uint64_t rotl(uint64_t x, int k) {
    return (x << k) | (x >> (64 - k));
}

static uint64_t rng_next(rng_t *r) {
    uint64_t result = rotl(r->s[1] * 5, 7) * 9;
    uint64_t t = r->s[1] << 17;
    r->s[2] ^= r->s[0];
    r->s[3] ^= r->s[1];
    r->s[1] ^= r->s[2];
    r->s[0] ^= r->s[3];
    r->s[2] ^= t;
    r->s[3] = rotl(r->s[3], 45);
    return result;
}

/* Uniform in [0, n). */
static uint32_t rng_range(rng_t *r, uint32_t n) {
    if (n == 0) return 0;
    return (uint32_t)(rng_next(r) % n);
}

/* Inclusive [lo, hi]. */
static int rng_int(rng_t *r, int lo, int hi) {
    if (hi < lo) return lo;
    return lo + (int)rng_range(r, (uint32_t)(hi - lo + 1));
}

static double rng_double(rng_t *r) {
    return (rng_next(r) >> 11) * (1.0 / (double)(1ULL << 53));
}

/* ------------------------------------------------------------------ */
/* Dynamic byte buffer                                                */
/* ------------------------------------------------------------------ */

typedef struct {
    uint8_t *data;
    size_t   len;
    size_t   cap;
} buf_t;

static void buf_init(buf_t *b) { b->data = NULL; b->len = 0; b->cap = 0; }
static void buf_free(buf_t *b) { free(b->data); b->data = NULL; b->len = b->cap = 0; }

static void buf_reserve(buf_t *b, size_t need) {
    if (b->cap >= need) return;
    size_t c = b->cap ? b->cap : 32;
    while (c < need) c *= 2;
    uint8_t *p = (uint8_t *)realloc(b->data, c);
    if (!p) { perror("realloc"); exit(2); }
    b->data = p;
    b->cap = c;
}

static void buf_append(buf_t *b, const void *p, size_t n) {
    buf_reserve(b, b->len + n);
    memcpy(b->data + b->len, p, n);
    b->len += n;
}

static void buf_push(buf_t *b, uint8_t v) { buf_append(b, &v, 1); }

static void buf_insert(buf_t *b, size_t pos, const uint8_t *p, size_t n) {
    buf_reserve(b, b->len + n);
    memmove(b->data + pos + n, b->data + pos, b->len - pos);
    memcpy(b->data + pos, p, n);
    b->len += n;
}

static void buf_delete(buf_t *b, size_t pos, size_t n) {
    if (pos + n > b->len) return;
    memmove(b->data + pos, b->data + pos + n, b->len - (pos + n));
    b->len -= n;
}

static buf_t buf_dup(const uint8_t *p, size_t n) {
    buf_t b; buf_init(&b); buf_append(&b, p, n); return b;
}

/* ------------------------------------------------------------------ */
/* AX.25 helpers                                                      */
/* ------------------------------------------------------------------ */

#define PID_ISO8208   0x01
#define PID_IP        0xCC
#define PID_ARP       0xCD
#define PID_NETROM    0xCF
#define PID_NOL3      0xF0
#define PID_ESCAPE    0xFF

#define U_SABM   0x2F
#define U_SABME  0x6F
#define U_DISC   0x43
#define U_DM     0x0F
#define U_UA     0x63
#define U_FRMR   0x87
#define U_UI     0x03
#define U_XID    0xAF
#define U_TEST   0xE3

typedef struct { const char *call; int ssid; } addr_t;

/* Encode one 7-byte AX.25 address subfield. */
static void ax25_address(uint8_t out[7], const char *call, int ssid,
                         bool last, bool cr, bool has_been_repeated) {
    char padded[7];
    size_t n = strlen(call);
    for (int i = 0; i < 6; i++) {
        char c = (i < (int)n) ? call[i] : ' ';
        if (c >= 'a' && c <= 'z') c = (char)(c - 'a' + 'A');
        padded[i] = c;
    }
    for (int i = 0; i < 6; i++)
        out[i] = (uint8_t)((padded[i] << 1) & 0xFE);
    uint8_t ssid_byte = 0x60 | (uint8_t)((ssid & 0x0F) << 1);
    if (last) ssid_byte |= 0x01;
    if (cr)   ssid_byte |= 0x80;
    if (has_been_repeated) ssid_byte |= 0x80;
    out[6] = ssid_byte;
}

static void buf_addr(buf_t *b, const char *call, int ssid,
                     bool last, bool cr) {
    uint8_t a[7];
    ax25_address(a, call, ssid, last, cr, false);
    buf_append(b, a, 7);
}

/* AX.25 FCS: CRC-16-CCITT, polynomial 0x1021 reflected (0x8408). */
static uint16_t crc16_ccitt(const uint8_t *p, size_t n) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < n; i++) {
        crc ^= p[i];
        for (int j = 0; j < 8; j++)
            crc = (crc & 1) ? (uint16_t)((crc >> 1) ^ 0x8408) : (uint16_t)(crc >> 1);
    }
    return (uint16_t)(crc ^ 0xFFFF);
}

static buf_t with_fcs(const uint8_t *frame, size_t n) {
    buf_t b; buf_init(&b);
    buf_append(&b, frame, n);
    uint16_t crc = crc16_ccitt(frame, n);
    buf_push(&b, (uint8_t)(crc & 0xFF));
    buf_push(&b, (uint8_t)((crc >> 8) & 0xFF));
    return b;
}

/* ------------------------------------------------------------------ */
/* Frame templates                                                    */
/* ------------------------------------------------------------------ */

static const addr_t DEFAULT_SRC = { "FUZZER", 7 };
static const addr_t DEFAULT_DST = { "G9DUM",  1 };
static const addr_t NODES_DST   = { "NODES",  0 };
static const addr_t G9DUM0      = { "G9DUM",  0 };
static const addr_t G9DUM1      = { "G9DUM",  1 };

static buf_t ui_frame(addr_t dst, addr_t src, int pid,
                      const uint8_t *info, size_t info_len, bool pf) {
    buf_t b; buf_init(&b);
    buf_addr(&b, dst.call, dst.ssid, false, true);
    buf_addr(&b, src.call, src.ssid, true,  false);
    uint8_t ctl = (uint8_t)(U_UI | (pf ? 0x10 : 0));
    buf_push(&b, ctl);
    buf_push(&b, (uint8_t)pid);
    if (info_len) buf_append(&b, info, info_len);
    return b;
}

static buf_t i_frame(addr_t dst, addr_t src, int ns, int nr, int pid,
                     const uint8_t *info, size_t info_len, bool pf) {
    buf_t b; buf_init(&b);
    buf_addr(&b, dst.call, dst.ssid, false, true);
    buf_addr(&b, src.call, src.ssid, true,  false);
    uint8_t ctl = (uint8_t)(((nr & 7) << 5) | ((pf ? 1 : 0) << 4) | ((ns & 7) << 1));
    buf_push(&b, ctl);
    buf_push(&b, (uint8_t)pid);
    if (info_len) buf_append(&b, info, info_len);
    return b;
}

static buf_t u_frame(addr_t dst, addr_t src, int ctl) {
    buf_t b; buf_init(&b);
    buf_addr(&b, dst.call, dst.ssid, false, true);
    buf_addr(&b, src.call, src.ssid, true,  false);
    buf_push(&b, (uint8_t)ctl);
    return b;
}

static buf_t s_frame(addr_t dst, addr_t src, int code, int nr, bool pf) {
    buf_t b; buf_init(&b);
    buf_addr(&b, dst.call, dst.ssid, false, true);
    buf_addr(&b, src.call, src.ssid, true,  false);
    uint8_t ctl = (uint8_t)(((nr & 7) << 5) | ((pf ? 1 : 0) << 4) | code);
    buf_push(&b, ctl);
    return b;
}

/* ------------------------------------------------------------------ */
/* NetRom L3 / L4                                                     */
/* ------------------------------------------------------------------ */

#define NR_OP_PROTO_EXT 0x00
#define NR_OP_CONREQ    0x01
#define NR_OP_CONACK    0x02
#define NR_OP_DISCREQ   0x03
#define NR_OP_DISCACK   0x04
#define NR_OP_INFO      0x05
#define NR_OP_INFOACK   0x06
#define NR_OP_RESET     0x07
#define NR_FL_MORE      0x20
#define NR_FL_NAK       0x40
#define NR_FL_CHOKE     0x80

static buf_t netrom_l3_header(addr_t src, addr_t dst,
                              int ttl, int idx, int cid,
                              int ns, int nr, int flags) {
    buf_t b; buf_init(&b);
    buf_addr(&b, src.call, src.ssid, false, false);
    buf_addr(&b, dst.call, dst.ssid, false, false);
    buf_push(&b, (uint8_t)(ttl & 0xFF));
    buf_push(&b, (uint8_t)(idx & 0xFF));
    buf_push(&b, (uint8_t)(cid & 0xFF));
    buf_push(&b, (uint8_t)(ns & 0xFF));
    buf_push(&b, (uint8_t)(nr & 0xFF));
    buf_push(&b, (uint8_t)(flags & 0xFF));
    return b;
}

static buf_t netrom_conreq(addr_t src, addr_t dst, int window,
                           addr_t orig, addr_t caller_dst) {
    buf_t b = netrom_l3_header(src, dst, 25, 0, 0, 0, 0, NR_OP_CONREQ);
    buf_push(&b, (uint8_t)(window & 0xFF));
    buf_addr(&b, orig.call, orig.ssid, false, false);
    buf_addr(&b, caller_dst.call, caller_dst.ssid, false, false);
    return b;
}

static buf_t netrom_info(addr_t src, addr_t dst,
                         const uint8_t *payload, size_t plen,
                         int ns, int nr, bool more) {
    int fl = NR_OP_INFO | (more ? NR_FL_MORE : 0);
    buf_t b = netrom_l3_header(src, dst, 25, 0, 0, ns, nr, fl);
    if (plen) buf_append(&b, payload, plen);
    return b;
}

static buf_t netrom_disc(addr_t src, addr_t dst, int idx, int cid) {
    return netrom_l3_header(src, dst, 25, idx, cid, 0, 0, NR_OP_DISCREQ);
}

typedef struct {
    const char *dest_call; int dest_ssid;
    const char *dest_alias;
    const char *nbr_call;  int nbr_ssid;
    int quality;
} nodes_rec_t;

static buf_t nodes_broadcast(const char *origin_alias,
                             const nodes_rec_t *recs, size_t nrecs) {
    buf_t b; buf_init(&b);
    buf_push(&b, 0xFF);
    char alias[6];
    size_t an = strlen(origin_alias);
    for (int i = 0; i < 6; i++) {
        char c = (i < (int)an) ? origin_alias[i] : ' ';
        if (c >= 'a' && c <= 'z') c = (char)(c - 'a' + 'A');
        alias[i] = c;
    }
    buf_append(&b, alias, 6);
    for (size_t i = 0; i < nrecs; i++) {
        const nodes_rec_t *r = &recs[i];
        buf_addr(&b, r->dest_call, r->dest_ssid, false, false);
        char da[6];
        size_t dan = strlen(r->dest_alias);
        for (int k = 0; k < 6; k++) {
            char c = (k < (int)dan) ? r->dest_alias[k] : ' ';
            if (c >= 'a' && c <= 'z') c = (char)(c - 'a' + 'A');
            da[k] = c;
        }
        buf_append(&b, da, 6);
        buf_addr(&b, r->nbr_call, r->nbr_ssid, false, false);
        buf_push(&b, (uint8_t)(r->quality & 0xFF));
    }
    return b;
}

/* ------------------------------------------------------------------ */
/* Seed corpus                                                        */
/* ------------------------------------------------------------------ */

typedef struct {
    const char *label;
    uint8_t *data;
    size_t   len;
} seed_t;

static void seed_push(seed_t **vec, size_t *n, size_t *cap,
                      const char *label, buf_t b) {
    if (*n == *cap) {
        *cap = *cap ? *cap * 2 : 16;
        *vec = (seed_t *)realloc(*vec, *cap * sizeof **vec);
        if (!*vec) { perror("realloc"); exit(2); }
    }
    (*vec)[*n].label = label;
    (*vec)[*n].data  = b.data;       /* take ownership */
    (*vec)[*n].len   = b.len;
    (*n)++;
}

/* Build a UI frame wrapping a netrom payload, then take its bytes. */
static buf_t ui_wrap(addr_t dst, addr_t src, const buf_t *payload) {
    return ui_frame(dst, src, PID_NETROM, payload->data, payload->len, false);
}

static int hex_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return 10 + c - 'a';
    if (c >= 'A' && c <= 'F') return 10 + c - 'A';
    return -1;
}

static buf_t from_hex(const char *s) {
    buf_t b; buf_init(&b);
    size_t n = strlen(s);
    for (size_t i = 0; i + 1 < n; i += 2) {
        int hi = hex_nibble(s[i]);
        int lo = hex_nibble(s[i+1]);
        if (hi < 0 || lo < 0) break;
        buf_push(&b, (uint8_t)((hi << 4) | lo));
    }
    return b;
}

static void build_seed_corpus(seed_t **out, size_t *out_n) {
    seed_t *v = NULL; size_t n = 0, cap = 0;

    seed_push(&v, &n, &cap, "ax25_sabm",  u_frame(DEFAULT_DST, DEFAULT_SRC, U_SABM));
    seed_push(&v, &n, &cap, "ax25_sabme", u_frame(DEFAULT_DST, DEFAULT_SRC, U_SABME));
    seed_push(&v, &n, &cap, "ax25_disc",  u_frame(DEFAULT_DST, DEFAULT_SRC, U_DISC));
    seed_push(&v, &n, &cap, "ax25_ua",    u_frame(DEFAULT_DST, DEFAULT_SRC, U_UA));
    seed_push(&v, &n, &cap, "ax25_dm",    u_frame(DEFAULT_DST, DEFAULT_SRC, U_DM));

    {
        buf_t f = u_frame(DEFAULT_DST, DEFAULT_SRC, U_TEST);
        buf_append(&f, "TESTDATA", 8);
        seed_push(&v, &n, &cap, "ax25_test", f);
    }
    {
        buf_t f = u_frame(DEFAULT_DST, DEFAULT_SRC, U_XID);
        buf_append(&f, "\x82\x80\x00", 3);
        seed_push(&v, &n, &cap, "ax25_xid", f);
    }
    {
        buf_t f = u_frame(DEFAULT_DST, DEFAULT_SRC, U_FRMR);
        buf_append(&f, "\x00\x00\x00", 3);
        seed_push(&v, &n, &cap, "ax25_frmr", f);
    }

    seed_push(&v, &n, &cap, "ax25_rr_nr0",  s_frame(DEFAULT_DST, DEFAULT_SRC, 0x01, 0, false));
    seed_push(&v, &n, &cap, "ax25_rnr_nr3", s_frame(DEFAULT_DST, DEFAULT_SRC, 0x05, 3, false));
    seed_push(&v, &n, &cap, "ax25_rej_nr7", s_frame(DEFAULT_DST, DEFAULT_SRC, 0x09, 7, false));

    seed_push(&v, &n, &cap, "ax25_i_short",
              i_frame(DEFAULT_DST, DEFAULT_SRC, 0, 0, PID_NOL3,
                      (const uint8_t *)"hello", 5, false));
    {
        uint8_t big[250]; memset(big, 'A', sizeof big);
        seed_push(&v, &n, &cap, "ax25_i_big",
                  i_frame(DEFAULT_DST, DEFAULT_SRC, 3, 1, PID_NOL3, big, sizeof big, false));
    }
    seed_push(&v, &n, &cap, "ax25_ui_text",
              ui_frame(DEFAULT_DST, DEFAULT_SRC, PID_NOL3,
                       (const uint8_t *)"CQ CQ DE FUZZER", 15, false));

    /* NetRom L3/L4 carried in UI/PID-0xCF */
    {
        buf_t p = netrom_conreq(DEFAULT_SRC, G9DUM1, 4, DEFAULT_SRC, DEFAULT_DST);
        buf_t f = ui_wrap(G9DUM0, DEFAULT_SRC, &p);
        buf_free(&p);
        seed_push(&v, &n, &cap, "nr_l4_conreq", f);
    }
    {
        buf_t p = netrom_info(DEFAULT_SRC, G9DUM1,
                              (const uint8_t *)"netrom payload", 14, 0, 0, false);
        buf_t f = ui_wrap(G9DUM0, DEFAULT_SRC, &p);
        buf_free(&p);
        seed_push(&v, &n, &cap, "nr_l4_info", f);
    }
    {
        buf_t p = netrom_disc(DEFAULT_SRC, G9DUM1, 0, 0);
        buf_t f = ui_wrap(G9DUM0, DEFAULT_SRC, &p);
        buf_free(&p);
        seed_push(&v, &n, &cap, "nr_l4_disc", f);
    }
    {
        buf_t p = netrom_l3_header(DEFAULT_SRC, G9DUM1, 25, 0, 0, 0, 0, NR_OP_RESET);
        buf_t f = ui_wrap(G9DUM0, DEFAULT_SRC, &p);
        buf_free(&p);
        seed_push(&v, &n, &cap, "nr_l4_reset", f);
    }

    {
        nodes_rec_t recs[] = {
            { "G8PZT", 0, "KIDDER", "G8PZT", 0, 200 },
            { "VK1UDP", 7, "VKDOT", "VK1UDP", 7, 180 },
        };
        buf_t p = nodes_broadcast("FUZZRX", recs, sizeof recs / sizeof recs[0]);
        buf_t f = ui_wrap(NODES_DST, DEFAULT_SRC, &p);
        buf_free(&p);
        seed_push(&v, &n, &cap, "nr_nodes_bc", f);
    }

    /* Sore spots */
    {
        buf_t f; buf_init(&f);
        buf_addr(&f, DEFAULT_DST.call, DEFAULT_DST.ssid, false, true);
        buf_addr(&f, DEFAULT_SRC.call, DEFAULT_SRC.ssid, false, false);
        buf_push(&f, U_UI);
        buf_push(&f, PID_NOL3);
        buf_push(&f, 'x');
        seed_push(&v, &n, &cap, "ax25_no_end_bit", f);
    }
    {
        buf_t f; buf_init(&f);
        buf_addr(&f, DEFAULT_DST.call, DEFAULT_DST.ssid, false, true);
        buf_addr(&f, DEFAULT_SRC.call, DEFAULT_SRC.ssid, false, false);
        for (int i = 0; i < 7; i++) {
            char nm[8]; snprintf(nm, sizeof nm, "DIGI%d", i);
            buf_addr(&f, nm, i, false, false);
        }
        buf_addr(&f, "DIGI8", 8, true, false);
        buf_push(&f, U_UI);
        buf_push(&f, PID_NOL3);
        buf_push(&f, 'x');
        seed_push(&v, &n, &cap, "ax25_max_digis", f);
    }
    {
        buf_t f; buf_init(&f);
        const uint8_t bytes[] = { 0x82, 0x84, 0x66, 0x40, 0x40, 0x40, 0xE0 };
        buf_append(&f, bytes, sizeof bytes);
        seed_push(&v, &n, &cap, "ax25_truncated_addr", f);
    }
    {
        buf_t f; buf_init(&f);
        seed_push(&v, &n, &cap, "ax25_empty", f);
    }

    /* Known regression: ARP-over-AX.25 short, segfaults 504p..505c */
    {
        buf_t f = from_hex(
            "8e7288aa9a40e08caab4b48aa46f"
            "03cd"
            "8caab4b48aa46e8e7288aa9a4062190000000003");
        seed_push(&v, &n, &cap, "arp_short_segfault", f);
    }

    *out = v;
    *out_n = n;
}

static void free_seeds(seed_t *v, size_t n) {
    for (size_t i = 0; i < n; i++) free(v[i].data);
    free(v);
}

/* ------------------------------------------------------------------ */
/* Mutators                                                           */
/* ------------------------------------------------------------------ */

static const uint8_t MAGIC_VALUES[] = {
    0, 1, 2, 3, 0x7F, 0x80, 0xFE, 0xFF,
    0x10, 0x40, 0x60, 0xC0,
    PID_NETROM, PID_IP, PID_ARP, PID_NOL3,
    U_UI, U_SABM, U_DISC, U_UA, U_DM, U_FRMR, U_XID, U_TEST,
    NR_OP_CONREQ, NR_OP_INFO, NR_OP_DISCREQ, NR_OP_RESET,
};
#define MAGIC_N (sizeof MAGIC_VALUES / sizeof MAGIC_VALUES[0])

static void m_bit_flip(buf_t *b, rng_t *r) {
    if (!b->len) return;
    size_t i = rng_range(r, (uint32_t)b->len);
    b->data[i] ^= (uint8_t)(1u << rng_range(r, 8));
}
static void m_byte_replace(buf_t *b, rng_t *r) {
    if (!b->len) return;
    size_t i = rng_range(r, (uint32_t)b->len);
    b->data[i] = (uint8_t)rng_range(r, 256);
}
static void m_magic(buf_t *b, rng_t *r) {
    if (!b->len) return;
    size_t i = rng_range(r, (uint32_t)b->len);
    b->data[i] = MAGIC_VALUES[rng_range(r, MAGIC_N)];
}
static void m_insert(buf_t *b, rng_t *r) {
    if (b->len > 1024) return;
    int n = rng_int(r, 1, 8);
    size_t pos = b->len ? rng_range(r, (uint32_t)(b->len + 1)) : 0;
    uint8_t tmp[8];
    for (int i = 0; i < n; i++) tmp[i] = (uint8_t)rng_range(r, 256);
    buf_insert(b, pos, tmp, (size_t)n);
}
static void m_delete(buf_t *b, rng_t *r) {
    if (b->len < 2) return;
    int maxn = (int)b->len - 1; if (maxn > 8) maxn = 8;
    int n = rng_int(r, 1, maxn);
    size_t pos = rng_range(r, (uint32_t)(b->len - n + 1));
    buf_delete(b, pos, (size_t)n);
}
static void m_duplicate(buf_t *b, rng_t *r) {
    if (b->len < 2 || b->len > 800) return;
    int maxn = (int)(b->len / 2); if (maxn > 16) maxn = 16; if (maxn < 1) maxn = 1;
    int n = rng_int(r, 1, maxn);
    size_t src = rng_range(r, (uint32_t)(b->len - n + 1));
    size_t dst = rng_range(r, (uint32_t)(b->len + 1));
    /* Snapshot first since insert may realloc. */
    uint8_t tmp[16];
    memcpy(tmp, b->data + src, (size_t)n);
    buf_insert(b, dst, tmp, (size_t)n);
}
static void m_chunk_random(buf_t *b, rng_t *r) {
    if (b->len < 2) return;
    int maxn = (int)b->len; if (maxn > 16) maxn = 16;
    int n = rng_int(r, 1, maxn);
    size_t pos = rng_range(r, (uint32_t)(b->len - n + 1));
    for (int k = 0; k < n; k++) b->data[pos + k] = (uint8_t)rng_range(r, 256);
}

typedef void (*mutator_fn)(buf_t *, rng_t *);
static const mutator_fn MUTATORS[] = {
    m_bit_flip, m_byte_replace, m_magic, m_insert,
    m_delete, m_duplicate, m_chunk_random,
};
#define MUT_N (sizeof MUTATORS / sizeof MUTATORS[0])

static buf_t mutate(const uint8_t *seed, size_t n, rng_t *r) {
    buf_t b = buf_dup(seed, n);
    int rounds = rng_int(r, 1, 6);
    for (int i = 0; i < rounds; i++) MUTATORS[rng_range(r, MUT_N)](&b, r);
    return b;
}

static buf_t random_garbage(rng_t *r) {
    /* Length distribution matching the Python weights. */
    static const int lo_hi_w[][3] = {
        {0, 16, 30}, {16, 64, 30}, {64, 256, 25}, {256, 340, 10},
        {340, 1500, 4}, {1500, 4096, 1},
    };
    const int N = (int)(sizeof lo_hi_w / sizeof lo_hi_w[0]);
    int total = 0;
    for (int i = 0; i < N; i++) total += lo_hi_w[i][2];
    int rr = rng_int(r, 1, total);
    int acc = 0, lo = 0, hi = 16;
    for (int i = 0; i < N; i++) {
        acc += lo_hi_w[i][2];
        if (rr <= acc) { lo = lo_hi_w[i][0]; hi = lo_hi_w[i][1]; break; }
    }
    int n = rng_int(r, lo, hi - 1 >= lo ? hi - 1 : lo);
    buf_t b; buf_init(&b);
    buf_reserve(&b, (size_t)n);
    for (int i = 0; i < n; i++) buf_push(&b, (uint8_t)rng_range(r, 256));
    return b;
}

/* ------------------------------------------------------------------ */
/* Frame description for crash artefacts                              */
/* ------------------------------------------------------------------ */

static void decode_call(const uint8_t a[7], char call[7], int *ssid) {
    for (int i = 0; i < 6; i++) call[i] = (char)((a[i] >> 1) & 0x7F);
    call[6] = 0;
    int end = 5;
    while (end >= 0 && call[end] == ' ') call[end--] = 0;
    *ssid = (a[6] >> 1) & 0x0F;
}

static void describe_frame(const uint8_t *f, size_t n, char *out, size_t out_n) {
    size_t pos = 0;
    #define APPEND(...) do { \
        int _r = snprintf(out + pos, out_n - pos, __VA_ARGS__); \
        if (_r < 0) return; \
        if ((size_t)_r >= out_n - pos) { pos = out_n - 1; return; } \
        pos += (size_t)_r; \
    } while (0)

    if (n < 14) { APPEND("<truncated, %zu bytes>", n); return; }
    char dc[7], sc[7]; int dssid, sssid;
    decode_call(f, dc, &dssid);
    decode_call(f + 7, sc, &sssid);
    APPEND("dst=%s-%d src=%s-%d", dc, dssid, sc, sssid);

    size_t i = 14;
    if (!(f[13] & 0x01)) {
        while (i + 7 <= n) {
            char dg[7]; int ds;
            decode_call(f + i, dg, &ds);
            APPEND(" digi=%s-%d", dg, ds);
            bool stop = (f[i + 6] & 0x01) != 0;
            i += 7;
            if (stop) break;
        }
    }
    if (i >= n) { APPEND(" <no control>"); return; }
    uint8_t ctl = f[i];
    APPEND(" ctl=0x%02X", ctl);
    i++;
    bool has_pid = ((ctl & 0x03) != 0x03) || ctl == U_UI || ctl == (U_UI | 0x10);
    if (has_pid && i < n) {
        APPEND(" pid=0x%02X", f[i]);
        i++;
    }
    long info_len = (long)n - (long)i - 2;
    if (info_len < 0) info_len = 0;
    APPEND(" info_len=%ld", info_len);
    #undef APPEND
}

/* ------------------------------------------------------------------ */
/* Time / filesystem helpers                                          */
/* ------------------------------------------------------------------ */

static double mono_now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

static void mono_sleep(double sec) {
    if (sec <= 0) return;
    struct timespec ts;
    ts.tv_sec  = (time_t)sec;
    ts.tv_nsec = (long)((sec - ts.tv_sec) * 1e9);
    nanosleep(&ts, NULL);
}

static int mkdir_p(const char *path) {
    char tmp[1024];
    size_t n = strlen(path);
    if (n >= sizeof tmp) return -1;
    memcpy(tmp, path, n + 1);
    for (size_t i = 1; i < n; i++) {
        if (tmp[i] == '/') {
            tmp[i] = 0;
            if (mkdir(tmp, 0755) < 0 && errno != EEXIST) return -1;
            tmp[i] = '/';
        }
    }
    if (mkdir(tmp, 0755) < 0 && errno != EEXIST) return -1;
    return 0;
}

static int count_glob(const char *dir, const char *prefix, const char *suffix) {
    DIR *d = opendir(dir);
    if (!d) return 0;
    int n = 0;
    struct dirent *de;
    size_t plen = strlen(prefix), slen = strlen(suffix);
    while ((de = readdir(d))) {
        size_t nl = strlen(de->d_name);
        if (nl < plen + slen) continue;
        if (memcmp(de->d_name, prefix, plen) != 0) continue;
        if (memcmp(de->d_name + nl - slen, suffix, slen) != 0) continue;
        n++;
    }
    closedir(d);
    return n;
}

static void timestamp(char out[16]) {
    time_t t = time(NULL);
    struct tm tm;
    localtime_r(&t, &tm);
    strftime(out, 16, "%Y%m%d-%H%M%S", &tm);
}

static void hexdump_line(const uint8_t *p, size_t n, FILE *fp) {
    static const char hx[] = "0123456789abcdef";
    for (size_t i = 0; i < n; i++) {
        fputc(hx[p[i] >> 4], fp);
        fputc(hx[p[i] & 0xF], fp);
    }
}

static char *save_crash(const char *corpus, const uint8_t *frame, size_t n,
                        const char *suffix) {
    mkdir_p(corpus);
    char ts[16]; timestamp(ts);
    int idx = count_glob(corpus, "crash-", ".bin");
    char *base = (char *)malloc(strlen(corpus) + 64 + strlen(suffix));
    sprintf(base, "%s/crash-%s-%04d%s", corpus, ts, idx, suffix);

    char path[1280];
    snprintf(path, sizeof path, "%s.bin", base);
    FILE *fp = fopen(path, "wb");
    if (fp) { fwrite(frame, 1, n, fp); fclose(fp); }

    snprintf(path, sizeof path, "%s.txt", base);
    fp = fopen(path, "w");
    if (fp) {
        char dec[1024];
        describe_frame(frame, n, dec, sizeof dec);
        fprintf(fp, "length: %zu\n", n);
        fprintf(fp, "hex   : ");
        hexdump_line(frame, n, fp);
        fputc('\n', fp);
        fprintf(fp, "decode: %s\n", dec);
        fclose(fp);
    }

    char *binpath = (char *)malloc(strlen(base) + 8);
    sprintf(binpath, "%s.bin", base);
    free(base);
    return binpath;
}

static char *save_batch(const char *corpus, buf_t *batch, size_t batch_n) {
    mkdir_p(corpus);
    char ts[16]; timestamp(ts);
    int idx = count_glob(corpus, "batch-", ".txt");
    char *path = (char *)malloc(strlen(corpus) + 64);
    sprintf(path, "%s/batch-%s-%04d.txt", corpus, ts, idx);
    FILE *fp = fopen(path, "w");
    if (fp) {
        for (size_t i = 0; i < batch_n; i++) {
            hexdump_line(batch[i].data, batch[i].len, fp);
            fputc('\n', fp);
        }
        fclose(fp);
    }
    return path;
}

static int load_batch(const char *path, buf_t **out_vec, size_t *out_n) {
    FILE *fp = fopen(path, "r");
    if (!fp) return -1;
    buf_t *vec = NULL; size_t n = 0, cap = 0;
    char line[16384];
    while (fgets(line, sizeof line, fp)) {
        char *p = line;
        while (*p == ' ' || *p == '\t') p++;
        if (*p == '#' || *p == '\n' || *p == 0) continue;
        size_t L = strlen(p);
        while (L && (p[L-1] == '\n' || p[L-1] == '\r' || p[L-1] == ' ')) p[--L] = 0;
        buf_t b = from_hex(p);
        if (n == cap) {
            cap = cap ? cap * 2 : 16;
            vec = (buf_t *)realloc(vec, cap * sizeof *vec);
        }
        vec[n++] = b;
    }
    fclose(fp);
    *out_vec = vec;
    *out_n   = n;
    return 0;
}

/* ------------------------------------------------------------------ */
/* HTTP health probe                                                  */
/* ------------------------------------------------------------------ */

typedef struct {
    char host[256];
    int  port;
    char path[512];
} url_t;

static int parse_url(const char *url, url_t *out) {
    const char *p = url;
    if (strncasecmp(p, "http://", 7) == 0) p += 7;
    else if (strncasecmp(p, "https://", 8) == 0) return -1;  /* not supported */
    const char *slash = strchr(p, '/');
    const char *colon = strchr(p, ':');
    const char *host_end = slash;
    if (!host_end) host_end = p + strlen(p);
    if (colon && colon < host_end) {
        size_t hl = (size_t)(colon - p);
        if (hl >= sizeof out->host) hl = sizeof out->host - 1;
        memcpy(out->host, p, hl);
        out->host[hl] = 0;
        out->port = atoi(colon + 1);
        if (out->port <= 0) out->port = 80;
    } else {
        size_t hl = (size_t)(host_end - p);
        if (hl >= sizeof out->host) hl = sizeof out->host - 1;
        memcpy(out->host, p, hl);
        out->host[hl] = 0;
        out->port = 80;
    }
    if (slash) {
        size_t pl = strlen(slash);
        if (pl >= sizeof out->path) pl = sizeof out->path - 1;
        memcpy(out->path, slash, pl);
        out->path[pl] = 0;
    } else {
        strcpy(out->path, "/");
    }
    return 0;
}

static bool health_ok(const url_t *u, double timeout) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return false;

    struct timeval tv;
    tv.tv_sec  = (time_t)timeout;
    tv.tv_usec = (long)((timeout - tv.tv_sec) * 1e6);
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);

    struct addrinfo hints, *res = NULL;
    memset(&hints, 0, sizeof hints);
    hints.ai_family   = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    char portstr[16]; snprintf(portstr, sizeof portstr, "%d", u->port);
    if (getaddrinfo(u->host, portstr, &hints, &res) != 0) {
        close(fd); return false;
    }

    /* Non-blocking connect with timeout. */
    int flags = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    int cr = connect(fd, res->ai_addr, res->ai_addrlen);
    if (cr < 0 && errno != EINPROGRESS) {
        freeaddrinfo(res); close(fd); return false;
    }
    if (cr < 0) {
        fd_set wf; FD_ZERO(&wf); FD_SET(fd, &wf);
        struct timeval to = tv;
        if (select(fd + 1, NULL, &wf, NULL, &to) <= 0) {
            freeaddrinfo(res); close(fd); return false;
        }
        int err = 0; socklen_t el = sizeof err;
        getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &el);
        if (err) { freeaddrinfo(res); close(fd); return false; }
    }
    freeaddrinfo(res);
    fcntl(fd, F_SETFL, flags);

    char req[1024];
    int rl = snprintf(req, sizeof req,
                      "GET %s HTTP/1.0\r\nHost: %s:%d\r\n"
                      "User-Agent: axudp-fuzz/1\r\nConnection: close\r\n\r\n",
                      u->path, u->host, u->port);
    if (send(fd, req, (size_t)rl, 0) != rl) { close(fd); return false; }

    char buf[256];
    ssize_t got = 0, total = 0;
    while (total < (ssize_t)sizeof buf - 1 &&
           (got = recv(fd, buf + total, sizeof buf - 1 - (size_t)total, 0)) > 0) {
        total += got;
        if (total >= 12) break;  /* enough for status line */
    }
    close(fd);
    if (total < 12) return false;
    buf[total] = 0;
    /* Expect "HTTP/1.x SSS ..." */
    if (memcmp(buf, "HTTP/", 5) != 0) return false;
    char *sp = strchr(buf, ' ');
    if (!sp) return false;
    int status = atoi(sp + 1);
    return status >= 200 && status < 500;
}

/* ------------------------------------------------------------------ */
/* Restart + replay/bisect                                            */
/* ------------------------------------------------------------------ */

static bool restart_and_wait(const char *cmd, const url_t *health,
                             double probe_timeout, double boot_grace) {
    int rc = system(cmd);
    (void)rc;
    double deadline = mono_now() + boot_grace;
    while (mono_now() < deadline) {
        if (health_ok(health, probe_timeout)) return true;
        mono_sleep(0.25);
    }
    return false;
}

typedef struct {
    int fd;
    struct sockaddr_in to;
} udp_t;

static int udp_open(udp_t *u, const char *host, int port) {
    u->fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (u->fd < 0) return -1;
    memset(&u->to, 0, sizeof u->to);
    u->to.sin_family = AF_INET;
    u->to.sin_port = htons((uint16_t)port);
    struct addrinfo hints, *res = NULL;
    memset(&hints, 0, sizeof hints);
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_DGRAM;
    char ps[16]; snprintf(ps, sizeof ps, "%d", port);
    if (getaddrinfo(host, ps, &hints, &res) != 0) return -1;
    memcpy(&u->to, res->ai_addr, sizeof u->to);
    freeaddrinfo(res);
    return 0;
}

static int udp_send(udp_t *u, const uint8_t *p, size_t n) {
    ssize_t r = sendto(u->fd, p, n, 0, (struct sockaddr *)&u->to, sizeof u->to);
    if (r < 0 && n > 1472) {
        r = sendto(u->fd, p, 1472, 0, (struct sockaddr *)&u->to, sizeof u->to);
    }
    return r < 0 ? -1 : 0;
}

typedef struct {
    int  idx;
    buf_t frame;
    bool ok;
} bisect_result_t;

static bool replay_send_and_check(udp_t *u, const buf_t *frames, size_t n,
                                  const url_t *health, const char *restart_cmd,
                                  double settle, double probe_timeout,
                                  double boot_grace) {
    if (!restart_and_wait(restart_cmd, health, probe_timeout, boot_grace)) {
        fprintf(stderr, "[!] target failed to come back after restart\n");
        exit(3);
    }
    for (size_t i = 0; i < n; i++) udp_send(u, frames[i].data, frames[i].len);
    mono_sleep(settle);
    return health_ok(health, probe_timeout);
}

static bisect_result_t replay_bisect(buf_t *batch, size_t bn, udp_t *u,
                                     const url_t *health, const char *restart_cmd,
                                     double settle, double probe_timeout,
                                     double boot_grace) {
    bisect_result_t res = { -1, {NULL,0,0}, false };
    if (bn == 0) return res;
    if (replay_send_and_check(u, batch, bn, health, restart_cmd,
                              settle, probe_timeout, boot_grace)) {
        return res;  /* not reproducible */
    }
    size_t lo = 0, hi = bn;
    while (hi - lo > 1) {
        size_t mid = (lo + hi) / 2;
        bool first_alive = replay_send_and_check(u, batch + lo, mid - lo,
                                                 health, restart_cmd, settle,
                                                 probe_timeout, boot_grace);
        if (!first_alive) { hi = mid; continue; }
        bool second_alive = replay_send_and_check(u, batch + mid, hi - mid,
                                                  health, restart_cmd, settle,
                                                  probe_timeout, boot_grace);
        if (!second_alive) { lo = mid; continue; }
        /* stateful */
        return res;
    }
    res.idx = (int)lo;
    res.frame = buf_dup(batch[lo].data, batch[lo].len);
    res.ok = true;
    return res;
}

/* ------------------------------------------------------------------ */
/* Driver                                                             */
/* ------------------------------------------------------------------ */

typedef struct {
    const char *target;
    const char *health;
    int    duration;
    int    max_frames;
    int    probe_every;
    double probe_timeout;
    double settle;
    int64_t seed;       /* -1 = unset */
    double rate;
    double mutation_bias;
    double bad_fcs_prob;
    const char *corpus;
    bool   continue_on_crash;
    bool   quiet;
    const char *replay;
    const char *restart_cmd;
    double boot_grace;
} args_t;

static void usage(FILE *fp) {
    fputs(
        "axudp-fuzz: AXUDP fuzzer for XRouter (C port).\n"
        "\n"
        "Required:\n"
        "  --target host:port            UDP target\n"
        "  --health URL                  HTTP liveness probe URL\n"
        "\n"
        "Optional:\n"
        "  --duration N                  seconds to fuzz (0 = until SIGINT)\n"
        "  --max-frames N                stop after N frames\n"
        "  --probe-every N               probe every N frames (default 200)\n"
        "  --probe-timeout S             default 3.0\n"
        "  --settle S                    default 0.2\n"
        "  --seed N                      PRNG seed\n"
        "  --rate F                      frames/sec cap (0 = unbounded)\n"
        "  --mutation-bias F             default 0.85\n"
        "  --bad-fcs-prob F              default 0.5\n"
        "  --corpus DIR                  default fuzz/crashes\n"
        "  --continue-on-crash\n"
        "  --quiet\n"
        "  --replay PATH                 bisect a batch dump\n"
        "  --restart-cmd CMD             shell command to restart target\n"
        "  --boot-grace S                default 30.0\n",
        fp);
}

static int parse_target(const char *spec, char *host, size_t hn, int *port) {
    const char *colon = strrchr(spec, ':');
    if (!colon || colon == spec) return -1;
    size_t hl = (size_t)(colon - spec);
    if (hl >= hn) return -1;
    memcpy(host, spec, hl);
    host[hl] = 0;
    *port = atoi(colon + 1);
    return *port > 0 ? 0 : -1;
}

static volatile sig_atomic_t g_stop = 0;
static void on_sigint(int sig) { (void)sig; g_stop = 1; }

static int parse_args(int argc, char **argv, args_t *a) {
    memset(a, 0, sizeof *a);
    a->probe_every = 200;
    a->probe_timeout = 3.0;
    a->settle = 0.2;
    a->seed = -1;
    a->mutation_bias = 0.85;
    a->bad_fcs_prob = 0.5;
    a->corpus = "fuzz/crashes";
    a->boot_grace = 30.0;

    for (int i = 1; i < argc; i++) {
        const char *k = argv[i];
        #define NEED() do { if (++i >= argc) { fprintf(stderr, "missing arg for %s\n", k); return -1; } } while (0)
        if      (!strcmp(k, "--target"))            { NEED(); a->target = argv[i]; }
        else if (!strcmp(k, "--health"))            { NEED(); a->health = argv[i]; }
        else if (!strcmp(k, "--duration"))          { NEED(); a->duration = atoi(argv[i]); }
        else if (!strcmp(k, "--max-frames"))        { NEED(); a->max_frames = atoi(argv[i]); }
        else if (!strcmp(k, "--probe-every"))       { NEED(); a->probe_every = atoi(argv[i]); }
        else if (!strcmp(k, "--probe-timeout"))     { NEED(); a->probe_timeout = atof(argv[i]); }
        else if (!strcmp(k, "--settle"))            { NEED(); a->settle = atof(argv[i]); }
        else if (!strcmp(k, "--seed"))              { NEED(); a->seed = strtoll(argv[i], NULL, 0); }
        else if (!strcmp(k, "--rate"))              { NEED(); a->rate = atof(argv[i]); }
        else if (!strcmp(k, "--mutation-bias"))     { NEED(); a->mutation_bias = atof(argv[i]); }
        else if (!strcmp(k, "--bad-fcs-prob"))      { NEED(); a->bad_fcs_prob = atof(argv[i]); }
        else if (!strcmp(k, "--corpus"))            { NEED(); a->corpus = argv[i]; }
        else if (!strcmp(k, "--continue-on-crash")) { a->continue_on_crash = true; }
        else if (!strcmp(k, "--quiet"))             { a->quiet = true; }
        else if (!strcmp(k, "--replay"))            { NEED(); a->replay = argv[i]; }
        else if (!strcmp(k, "--restart-cmd"))       { NEED(); a->restart_cmd = argv[i]; }
        else if (!strcmp(k, "--boot-grace"))        { NEED(); a->boot_grace = atof(argv[i]); }
        else if (!strcmp(k, "-h") || !strcmp(k, "--help")) { usage(stdout); exit(0); }
        else { fprintf(stderr, "unknown arg: %s\n", k); return -1; }
        #undef NEED
    }
    if (!a->target || !a->health) {
        fprintf(stderr, "--target and --health are required\n");
        return -1;
    }
    return 0;
}

int main(int argc, char **argv) {
    args_t args;
    if (parse_args(argc, argv, &args) < 0) { usage(stderr); return 2; }

    char host[256]; int port;
    if (parse_target(args.target, host, sizeof host, &port) < 0) {
        fprintf(stderr, "bad --target: %s\n", args.target); return 2;
    }
    url_t hurl;
    if (parse_url(args.health, &hurl) < 0) {
        fprintf(stderr, "bad --health URL: %s\n", args.health); return 2;
    }

    signal(SIGINT, on_sigint);
    signal(SIGPIPE, SIG_IGN);

    /* ------------------------------------------------------ replay */
    if (args.replay) {
        if (!args.restart_cmd) {
            fprintf(stderr, "--replay requires --restart-cmd\n"); return 2;
        }
        udp_t u; if (udp_open(&u, host, port) < 0) {
            perror("socket"); return 2;
        }
        buf_t *batch = NULL; size_t bn = 0;
        if (load_batch(args.replay, &batch, &bn) < 0) {
            fprintf(stderr, "could not read %s\n", args.replay); return 2;
        }
        printf("[+] replay: %zu frames from %s\n", bn, args.replay);
        bisect_result_t r = replay_bisect(batch, bn, &u, &hurl,
                                          args.restart_cmd, args.settle,
                                          args.probe_timeout, args.boot_grace);
        if (!r.ok) {
            printf("[-] crash not reproduced on replay (or stateful interaction)\n");
            return 2;
        }
        char suffix[64]; snprintf(suffix, sizeof suffix, "-minimal-idx%d", r.idx);
        char *path = save_crash(args.corpus, r.frame.data, r.frame.len, suffix);
        char dec[1024];
        describe_frame(r.frame.data, r.frame.len, dec, sizeof dec);
        printf("[+] minimal trigger: frame #%d (%zu bytes)\n", r.idx, r.frame.len);
        printf("    decode: %s\n", dec);
        printf("    saved : %s\n", path);
        free(path);
        buf_free(&r.frame);
        for (size_t i = 0; i < bn; i++) buf_free(&batch[i]);
        free(batch);
        return 0;
    }

    /* ------------------------------------------------------ fuzz */
    rng_t rng;
    uint64_t seed;
    if (args.seed < 0) {
        struct timespec ts;
        clock_gettime(CLOCK_REALTIME, &ts);
        seed = (uint64_t)ts.tv_sec * 1000000003ULL + (uint64_t)ts.tv_nsec;
        seed ^= (uint64_t)getpid() << 16;
    } else {
        seed = (uint64_t)args.seed;
    }
    rng_seed(&rng, seed);

    seed_t *seeds = NULL; size_t nseeds = 0;
    build_seed_corpus(&seeds, &nseeds);

    if (!args.quiet) {
        printf("[+] target = %s:%d/udp\n", host, port);
        printf("[+] health = %s\n", args.health);
        printf("[+] seeds  = %zu  rng-seed = %" PRIu64 "\n", nseeds, seed);
        printf("[+] corpus = %s\n", args.corpus);
    }

    if (!health_ok(&hurl, args.probe_timeout)) {
        fprintf(stderr, "[!] health probe failed BEFORE fuzzing — is target up?\n");
        free_seeds(seeds, nseeds);
        return 2;
    }

    udp_t udp; if (udp_open(&udp, host, port) < 0) {
        perror("socket"); free_seeds(seeds, nseeds); return 2;
    }
    mkdir_p(args.corpus);
    char findings_path[1024];
    snprintf(findings_path, sizeof findings_path, "%s/findings.jsonl", args.corpus);
    FILE *findings = fopen(findings_path, "a");
    if (findings) setvbuf(findings, NULL, _IOLBF, 0);

    /* Stats */
    uint64_t sent = 0, bytes_sent = 0, probes_ok = 0, probes_fail = 0, crashes = 0;
    double started = mono_now();
    double last_status = started;
    double rate_token = started;
    double deadline = args.duration ? started + args.duration : 0;

    /* Batch of frames since last good probe. */
    buf_t *batch = NULL; size_t bn = 0, bcap = 0;
    const char *last_label = "<none>";

    while (!g_stop) {
        if (deadline && mono_now() >= deadline) break;
        if (args.max_frames && sent >= (uint64_t)args.max_frames) break;

        buf_t ax;
        if (rng_double(&rng) < args.mutation_bias) {
            uint32_t si = rng_range(&rng, (uint32_t)nseeds);
            last_label = seeds[si].label;
            ax = mutate(seeds[si].data, seeds[si].len, &rng);
        } else {
            last_label = "random";
            ax = random_garbage(&rng);
        }

        buf_t wire;
        if (rng_double(&rng) < args.bad_fcs_prob) {
            wire = buf_dup(ax.data, ax.len);
            buf_push(&wire, (uint8_t)rng_range(&rng, 256));
            buf_push(&wire, (uint8_t)rng_range(&rng, 256));
        } else {
            wire = with_fcs(ax.data, ax.len);
        }
        buf_free(&ax);

        udp_send(&udp, wire.data, wire.len);
        sent++;
        bytes_sent += wire.len;

        if (bn == bcap) {
            bcap = bcap ? bcap * 2 : 256;
            batch = (buf_t *)realloc(batch, bcap * sizeof *batch);
        }
        batch[bn++] = wire;

        if (args.rate > 0) {
            rate_token += 1.0 / args.rate;
            double slack = rate_token - mono_now();
            if (slack > 0) mono_sleep(slack);
        }

        if ((int)(sent % args.probe_every) == 0) {
            mono_sleep(args.settle);
            if (health_ok(&hurl, args.probe_timeout)) {
                probes_ok++;
                for (size_t i = 0; i < bn; i++) buf_free(&batch[i]);
                bn = 0;
            } else {
                probes_fail++;
                crashes++;
                char *sample = save_batch(args.corpus, batch, bn);
                if (findings) {
                    fprintf(findings,
                            "{\"ts\":%.3f,\"kind\":\"health-probe-fail\","
                            "\"frames_in_batch\":%zu,\"sent_total\":%" PRIu64 ","
                            "\"rng_seed\":%" PRIu64 ",\"last_label\":\"%s\","
                            "\"batch_dump\":\"%s\"}\n",
                            (double)time(NULL), bn, sent, seed,
                            last_label, sample);
                }
                fprintf(stderr,
                        "\n[!] CRASH at frame %" PRIu64 " (batch of %zu). Dump: %s\n",
                        sent, bn, sample);
                free(sample);
                if (args.restart_cmd) {
                    if (!restart_and_wait(args.restart_cmd, &hurl,
                                          args.probe_timeout, args.boot_grace)) {
                        fprintf(stderr, "[!] target did not come back after restart; stopping.\n");
                        for (size_t i = 0; i < bn; i++) buf_free(&batch[i]);
                        free(batch);
                        if (findings) fclose(findings);
                        free_seeds(seeds, nseeds);
                        return 3;
                    }
                    fprintf(stderr, "[+] target restarted; continuing\n");
                } else if (!args.continue_on_crash) {
                    fprintf(stderr, "[!] Restart the target and re-run with the same "
                                    "--seed to reproduce. Pass --restart-cmd to keep "
                                    "fuzzing past crashes.\n");
                    for (size_t i = 0; i < bn; i++) buf_free(&batch[i]);
                    free(batch);
                    if (findings) fclose(findings);
                    free_seeds(seeds, nseeds);
                    return 3;
                }
                for (size_t i = 0; i < bn; i++) buf_free(&batch[i]);
                bn = 0;
            }
        }

        double now = mono_now();
        if (!args.quiet && now - last_status >= 5) {
            double dt = now - started; if (dt < 1e-6) dt = 1e-6;
            printf("  sent=%8" PRIu64 "  bytes=%10" PRIu64 "  "
                   "rate=%7.1f/s  probes_ok=%" PRIu64 "  crashes=%" PRIu64 "\n",
                   sent, bytes_sent, sent / dt, probes_ok, crashes);
            last_status = now;
        }
    }

    if (g_stop) printf("\n[+] stopped by user\n");

    if (!args.quiet) {
        printf("\n[+] done. sent=%" PRIu64 " crashes=%" PRIu64 " elapsed=%.1fs\n",
               sent, crashes, mono_now() - started);
    }

    for (size_t i = 0; i < bn; i++) buf_free(&batch[i]);
    free(batch);
    if (findings) fclose(findings);
    close(udp.fd);
    free_seeds(seeds, nseeds);
    return crashes ? 1 : 0;
}
